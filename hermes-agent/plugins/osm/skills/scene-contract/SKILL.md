---
name: scene-contract
description: The data contract an OSM→Unreal pipeline must emit. Load before writing any translation code for a new area.
---

# Scene contract

Unreal reads exactly one file per area: `data/ue/<area>/scene.json`. The engine dispatches
on `kind` and knows nothing about OpenStreetMap — no tag names, no highway classes, no
roof vocabulary. Whatever an area needs must arrive as one of the primitives below.

Emitting anything outside this contract means the city does not appear.

```json
{
  "manifest": { "area": "...", "origin": {"lat": .., "lon": ..},
                "projection": {...}, "units": "cm",
                "axis_convention": "+X North, +Y East, +Z Up",
                "counts": {...}, "assumptions": {...} },
  "nodes": [
    {"id": "b/12345", "kind": "extrude",
     "outline": [[x, y], ...], "base_cm": 0, "height_cm": 39700,
     "tags": ["building"], "attrs": {"height_source": "tag:height"}},

    {"id": "r/12345", "kind": "mesh",
     "vertices": [[x, y, z], ...], "indices": [[i, j, k], ...],
     "tags": ["roof"], "attrs": {"shape": "pyramidal"}},

    {"id": "w/6789", "kind": "ribbon",
     "points": [[x, y], ...], "width_cm": 1300,
     "tags": ["road", "primary"], "attrs": {"width_source": "lanes*3.25m"}}
  ]
}
```

## The primitives

| kind | geometry | used for |
|---|---|---|
| `extrude` | closed ring + `base_cm` + `height_cm` | building volumes, any prism |
| `mesh` | indexed triangles, absolute coordinates | roofs, or anything the other two cannot express |
| `ribbon` | polyline + `width_cm` | roads, paths, any flat strip |
| `instance` | `asset` + `transform` | **reserved, do not emit** — no asset library yet |

`kind` is a *geometric primitive*, never a feature type. There is no `"kind": "building"`
or `"kind": "water"`. A canal is a `ribbon` or a `mesh` tagged `water`; a park is a `mesh`
tagged `park`. This is what lets a new feature class ship without touching the engine.

## Rules that break the build if ignored

- **Rings**: exterior only in `outline`, counter-clockwise in (X, Y), first vertex **not**
  repeated. Clockwise rings extrude inside-out.
- **Mesh winding**: counter-clockwise seen from outside, or normals face inward.
- **Absolute coordinates**: `mesh` vertices are in the same world frame as `outline` — no
  per-node local origins.
- **`height_cm` is the absolute top**, `base_cm` the absolute bottom. A part starting at
  30 m and ending at 80 m is `base_cm: 3000, height_cm: 8000`, not a height of 8000.
- **Roof heights are contained in the total height** (OSM Simple 3D Buildings), so walls
  stop at `height_cm - roof_height`; never add a roof on top of the full height.
- **Indices** must be in range for that node's own `vertices`.

Two traps that produce exactly these failures:

- **OSM closes a ring by repeating its first vertex; the contract does not.** Strip that
  duplicate before emitting, and strip it *before* computing anything from the ring —
  a repeated vertex also breaks a naive self-intersection test, which then reports every
  building as a bow-tie.
- **Winding is the sign of the shoelace sum in (X, Y), after projection** — not the
  winding the source data happened to have, and not the sign in lon/lat. Compute it on
  the coordinates you are about to emit, and reverse when negative.

## Surfaces that overlap

A node can satisfy every rule above and still render badly, because the renderer sees
*all* the nodes at once:

- **Nothing flat may share a plane with something else flat over the same ground.** Two
  ribbons at the same Z covering the same street z-fight: the depth test cannot order
  them, so they dither frame to frame. This is not fixable in the engine.
- Ribbons of different kinds (carriageway, footway, plaza) need **distinct heights** if
  they overlap, expressed through `layer` in `attrs` or through the Z you choose.
- `layer` on a way is real vertical ordering: negative is below grade. A tunnel emitted at
  street level paves over the road above it.
- Do not emit the same feature twice. A way that also appears as a relation member is one
  surface, not two.

The ground slab sits just below zero, so ordinary road ribbons a few centimetres above it
are fine. The problem is always ribbons against *each other*.

## Semantics and provenance

`tags` carry meaning (`building`, `building:part`, `roof`, `road`, the highway class,
`tunnel`). `attrs` carry provenance: how each derived number was obtained. Every height and
width must name its source — `tag:height`, `building:levels*3.4m`, `lanes*3.25m`,
`class_default:residential=10m`, or a fitted estimate. A reviewer has to be able to
separate what was measured from what was assumed without reading code.

## Non-negotiables

- **Deterministic**: same input → byte-identical output. No RNG, no dict ordering by hash,
  no timestamps inside the geometry files.
- **Paths recorded in the manifest are repo-relative** (`data/raw/<area>.geojson`), never
  an absolute path. An absolute path bakes the author's checkout into the delivered
  artifact and makes the byte-identical claim false on any other machine.
- **Nothing silently dropped**: anything skipped is counted by reason in the manifest.
- **Assumptions declared**: every constant the run actually used goes in
  `manifest.assumptions`, with its value and where it came from.

Keep writing whatever intermediate files help you debug; `scene.json` is the only one the
engine reads.
