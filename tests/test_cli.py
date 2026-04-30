from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from chameleon.cli import main
from chameleon.renderer import RenderResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "tiny_dataset"
BUNDLED_JAR = PROJECT_ROOT / "plantuml-1.2025.9.jar"

requires_plantuml = pytest.mark.skipif(
    shutil.which("java") is None or not BUNDLED_JAR.is_file(),
    reason="java or plantuml jar not available",
)


PROFILES_YAML = """\
profiles:
  - name: default
    theme: null
    skinparams: {}
    handwritten: false
  - name: whiteboard
    theme: sketchy
    skinparams: {shadowing: false}
    handwritten: true
sampling:
  - profile: default
    probability: 0.6
  - profile: whiteboard
    probability: 0.4
"""


def _make_inputs(input_dir: Path, names: list[str]) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    for n in names:
        (input_dir / n).write_text("@startuml\nA -> B\n@enduml\n", encoding="utf-8")


def _write_profiles(path: Path, body: str = PROFILES_YAML) -> None:
    path.write_text(body, encoding="utf-8")


# --- run --dry-run ---------------------------------------------------------


def test_dry_run_writes_manifest_run_config_and_snapshot(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _make_inputs(input_dir, ["a.puml", "b.puml", "c.puml"])
    profiles = tmp_path / "profiles.yaml"
    _write_profiles(profiles)
    output = tmp_path / "output"

    rc = main(
        [
            "run",
            "--input",
            str(input_dir),
            "--profiles",
            str(profiles),
            "--output",
            str(output),
            "--seed",
            "42",
            "--dry-run",
        ]
    )
    assert rc == 0

    manifest = output / "manifest.jsonl"
    run_config = output / "run_config.json"
    snapshot = output / "profiles_used.yaml"
    assert manifest.is_file()
    assert run_config.is_file()
    assert snapshot.is_file()

    entries = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert len(entries) == 3
    for e in entries:
        assert e["render_status"] == "skip"
        assert e["output_path"] is None
        assert e["profile_name"] in {"default", "whiteboard"}

    rc_data = json.loads(run_config.read_text())
    assert rc_data["seed"] == 42
    assert rc_data["n_input_files"] == 3
    assert rc_data["n_rendered_ok"] == 0
    assert rc_data["n_rendered_fail"] == 0
    assert sum(rc_data["realized_profile_counts"].values()) == 3
    assert set(rc_data["realized_profile_counts"]) == {"default", "whiteboard"}
    assert rc_data["format"] == "png"

    assert snapshot.read_text() == PROFILES_YAML


def test_dry_run_is_deterministic_with_seed(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _make_inputs(input_dir, [f"f{i}.puml" for i in range(20)])
    profiles = tmp_path / "profiles.yaml"
    _write_profiles(profiles)

    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"

    for out in (out1, out2):
        rc = main(
            [
                "run",
                "--input",
                str(input_dir),
                "--profiles",
                str(profiles),
                "--output",
                str(out),
                "--seed",
                "7",
                "--dry-run",
            ]
        )
        assert rc == 0

    assert (out1 / "manifest.jsonl").read_text() == (out2 / "manifest.jsonl").read_text()


def test_dry_run_with_limit(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _make_inputs(input_dir, [f"f{i}.puml" for i in range(10)])
    profiles = tmp_path / "profiles.yaml"
    _write_profiles(profiles)
    output = tmp_path / "out"

    rc = main(
        [
            "run",
            "--input",
            str(input_dir),
            "--profiles",
            str(profiles),
            "--output",
            str(output),
            "--seed",
            "1",
            "--limit",
            "3",
            "--dry-run",
        ]
    )
    assert rc == 0
    entries = (output / "manifest.jsonl").read_text().splitlines()
    assert len(entries) == 3


def test_dry_run_recursive_input_discovery(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "a.puml").write_text("@startuml\n@enduml\n")
    (input_dir / "sub" / "b.puml").write_text("@startuml\n@enduml\n")
    profiles = tmp_path / "profiles.yaml"
    _write_profiles(profiles)
    output = tmp_path / "out"

    rc = main(
        [
            "run",
            "--input",
            str(input_dir),
            "--profiles",
            str(profiles),
            "--output",
            str(output),
            "--seed",
            "0",
            "--dry-run",
        ]
    )
    assert rc == 0
    entries = [json.loads(line) for line in (output / "manifest.jsonl").read_text().splitlines()]
    paths = {e["input_path"] for e in entries}
    assert paths == {"a.puml", "sub/b.puml"}


def test_run_missing_input_dir_returns_2(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles.yaml"
    _write_profiles(profiles)
    rc = main(
        [
            "run",
            "--input",
            str(tmp_path / "nope"),
            "--profiles",
            str(profiles),
            "--output",
            str(tmp_path / "out"),
            "--dry-run",
        ]
    )
    assert rc == 2


def test_run_invalid_profiles_returns_2(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    _make_inputs(input_dir, ["a.puml"])
    bad = tmp_path / "bad.yaml"
    bad.write_text("profiles: not-a-list\nsampling: []\n", encoding="utf-8")
    rc = main(
        [
            "run",
            "--input",
            str(input_dir),
            "--profiles",
            str(bad),
            "--output",
            str(tmp_path / "out"),
            "--dry-run",
        ]
    )
    assert rc == 2


def test_run_no_inputs_returns_2(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    profiles = tmp_path / "profiles.yaml"
    _write_profiles(profiles)
    rc = main(
        [
            "run",
            "--input",
            str(input_dir),
            "--profiles",
            str(profiles),
            "--output",
            str(tmp_path / "out"),
            "--dry-run",
        ]
    )
    assert rc == 2


# --- validate --------------------------------------------------------------


def test_validate_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profiles = tmp_path / "profiles.yaml"
    _write_profiles(profiles)
    rc = main(["validate", str(profiles)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out


def test_validate_failure(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("profiles: not-a-list\nsampling: []\n", encoding="utf-8")
    rc = main(["validate", str(bad)])
    assert rc == 1


def test_validate_missing_file_returns_1(tmp_path: Path) -> None:
    rc = main(["validate", str(tmp_path / "missing.yaml")])
    assert rc == 1


# --- end-to-end render via CLI --------------------------------------------


def test_cmd_run_chunks_oversized_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_dir = tmp_path / "input"
    names = [f"f{i:02d}.puml" for i in range(10)]
    _make_inputs(input_dir, names)

    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        "profiles:\n"
        "  - name: only\n"
        "    theme: null\n"
        "    skinparams: {}\n"
        "    handwritten: false\n"
        "sampling:\n"
        "  - profile: only\n"
        "    probability: 1.0\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    fake_jar = tmp_path / "fake.jar"
    fake_jar.write_bytes(b"")

    monkeypatch.setattr("chameleon.cli.MAX_BATCH_SIZE", 3)
    monkeypatch.setattr("chameleon.cli.detect_java", lambda: "/usr/bin/java")
    monkeypatch.setattr(
        "chameleon.cli.get_plantuml_version", lambda *a, **kw: "fake"
    )

    calls: list[list[Path]] = []

    def fake_render_batch(
        *,
        inputs: list[Path],
        output_dir: Path,
        profile,  # type: ignore[no-untyped-def]
        plantuml_jar: Path,
        image_format: str = "png",
        timeout_seconds: int | None = None,
        java: str | None = None,
    ) -> list[RenderResult]:
        calls.append(list(inputs))
        return [
            RenderResult(
                output_path=output_dir / f"{p.stem}.{image_format}",
                status="ok",
                stderr="",
            )
            for p in inputs
        ]

    monkeypatch.setattr("chameleon.cli.render_batch", fake_render_batch)

    rc = main(
        [
            "run",
            "--input",
            str(input_dir),
            "--profiles",
            str(profiles),
            "--output",
            str(output),
            "--seed",
            "0",
            "--plantuml-jar",
            str(fake_jar),
        ]
    )
    assert rc == 0

    # 10 inputs / chunk-size 3 = 4 chunks
    assert len(calls) == 4
    assert [len(c) for c in calls] == [3, 3, 3, 1]

    flat = [p for chunk in calls for p in chunk]
    assert [p.name for p in flat] == names

    entries = [json.loads(line) for line in (output / "manifest.jsonl").read_text().splitlines()]
    assert [e["input_path"] for e in entries] == names
    assert all(e["render_status"] == "ok" for e in entries)


@requires_plantuml
def test_run_renders_fixtures_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for src in sorted(FIXTURE_DIR.glob("*.puml")):
        (input_dir / src.name).write_bytes(src.read_bytes())

    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        "profiles:\n"
        "  - name: default\n"
        "    theme: null\n"
        "    skinparams: {}\n"
        "    handwritten: false\n"
        "sampling:\n"
        "  - profile: default\n"
        "    probability: 1.0\n",
        encoding="utf-8",
    )
    output = tmp_path / "out"
    monkeypatch.setenv("PLANTUML_JAR", str(BUNDLED_JAR))

    rc = main(
        [
            "run",
            "--input",
            str(input_dir),
            "--profiles",
            str(profiles),
            "--output",
            str(output),
            "--seed",
            "0",
        ]
    )
    assert rc == 0

    rc_data = json.loads((output / "run_config.json").read_text())
    assert rc_data["n_input_files"] == 5
    assert rc_data["n_rendered_ok"] == 5
    assert rc_data["n_rendered_fail"] == 0
    assert rc_data["plantuml_version"]

    images_dir = output / "images" / "default"
    pngs = sorted(images_dir.glob("*.png"))
    assert len(pngs) == 5
    for p in pngs:
        assert p.stat().st_size > 0
