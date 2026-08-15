# CityGen — OpenStreetMap → Unreal Engine 5.7 (PCG)

Reconstructs a real city area in UE 5.7 from OpenStreetMap: buildings, roads and ground,
extruded and placed from the source data, with no hand-modelling.

The translation is not a fixed program. A coding agent writes a **pipeline per area**,
because tagging habits differ enormously between cities — Midtown Manhattan states
`height` on 84% of buildings, Le Marais on 1 building in 694, and a rule fitted on one is
useless on the other. The agent measures the area first, then writes a translator fitted
to it. What stays constant is the contract it writes against.

Default area: **Midtown Manhattan** (`nyc_midtown`). Four more presets in
`data/areas.json`.

## Quick start

```bash
# 1. Translate an area: Overpass -> data/ue/<area>/scene.json. One self-contained file.
python3 agent_scripts/nyc_midtown/pipeline.py --area nyc_midtown

# 2. Check it against the original OSM extract (not against its own manifest)
tools/verify_area.sh nyc_midtown

# 3. Stage it into the engine's area-neutral slot
tools/stage_area.sh nyc_midtown

# 4. Compile the C++ module
tools/build_ue.sh
```

Then open `UnrealProject/CityGen.uproject`. `CityLevel` is the default map and contains
`BP_CityGenerator`, which regenerates the city from
`Content/Data/City/scene.json` on load. **Generate City** / **Cleanup City** in its
details panel force it.

Requires UE 5.7 at `/Users/Shared/Epic Games/UE_5.7` (override with `UE_ROOT`), Xcode
command-line tools, and Python ≥ 3.10 (`tools/find_python.sh` locates one; override with
`PYTHON`). The translation stage needs no third-party packages at all — standard library
only.

## Data flow

```
data/areas.json ──► bbox
       │
       ▼
Overpass API ──fetch──► data/raw/osm_<area>.json        raw payload, untouched
                        data/raw/<area>.geojson         every OSM tag preserved
                        data/raw/<area>.fetch.json      bbox, endpoint, query, licence
       │                                                (cached; --force re-downloads)
       ├─inspect──► tag coverage, ring extrudability, road width availability
       │
       ├─fit──────► storey height, lane width, height estimator — from THIS area
       │
       ├─project──► local tangent plane at the bbox centre
       │            → metres → ×100 → UE cm, +X = North, +Y = East, +Z = Up
       │
       └─emit─────► data/ue/<area>/scene.json
                        │  tools/stage_area.sh
                        ▼
                   UnrealProject/Content/Data/City/scene.json
                        │  UOSMCityDataLibrary::LoadSceneFromDirectory
                        ▼
     PCG_City graph:  OSM City Source ──Meshes───► Spawn Dynamic Mesh
                                      ──Splines──► (spare pin for spline meshes)
                        │  run by the PCGComponent on BP_CityGenerator in CityLevel
                        ▼
                   PCG-managed dynamic mesh components (regenerate = replace)
```

`AOSMCityBuilder` builds the identical geometry without PCG; both call `UOSMCityGeometry`,
so the reference path and the PCG path cannot drift.

## The scene contract

`scene.json` is the only file the engine reads, and it knows nothing about
OpenStreetMap — no tag names, no highway classes, no roof vocabulary. Everything arrives
as one of three geometric primitives:

| kind | geometry | used for |
|---|---|---|
| `extrude` | closed CCW ring + `base_cm` + `height_cm` | building volumes, any prism |
| `mesh` | indexed triangles, absolute coordinates | roofs, anything the others cannot express |
| `ribbon` | polyline + `width_cm` | roads, paths, any flat strip |

`tags` carry meaning; `attrs` carry provenance — every derived height and width names its
source (`tag:height`, `lanes*3.25m`, `class_default:residential=10m`, a fitted estimate),
so a reviewer can separate what was measured from what was assumed without reading code.
The manifest records the projection, origin, axis convention, every assumption the run
used, and a count of everything skipped, by reason.

Full spec: `hermes-agent/plugins/osm/skills/scene-contract/SKILL.md`.

## The agent

A Hermes agent (`grok-4.6`, isolated profile `citygen`) writes each pipeline. It is given
**skills, not data tools**: the contract, the projection, the fetch protocol, what to
measure, how to estimate honestly — and it writes the code for all of it.

```bash
tools/agent_task.sh docs/agent-prompts/task_pipeline_nyc_midtown.txt \
  --expect agent_scripts/nyc_midtown/pipeline.py \
  --expect data/ue/nyc_midtown/scene.json \
  --verify-cmd "tools/verify_area.sh nyc_midtown"
```

Nothing trusts the agent's report: `--expect` requires each artifact to exist and to be
newer than the run, and `--verify-cmd` executes the checks here rather than believing an
account of them. The one tool the agent gets is `osm_verify_scene`, which re-derives the
scene from the raw OSM extract — a grader it wrote itself would be wrong in the same way
its pipeline is.

See `hermes-agent/plugins/osm/README.md` for why the fetch and analysis tools were
removed, and `docs/hermes-service.md` for how the agent is run.

## Layout

```
data/areas.json             area presets (bbox + what each area's tagging is like)
data/raw/                   Overpass payload + GeoJSON + provenance (cached)
data/ue/<area>/scene.json   the translated scene
agent_scripts/<area>/       PLAN.md + pipeline.py — agent-generated, one per area
hermes-agent/plugins/osm/   the skills (the contract) + the scene verifier
docs/agent-prompts/         the prompts that produced each pipeline
UnrealProject/              UE 5.7 project — C++ module, PCG graph, level
tools/                      agent_task / verify_area / stage_area / build_ue / ue_run
```

## Status

- [x] Agent-written per-area pipeline: fetch → inspect → fit → project → `scene.json`
- [x] C++ loader + dynamic-mesh generation (`UOSMCityGeometry`)
- [x] PCG graph `PCG_City` + `BP_CityGenerator`, regenerating on level load
- [x] Independent verification against the OSM source (`osm_verify_scene`)
- [ ] Roof meshes for the shapes the area actually tags
- [x] [`docs/report.md`](docs/report.md) with the overhead generated-vs-OSM side-by-side
- [ ] `demo/demo.mp4` (30–90 s fly-through)

Data © OpenStreetMap contributors, ODbL.
