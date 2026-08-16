# nyc_midtown — OSM → Unreal pipeline plan

Measured from the Overpass extract for the requested bbox
`[40.7500, -73.9860, 40.7555, -73.9790]` plus a 150 m fetch buffer.
Properties are **flat** (tags sit on `properties`; there is no nested
`tags` object). Numbers below are from this area, not from another city.

The previous Midtown pipelines failed in three ways that this plan is
written against:

1. Street network under-built twice: once by dumping every `highway` on
   one Z, once by dropping 1062 non-driveable ways as a single lump.
2. Scene extent exploded to ~1438 × 1567 m against a ~611 × 591 m
   request because three underground station complexes
   (`building=train_station` + `location=underground` + `layer<0`) were
   extruded at street level. Grand Central Terminal is 737 m across.
3. Ground cover was missing because the default selectors do not ask
   for it, and the cache was keyed on filename so a widened query
   silently reused the old 3024-feature extract (1 leisure, 2 landuse,
   0 water, 0 railway).

## Inventory

### Buildings (714 features with `building=*`, including 19 dual-tagged)

- `height` on **606 / 714 = 84.9%**. After parsing, the emit-time
  provenance histogram must show `tag:height` dominating. If it
  collapses to a default, tags were read from the wrong level.
- `building:levels` on 125 (17.5%).
- Both `height` and `building:levels` on **119 parent buildings**
  (the storey-height sample). Median ratio **3.883 m/storey**.
  Leave-one-out using that median: MedAE **2.52 m**.
- Neither tag: 102. Levels only: 6.
- Tagged parent heights (n=606): median **26.25 m**.
- `building=*` is 594× `yes`. Type medians are not a useful estimator.
- 19 features carry both `building` and `building:part`. They are
  large parent outlines, not massing parts — treat them as parents.

### Below-grade buildings (the extent bug)

The same `location` / `layer` / `tunnel` / `indoor` / `level` test
used on highways applies to buildings. This extract has **3** such
buildings, all `building=train_station`:

- Grand Central Terminal underground concourse (`relation/11171793`,
  `location=underground`, `layer=-2`) — up to 737 m across.
- Times Square–42nd Street / Port Authority.
- 34th Street–Herald Square.

**Test the tags, never `building=train_station`.** Grand Central also
appears as `way/265947358`, the real terminal, with no below-grade
marker. That one stays.

### building:part (1065 exclusive parts)

- `height` on **1061 / 1065 = 99.6%**.
- `min_height` on 191 (17.9%); `building:min_level` on 38. This is
  where setbacks start above ground.
- Non-flat `roof:shape` on exclusive parts: 43 skillion, 36 pyramidal,
  18 gabled, 12 hipped, 4 dome, 1 mansard. `roof:height` is present
  on **every** non-flat part (114 / 114).
- Centroid-in-polygon against `building=*` parents assigns essentially
  every part. Parents that own parts are not extruded.

### Rings

Building/part polygons are closed after stripping OSM's repeated
vertex. Interior rings exist (courtyards). The contract is
exterior-only, so holes are counted as skipped, not silently filled.

### Roads (1245 highway features)

Class histogram: footway 865, steps 117, pedestrian 68, secondary 63,
residential 59, primary 32, service 23, cycleway 7, elevator 5,
unclassified 3, primary_link 2, living_street 1.

**Driveable** (primary / secondary / residential / service /
unclassified / living_street + links): **183** (181 LineString + 2
service area polygons). Explicit `width` on driveable: **0**. `lanes`
on 149 / 181 lines (82%). Median lanes by class: secondary 3, primary
2.5, residential 2, primary_link 1, living_street 1, unclassified 2
(n=1). Service: 0 of 20 lines state lanes. Two driveable ways are
tunnels — emit them with `attrs.layer`, do not drop them.

Driveable extra tags (the cross-section, not just `lanes`):

- `sidewalk` / `sidewalk:both` on 154; **134 are `separate`** (the 453
  mapped sidewalks are authoritative — do not synthesise a strip)
- `sidewalk=no` on 11 (respect; do not invent)
- `oneway` on 159 (144 yes)
- `cycleway:left/right`: lane 28, track 26, shared_lane 7, no 31
- `lanes:bus` on 24 (mostly 2)
- `parking:left/right=lane` on 7 sides
- `turn:lanes` on 26; 2 disagree with `lanes` (prefer `lanes`)
- `surface` 165, `maxspeed` 98, `name` 157
- layer / bridge / tunnel on driveable: 6 / 6 / 2

**Exclusive pedestrian / other split** (driveable held out):

| subset | n | action |
|---|---|---|
| indoor / tunnel / layer<0 / location=underground / level<0 | ~93 | exclude (subway, concourse) |
| elevator | 5 | exclude (vertical connector) |
| `footway=sidewalk` at grade | 453 | `extrude` prism, base 0, top 19 cm |
| `footway=crossing` at grade | 241 | exclude (markings on the roadway) |
| `footway=traffic_island` | 24 | `extrude` prism, curb height |
| `area=yes` pedestrian polygons | 59 | `extrude` prism, 16 cm (plazas) |
| `highway=steps` remaining at grade | 58 | omit (not a flat strip) |
| `highway=pedestrian` at-grade lines | 9 | `extrude` prism, curb height |
| `highway=cycleway` own ways | 7 | ribbon at carriageway layer |
| generic at-grade `footway` | 118 | `extrude` prism, curb height |
| driveable LineString | 181 | ribbon, cross-section width, junctions resolved |
| driveable area (service) | 2 | skip — parking-pad polygons |

~174 unique driveable endpoints; **~102 shared by 2+ ways**. Those
are junctions, not seams to ignore.

Sidewalks state `width` on **0** ways. A curb is a prism, not a
floating plate: `extrude` with `base_cm: 0` and `height_cm: 19` so
the walking surface *and* the vertical face sit on the slab. Engine
ribbons only step 4 m per integer `layer`, so a 19 cm curb cannot
be a ribbon.

### Ground cover (not in the default selectors)

Must add `leisure`, `landuse`, `natural`, `water`, `waterway`,
`railway`, `amenity=parking`. The cached extract predates these
(~1 leisure, 2 landuse, 0 water, 0 railway) so this run **must
re-fetch**. Cache is keyed on selectors + bbox + buffer + date,
not on file existence.

Expected ~303 extra elements, mostly Bryant Park interiors plus
58 `railway=subway` ways. Those subway ways are below grade and
must be excluded by the same test as indoor footways.

Composition (this area, not a template):

- leisure: garden, park, pitch, playground
- landuse: flowerbed, construction, brownfield, commercial, grass
- natural: water, sand
- railway: subway (exclude), plus some rail / platform / abandoned

City blocks are not OSM objects here (three `landuse=commercial`
polygons for dozens of blocks). They are not invented. The slab
plus mapped cover is the ground.

### Top keys overall (unfiltered, pre-ground-cover extract)

`osm_id`, `osm_type`, `height` (1667), `highway` (1245), `roof:shape`
(1108), `building:part`, `roof:material`, `surface`, `building:colour`,
`footway`, `building` (714). `ele` is orthometric elevation, not height.

## Mapping

| OSM | Primitive | Notes |
|---|---|---|
| exclusive `building:part` polygon | `extrude` | Always emitted unless below grade. `base_cm` from `min_height` / `building:min_level`. `height_cm` is the absolute top of the walls if a roof mesh is split off. |
| `building` polygon with no assigned parts | `extrude` | Keep the footprint even if height is estimated. Dual-tagged outlines count as buildings. |
| `building` whose outline contains ≥1 part | **suppressed** | Parts describe the massing. `skipped.parent_replaced_by_parts`. |
| below-grade building / part / railway / highway | **excluded** | `location=underground` OR `layer<0` OR `tunnel=*` OR `indoor=yes` OR `level<0`. Counted by class and reason. |
| non-flat `roof:shape` with `roof:height` | `mesh` | Roof is **contained** in `height`. Walls stop at `height - roof:height`. |
| driveable `highway` LineString | `ribbon` | Width is a cross-section (lanes + bus + parking + cycle lane/track). OSM `layer` recorded so the engine lifts bridges and drops tunnels (`LayerSpacingCm = 400`). |
| driveable junctions | `mesh` | Merge collinear same-section runs, then trim each ribbon by half the other way's width and emit one junction footprint at +6 cm. |
| mapped sidewalk / traffic island / pedestrian line / generic footway | `extrude` | Curb prism: `base_cm: 0`, `height_cm: 19`. |
| pedestrian `area=yes` polygons | `extrude` | Plaza prism at 16 cm. |
| cycleway as its own way | `ribbon` | Carriageway layer. |
| crossings, steps, indoor/tunnel/below-grade, elevator | **excluded** | Each counted with its reason. |
| landuse (general) | `mesh` | Z = 0.5 cm |
| park / garden | `mesh` | Z = 1.0 cm |
| flowerbed / pitch / playground / sand | `mesh` | Z = 2.0 cm |
| water / fountain basin | `mesh` | Z = 3.0 cm |
| `railway` at grade | `ribbon` | Only if the below-grade test fails. Subway is excluded. |
| `sidewalk:both=separate` | pointer only | Does not synthesise geometry. |
| interior rings | **skipped** | Contract is exterior-only. |
| city blocks | **not invented** | Not an OSM object in this extract. |
| `instance` | never | No asset library. |

## Overlap / Z stack

The engine slab is `AppendBox` with Origin=Base at Z = −100, so its
**top is Z = 0**. That is the ground. Anything below zero is inside
the slab and renders as nothing.

```
+19  sidewalks, traffic islands, footways   (extrude prism)
+16  plazas                                 (extrude prism)
 +6  junction caps                          (mesh)
 +4  carriageway ribbons                    (RibbonZOffsetCm)
 +3  water
 +2  flowerbed / pitch / playground / sand
 +1  park / garden
+0.5 landuse / parking
  0  GROUND — slab top, building base
-100 slab bottom
```

Ground cover lives in the band between 0 and the carriageway. Each
flat class has its own Z. Order is specificity, not tag family:
landuse under park under flowerbed under water. No two overlapping
flat classes share a plane.

## Fits (this area only)

1. **Storey height.** 119 parent buildings tag both `height` and
   `building:levels`. Median ratio computed at runtime. Label:
   `building:levels*<fitted>m`.
2. **Height from footprint.** kNN on `log(area_m2)`, type-restricted
   when that `building=*` has ≥7 labelled peers. Leave-one-out over
   k ∈ {3,5,7,9,11,15}. Ships only if it beats the area-median
   baseline MedAE. Type medians dropped (`building=yes` dominates).
   Spatial neighbours not used (a tower sits next to a loft).
3. **Lane-count defaults.** Median `lanes` per highway class among
   Midtown driveable ways that state `lanes`. Service has no sample →
   1 lane, labelled as a fallback, not a fit.
4. **Lane / parking / bike / sidewalk widths.** **Cannot be fitted
   here** (0 driveable `width` tags; 0 sidewalk `width` tags).
   Borrowed from the NYCDOT Street Design Manual and labelled as
   borrowed, not fitted:
   - travel / bus lane **10 ft = 3.05 m** (`nycdot_travel_lane:3.05m`)
   - parking lane **8 ft = 2.44 m** (`nycdot_parking_lane:2.44m`)
   - bike lane **5 ft = 1.52 m**; cycle track **8 ft = 2.44 m**
   - commercial sidewalk **15 ft = 4.57 m**
   - generic footway / island **6 ft = 1.83 m**
   Boston is not consulted: a clean checkout has no other extract.

## Fallbacks

- Height tag present → `tag:height`.
- Else levels → `building:levels*<storey>m`.
- Else kNN if the fit beat the baseline → `knn[type=… k=… n=…]`.
- Else area median of tagged parent heights, labelled
  `area_median:<m>m` with the sample size. Never a bare `45`.
- Missing carriageway width → (lanes tag or class median) × 3.05 m
  plus the tagged extras. Never drop the ribbon.
- `roof:height` missing on a non-flat shape → skip the mesh, keep a
  flat extrude to full `height`, count the skip.
- Unextrudable ring → drop that volume, count the reason.
- Refusing a *value* still emits the footprint.

## Cache

Write `data/raw/osm_<area>.json`, `<area>.geojson`, `<area>.fetch.json`.
Reuse only when the sidecar's `selectors`, `bbox_requested`,
`buffer_m` and `date_pinned` all match this run. If any differ, log
which field changed and re-fetch. `--force` always re-fetches.

## Acceptance

- `pipeline.py` fetches (or reuses a *matching* cache), inspects,
  fits, projects, resolves parts, writes `data/ue/nyc_midtown/scene.json`.
- `--repo` is honoured. No absolute path in the file or in the scene.
- After parse, print the tag-level height coverage and the emit-time
  provenance histogram. Parent `tag:height` must be ~85%, not ~0%.
- Emitted extent is printed next to the requested bbox (~611 × 591 m).
  A multi-kilometre scene means below-grade stations leaked through.
- `--verify` asserts: origin projects to (0,0) ±1 cm; every ring CCW
  and unclosed; `height_cm > base_cm`; mesh indices in range; ribbon
  width > 0; counts match the manifest; no absolute path in the JSON;
  scale error vs Vincenty < 0.05%; `tag:height` dominates provenance;
  sidewalk / plaza / driveable subset counts were recorded; sidewalks
  were not silently dropped; below-grade buildings were counted;
  ground-cover classes have distinct Z in (0, 4] cm. Failures exit
  non-zero.
- `osm_verify_scene` re-derives from the extract: 0 errors.
- Second run is byte-identical.

## Designed against previous failures

- Do not lay every pedestrian way on the carriageway plane.
- Do not drop the pedestrian realm as one undifferentiated lump.
- Do not drop no-height buildings.
- Do not extrude parent + parts.
- Do not add `roof:height` on top of `height`.
- Model the non-flat shapes this area actually tags.
- Do not read `properties["tags"]` — tags are flat.
- Do not ship a `--verify` that prints success without asserting.
- Do not label a constant as a median that was never computed.
- Do not hardcode a checkout path; `--repo` / `CITYGEN_REPO` / `__file__`.
- Do not ignore `lanes:bus`, parking, cycleway, or the ~100 junctions.
- Do not extrude `location=underground` buildings at Z = 0.
- Do not key the cache on filename alone.
- Do not emit ground cover at Z ≤ 0 (inside the slab).
- Sidewalks are prisms (`extrude`), not floating plates.
