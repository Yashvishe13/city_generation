# CityGen — OSM → UE 5.7 PCG city reconstruction

Task UE-3. Translate a real city area from OpenStreetMap into UE 5.7 and generate it
with the PCG framework. Graded manually on geometric fidelity + pipeline automation.
Materials/textures are NOT graded — grey-box geometry is fine.

## Layout

```
pipeline/osm2pcg/     Python translator: fetch → parse → project → export
  fetch.py            Overpass API download (cached in data/raw/)
  parse.py            OSM tags → typed features; height derivation
  project.py          WGS84 → local tmerc metres → UE cm; polygon cleanup
  export.py           city.json / buildings.json / roads.json / *.csv / GeoJSON
  preview.py          matplotlib overhead PNG (report side-by-side, sanity check)
  cli.py              `osm2pcg --area midtown`
data/raw/             Raw Overpass JSON (gitignored) + <area>.geojson
data/out/<area>/      Translated exports
UnrealProject/        UE 5.7 project "CityGen"
  Source/CityGen/     C++ module
    OSMCityData.*     FOSMCity structs + JSON loader (UOSMCityDataLibrary)
    OSMCityGeometry.* UOSMCityGeometry: footprint extrusion, road ribbons, ground
    PCGOSMCity.*      UPCGOSMCitySettings: PCG source node (the graded path)
    CityGeneratorActor.* ACityGeneratorActor: PCGComponent host, parent of BP_CityGenerator
    OSMCityBuilder.*  AOSMCityBuilder: same geometry without PCG (preview/reference)
  Content/Data/       city.json + CSVs the UE side reads at generate time
  Content/Maps/       CityLevel.umap (default map)
  Content/PCG/        PCG_City graph
  Content/Blueprints/ BP_CityGenerator
  Scripts/            UE editor Python (asset/level authoring, headless)
tools/                regen.sh / build_ue.sh / ue_run.sh
docs/                 report.md, previews, notes
demo/                 demo.mp4 (mandatory 30–90 s)
```

## Conventions that must not drift

- **Axes**: UE `+X = North`, `+Y = East`, `+Z = Up`, units **centimetres**.
  Origin = the area bbox centre. Top-down in the editor then matches a north-up map.
- **Projection**: local Transverse Mercator centred on the origin
  (`+proj=tmerc +lat_0=… +lon_0=… +k=1 +units=m`). Recorded in `manifest.json`;
  never hardcode a scale factor elsewhere.
- **Footprint rings**: exterior ring, CCW in (X,Y), first vertex **not** repeated.
  `AppendSimpleExtrudePolygon` produces inside-out solids on CW input.
- **Heights**: `height` tag → `building:levels × 3.2 m` → per-`building=*` estimate →
  12 m default. Every building carries `height_source` so the report can quantify this.
- **`building:part` vs parent** (`parts.py`): a parent envelope covered ≥55% by its
  parts is dropped (the parts *are* the massing); parts under 40 m² are ornaments and
  dropped; parts not claimed by a parent are dropped. Extruding both parent and parts
  double-builds every tower and turns spires into free-standing needles — do not
  "simplify" this away. Stats land in `manifest.json.building_part_resolution`.
- **Reproducibility**: anything in `Content/Data` or the level must be regenerable by
  `tools/regen.sh <area>`. No hand-placed geometry. Re-running clears before building
  (`AOSMCityBuilder::ClearCity`), so no stale actors/meshes.

## Commands

```bash
pipeline/.venv/bin/osm2pcg --area midtown_small     # translate (cached fetch)
pipeline/.venv/bin/osm2pcg --bbox 41.87 -87.64 41.88 -87.62 --name loop2
tools/build_ue.sh                                   # compile CityGenEditor
tools/ue_run.sh UnrealProject/Scripts/bootstrap_city_level.py   # headless level author
tools/regen.sh midtown                              # full pipeline → level
```

Areas are presets in `pipeline/osm2pcg/config.py` (`midtown`, `midtown_small`, `loop`).
`midtown_small` is the fast iteration area (~340 buildings).

## PCG wiring

`PCG_City` = `OSM City Source` (custom C++ node, 4 output pins) → three
`Spawn Dynamic Mesh` nodes for Buildings / Roads / Ground. `RoadSplines` is emitted
but unconnected, ready for a spline-mesh road pass. Spawned components are PCG-managed,
so regeneration replaces them instead of stacking.

`BP_CityGenerator` derives from `ACityGeneratorActor`, which owns the `PCGComponent`
and calls `Generate` from its construction script — opening `CityLevel` regenerates
the city with no manual step. `Generate City` / `Cleanup City` buttons force it.

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

## State / next steps

Done: pipeline (fetch→export); C++ loader, shared geometry lib; PCG source node +
`PCG_City` graph + `BP_CityGenerator`; non-PCG reference builder; headless authoring of
everything. Verified live in the editor: `midtown_small` → 343 buildings, 41 road
ribbons, 41 splines.

Next: run the bigger `midtown` area; road spline meshes off the `RoadSplines` pin;
`report.md` with the overhead side-by-side; `demo/demo.mp4` (30–90 s, hard gate).
