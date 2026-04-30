#!/usr/bin/env python3
"""End-to-end demo run: 50 puml files, 4 profiles, visible profiles/inputs/outputs."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from chameleon.cli import main as chameleon_main
from chameleon.profile import Profile, ProfileSet, load_profile_set


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run chameleon end-to-end on the first N puml_files with 4 profiles."
    )
    p.add_argument("--input", type=Path, default=PROJECT_ROOT / "puml_files")
    p.add_argument(
        "--profiles", type=Path, default=PROJECT_ROOT / "tests/fixtures/profiles_e2e.yaml"
    )
    p.add_argument("--output", type=Path, default=None, help="default: output/e2e_<UTC_TS>/")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--format", default="png", choices=("png", "svg"))
    p.add_argument(
        "--plantuml-jar", type=Path, default=PROJECT_ROOT / "plantuml-1.2025.9.jar"
    )
    return p.parse_args()


def discover_inputs(input_dir: Path, limit: int) -> list[Path]:
    files = sorted(input_dir.rglob("*.puml"))
    return files[:limit]


def render_profile_table(ps: ProfileSet) -> str:
    weights = {e.profile: e.probability for e in ps.sampling}
    rows = [("name", "prob", "theme", "hand", "skinparams")]
    for prof in ps.profiles:
        rows.append(
            (
                prof.name,
                f"{weights.get(prof.name, 0.0):.3f}",
                str(prof.theme),
                str(prof.handwritten),
                _fmt_skinparams(prof),
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for i, row in enumerate(rows):
        lines.append("  " + "  ".join(c.ljust(widths[j]) for j, c in enumerate(row)))
        if i == 0:
            lines.append("  " + "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _fmt_skinparams(prof: Profile) -> str:
    if not prof.skinparams:
        return "{}"
    return ", ".join(f"{k}={v}" for k, v in prof.skinparams.items())


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def print_pre_run(args: argparse.Namespace, ps: ProfileSet, inputs: list[Path]) -> None:
    banner("E2E run configuration")
    print(f"  input dir   : {args.input}")
    print(f"  profiles    : {args.profiles}")
    print(f"  output dir  : {args.output}")
    print(f"  plantuml.jar: {args.plantuml_jar}")
    print(f"  format      : {args.format}")
    print(f"  seed        : {args.seed}")
    print(f"  limit       : {args.limit}")

    banner(f"Profiles ({len(ps.profiles)}) and sampling weights")
    print(render_profile_table(ps))

    banner(f"Selected input files ({len(inputs)})")
    for i, p in enumerate(inputs, 1):
        print(f"  [{i:2d}] {p.relative_to(args.input)}")


def print_post_run(output_dir: Path) -> int:
    run_config = json.loads((output_dir / "run_config.json").read_text())
    entries = [
        json.loads(line)
        for line in (output_dir / "manifest.jsonl").read_text().splitlines()
        if line.strip()
    ]

    banner("run_config.json")
    print(f"  tool_version       : {run_config['tool_version']}")
    print(f"  plantuml_version   : {run_config['plantuml_version']}")
    print(f"  seed               : {run_config['seed']}")
    print(f"  format             : {run_config['format']}")
    print(f"  n_input_files      : {run_config['n_input_files']}")
    print(f"  n_rendered_ok      : {run_config['n_rendered_ok']}")
    print(f"  n_rendered_fail    : {run_config['n_rendered_fail']}")
    print(f"  run_start_iso      : {run_config['run_start_iso']}")
    print(f"  run_end_iso        : {run_config['run_end_iso']}")
    print(f"  duration           : {_duration(run_config)}")
    print(f"  realized_profile_counts:")
    for name, n in run_config["realized_profile_counts"].items():
        print(f"      {name:<14} {n}")

    banner(f"Manifest assignments ({len(entries)})")
    print(f"  {'#':>3}  {'input':<46}  {'profile':<12}  {'status'}")
    print(f"  {'---':>3}  {'-' * 46}  {'-' * 12}  {'------'}")
    for i, e in enumerate(entries, 1):
        ip = e["input_path"]
        if len(ip) > 46:
            ip = ip[:20] + "..." + ip[-23:]
        status = e["render_status"]
        print(f"  {i:>3}  {ip:<46}  {e['profile_name']:<12}  {status}")

    failures = [e for e in entries if e["render_status"] != "ok"]
    if failures:
        banner(f"Failures ({len(failures)})")
        for e in failures:
            print(f"  {e['input_path']}  [{e['profile_name']}]  {e['render_status']}")
            if e.get("render_stderr"):
                print(f"    stderr: {e['render_stderr']}")

    banner("On-disk output tree")
    fmt = run_config["format"]
    images_dir = output_dir / "images"
    if images_dir.is_dir():
        total_bytes = 0
        total_files = 0
        for prof_dir in sorted(images_dir.iterdir()):
            if not prof_dir.is_dir():
                continue
            files = sorted(prof_dir.rglob(f"*.{fmt}"))
            size = sum(f.stat().st_size for f in files)
            total_bytes += size
            total_files += len(files)
            print(f"  images/{prof_dir.name:<14} {len(files):>3} {fmt}  {_human_bytes(size)}")
        print(f"  total                 {total_files:>3} {fmt}  {_human_bytes(total_bytes)}")
    else:
        print(f"  (no images/ dir at {images_dir})")

    print()
    counts = run_config["realized_profile_counts"]
    summary = ", ".join(f"{k}={v}" for k, v in counts.items())
    n_ok = run_config["n_rendered_ok"]
    n_fail = run_config["n_rendered_fail"]
    n_in = run_config["n_input_files"]
    verdict = "OK" if n_fail == 0 else "FAIL"
    print(f"{verdict}: {n_ok}/{n_in} rendered, profiles {{{summary}}}, output -> {output_dir}")
    return 0 if n_fail == 0 else 1


def _duration(run_config: dict) -> str:
    start = datetime.fromisoformat(run_config["run_start_iso"])
    end = datetime.fromisoformat(run_config["run_end_iso"])
    return f"{(end - start).total_seconds():.1f}s"


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> int:
    args = parse_args()
    if args.output is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        args.output = PROJECT_ROOT / "output" / f"e2e_{ts}"

    if not args.input.is_dir():
        print(f"ERROR: input dir not found: {args.input}", file=sys.stderr)
        return 2
    if not args.profiles.is_file():
        print(f"ERROR: profiles YAML not found: {args.profiles}", file=sys.stderr)
        return 2
    if not args.plantuml_jar.is_file():
        print(f"ERROR: plantuml.jar not found: {args.plantuml_jar}", file=sys.stderr)
        return 2

    profile_set = load_profile_set(args.profiles)
    inputs = discover_inputs(args.input, args.limit)
    if not inputs:
        print(f"ERROR: no .puml files in {args.input}", file=sys.stderr)
        return 2

    print_pre_run(args, profile_set, inputs)

    banner(f"Rendering {len(inputs)} files...")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rc = chameleon_main(
        [
            "run",
            "--input",
            str(args.input),
            "--profiles",
            str(args.profiles),
            "--output",
            str(args.output),
            "--seed",
            str(args.seed),
            "--format",
            args.format,
            "--limit",
            str(args.limit),
            "--plantuml-jar",
            str(args.plantuml_jar),
        ]
    )
    if rc not in (0, 1):
        print(f"ERROR: chameleon run exited with {rc}", file=sys.stderr)
        return rc

    return print_post_run(args.output)


if __name__ == "__main__":
    sys.exit(main())
