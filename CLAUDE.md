# CLAUDE.md

Guidance for Claude Code working in this repository.

---

## Project Goal

A CLI tool — **`chameleon`** — that renders a directory of PlantUML
source files into visually diversified images by applying a set of named
**profiles** (theme + skinparams + handwritten mode), with each
input file assigned to exactly one profile via probability-weighted sampling.

The tool is a demonstration artifact for a 5–6 slide conference
methodology paper on visual diversification of image-to-PlantUML datasets
using PlantUML's native rendering controls.

The methodology paper's contribution: a parameterized, reproducible
methodology for diversifying image-to-PlantUML datasets without modifying
underlying `.puml` source files. This tool is the operational realization
of that methodology.

---

## Scope

### In scope
- CLI tool (no GUI, no web UI)
- Profile schema (YAML)
- Per-file probability-weighted profile assignment
- Invocation of `plantuml.jar` via subprocess
- Run metadata logging (which file rendered with which profile, with what seed)
- Reproducibility via random-seed control

---

## Core Concepts

### Profile

A named, reusable bundle of PlantUML rendering settings. Specified in YAML.

```yaml
name: whiteboard
theme: sketchy            # PlantUML --theme value, or null
skinparams:               # passed as -S<key>=<value>
  shadowing: false
  defaultFontName: Comic Sans MS
handwritten: true         # emitted as `!option handwritten true`
```

A profile is the abstract specification. It is reusable across runs and
datasets, version-controllable, and citeable in the paper.

### Profile Set

A list of profiles paired with sampling probabilities. Probabilities should
sum to 1.0 (tool normalizes if they don't, with a warning).

```yaml
sampling:
  - profile: default
    probability: 0.4
  - profile: whiteboard
    probability: 0.2
  - profile: corporate
    probability: 0.3
  - profile: monochrome
    probability: 0.1
```

### PlantUML Config File

An ephemeral text file the tool generates per-profile, containing PlantUML
directives derived from the profile. Passed via `--config` to plantuml.jar.

This is an internal implementation detail — users never write these directly.

```
' generated from profile: whiteboard
!option handwritten true
skinparam shadowing false
left to right direction
```

### Per-file Assignment Semantics

For each `.puml` file in the input directory:
1. Sample one profile from the profile set using its probability weight
2. Render that file with that profile, producing one image
3. Log the (file, profile, seed) tuple in the run manifest

N input files → N output images. Realized per-profile counts are stochastic
and logged in run metadata.

---

## CLI Specification

### Primary command

```
chameleon run \
    --input <dataset_dir> \
    --profiles <profiles.yaml> \
    --output <output_dir> \
    [--seed <int>] \
    [--format png|svg] \
    [--threads <n>] \
    [--limit <n>] \
    [--dry-run]
```

### Options

- `--input` — directory containing `.puml` files (recursive search)
- `--profiles` — path to YAML defining profiles + sampling weights
- `--output` — directory for rendered images and run manifest
- `--seed` — RNG seed for reproducible profile assignment (default: random, but logged)
- `--format` — output image format (default: png)
- `--threads` — parallelism for plantuml invocations (default: CPU count)
- `--limit` — process at most N input files (for testing)
- `--dry-run` — assign profiles and write manifest, but skip rendering
- `--plantuml-jar` — path to plantuml.jar (alternative: `PLANTUML_JAR` env var)
- `-v`, `--verbose` — DEBUG-level logging (default INFO, on stderr)

### Auxiliary commands

- `chameleon validate <profiles.yaml>` — validate profile YAML against schema
- `chameleon list-themes` — print available PlantUML built-in themes (calls plantuml)

---

## Output Structure

```
<output_dir>/
├── manifest.jsonl              # one line per input file
├── run_config.json             # invocation metadata
├── profiles_used.yaml          # snapshot of profiles input (for reproducibility)
└── images/
    └── <profile_name>/
        └── <relative_input_path>.png
```

### `manifest.jsonl` schema (per line)

```json
{
  "input_path": "subdir/diagram_42.puml",
  "output_path": "images/whiteboard/subdir/diagram_42.png",
  "profile_name": "whiteboard",
  "render_status": "ok|fail|skip",
  "render_stderr": "string"
}
```

### `run_config.json` schema

```json
{
  "tool_version": "x.y.z",
  "plantuml_version": "string (parsed from plantuml.jar --version)",
  "plantuml_jar_path": "string",
  "input_dir": "string",
  "output_dir": "string",
  "profiles_yaml_path": "string",
  "seed": 0,
  "format": "png",
  "threads": 0,
  "n_input_files": 0,
  "n_rendered_ok": 0,
  "n_rendered_fail": 0,
  "realized_profile_counts": { "default": 0, "whiteboard": 0 },
  "run_start_iso": "ISO-8601",
  "run_end_iso": "ISO-8601"
}
```

---

## Profile YAML Schema

Two top-level sections — `profiles` (definitions) and `sampling` (weights).

```yaml
profiles:
  - name: default
    theme: null
    skinparams: {}
    handwritten: false

  - name: whiteboard
    theme: sketchy
    skinparams:
      shadowing: false
    handwritten: true

  - name: corporate
    theme: cerulean
    skinparams:
      shadowing: true
    handwritten: false

  - name: monochrome
    theme: null
    skinparams:
      monochrome: true
    handwritten: false

sampling:
  - profile: default
    probability: 0.4
  - profile: whiteboard
    probability: 0.2
  - profile: corporate
    probability: 0.3
  - profile: monochrome
    probability: 0.1
```

### Validation rules
- Each profile `name` is unique
- Every `sampling.profile` references a defined profile
- `sampling` probabilities are non-negative; warn and normalize if sum != 1.0
- `theme` is either `null` or a non-empty string (no validation against
  PlantUML's actual theme list — that's runtime responsibility)
- `skinparams` keys/values are passed through as strings to plantuml
- `handwritten` is boolean

---

## PlantUML Invocation

### How profiles map to plantuml CLI

Given a profile, generate a temporary config file and invoke plantuml:

```
plantuml \
    --theme <profile.theme>                    # if non-null
    --config <generated_config.tmp>            # always
    --format <format>                          # png/svg
    --output-dir <output_dir>/images/<profile_name>/<relative_subdir>
    <input.puml>
```

### Generated config file content

```
' generated by chameleon from profile: <name>

!option handwritten true                    ' if profile.handwritten (omitted when false)

skinparam <key> <value>                     ' for each profile.skinparams entry
```

**Important:** `--config` content is prepended to the source. Test that
themes loaded via `--theme` and skinparams set via the config file
compose correctly. There can be ordering issues. If a skinparam fails to
override a theme value, switch to setting it via `-S` instead.

### Subprocess management

- Use `subprocess.run` with explicit timeout (e.g., 60s per file)
- Capture stdout and stderr for the manifest
- Pin `plantuml.jar` path via env var `PLANTUML_JAR` or CLI flag
- Validate `plantuml.jar` exists at startup; fail fast if missing
- Detect plantuml version via `--version` and log it
- **Per-file success in batch mode is reconciled from stderr, not exit code.**
  PlantUML's exit code is unreliable when batching multiple files. `render_batch`
  groups stderr lines by the `Error line N in file: <path>` / `Warning: no image in: <path>`
  pattern to attribute failures, then falls back to checking that the expected
  `<stem>.<format>` exists on disk. `MAX_BATCH_SIZE = 200` caps a single invocation.

### Performance

- JVM startup is expensive (~1s per invocation). Two options:
  1. **Multi-file batching** — pass multiple files in one plantuml invocation
     (same profile only). Simpler.
  2. **Long-lived plantuml HTTP server** — `plantuml --http-server`, post
     requests. Faster but more complex.
- Start with option 1. Switch to option 2 only if rendering becomes the
  bottleneck on real datasets.
- Parallelize across profiles trivially with `concurrent.futures`.

---

## Repository Layout

```
.
├── CLAUDE.md
├── README.md
├── PLAN.md                     # checklist of in-progress paper work
├── pyproject.toml
├── plantuml-1.2025.9.jar       # pinned jar (matches pyproject expected_plantuml_version)
├── src/
│   └── chameleon/
│       ├── __init__.py
│       ├── cli.py              # argparse entry point
│       ├── profile.py          # Profile, ProfileSet dataclasses + YAML I/O
│       ├── sampler.py          # probability-weighted assignment with seed control
│       ├── renderer.py         # plantuml subprocess invocation (multi-file batching)
│       ├── config_gen.py       # profile -> plantuml config file
│       └── manifest.py         # JSONL manifest + run_config.json + profiles snapshot
├── tests/
│   ├── test_cli.py
│   ├── test_profile.py
│   ├── test_sampler.py
│   ├── test_config_gen.py
│   ├── test_manifest.py
│   ├── test_renderer.py
│   ├── test_smoke.py
│   └── fixtures/
│       ├── tiny_dataset/       # 5 puml files for tests
│       └── profiles_e2e.yaml   # 4-profile curated set used by the e2e script
├── scripts/
│   └── run_e2e.py              # demo runner: 50 puml_files × 4 profiles, formatted report
├── puml_files/                 # paper dataset (~270 .puml files)
└── output/                     # generated runs (gitignored): images/, manifest.jsonl, run_config.json
```

## Dev Workflow

```bash
# install dev deps (one-time, into .venv)
pip install -e '.[dev]'

# tests + lint
pytest -q                    # 67 tests, ~8s
ruff check .
ruff format .

# end-to-end demo (renders 50 files × 4 profiles into output/e2e_<UTC_TS>/)
python scripts/run_e2e.py

# CLI smoke
chameleon validate tests/fixtures/profiles_e2e.yaml
chameleon run --input tests/fixtures/tiny_dataset \
              --profiles tests/fixtures/profiles_e2e.yaml \
              --output output/manual_run \
              --plantuml-jar plantuml-1.2025.9.jar --seed 42
```

`PLANTUML_JAR` env var is an alternative to `--plantuml-jar`. The repo ships
a pinned `plantuml-1.2025.9.jar` at the root.

---

## Conventions

### Determinism & reproducibility
- All randomness flows through one seeded RNG (Python `random.Random(seed)`)
- If `--seed` is not provided, generate one, log it, use it
- Same seed + same input dir + same profiles MUST produce the same per-file
  assignment
- Order of file iteration must be deterministic (sort by relative path)

### Logging
- Use stdlib `logging`; default INFO level
- Log to stderr; manifest goes to disk
- One progress line per N files (configurable)

### Error handling
- A single file render failure must NOT abort the run; log it and continue
- Validate profile YAML upfront; fail before invoking plantuml
- Missing `plantuml.jar` → fail at startup with actionable message

### Code style
- Python 3.11+
- Type hints required on public APIs
- ruff for lint + format
- pytest for tests
- Keep dependencies minimal: `pyyaml`, `tqdm`, `pydantic` (optional for schema)

---

## Open Decisions (require user input)

These are not yet decided. Ask before assuming.

1. **Curated profile set for the paper.** Default, Whiteboard, Corporate,
   Monochrome are working candidates (operationalized in
   `tests/fixtures/profiles_e2e.yaml`). Final, or revise before promoting to
   `examples/profiles.yaml`?

### Resolved
- **`plantuml.jar` version: pinned to 1.2025.9.** Matches
  `[tool.chameleon].expected_plantuml_version` in `pyproject.toml`; jar shipped
  at repo root as `plantuml-1.2025.9.jar`.

---

## Things Claude Code Should Avoid

- **Don't add image-level perturbations** (blur, rotation, noise). Out of scope.
- **Don't modify input `.puml` files.** Profiles are non-invasive — config
  file injection only.
- **Don't auto-discover or scrape themes** from the internet. Use what
  PlantUML ships, plus what the user specifies.
- **Don't add image quality / similarity metrics.** Separate work.
- **Don't silently drop files.** Render failures get logged, run continues.
- **Don't bake in implicit defaults** for skinparams. Profiles specify what
  they specify; nothing more.
- **Don't add validation against PlantUML's actual theme list at parse time.**
  Theme name is a string passed to plantuml; let plantuml fail if invalid.
- **Don't optimize prematurely.** Correctness first; only switch from per-file
  plantuml invocation to batched/server mode if profiling shows it's a real
  bottleneck.

---

## Quick References

- PlantUML CLI: https://plantuml.com/command-line
- PlantUML themes: https://plantuml.com/theme
- PlantUML skinparams: https://plantuml.com/skinparam
