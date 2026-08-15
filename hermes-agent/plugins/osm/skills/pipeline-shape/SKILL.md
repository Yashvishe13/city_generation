---
name: pipeline-shape
description: What the generated pipeline must be as an artifact - one self-contained file, no absolute paths, real self-checks. Load before writing any pipeline code.
---

# The shape of the artifact

You are writing **one file**: `agent_scripts/<area>/pipeline.py`. It is the deliverable,
not scaffolding around a deliverable. A reviewer on another machine clones the repo, runs
that one file, and gets `data/ue/<area>/scene.json`. If anything else has to happen first,
the pipeline is not finished.

## One file, end to end

The whole job lives in it, in this order:

```
fetch (Overpass, cached) -> inspect -> fit -> project -> resolve parts -> emit scene.json -> self-check
```

No stage may be satisfied by something that already ran. In particular **you must write
the fetch**; there is no tool that downloads for you. A pipeline that opens
`data/raw/<area>.geojson` and exits with "run the fetch first" is a fragment, not a
pipeline. See `osm:fetching` for how the download works and `osm:inspection` for what to
measure once you have it.

Standard library only — `urllib.request`, `json`, `math`, `collections`. **pyproj,
shapely and numpy are not installed** and will not be. The projection is fifteen lines
(`osm:coordinates`), the ring tests are twenty (`osm:inspection`).

Splitting helpers into a second file in the same directory is acceptable if the file
genuinely gets unwieldy, but the entry point must still run standalone with no
installation step and no `sys.path` surgery.

## Command line

```
python3 agent_scripts/<area>/pipeline.py --area <name> [--repo PATH] [--force] [--verify]
```

- `--area` — which area, defaulting to the one this pipeline was written for.
- `--repo` — project root. **Must actually be honoured.** The tools and shell wrappers
  pass it; a pipeline whose argparse does not define it exits with an argparse error
  instead of running, and one that defines it and ignores it is worse.
- `--force` — re-download instead of reusing the cache.
- `--verify` — run the self-checks (see below).

## Paths: nothing absolute, ever

Derive the root, do not name it:

```python
REPO_ROOT = Path(args.repo or os.environ.get("CITYGEN_REPO")
                 or Path(__file__).resolve().parents[2])
```

Everything else hangs off that: `REPO_ROOT / "data" / "raw"`,
`REPO_ROOT / "data" / "ue" / area`, `REPO_ROOT / "data" / "areas.json"`.

Banned outright, because each of these has actually shipped in this project:

- a literal `"/Users/..."` — a previous pipeline hardcoded the author's checkout as
  `project_root` and was unrunnable anywhere else;
- `/opt/homebrew/bin/python3` or any other interpreter path — use `sys.executable`;
- `~` expansion, `$HOME`, or any user, machine or volume name.

**This applies to what you write, not only to what you read.** Provenance recorded in
`scene.json` and in the fetch sidecar must be repo-relative — `"data/raw/<area>.geojson"`,
never the resolved absolute path. An absolute path in the manifest is both a leak into
the delivered artifact and a broken determinism claim: the same input then produces
different bytes on a different machine, and "byte-identical rerun" stops meaning anything.

## Caching

The fetch writes `data/raw/<area>.geojson` and `data/raw/<area>.fetch.json` and reuses
them on every later run unless `--force`. Re-running the pipeline must not re-hit
Overpass — the mirrors rate-limit, and a reviewer running it three times should not be
punished for it.

## Determinism

Same input, byte-identical output. No RNG. No wall-clock timestamp inside `scene.json`.
Sort anything whose order comes from a dict or a set before emitting. Round to whole
centimetres. Confirm it by running twice and comparing the files, and say in your report
that you did.

## `--verify` must be able to fail

A self-check that prints "checks passed" without evaluating anything is worse than having
none, because it removes the reason to look. This exact line shipped here:

```python
print("VERIFY MODE: basic checks passed (projection math, CCW, counts >0)")   # asserts nothing
```

and three lines below it a sample projection was computed, printed with the comment
"(should be ~0,0)", and never compared to anything.

So: every check is an assertion with a threshold, failures print what failed and what the
value was, and the process exits non-zero. At minimum re-project the origin and assert it
lands within a centimetre of (0,0); assert every emitted ring is counter-clockwise;
assert `height_cm > base_cm` on every extrude; assert each node count is what the
manifest claims. Then run `osm_verify_scene`, which re-derives from the OSM extract
rather than trusting your manifest, and fix what it reports.

Your own checks and the verifier catch different things. Run both.
