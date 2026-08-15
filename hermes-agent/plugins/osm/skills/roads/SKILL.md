---
name: roads
description: Building the street network - cross-section width, the pedestrian realm, surfaces and junctions. Load before writing the road part of a pipeline.
---

# The street network

Buildings are the easy half. A city read as *buildings plus centrelines* looks like a
model of a city; the street is where the ground actually reads as a place. This project
has under-built roads twice, and both times the data was there and went unused.

The failure to avoid is not a wrong number — it is **using one tag when the area states
twelve**. A Midtown extract states `lanes` on 82% of driveable ways, and also
`sidewalk:*` on 73%, `oneway` on 87%, `cycleway:left/right` on ~25%, `lanes:bus` on 13%,
`turn:lanes` on 14%, `parking:left/right`, `surface`, `maxspeed`, `name`. A pipeline that
reads `lanes` and stops has thrown away the whole cross-section.

## 1. Width is a cross-section, not a lane count

`lanes` counts **travel lanes only**. Kerb-to-kerb width is travel lanes plus everything
else the way declares beside them:

| tag | typical values | contributes |
|---|---|---|
| `lanes` | 1–5 | travel lanes × lane width |
| `lanes:bus` | 1–2 | additional running lanes |
| `parking:left` / `:right` | `lane`, `no` | a parking lane per side that says `lane` |
| `cycleway:left` / `:right` | `track`, `lane`, `shared_lane`, `no` | `lane` adds width; `shared_lane` adds none (it is inside a travel lane) |
| `turn:lanes` | `left|through|right` | a lane list — its length is a lane count, and it can contradict `lanes`. Prefer `lanes`, and count the disagreement |

`cycleway:*=track` is physically separated from the carriageway. Add it to the width only
if you are not emitting it as its own ribbon; doing both double-counts.

Emitting `lanes × w` alone produces streets that are visibly too narrow for the gaps
between the buildings — the most common way a correct-looking city reads wrong.

Lane width itself is a separate question and belongs to `osm:estimation`: fit it from
`width` where the area states it, borrow it with the source named where it does not
(Midtown states `width` on **zero** driveable ways), and label whichever you did.

## 2. The pedestrian realm is where most of the network is

In Midtown, 1062 of 1245 highway features are non-driveable. Dropping them all as
"sidewalks z-fight" is wrong; including them all is worse. They are **labelled**, so
split them:

| subset | Midtown count | what to do |
|---|---|---|
| `indoor=yes`, `tunnel=*`, `layer<0` | 93 | **exclude.** Subway passages and building concourses. Drawn at street level they pave over the street and run through buildings |
| `footway=sidewalk`, at grade | 453 | **emit** as ribbons at curb height, ~15 cm above the carriageway |
| `footway=crossing`, at grade | 241 | **exclude, or emit flush at carriageway Z as markings.** These lie *on* the roadway by definition — this is the real coplanar case |
| `footway=traffic_island` | 24 | emit at curb height, same plane as sidewalks |
| `area=yes` + `highway` | 59 | **emit as `mesh`**, not as ribbons — they are surface polygons (in this bbox, the Times Square / Herald Square plazas) |
| `highway=steps` | 117 | a stair is not a flat strip. Omit, or emit as a ramped mesh; count either way |
| `highway=pedestrian`, at grade, not an area | 9 | ribbon, curb height |
| `highway=cycleway` as its own way | 7 | ribbon, carriageway height |
| `highway=elevator` | 5 | exclude — it is a vertical connector, not a surface |

**`sidewalk:both=separate` is a pointer, not geometry.** All 134 Midtown occurrences are
`separate`, which means *"the sidewalk exists and is mapped as its own way"* — it tells
you the 453 `footway=sidewalk` ways are authoritative, it does not license you to
synthesize a strip beside the carriageway. Synthesizing one *and* emitting the mapped way
puts two sidewalks side by side.

`sidewalk=no` / `sidewalk:left=no` (11 and 10 here) is a positive statement that there is
no sidewalk on that side. Respect it rather than defaulting one in.

Curb height is what makes this safe. Sidewalks and the carriageway are not coplanar in
reality and must not be coplanar in the scene: give the pedestrian plane a distinct Z and
the z-fight cannot occur, whatever overlaps.

**A curb is a prism, not a floating plate.** The obvious way to lift a sidewalk is a flat
`mesh` with every vertex at +19 cm — and that is a surface with nothing under it, open at
every edge, hanging in the air above the ground slab. It reads fine from altitude and
wrong from the street, which is where a fly-through spends its time.

Use `extrude` instead: the sidewalk outline as the ring, `base_cm: 0`, `height_cm: 19`.
The contract's extrude primitive takes an arbitrary base and top, so it gives you the
walking surface *and* the vertical curb face, sitting on the ground rather than over it.
The same applies to plazas, traffic islands and any other raised pedestrian surface.

Note that a `ribbon` cannot do this — its only vertical control is `layer`, and the engine
spaces layers 4 m apart (`FOSMBuildOptions::LayerSpacingCm`), so a 19 cm curb is not
expressible as a ribbon. That is a reason to reach for `extrude`, not a reason to reach
for a flat mesh.

## 3. Junctions

The junction graph is in the source and is nearly free to read: ways that meet share an
endpoint coordinate exactly. In this extract 102 of 174 driveable endpoints are shared by
two or more ways — roughly a hundred intersections.

Emitting each way as an independent full-length ribbon puts two quads on the same plane at
every one of them. That is the coplanar overlap `osm:scene-contract` warns about, between
carriageways rather than between sidewalk and road, and it dithers exactly the same way.

Resolve it. In rough order of effort:

1. **Trim and cap** — pull each ribbon back from the shared endpoint by about half the
   other way's width, and emit the junction footprint once as a `mesh`. Correct, and it
   also gives you the intersection surface, which is a real part of a street grid.
2. **Order by class** — carry the ribbons but separate them by a small Z per highway
   class, so the depth test has something to sort. Cheap; produces visible steps where a
   minor road meets a major one.
3. **Merge collinear runs** — join consecutive ways with identical cross-section into one
   ribbon first. This removes the *seam* overlaps (same-direction, same-width joins) that
   are the majority of shared endpoints, and shrinks the real junction count.

Whatever you choose, say which, and count the junctions you resolved.

## 4. Vertical ordering is real

`layer`, `bridge` and `tunnel` are not metadata — they are the Z ordering. A tunnel drawn
at street level paves over the road above it. In this extract 48 pedestrian ways carry
`layer=-1`, five `-2`, four `-3`, and 58 carry `tunnel=yes`. Below-grade means below
grade or excluded, never flush.

## 5. What to report

The manifest should let a reviewer reconstruct the network without opening the geometry:

- ribbons emitted per class, and the total centreline length;
- the width histogram, with the cross-section components that produced it;
- the pedestrian subsets you emitted and the ones you excluded, **each with its count and
  reason** — "1062 non-driveable ways excluded" is not a reason, it is a number;
- junctions detected and how they were resolved;
- what you read `width` from, per `osm:estimation`'s provenance rules.

A network of 181 carriageway ribbons in an area whose source describes 453 sidewalks, 59
plazas and ~100 junctions is not a complete answer, however well each of the 181 is built.
