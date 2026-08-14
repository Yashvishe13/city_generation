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
    OSMCityBuilder.*  AOSMCityBuilder: dynamic-mesh generation from FOSMCity
  Content/Data/       city.json + CSVs the UE side reads at generate time
  Content/Maps/       CityLevel.umap (default map)
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

## UE specifics worth remembering

- Editor Python is the authoring path for anything asset-shaped (levels, DataTables,
  PCG graphs) — `.uasset` is binary, so do not try to author it by hand.
- UHT rejects a function parameter whose name matches a `UPROPERTY` in the same class
  (shadowing) — hence `InHeightBiasCm`.
- Python property names are snake_case *without* the bool `b` prefix:
  `bBuildOnConstruction` → `build_on_construction`.
- Geometry from `GeometryScriptingCore`
  (`UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSimpleExtrudePolygon`, etc.).

## State / next steps

Done: pipeline (fetch→export), C++ loader + dynamic-mesh builder, headless `CityLevel`
authoring, verified 343 buildings / 41 roads for `midtown_small`.

Next: PCG graph (`BP_CityGenerator` / `PCG_City`) that consumes the same exports —
buildings as PCG points + dynamic-mesh extrusion, roads as PCG splines; then
report.md with the overhead side-by-side, then demo.mp4.
