# nyc_midtown — OSM → Unreal pipeline plan

Measured from the Overpass extract for the requested bbox
`[40.7500, -73.9860, 40.7555, -73.9790]` plus the 150 m fetch buffer
(3024 features: 1840 Polygon, 1184 LineString). Properties are **flat**
(tags sit on `properties`; there is no nested `tags` object). Numbers
below are from this extract, not from another city.

The previous Midtown pipelines under-built the street network twice:
once by dumping every `highway` onto one Z, and once by dropping 1062
non-driveable ways as a single lump. This plan splits the 1245 highway
features the way the tags already split them.

## Inventory

### Buildings (714 features with `building=*`, including 19 dual-tagged)

- `height` on **606 / 714 = 84.9%**. This is the parser-sanity number:
  after reading tags, ~85% of parent buildings must show a real height
  tag. If the emit-time provenance histogram collapses to a default,
  tags were read from the wrong level.
- `building:levels` on 125 (17.5%).
- Both `height` and `building:levels` on **119 parent buildings**
  (the storey-height sample). Median ratio **3.883 m/storey**. Leave-one-out
  using that median: MedAE **2.52 m**.
- Neither tag: 102. Levels only: 6.
- `min_height` on 2 dual-tagged outlines; `building:min_level` is unused
  on parents (0). Parts carry the setbacks.
- `roof:shape` on 108 buildings, almost all `flat`. One `mansard`.
- Tagged parent heights (n=606): median **26.25 m**.
- `building=*` is 594× `yes`, then commercial / hotel / office.
  Type medians are not a useful estimator.
- 19 features carry both `building` and `building:part`. They are
  large parent outlines, not massing parts — treat them as parents.

### building:part (1065 exclusive parts)

- `height` on **1061 / 1065 = 99.6%**.
- `min_height` on 191 (17.9%); `building:min_level` on 38. This is
  where setbacks start above ground.
- `roof:shape` on exclusive parts: 886 flat, 43 skillion, 36 pyramidal,
  18 gabled, 12 hipped, 4 dome, 1 mansard, 65 unset.
- `roof:height` is present on **every** non-flat part (114 / 114).
- Centroid-in-polygon against `building=*` parents assigns essentially
  every part. Parents that own parts are not extruded.

### Rings

- Building/part polygons are closed after stripping OSM's repeated
  vertex. Interior rings exist (5 courtyards). The contract is
  exterior-only, so holes are counted as skipped, not silently filled.
- Unextrudable rings are not expected; any that appear are dropped
  with a reason.

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
tunnels and one carries `layer<0` — emit them with `attrs.layer`, do
not drop them.

Driveable extra tags (this is the cross-section, not just `lanes`):

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
| indoor / tunnel / layer<0 (incl. 5 elevators) | 93 | exclude (subway, concourse) |
| `footway=sidewalk` at grade | 453 | emit mesh strip at curb Z |
| `footway=crossing` at grade | 241 | exclude (markings on the roadway; the real coplanar case) |
| `footway=traffic_island` | 24 | emit mesh strip at curb Z |
| `area=yes` pedestrian polygons | 59 | emit mesh (Times Square / Herald Square plazas) |
| `highway=steps` remaining at grade | 58 | omit (not a flat strip); 59 more steps sit in the 93 below-grade |
| `highway=pedestrian` at-grade lines | 9 | emit mesh strip at curb Z |
| `highway=cycleway` own ways | 7 | ribbon at carriageway layer |
| generic at-grade `footway` | 118 | emit mesh strip at curb Z (through-block / plaza edges) |
| driveable LineString | 181 | ribbon, cross-section width, junctions resolved |
| driveable area (service) | 2 | skip — parking-pad polygons, not carriageways |

173 unique driveable endpoints; **99 shared by 2+ ways** (50 degree-2,
13 degree-3, 35 degree-4, 1 degree-5) when below-grade driveable ends
are excluded; including them is ~100 junctions. Those are junctions,
not seams to ignore.

Sidewalks state `width` on **0** ways.

### Top keys overall (unfiltered)

`osm_id`, `osm_type`, `height` (1667), `highway` (1245), `roof:shape`
(1108), `building:part`, `roof:material`, `surface`, `building:colour`,
`footway`, `building` (714), `nycdoitt:bin`, addresses,
`building:levels` (345). `ele` is orthometric elevation, not height.
One height value is unit-suffixed (`38 m`); the rest are bare metres.

## Mapping

| OSM | Primitive | Notes |
|---|---|---|
| exclusive `building:part` polygon | `extrude` | Always emitted. `base_cm` from `min_height` / `building:min_level`. `height_cm` is the absolute top of the walls if a roof mesh is split off. |
| `building` polygon with no assigned parts | `extrude` | Keep the footprint even if height is estimated. Dual-tagged outlines count as buildings. |
| `building` whose outline contains ≥1 part | **suppressed** | Parts describe the massing. `skipped.parent_replaced_by_parts`. |
| non-flat `roof:shape` with `roof:height` | `mesh` | Roof is **contained** in `height`. Walls stop at `height - roof:height`. Shapes: pyramidal, skillion, gabled, hipped, dome, mansard. |
| driveable `highway` LineString | `ribbon` | Width is a cross-section (lanes + bus + parking + cycle lane/track). OSM `layer` / `bridge` / `tunnel` recorded so the engine can lift bridges and drop tunnels (`LayerSpacingCm = 400`). |
| driveable junctions | `mesh` | Shared endpoints: merge collinear same-section runs, then trim each ribbon by half the other way's width and emit one junction footprint. |
| mapped sidewalk / traffic island / pedestrian line / generic footway | `mesh` strip | Curb Z = 19 cm. Engine ribbons only step 4 m per integer `layer`, so a 15 cm curb cannot be a ribbon. |
| pedestrian `area=yes` polygons | `mesh` | Plaza surface at 16 cm (below sidewalks, above carriageway ribbons at 4 cm). |
| cycleway as its own way | `ribbon` | Carriageway layer. |
| crossings, steps, indoor/tunnel/layer<0, elevator | **excluded** | Each counted with its reason. |
| `sidewalk:both=separate` | pointer only | Does not synthesise geometry. |
| interior rings | **skipped** | Contract is exterior-only. |
| `instance` | never | No asset library. |

## Fits (this area only)

1. **Storey height.** 119 parent buildings tag both `height` and
   `building:levels`. Median ratio **3.883 m**. LOO MedAE **2.52 m**.
   Label: `building:levels*<fitted>m`. Computed at runtime from the
   extract, not hardcoded.
2. **Height from footprint.** 606 labelled parent footprints. Global
   median height **26.25 m**, baseline MedAE **12.35 m**. kNN on
   `log(area_m2)`, type-restricted when that `building=*` has ≥7
   labelled peers. Leave-one-out over k ∈ {3,5,7,9,11,15} picks k
   (best MedAE here is **6.60 m** at k=15; k=9 is 6.85 m). Beats the
   median, so it ships. Type medians are dropped (almost everything is
   `building=yes`). Spatial neighbours are not used (a tower sits
   next to a loft).
3. **Lane-count defaults.** Median `lanes` per highway class among
   Midtown driveable ways that state `lanes`. Service has no sample →
   1 lane, labelled as a fallback, not a fit.
4. **Lane / parking / bike widths.** **Cannot be fitted here** (0
   driveable `width` tags; 0 sidewalk `width` tags). Borrowed from
   the NYCDOT Street Design Manual and labelled as borrowed, not
   fitted:
   - travel / bus lane **10 ft = 3.05 m** (`nycdot_travel_lane:3.05m`)
   - parking lane **8 ft = 2.44 m** (`nycdot_parking_lane:2.44m`)
   - bike lane **5 ft = 1.52 m**; cycle track **8 ft = 2.44 m**
   - commercial sidewalk **15 ft = 4.57 m** (`nycdot_commercial_sidewalk:4.57m`)
   - generic footway / island **6 ft = 1.83 m** (`nycdot_min_clear_path:1.83m`)
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
  flat extrude to full `height`, count `skipped.roof_<shape>_no_roof_height`.
- Unextrudable ring → drop that volume, count the reason.
- Refusing a *value* still emits the footprint.

## Overlap plan

- Parents that contain parts are not extruded. Parts at different
  `min_height` stack.
- Dual `building`+`building:part` outlines are parents, not a second
  copy of the massing.
- Carriageway ribbons sit at engine Z = `4 + layer*400` cm. Sidewalks
  / islands / pedestrian lines are meshes at 19 cm. Plazas are meshes
  at 16 cm. Crossings are not emitted. That is the curb, not an
  exclusion.
- Driveable tunnels keep `layer < 0` so they do not pave the street.
  Pedestrian indoor / tunnel / layer<0 ways are excluded.
- Junctions: merge collinear same-section runs first (kills seam
  overlaps), then trim-and-cap the remaining shared endpoints
  with one mesh per junction, 2 cm above the carriageway.
- Roof mesh sits on the wall top (`height - roof:height`). When
  `roof:height` consumes the whole span, the extrude is omitted.
- A way is emitted once.

## Acceptance

- `pipeline.py` fetches (or reuses `data/raw/`), inspects, fits,
  projects, resolves parts, writes `data/ue/nyc_midtown/scene.json`.
- `--repo` is honoured. No absolute path in the file or in the scene.
- After parse, print the tag-level height coverage and the emit-time
  provenance histogram. Parent `tag:height` must be ~85%, not ~0%.
- `--verify` asserts: origin projects to (0,0) ±1 cm; every ring CCW
  and unclosed; `height_cm > base_cm`; mesh indices in range; ribbon
  width > 0; counts match the manifest; no absolute path in the JSON;
  scale error vs Vincenty < 0.05%; `tag:height` dominates provenance;
  sidewalk / plaza / driveable subset counts were recorded and
  sidewalks were not silently dropped. Failures exit non-zero.
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
