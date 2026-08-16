# CityGen — OSM → UE 5.7 PCG city reconstruction

Task UE-3. Translate a real city area from OpenStreetMap into UE 5.7 and generate it
with the PCG framework. Graded manually on geometric fidelity + pipeline automation.
Materials/textures are NOT graded — grey-box geometry is fine.

The translator is **written per area by a coding agent**, not shipped as a fixed program.
Tagging habits differ enormously between cities, so a rule fitted on one area is useless
on another; the agent measures the area, then writes a pipeline fitted to it. What stays
constant is the contract it writes against, which lives in skills.

## Layout

```
data/areas.json       area presets: bbox + what each area's tagging is actually like
data/raw/             Overpass payload, GeoJSON (all tags), <area>.fetch.json provenance
data/ue/<area>/       scene.json — the translated scene
agent_scripts/<area>/ PLAN.md + pipeline.py — agent-generated, one directory per area,
                      not maintained by hand
hermes-agent/         vendored Hermes agent framework; the project's part is plugins/osm/
  plugins/osm/
    skills/           the contract the agent writes against (7 skills, see below)
    verify_scene.py   independent verifier: re-derives the scene from the OSM extract
    tools.py          the single tool, osm_verify_scene
UnrealProject/        UE 5.7 project "CityGen"
  Source/CityGen/     C++ module
    OSMCityData.*     FOSMScene structs + scene.json loader (UOSMCityDataLibrary)
    OSMCityGeometry.* UOSMCityGeometry: footprint extrusion, road ribbons, ground
    PCGOSMCity.*      UPCGOSMCitySettings: PCG source node (the graded path)
    CityGeneratorActor.* ACityGeneratorActor: PCGComponent host, parent of BP_CityGenerator
    OSMCityBuilder.*  AOSMCityBuilder: same geometry without PCG (preview/reference)
  Content/Data/City/  scene.json — the one file the engine reads (area-neutral slot)
  Content/Maps/       CityLevel.umap (default map)
  Content/PCG/        PCG_City graph
  Content/Blueprints/ BP_CityGenerator
  Scripts/            UE editor Python (asset/level authoring, headless)
tools/                agent_task / verify_area / stage_area / build_ue / ue_run / find_python
docs/                 report.html + figures, agent-prompts/, area_survey.*, hermes-service.md
demo/                 demo.mp4 (mandatory 30–90 s)
```

## Conventions that must not drift

- **Axes**: UE `+X = North`, `+Y = East`, `+Z = Up`, units **centimetres**.
  Origin = the centre of the *requested* bbox. Buffering the fetch must not move it.
  Top-down in the editor then matches a north-up map.
- **Projection**: local tangent plane at the origin using the WGS84 radii of curvature.
  Not `111320 * cos(lat)` — that ignores the ellipsoid and drifts ~0.1–0.2% per km.
  Recorded in the manifest; never hardcode a scale factor elsewhere.
- **The scene contract**: `data/ue/<area>/scene.json`, three geometric primitives —
  `extrude` (CCW ring + `base_cm` + `height_cm`), `mesh` (indexed triangles, absolute
  coords), `ribbon` (polyline + `width_cm`). `kind` is a *primitive*, never a feature
  type: a canal is a `ribbon` tagged `water`. That is what lets a new feature class ship
  without touching C++.
- **Footprint rings**: exterior ring, CCW in (X,Y), first vertex **not** repeated.
  OSM repeats it; strip it *before* computing winding or self-intersection.
  `AppendSimpleExtrudePolygon` produces inside-out solids on CW input.
- **Heights**: stated → fitted from this area → borrowed with the source named → refuse.
  Refusing a value is not the same as dropping the feature: footprint fidelity is the
  most heavily weighted thing graded, so keep the volume and label the estimate. Every
  height and width carries its provenance in `attrs`, and the distribution goes in the
  manifest.
- **Roof height is contained in `height`** (OSM Simple 3D Buildings). Walls stop at
  `height - roof:height`; adding a roof on top makes every roofed building too tall.
- **`building:part` vs parent**: parts overlap the parent outline they belong to.
  Extruding both double-builds every tower and buries the setbacks inside a slab.
  Resolve which one describes the massing, and count the resolution in the manifest.
- **No absolute paths.** Not in a generated pipeline, not in what it writes. Repo root is
  derived from `--repo` / `CITYGEN_REPO` / `__file__`; provenance in `scene.json` is
  repo-relative. An absolute path bakes one checkout into the delivered artifact and
  makes the byte-identical claim false anywhere else. The one exception is
  `tools/ai.hermes.serve-citygen.plist`, which launchd cannot parameterise — it says so
  in its header.
- **Reproducibility**: `data/ue/<area>/scene.json` and everything in `Content/Data/City`
  is regenerable by running the area's pipeline plus `tools/stage_area.sh`. No
  hand-placed geometry. Same input → byte-identical output; no RNG, no timestamps inside
  the geometry files.

## Commands

```bash
python3 agent_scripts/nyc_midtown/pipeline.py --area nyc_midtown   # translate (cached fetch)
python3 agent_scripts/nyc_midtown/pipeline.py --area nyc_midtown --verify
tools/verify_area.sh nyc_midtown                    # independent check vs the OSM source
tools/stage_area.sh nyc_midtown                     # -> Content/Data/City/scene.json
tools/build_ue.sh                                   # compile CityGenEditor
tools/ue_run.sh UnrealProject/Scripts/bootstrap_city_level.py   # headless level author
tools/find_python.sh                                # a Python 3.10+ on this machine
```

Areas are presets in `data/areas.json` (`nyc_midtown`, `vienna_innere`,
`boston_financial`, `chicago_loop`, `paris_marais`); any bbox works. `nyc_midtown` is the
working area — richest height data, and it contains every hard case (parts over parents,
roofs, parts starting above ground, zero road width tags).

## The agent

Hermes (`grok-4.6`, isolated profile `citygen`, launchd service — `docs/hermes-service.md`).

```bash
tools/agent_task.sh docs/agent-prompts/task_pipeline_nyc_midtown.txt \
  --expect agent_scripts/nyc_midtown/pipeline.py \
  --expect data/ue/nyc_midtown/scene.json \
  --verify-cmd "tools/verify_area.sh nyc_midtown"
```

- **Skills, not data tools.** Eight skills in `hermes-agent/plugins/osm/skills/`:
  `pipeline-plan` (load first), `pipeline-shape`, `scene-contract`, `coordinates`,
  `fetching`, `inspection`, `roads`, `estimation`. Plugin skills are **not** in the system
  prompt's `<available_skills>` index and are not auto-discovered — a skill must be in
  the `SKILLS` tuple in `plugins/osm/__init__.py` *and* named verbatim in the prompt.
- **The agent writes the fetch and the analysis itself.** There used to be
  `osm_fetch_area` / `osm_tag_stats` / `osm_quality_check` / `osm_run_pipeline` tools;
  handing over finished data produced a pipeline that could not run without the tool that
  fed it, and that hardcoded the author's checkout because a tool had resolved paths for
  it. `plugins/osm/README.md` records this.
- **`osm_verify_scene` stays a tool** because it must not be the agent's own code — it
  re-derives from the raw extract instead of reading the pipeline's manifest.
- **Nothing trusts the report.** `--expect` requires artifacts newer than the run;
  `--verify-cmd` runs the checks here. An agent has claimed completed work twice in this
  project without touching a file, once quoting a verifier result it never obtained.
- `agent_task.sh` steps reasoning effort down on retry: xAI's gateway drops the
  connection when the thinking phase outlasts the proxy's idle timeout, before any
  content token arrives.

## PCG wiring

`PCG_City` = `OSM City Source` (custom C++ node, **two** output pins) → one
`Spawn Dynamic Mesh`. Everything — extrudes, meshes, ribbons and the ground slab —
arrives on the single `Meshes` pin carrying its node's tags, so a feature class the
pipeline invents later needs no new pin and no C++. `Splines` (one per ribbon centreline)
is emitted but unconnected, ready for a spline-mesh road pass. Spawned components are
PCG-managed, so regeneration replaces them instead of stacking.

Build order in `FPCGOSMCityElement::ExecuteInternal`: extrudes → meshes → ribbons →
ground. `AOSMCityBuilder` uses the reverse (ground → ribbons → extrudes → meshes) because
it puts them in separate components. **Order does not position anything** — every node
carries absolute Z, so the stack is decided by the pipeline, not the engine.

`BP_CityGenerator` derives from `ACityGeneratorActor`, which owns the `PCGComponent`
and calls `Generate` from its construction script — opening `CityLevel` regenerates
the city with no manual step. `Generate City` / `Cleanup City` buttons force it.

Both the PCG node and `AOSMCityBuilder` read `CityDataDir = "Data/City"` relative to
`Content/`, and both go through `UOSMCityDataLibrary::LoadSceneFromDirectory`, so the
reference path and the graded path cannot drift.

## UE specifics worth remembering

- Editor Python is the authoring path for anything asset-shaped (levels, DataTables,
  PCG graphs) — `.uasset` is binary, so do not try to author it by hand.
- UHT rejects a function parameter whose name matches a `UPROPERTY` in the same class
  (shadowing) — hence `InHeightBiasCm`.
- Python property names are snake_case *without* the bool `b` prefix:
  `bBuildOnConstruction` → `build_on_construction`.
- Geometry from `GeometryScriptingCore`
  (`UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSimpleExtrudePolygon`, etc.).
- Node layout is `node.set_node_position(x, y)`, not editor properties.
- `PCGComponent::Graph` is protected — use `set_graph()` from Python.
- A `PCGComponent` whose actor has no volume logs "Component has invalid bounds, not
  registered" and silently generates nothing; `ACityGeneratorActor` therefore roots a
  `UBoxComponent` (`BoundsExtentCm`).
- `GenerateOnLoad` fires for game worlds, *not* when the editor opens a map — hence the
  construction-script trigger.
- PCG generation is asynchronous and cannot be flushed inside a `-run=pythonscript`
  commandlet. Headless runs only schedule it; verify by launching the editor and
  grepping `~/Library/Logs/Unreal Engine/CityGenEditor/CityGen.log` for
  `OSM City Source` (the project's `Saved/Logs` stays empty on Mac).
- `python3` on this machine resolves to a broken 3.5 framework build. Scripts use
  `tools/find_python.sh`, which takes `$PYTHON` or the first 3.10+ interpreter on PATH.

## State / next steps

`agent_scripts/nyc_midtown/` regenerated under the nine-skill harness. 2811 nodes: 2294
extrude (1648 building volumes + 646 pedestrian curb prisms), 344 mesh (114 roofs, 87
junction caps, 143 ground cover), 173 ribbons. 97.6% of heights from `tag:height`,
byte-identical on re-run, confirmed loading in the editor with 0 skipped.

Fixed in this round: ground cover (Bryant Park has a lawn), curbs as `extrude` prisms
rather than flat plates, below-grade exclusion applied to buildings (3 subway complexes
that were standing on the street, and were inflating the scene to ~6x its requested area),
and the fetch cache keyed on the query rather than on the filename.

Still open: no blocks or parcels — a city block is not an OSM object, so they would have to
be derived as faces of the road graph; the underground is excluded rather than modelled;
9 of 453 sidewalk rings self-intersect after cm rounding and are dropped; the scene still
spans 1438 x 1245 m against a 611 x 591 m request because Overpass returns intersecting
ways whole; `demo/demo.mp4` (30-90 s) is not recorded.

`docs/report.html` is current with all of the above.
