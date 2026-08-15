# osm plugin

The contract an OSM → Unreal Engine city reconstruction pipeline is written against,
plus the one check that is not allowed to be the agent's own code.

## Skills, not tools

Nine skills, registered in `__init__.py`. They are **explicit loads**: plugin skills do
not appear in the system prompt's `<available_skills>` index, so a task prompt has to
name them verbatim (`osm:pipeline-plan`, and so on) or the agent cannot find them.

| Skill | What it carries |
|---|---|
| `pipeline-plan` | Load first. How to plan, what to write down, and the failures this project has actually hit |
| `pipeline-shape` | What the artifact must be: one self-contained file, no absolute paths, self-checks that can fail |
| `scene-contract` | `data/ue/<area>/scene.json` — the only file Unreal reads, and the rules that break the build |
| `coordinates` | WGS84 → Unreal frame: local tangent plane, cm, +X North / +Y East / +Z Up |
| `fetching` | Writing the Overpass download yourself: query, mirrors, truncation, relations, cache, provenance |
| `inspection` | Measuring an area before interpreting it: tag coverage, ring extrudability, road widths |
| `roads` | The street network: cross-section width, the pedestrian realm, surfaces, junctions |
| `ground-cover` | Water, parks, landuse, the Z stack, and why OSM has no city blocks |
| `estimation` | Deriving heights and widths OSM does not state, without inventing them |

## One tool

| Tool | Purpose |
|---|---|
| `osm_verify_scene` | Check a generated `scene.json` against the contract **and** against the original OSM extract |

It re-derives from the source — reprojecting sample vertices, recomputing road bearings
from lon/lat, counting source features, and comparing the emitted `height_source`
histogram against the tag coverage the extract actually has — rather than reading the
pipeline's own manifest, which only ever confirms the pipeline agrees with itself. That
last check exists because a scene with flawless geometry and every height set to one
invented constant passed everything else: `height_provenance` is the only check that can
see a pipeline losing the meaning while keeping the shapes. Advisory: it returns findings
with offending node ids and a fix hint, and blocks nothing. `tools/verify_area.sh` wraps
it as the acceptance gate for `tools/agent_task.sh --verify-cmd`, so a generation round is
accepted on the checks actually running, never on the agent's account of having run them.

## Why there are no fetch or analysis tools

There were, once: `osm_fetch_area`, `osm_list_areas`, `osm_tag_stats`,
`osm_quality_check`, `osm_run_pipeline`. They worked, and they quietly shaped what the
agent wrote. The brief demanded a self-contained pipeline; what came back opened
`data/raw/<area>.geojson` and exited with *"run osm_fetch_area first"*, and hardcoded
`/Users/<author>/Work/city_generation` as its root because a tool had always resolved
paths for it.

A tool that hands over finished data removes the reason to write the stage that produces
it. So the knowledge those tools encoded — Overpass query construction, mirror retry,
truncation detection at HTTP 200, relation and closed-way handling, tag coverage, ring
extrudability — moved into `osm:fetching` and `osm:inspection`, and the agent writes the
code. The pipeline that results runs anywhere, on its own, which is what it was always
supposed to be.

Verification did not move, for the opposite reason: an agent-authored grader is wrong in
the same way its pipeline is wrong.

## Layout

```
plugin.yaml       manifest
__init__.py       register(ctx): 7 skills + 1 tool schema
tools.py          the osm_verify_scene handler; JSON in, JSON string out
verify_scene.py   the verifier - stdlib only, re-derives from the raw extract
skills/<name>/SKILL.md
```

Area presets live in the project's `data/areas.json`, not here — the pipeline reads them
at runtime. The raw extract is expected in `data/raw/`, overridable per call with
`raw_dir` or globally with `CITYGEN_OSM_OUT_DIR`.
