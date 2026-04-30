import json
from pathlib import Path

from chameleon.manifest import (
    ManifestEntry,
    ManifestWriter,
    iso_now,
    write_profiles_snapshot,
    write_run_config,
)


def test_manifest_writer_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    with ManifestWriter(path) as mf:
        mf.write(
            ManifestEntry(
                input_path="a.puml",
                output_path="images/x/a.png",
                profile_name="x",
                render_status="ok",
                render_stderr="",
            )
        )
        mf.write(
            ManifestEntry(
                input_path="b.puml",
                output_path=None,
                profile_name="y",
                render_status="skip",
            )
        )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {
        "input_path": "a.puml",
        "output_path": "images/x/a.png",
        "profile_name": "x",
        "render_status": "ok",
        "render_stderr": "",
    }
    second = json.loads(lines[1])
    assert second["output_path"] is None
    assert second["render_status"] == "skip"


def test_manifest_writer_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "manifest.jsonl"
    with ManifestWriter(path) as mf:
        mf.write(ManifestEntry("a.puml", None, "x", "skip"))
    assert path.is_file()


def test_write_run_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "run_config.json"
    payload = {"seed": 42, "format": "png", "realized_profile_counts": {"a": 1, "b": 2}}
    write_run_config(path, payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_profiles_snapshot_is_verbatim_copy(tmp_path: Path) -> None:
    src = tmp_path / "profiles.yaml"
    src.write_text("# important comment\nprofiles: []\n", encoding="utf-8")
    dst = tmp_path / "out" / "profiles_used.yaml"
    write_profiles_snapshot(dst, src)
    assert dst.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_iso_now_format() -> None:
    s = iso_now()
    assert "T" in s
    assert s.endswith("+00:00")
