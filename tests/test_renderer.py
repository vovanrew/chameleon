from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from chameleon.profile import Profile
from chameleon.renderer import (
    JavaNotFoundError,
    PlantumlNotFoundError,
    detect_java,
    render_batch,
    resolve_plantuml_jar,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "tiny_dataset"
BUNDLED_JAR = PROJECT_ROOT / "plantuml-1.2025.9.jar"


def _profile(**overrides: Any) -> Profile:
    base = {
        "name": "default",
        "theme": None,
        "skinparams": {},
        "handwritten": False,
    }
    base.update(overrides)
    return Profile(**base)


# --- resolve_plantuml_jar -------------------------------------------------


def test_resolve_plantuml_jar_uses_cli_value(tmp_path: Path, monkeypatch) -> None:
    jar = tmp_path / "p.jar"
    jar.write_bytes(b"")
    monkeypatch.delenv("PLANTUML_JAR", raising=False)
    assert resolve_plantuml_jar(jar) == jar.resolve()


def test_resolve_plantuml_jar_falls_back_to_env(tmp_path: Path, monkeypatch) -> None:
    jar = tmp_path / "env.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("PLANTUML_JAR", str(jar))
    assert resolve_plantuml_jar(None) == jar.resolve()


def test_resolve_plantuml_jar_cli_overrides_env(tmp_path: Path, monkeypatch) -> None:
    cli_jar = tmp_path / "cli.jar"
    env_jar = tmp_path / "env.jar"
    cli_jar.write_bytes(b"")
    env_jar.write_bytes(b"")
    monkeypatch.setenv("PLANTUML_JAR", str(env_jar))
    assert resolve_plantuml_jar(cli_jar) == cli_jar.resolve()


def test_resolve_plantuml_jar_missing_raises(monkeypatch) -> None:
    monkeypatch.delenv("PLANTUML_JAR", raising=False)
    with pytest.raises(PlantumlNotFoundError, match="--plantuml-jar"):
        resolve_plantuml_jar(None)


def test_resolve_plantuml_jar_nonexistent_path_raises(tmp_path: Path) -> None:
    with pytest.raises(PlantumlNotFoundError, match="not found at"):
        resolve_plantuml_jar(tmp_path / "missing.jar")


# --- detect_java ----------------------------------------------------------


def test_detect_java_missing_raises(monkeypatch) -> None:
    monkeypatch.setattr("chameleon.renderer.shutil.which", lambda _: None)
    with pytest.raises(JavaNotFoundError):
        detect_java()


def test_detect_java_returns_path(monkeypatch) -> None:
    monkeypatch.setattr("chameleon.renderer.shutil.which", lambda _: "/usr/bin/java")
    assert detect_java() == "/usr/bin/java"


# --- render_batch (mocked) ------------------------------------------------


def _completed(stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["java"], returncode=returncode, stdout="", stderr=stderr
    )


def test_render_batch_empty_inputs_returns_empty(tmp_path: Path) -> None:
    results = render_batch(
        inputs=[],
        output_dir=tmp_path,
        profile=_profile(),
        plantuml_jar=Path("/p.jar"),
        java="java",
    )
    assert results == []


def test_render_batch_all_ok(tmp_path: Path) -> None:
    inputs = [tmp_path / f"{n}.puml" for n in ("a", "b", "c")]
    out_dir = tmp_path / "out"
    expected_pngs = [out_dir / f"{n}.png" for n in ("a", "b", "c")]

    with patch("chameleon.renderer.subprocess.run") as mock_run:
        mock_run.return_value = _completed()
        with patch.object(Path, "exists", return_value=True):
            results = render_batch(
                inputs=inputs,
                output_dir=out_dir,
                profile=_profile(),
                plantuml_jar=Path("/p.jar"),
                java="java",
            )

    assert mock_run.call_count == 1
    assert [r.status for r in results] == ["ok", "ok", "ok"]
    assert [r.output_path for r in results] == expected_pngs


def test_render_batch_one_syntax_error(tmp_path: Path) -> None:
    inputs = [tmp_path / "a.puml", tmp_path / "b.puml", tmp_path / "c.puml"]
    out_dir = tmp_path / "out"
    stderr = (
        f"Error line 5 in file: {inputs[1]}\n"
        "Some diagram description contains errors\n"
    )

    with patch("chameleon.renderer.subprocess.run", return_value=_completed(stderr=stderr)):
        with patch.object(Path, "exists", return_value=True):
            results = render_batch(
                inputs=inputs,
                output_dir=out_dir,
                profile=_profile(),
                plantuml_jar=Path("/p.jar"),
                java="java",
            )

    assert results[0].status == "ok"
    assert results[1].status == "fail"
    assert str(inputs[1]) in results[1].stderr
    assert results[2].status == "ok"


def test_render_batch_warning_no_image(tmp_path: Path) -> None:
    inputs = [tmp_path / "a.puml", tmp_path / "c.puml"]
    out_dir = tmp_path / "out"
    stderr = f"Warning: no image in {inputs[1]}\n"

    with patch("chameleon.renderer.subprocess.run", return_value=_completed(stderr=stderr)):
        with patch.object(Path, "exists", return_value=True):
            results = render_batch(
                inputs=inputs,
                output_dir=out_dir,
                profile=_profile(),
                plantuml_jar=Path("/p.jar"),
                java="java",
            )

    assert results[0].status == "ok"
    assert results[1].status == "fail"
    assert "Warning: no image" in results[1].stderr


def test_render_batch_missing_output_no_stderr(tmp_path: Path) -> None:
    inputs = [tmp_path / "a.puml", tmp_path / "b.puml"]
    out_dir = tmp_path / "out"
    expected = [out_dir / "a.png", out_dir / "b.png"]

    def fake_exists(self: Path) -> bool:
        return self != expected[1]

    with patch("chameleon.renderer.subprocess.run", return_value=_completed()):
        with patch.object(Path, "exists", fake_exists):
            results = render_batch(
                inputs=inputs,
                output_dir=out_dir,
                profile=_profile(),
                plantuml_jar=Path("/p.jar"),
                java="java",
            )

    assert results[0].status == "ok"
    assert results[1].status == "fail"
    assert "expected output missing" in results[1].stderr
    assert str(expected[1]) in results[1].stderr


def test_render_batch_timeout_marks_all_fail(tmp_path: Path) -> None:
    inputs = [tmp_path / f"{n}.puml" for n in ("a", "b", "c")]
    out_dir = tmp_path / "out"

    with patch(
        "chameleon.renderer.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["java"], timeout=60),
    ):
        results = render_batch(
            inputs=inputs,
            output_dir=out_dir,
            profile=_profile(),
            plantuml_jar=Path("/p.jar"),
            java="java",
        )

    assert len(results) == 3
    for r in results:
        assert r.status == "fail"
        assert "timeout" in r.stderr
        assert "batch of 3 files" in r.stderr


def test_render_batch_command_shape(tmp_path: Path) -> None:
    inputs = [tmp_path / f"{n}.puml" for n in ("a", "b", "c")]
    out_dir = tmp_path / "out"

    with patch("chameleon.renderer.subprocess.run") as mock_run:
        mock_run.return_value = _completed()
        with patch.object(Path, "exists", return_value=True):
            render_batch(
                inputs=inputs,
                output_dir=out_dir,
                profile=_profile(theme="cerulean"),
                plantuml_jar=Path("/p.jar"),
                java="/usr/bin/java",
            )

    cmd: list[str] = mock_run.call_args.args[0]
    assert cmd[:5] == ["/usr/bin/java", "-jar", "/p.jar", "-theme", "cerulean"]
    assert cmd[5] == "-config"
    cfg_idx = 5
    assert cmd[cfg_idx + 1].endswith(".cfg")
    assert cmd[cfg_idx + 2] == "-tpng"
    assert cmd[cfg_idx + 3] == "-o"
    assert cmd[cfg_idx + 4] == str(out_dir)
    assert cmd[cfg_idx + 5 :] == [str(p) for p in inputs]
    # Single shared -config flag
    assert cmd.count("-config") == 1


def test_render_batch_no_theme_omits_theme_flag(tmp_path: Path) -> None:
    inputs = [tmp_path / "a.puml"]
    out_dir = tmp_path / "out"

    with patch("chameleon.renderer.subprocess.run") as mock_run:
        mock_run.return_value = _completed()
        with patch.object(Path, "exists", return_value=True):
            render_batch(
                inputs=inputs,
                output_dir=out_dir,
                profile=_profile(theme=None),
                plantuml_jar=Path("/p.jar"),
                java="java",
            )

    cmd: list[str] = mock_run.call_args.args[0]
    assert "-theme" not in cmd


# --- render_batch (real plantuml) -----------------------------------------

requires_plantuml = pytest.mark.skipif(
    shutil.which("java") is None or not BUNDLED_JAR.is_file(),
    reason="java or plantuml jar not available",
)


@requires_plantuml
def test_render_batch_real_e2e_two_files(tmp_path: Path) -> None:
    fixtures = sorted(FIXTURE_DIR.glob("*.puml"))[:2]
    assert len(fixtures) == 2
    out_dir = tmp_path / "images"

    results = render_batch(
        inputs=list(fixtures),
        output_dir=out_dir,
        profile=_profile(),
        plantuml_jar=BUNDLED_JAR,
    )

    assert len(results) == 2
    for inp, r in zip(fixtures, results, strict=True):
        assert r.status == "ok", r.stderr
        expected = out_dir / f"{inp.stem}.png"
        assert r.output_path == expected
        assert expected.is_file()
        assert expected.stat().st_size > 0
        assert expected.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
