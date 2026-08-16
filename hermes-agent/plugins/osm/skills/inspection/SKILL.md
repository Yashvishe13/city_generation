---
name: inspection
description: Measuring a fetched area before converting it - tag coverage, ring extrudability, road width availability. Load before deciding how to interpret an area.
---

# Measuring the area before you convert it

Tagging habits differ enormously between cities. Midtown Manhattan states `height` on 84%
of buildings; Le Marais states it on 1 building in 694. A rule fitted on one is useless on
the other, so every design decision in your pipeline has to be preceded by a number.

You compute these yourself, as the second stage of the pipeline, right after the fetch.
There is no tool that reports them. Print them, put them in
`agent_scripts/<area>/PLAN.md`, and summarise them in `manifest.assumptions` — a reviewer
must be able to see what you measured without re-running anything.

## Tag coverage

For each key of interest: how many features carry it, the percentage, and its commonest
values. Restrict the pool with a gate tag (`building`) so that road tags do not dilute
building statistics.

Keys worth reporting on before writing any geometry:

- `height`, `building:levels`, `min_height`, `building:min_level`
- `building`, `building:part`
- `roof:shape`, `roof:height`, `roof:levels`
- `highway`, `width`, `lanes`, `layer`, `bridge`, `tunnel`

Also report the 20 most common keys overall, unfiltered. That is how you notice an area
carries something you were not planning for — a `building:colour` census, a `min_height`
convention, a local key.

The number that decides the estimator is not "how many state `height`" but **how many
state both `height` and `building:levels`** — those pairs are the only way to fit metres
per storey from this area rather than borrowing one (`osm:estimation`). Midtown has 57
such pairs. Some areas have none, and that is an answer.

## Ring extrudability

A footprint that OSM renders happily can still be impossible to extrude. Check each
building ring for:

- **not closed** — first and last vertex differ;
- **degenerate** — fewer than 4 points;
- **repeated vertex** — a vertex appearing twice inside the body;
- **self-intersecting** — two non-adjacent segments properly crossing.

The self-intersection test is a proper-crossing test on every non-adjacent segment pair,
using the orientation sign; shared endpoints do not count. It is twenty lines and worth
having, because extruding a bow-tie produces a tangled inside-out solid that looks like a
projection bug in the viewport.

**Strip OSM's repeated closing vertex before testing**, not after. OSM closes a ring by
repeating the first vertex; a naive self-intersection test that sees that duplicate
reports every building in the area as self-intersecting, and the resulting "0% extrudable"
sends you hunting a fetch bug that is not there. The same strip is required before
computing the shoelace winding and before emitting (`osm:scene-contract`).

Report: count, geometry types, interior-ring total, how many rings have each problem, and
an extrudable percentage. Interior rings matter on their own — Le Marais is courtyard
buildings, and a pipeline that silently drops holes fills every courtyard with stone.

## Road width availability

Split highways into the driveable classes and everything else, then for each pool:

- how many state an explicit `width`;
- how many state `lanes` only;
- how many state **neither**, i.e. the width can only come from the highway class —
  which means invented, and must be labelled that way;
- the commonest `lanes` values;
- the class histogram, plus `bridge`, `tunnel` and `layer` counts.

Then measure the rest of the cross-section, because width is not just `lanes`:
`lanes:bus`, `parking:left`/`:right`, `cycleway:left`/`:right`, `turn:lanes`, `oneway`.
And break the non-driveable pool down by what it actually is — `footway=sidewalk` vs
`crossing` vs `traffic_island`, `area=yes` surface polygons, `steps`, and anything
`indoor`/`tunnel`/`layer<0`. Those subsets get different treatment and one of them must
be excluded; a single count of "pedestrian ways" cannot tell you which. Count shared
endpoints among driveable ways too — that is the junction total you will have to resolve.
`osm:roads` says what to do with each.

The spread here is as wide as it is for heights: Boston's financial district states
`width` on 73% of driveable length, and Midtown states it on **no road at all**. Knowing
which of those you are in before writing the width logic is the difference between
fitting a number and inventing one.

`layer`, `bridge` and `tunnel` counts are not bookkeeping — they are the vertical
ordering. A tunnel emitted at street level paves over the road above it
(`osm:scene-contract`).

## What is below grade

Count it across **every class, not just highways**. For each of `location=underground`,
`layer<0`, `tunnel`, `indoor=yes` and `level<0`, report how many buildings, highways,
railways and ground-cover features carry it.

Midtown has 110 highways and **3 buildings**. Those three buildings are subway station
complexes spanning up to 737 m, and extruded at street level they set the entire scene's
extent — so this is not a footnote, it is the measurement that decides whether the scene
is the size it claims to be. A count of zero is worth knowing too; a count you never took
is how they end up standing on the road (`osm:scene-contract`).

Watch for the same landmark appearing twice, once above ground and once below: Grand
Central Terminal is one feature at street level and another as an underground concourse.
Report them separately rather than as one name.

## What to do with the numbers

Nothing about these measurements is decorative:

- 84% `height` → read tags, estimate the remainder, and expect the manifest's provenance
  histogram to be roughly 84% `tag:height`. **If it is not, your parser is wrong** — that
  mismatch is the cheapest bug detector in the pipeline, and it is the one that would
  have caught 606 heights silently falling through to a constant.
- 0% `width` → do not pretend. Derive from `lanes` where present, from class where not,
  and label both.
- non-flat `roof:shape` present → either model those shapes or count what you skipped by
  shape name. A roof vocabulary you did not implement is a number in `skipped`, never
  silence.
- unextrudable rings present → repair or drop them explicitly, with the count and the
  reason in the manifest.
- anything below grade → exclude it from the ground-level scene, or place it at its stated
  `layer`; never extrude it at Z = 0, whatever class it belongs to.
