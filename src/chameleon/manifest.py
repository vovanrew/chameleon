"""JSONL manifest writer + run_config + profiles snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any


@dataclass(frozen=True)
class ManifestEntry:
    input_path: str
    output_path: str | None
    profile_name: str
    render_status: str
    render_stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "profile_name": self.profile_name,
            "render_status": self.render_status,
            "render_stderr": self.render_stderr,
        }


class ManifestWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._fh = path.open("w", encoding="utf-8")

    def write(self, entry: ManifestEntry) -> None:
        self._fh.write(json.dumps(entry.to_dict()) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> ManifestWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def write_run_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_profiles_snapshot(dest: Path, source: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(source.read_bytes())


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
