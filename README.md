# CityGen — OpenStreetMap → Unreal Engine 5.7 (PCG)

Reconstructs a real city area in UE 5.7 from OpenStreetMap: buildings, roads and ground,
extruded and placed from the source data, with no hand-modelling.

📄 **[Read the technical report](https://yashvishe13.github.io/citygen-report/)** — area and
data source, the pipeline, the overhead comparison against OpenStreetMap, and an honest
self assessment.

The translation is not a fixed program. A coding agent writes a **pipeline per area**,
because tagging habits differ enormously between cities — Midtown Manhattan states
`height` on 84% of buildings, Le Marais on 1 building in 694, and a rule fitted on one is
useless on the other. The agent measures the area first, then writes a translator fitted
to it. What stays constant is the contract it writes against.

Default area: **Midtown Manhattan** (`nyc_midtown`). Four more presets in
`data/areas.json`.

## Getting the project

```bash
git lfs install                                              # once per machine
git clone https://github.com/Yashvishe13/city_generation.git
cd city_generation
```

The Unreal assets, the report figures and `demo/demo.mp4` are stored as ordinary git
objects, so downloading the repository as a ZIP works too. `git lfs install` is still
worth running before cloning: the vendored `hermes-agent/` tree keeps its own images in
LFS, and without it those arrive as pointer files. Nothing in the pipeline or the Unreal
project depends on them.

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


Data © OpenStreetMap contributors, ODbL.
