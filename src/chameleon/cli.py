"""argparse entry point."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from chameleon import __version__
from chameleon.manifest import (
    ManifestEntry,
    ManifestWriter,
    iso_now,
    write_profiles_snapshot,
    write_run_config,
)
from chameleon.profile import ProfileValidationError, load_profile_set
from chameleon.renderer import (
    MAX_BATCH_SIZE,
    JavaNotFoundError,
    PlantumlNotFoundError,
    RenderResult,
    detect_java,
    get_plantuml_version,
    render_batch,
    resolve_plantuml_jar,
)
from chameleon.sampler import Assignment, assign_profiles, generate_seed

logger = logging.getLogger("chameleon")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "list-themes":
        return _cmd_list_themes(args)

    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chameleon",
        description="Render PlantUML files into visually diversified images via profiles.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable DEBUG logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subs = parser.add_subparsers(dest="command", required=True)

    run_p = subs.add_parser("run", help="render a directory of .puml files")
    run_p.add_argument("--input", type=Path, required=True, help="input directory (recursive)")
    run_p.add_argument("--profiles", type=Path, required=True, help="profiles YAML")
    run_p.add_argument("--output", type=Path, required=True, help="output directory")
    run_p.add_argument("--seed", type=int, default=None, help="RNG seed (default: random)")
    run_p.add_argument(
        "--format", default="png", choices=("png", "svg"), help="image format (default: png)"
    )
    run_p.add_argument(
        "--threads", type=int, default=os.cpu_count() or 1, help="parallelism (unused in step 6)"
    )
    run_p.add_argument("--limit", type=int, default=None, help="process at most N files")
    run_p.add_argument(
        "--plantuml-jar",
        type=Path,
        default=None,
        help="path to plantuml.jar (or set PLANTUML_JAR)",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="assign profiles and write manifest, but skip rendering",
    )

    val_p = subs.add_parser("validate", help="validate a profiles YAML file")
    val_p.add_argument("path", type=Path)

    lt_p = subs.add_parser("list-themes", help="list PlantUML built-in themes")
    lt_p.add_argument("--plantuml-jar", type=Path, default=None)

    return parser


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _discover_inputs(input_dir: Path) -> list[Path]:
    return sorted(p for p in input_dir.rglob("*.puml") if p.is_file())


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.input.is_dir():
        logger.error("input directory not found: %s", args.input)
        return 2

    args.input = args.input.resolve()
    args.output = args.output.resolve()

    try:
        profile_set = load_profile_set(args.profiles)
    except FileNotFoundError as e:
        logger.error("profile YAML not found: %s", e)
        return 2
    except ProfileValidationError as e:
        logger.error("profile validation failed: %s", e)
        return 2

    inputs = _discover_inputs(args.input)
    if args.limit is not None:
        inputs = inputs[: args.limit]
    if not inputs:
        logger.error("no .puml files found under %s", args.input)
        return 2

    seed = args.seed if args.seed is not None else generate_seed()
    logger.info("seed: %d", seed)
    logger.info("input files: %d", len(inputs))

    rel_inputs = [str(p.relative_to(args.input)) for p in inputs]
    assignments = assign_profiles(rel_inputs, profile_set, seed)

    args.output.mkdir(parents=True, exist_ok=True)
    write_profiles_snapshot(args.output / "profiles_used.yaml", args.profiles)

    plantuml_jar: Path | None = None
    plantuml_version = ""
    java = ""
    if not args.dry_run:
        try:
            plantuml_jar = resolve_plantuml_jar(args.plantuml_jar)
            java = detect_java()
            plantuml_version = get_plantuml_version(plantuml_jar, java)
        except (PlantumlNotFoundError, JavaNotFoundError) as e:
            logger.error(str(e))
            return 2
        logger.info("plantuml: %s (%s)", plantuml_version, plantuml_jar)

    realized: Counter[str] = Counter({p.name: 0 for p in profile_set.profiles})
    n_ok = 0
    n_fail = 0
    run_start = iso_now()

    with ManifestWriter(args.output / "manifest.jsonl") as mf:
        if args.dry_run:
            for assignment in assignments:
                realized[assignment.profile.name] += 1
                mf.write(
                    ManifestEntry(
                        input_path=assignment.input_path,
                        output_path=None,
                        profile_name=assignment.profile.name,
                        render_status="skip",
                    )
                )
        else:
            assert plantuml_jar is not None
            groups: dict[tuple[str, str], list[Assignment]] = defaultdict(list)
            for assignment in assignments:
                parent = str(Path(assignment.input_path).parent)
                groups[(assignment.profile.name, parent)].append(assignment)

            results_by_input: dict[str, RenderResult] = {}
            for (profile_name, parent), members in groups.items():
                profile = profile_set.by_name(profile_name)
                output_dir = (args.output / "images" / profile_name / parent).resolve()
                for chunk_start in range(0, len(members), MAX_BATCH_SIZE):
                    chunk = members[chunk_start : chunk_start + MAX_BATCH_SIZE]
                    chunk_inputs = [(args.input / a.input_path).resolve() for a in chunk]
                    chunk_results = render_batch(
                        inputs=chunk_inputs,
                        output_dir=output_dir,
                        profile=profile,
                        plantuml_jar=plantuml_jar,
                        image_format=args.format,
                        java=java,
                    )
                    for a, r in zip(chunk, chunk_results, strict=True):
                        results_by_input[a.input_path] = r

            for assignment in assignments:
                result = results_by_input[assignment.input_path]
                realized[assignment.profile.name] += 1
                if result.status == "ok":
                    n_ok += 1
                else:
                    n_fail += 1
                    logger.warning(
                        "render failed: %s — %s", assignment.input_path, result.stderr
                    )
                rel_out = (
                    str(result.output_path.relative_to(args.output))
                    if result.output_path
                    else None
                )
                mf.write(
                    ManifestEntry(
                        input_path=assignment.input_path,
                        output_path=rel_out,
                        profile_name=assignment.profile.name,
                        render_status=result.status,
                        render_stderr=result.stderr,
                    )
                )

    run_end = iso_now()
    write_run_config(
        args.output / "run_config.json",
        {
            "tool_version": __version__,
            "plantuml_version": plantuml_version,
            "plantuml_jar_path": str(plantuml_jar) if plantuml_jar else None,
            "input_dir": str(args.input),
            "output_dir": str(args.output),
            "profiles_yaml_path": str(args.profiles),
            "seed": seed,
            "format": args.format,
            "threads": args.threads,
            "n_input_files": len(inputs),
            "n_rendered_ok": n_ok,
            "n_rendered_fail": n_fail,
            "realized_profile_counts": dict(realized),
            "run_start_iso": run_start,
            "run_end_iso": run_end,
        },
    )

    if args.dry_run:
        logger.info("dry-run complete: %d assignments written to manifest", len(inputs))
    else:
        logger.info("done: %d ok, %d fail", n_ok, n_fail)
    return 0 if n_fail == 0 else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        ps = load_profile_set(args.path)
    except FileNotFoundError as e:
        logger.error("file not found: %s", e)
        return 1
    except ProfileValidationError as e:
        logger.error("validation failed: %s", e)
        return 1
    print(f"OK: {len(ps.profiles)} profile(s), {len(ps.sampling)} sampling entry/entries")
    return 0


def _cmd_list_themes(args: argparse.Namespace) -> int:
    try:
        plantuml_jar = resolve_plantuml_jar(args.plantuml_jar)
        java = detect_java()
    except (PlantumlNotFoundError, JavaNotFoundError) as e:
        logger.error(str(e))
        return 2
    result = subprocess.run(
        [java, "-jar", str(plantuml_jar), "-listthemes"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
