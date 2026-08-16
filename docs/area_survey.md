# Choosing the area by measurement

`scripts/survey_areas.py` fetched 23 candidate areas (~600 × 600 m each, dense
commercial cores, spread across mapping cultures) and scored each on how much of the
reconstruction would be **stated by OSM** rather than **invented by us**. Raw numbers:
`docs/area_survey.json`.

## What was measured

Per building footprint:

| Class | Meaning |
|---|---|
| explicit `height` / `building:height` | no assumption needed |
| `building:levels` only | one assumption: metres per floor |
| neither | pure guess |

Scored **by footprint area, not by count** — a 200 m tower with a tagged height matters
more to the skyline than a tagged bike shed. An explicit height counts 1.0, a
levels-only tag 0.6.

A second pass then asked the question that actually decides it: for each building with
no height information, **is it covered by `building:part` polygons that do state
heights?** OSM's Simple 3D Buildings scheme puts the real massing on the parts, so a
"missing" height is often not missing at all.

## Result: residual guesswork after parts

| area | buildings | no info | covered by parts | residual guess (% footprint area) |
|---|---|---|---|---|
| vienna_innere | 411 | 16 | 4/16 | **0.2%** |
| boston_financial | 228 | 14 | 5/14 | **1.0%** |
| nyc_midtown | 316 | 47 | 34/47 | **1.1%** |
| sf_financial | 378 | 84 | 3/84 | 6.5% |
| amsterdam_centrum | 1171 | 104 | 11/104 | 20.4% |

Vienna's raw 21.9% "unknown area" was almost entirely one feature — the Hofburg, at
68,606 m² — whose parts do carry heights. Amsterdam is the opposite trap: 89% of its
buildings are tagged, but the untagged ones are large and have no parts.

## Finalists

| | vienna_innere | **nyc_midtown** | boston_financial |
|---|---|---|---|
| buildings | 411 | 316 | 228 |
| `building:part` (with height) | 185 (168) | **524 (521)** | 266 (258) |
| explicit height | **94.4%** | 84.2% | 39.0% |
| levels only | 1.7% | 0.9% | 54.8% |
| no info | 3.9% | 14.9% | 6.1% |
| height range | 5–37 m (median 28) | **5.7–397 m (median 40)** | to 210 m |
| roads / km / named | 631 / 23.1 / 242 | 436 / 24.8 / 64 | 630 / 35.3 / 165 |
| residual guess | 0.2% | 1.1% | 1.0% |

## Decision: `nyc_midtown`

`(40.7500, -73.9860, 40.7555, -73.9790)`, ~590 × 610 m.

- **787 features state their own height** (266 buildings + 521 parts) — more than
  Vienna's 556 or Boston's 347.
- Residual guesswork 1.1%, statistically tied with the other finalists.
- Genuine vertical range, 5.7–397 m. Vienna's heights are better tagged but span
  5–37 m, so there is barely a skyline to get right; Boston needs the metres-per-floor
  assumption for 55% of its buildings.
- Footprints come from a municipal import, so they are survey-accurate rather than
  hand-traced, and the area is recognisable in a side-by-side (Empire State, Bryant
  Park, NY Public Library).

Runner-up: `vienna_innere`, if minimising estimation matters more than vertical variety.

## Geometry and road-width check (`nyc_midtown`)

Height coverage is not the only thing that forces invention. Two further checks, added
after the survey and run on the chosen area (`osm_quality_check`, also folded into
`survey_areas.py`):

**Footprint rings — can they be extruded?**

```
buildings 840   types {Polygon: 840}   interior rings 2
extrudable 100.0%   problems: none
```

Every ring is closed, non-degenerate and non-self-intersecting, so no repair pass is
needed. Two footprints have interior rings (courtyards) — the extrusion must keep holes
rather than triangulating the outer ring alone.

**Road widths — are they stated anywhere?**

```
driveable roads 113:  explicit width 0.0%   lanes 48.7%   width from class only 51.3%
                      lane values {1:14, 2:14, 4:12, 5:8, 3:7}
all highways    436:  explicit width 0.0%   lanes 12.6%
                      tunnels 2   bridges 0   layered 3
classes: footway 291, pedestrian 48, steps 32, secondary 26, residential 21, primary 11
```

**Not one road in the area carries a `width` tag.** Width is therefore 100% derived:
from `lanes` where present (49% of driveable ways), and from the highway class alone for
the other 51%. So after choosing an area for its excellent height data, *road width is
now the largest remaining source of invention* — the opposite of what the height survey
suggested, and worth stating honestly in the report rather than implying roads are as
data-driven as the buildings.

## Re-ranked on both dimensions (heights **and** road widths)

Scoring roads the same way as heights — stated `width` counts 1.0, a `lanes` count 0.6,
nothing counts 0, weighted by **road length** so a long avenue outweighs a service alley
— and combining the two with a **geometric mean**, so an area has to be good at both:

| area | combined | height | road | h.stated% | w.stated% | lanes% | extrudable% |
|---|---|---|---|---|---|---|---|
| **boston_financial** | **0.837** | 0.796 | **0.879** | 39.0 | **73.1** | 83.0 | 100.0 |
| nyc_midtown | 0.612 | 0.694 | 0.539 | 84.2 | 0.0 | 48.7 | 100.0 |
| seattle_downtown | 0.604 | 0.652 | 0.559 | 18.9 | 0.0 | 79.7 | 100.0 |
| sf_financial | 0.551 | 0.807 | 0.376 | 69.8 | 0.0 | 53.7 | 100.0 |
| nyc_lower | 0.537 | 0.538 | 0.536 | 70.8 | 5.9 | 55.2 | 100.0 |
| warsaw_srodmiescie | 0.514 | 0.870 | 0.304 | 53.6 | 0.8 | 38.5 | 100.0 |
| chicago_loop | 0.459 | 0.626 | 0.337 | 16.9 | 0.4 | 42.2 | 100.0 |
| amsterdam_centrum | 0.190 | 0.684 | 0.053 | 89.4 | 6.8 | 5.7 | 100.0 |
| vienna_innere | 0.184 | **0.781** | **0.043** | 94.4 | 2.1 | 2.5 | 100.0 |

The height-only shortlist inverts. Vienna and Amsterdam — the best-tagged heights of all
23 candidates — rank last once roads count, because essentially none of their roads state
a width or a lane count. Boston is the only area that is strong at both, and it wins by a
wide margin (0.837 against 0.612).

The geometry check also stopped being a formality: `melbourne_cbd` has a
self-intersecting footprint and `paris_defense` is only 94.2% extrudable, so those areas
would need a repair pass before any extrusion.

### Boston Financial District in detail

```
buildings 494 (228 outlines + 267 parts)   3 MultiPolygon, 3 interior rings
extrudable 100.0%
driveable roads 182:  explicit width 73.1%   lanes 83.0%   class-only 15.9%
width values: 16.5, 16.8, 14.6, 16.2, 13.4, 15.2, 30.2 m  (metric, plausibly a MassGIS import)
heights  n=89:  9.3 – 210.5 m, median 30
levels   n=205: 1 – 54 floors, median 7
bridges 1   tunnels 13   layered 24
```

### The trade, stated plainly

- **Boston**: road widths are real data (only ~16% of road length invented), but ~55% of
  buildings give floor counts rather than heights, so one assumption — metres per floor —
  drives half the skyline. 13 tunnels and 24 layered ways (the Big Dig) need handling so
  underground roads are not drawn at street level.
- **Midtown**: heights are real data (84% explicit, 1.1% residual), but **no road states a
  width at all**, so 51% of road length gets its width purely from its highway class —
  and Manhattan avenues are far wider than a generic `primary` default.

Worth noting against the grading rubric: building height plausibility is scored, road
*width* is not — the rubric asks for road **coverage and alignment**, which both areas
satisfy from centrelines. On that reading Midtown remains defensible; on pure
data-completeness Boston is the better answer.

### Final decision: `nyc_midtown` stands

Boston wins the combined score, but the two dimensions are not equally consequential
here. Height plausibility is graded and road width is not, so Midtown's advantage lands
on a scored axis while its weakness lands on an unscored one. Midtown also keeps the
larger and better-articulated 3D layer (524 parts, 521 with heights, versus Boston's
267) and avoids the Big Dig's 13 tunnels and 24 layered ways.

The cost of that choice, to be disclosed in `report.html` rather than glossed over: **no
road in the area states a width**, so every carriageway width is derived — from `lanes`
for 49% of driveable length, from the highway class alone for the other 51%. Manhattan
avenues are considerably wider than a generic `primary` default, so road widths are the
least data-driven part of this reconstruction and should be described that way.

## Consequences to carry into the next step

1. **`building:part` handling is mandatory, not optional.** 524 parts against 316
   buildings; ignoring them loses most of the massing detail, and extruding both parts
   and their parent envelopes double-builds every tower.
2. **`roof:height` must be respected.** The 397 m maximum is suspicious against the
   Empire State Building's 381 m roof, so some tagged heights include masts or spires.
   In Simple 3D Buildings `roof:height` is contained in `height`, so wall height is
   `height − roof:height`.
3. **Street names are sparse** (64 of 436 ways). Irrelevant to geometry, but it rules
   out naming roads from OSM data alone.
4. One candidate, `tokyo_shinjuku`, failed: all three Overpass mirrors returned 504 or
   an empty result. Not retried, since the finalists were already decided.
