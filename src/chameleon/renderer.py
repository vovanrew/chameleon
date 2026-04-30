"""plantuml subprocess invocation."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chameleon.config_gen import render_config
from chameleon.profile import Profile

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 200

_STDERR_FILE_REF_RE = re.compile(
    r"(?:Error line \d+ in file|Warning: no image in)\s*:?\s*(?P<path>\S+\.puml)"
)


class PlantumlNotFoundError(RuntimeError):
    pass


class JavaNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderResult:
    output_path: Path | None
    status: str
    stderr: str


def resolve_plantuml_jar(cli_value: str | Path | None) -> Path:
    if cli_value is not None:
        candidate: str | None = str(cli_value)
    else:
        candidate = os.environ.get("PLANTUML_JAR")

    if not candidate:
        raise PlantumlNotFoundError(
            "plantuml.jar not found: pass --plantuml-jar or set PLANTUML_JAR"
        )

    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise PlantumlNotFoundError(f"plantuml.jar not found at {path}")
    return path


def detect_java() -> str:
    java = shutil.which("java")
    if java is None:
        raise JavaNotFoundError("`java` executable not found on PATH")
    return java


def get_plantuml_version(plantuml_jar: Path, java: str | None = None) -> str:
    java = java or detect_java()
    result = subprocess.run(
        [java, "-jar", str(plantuml_jar), "-version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    match = re.search(r"PlantUML version ([\d.]+)", result.stdout)
    if match:
        return match.group(1)
    return result.stdout.strip().splitlines()[0] if result.stdout else ""


def render_batch(
    *,
    inputs: list[Path],
    output_dir: Path,
    profile: Profile,
    plantuml_jar: Path,
    image_format: str = "png",
    timeout_seconds: int | None = None,
    java: str | None = None,
) -> list[RenderResult]:
    """Render N inputs in one plantuml call. Returns one RenderResult per input,
    in the same order as ``inputs``. PlantUML's exit code is unreliable for per-file
    success — we reconcile each input by parsing stderr for explicit error/warning
    lines naming it, and falling back to checking whether the expected output PNG
    exists on disk.
    """
    if not inputs:
        return []

    java = java or detect_java()
    if timeout_seconds is None:
        timeout_seconds = max(60, 5 + 2 * len(inputs))
    output_dir.mkdir(parents=True, exist_ok=True)

    config_text = render_config(profile)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cfg", delete=False, encoding="utf-8"
    ) as cfg:
        cfg.write(config_text)
        cfg_path = Path(cfg.name)

    try:
        cmd: list[str] = [java, "-jar", str(plantuml_jar)]
        if profile.theme is not None:
            cmd.extend(["-theme", profile.theme])
        cmd.extend(["-config", str(cfg_path), f"-t{image_format}", "-o", str(output_dir)])
        cmd.extend(str(p) for p in inputs)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            msg = (
                f"timeout after {timeout_seconds}s rendering batch of {len(inputs)} files"
            )
            return [RenderResult(None, "fail", msg) for _ in inputs]

        # Group stderr lines by the input path token they reference.
        stderr_by_path: dict[str, list[str]] = {}
        for line in result.stderr.splitlines():
            m = _STDERR_FILE_REF_RE.search(line)
            if m:
                stderr_by_path.setdefault(m.group("path"), []).append(line.rstrip())

        results: list[RenderResult] = []
        for inp in inputs:
            expected = output_dir / f"{inp.stem}.{image_format}"
            matched = stderr_by_path.get(str(inp))
            if matched:
                results.append(
                    RenderResult(
                        output_path=None,
                        status="fail",
                        stderr="\n".join(matched),
                    )
                )
            elif expected.exists():
                results.append(
                    RenderResult(output_path=expected, status="ok", stderr="")
                )
            else:
                results.append(
                    RenderResult(
                        output_path=None,
                        status="fail",
                        stderr=(
                            f"plantuml exited {result.returncode} but expected output "
                            f"missing: {expected}"
                        ),
                    )
                )
        return results
    finally:
        cfg_path.unlink(missing_ok=True)
