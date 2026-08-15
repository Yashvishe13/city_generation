---
name: ground-cover
description: Water, parks, landuse and the ground plane - what to fetch, how to stack it, and what OSM will not give you. Load before writing the ground part of a pipeline.
---

# The ground

Between the buildings and the streets is everything else, and a city with neither reads as
a model sitting on a grey plate. This is the cheapest remaining fidelity in the project:
the geometry is simple polygons, and the only hard part is deciding what sits on top of
what.

## 1. It is not in your extract unless you ask for it

The default selectors fetch buildings, `building:part` and highways. Nothing else. Parks,
water and landuse are simply absent — a park in the middle of the area comes through as
the *footways crossing it* and no park, which looks like a bug in the ground and is
actually a missing selector.

Add, and fetch them in the same request so there is one download and one cache:

```
way["leisure"]        relation["leisure"]
way["landuse"]        relation["landuse"]
way["natural"]        way["water"]        way["waterway"]
way["amenity"="parking"]                  way["railway"]
```

Relations matter more here than for buildings: a park with a lake in it is a
multipolygon, and the lake is an `inner` ring you must respect or you will pave it.

## 2. Measure before mapping, as always

What comes back is not what you expect. In the Midtown extract these selectors return 303
elements, 200 of them closed ways, and the composition is *not* a landuse story:

| tag | counts |
|---|---|
| `leisure` | garden 106, park 5, pitch 3, playground 2 |
| `landuse` | flowerbed 17, construction 7, brownfield 4, commercial 3, grass 1 |
| `natural` | water 17, sand 6, tree_row 1 |
| `amenity` | fountain 17, parking 3 |
| `railway` | subway 58, rail 38, platform 23, abandoned 5 |

Nearly all of it is **one park's interior detail** — Bryant Park's gardens, flowerbeds
and fountain basins — plus a subway network. Five polygons carry `leisure=park`. Expect a
different composition elsewhere and measure it rather than porting these numbers.

## 3. The trap: most `railway` here is under the street

58 `railway=subway`, 38 `rail`, 23 `platform`. Emitted at grade they lay a rail network
over Midtown's streets. This is the same failure as the 93 indoor and tunnel footways in
`osm:roads`, in a new tag family: **check `tunnel`, `layer` and `location=underground`
before emitting anything from `railway`**, and exclude what is below grade. Surface rail
is real and worth having; in a dense downtown extract there is usually none of it.

## 4. Nesting: draw the biggest thing first, the smallest last

Ground-cover polygons contain one another — a flowerbed inside a garden inside a park
inside a commercial block. All of them are flat, and flat things at the same Z over the
same ground z-fight (`osm:scene-contract`). Two rules keep it clean:

- **Order by specificity, not by tag family.** A stack from general to specific:
  landuse → park/garden → pitch/playground → flowerbed → water. Give each step its own Z,
  a centimetre or two apart. The smaller polygon is always on top, which is also what it
  looks like in reality.
- **Or subtract**, if you would rather have one surface per patch of ground: cut the
  children out of the parent so each patch is covered once. More correct, more work, and
  it needs a polygon difference you would have to write.

Pick one and say which. What you may not do is emit a park and a garden at the same Z.

## 5. Where the ground plane actually is

The engine already builds a ground slab: a box spanning the scene bounds plus 50 m of
padding, 1 m thick (`UOSMCityGeometry::AppendGround`). It is appended with
`AppendBox(..., Origin = EGeometryScriptPrimitiveOriginMode::Base)` — the geometry-script
default — at Z = −100, so the box runs from −100 **upward** and **its top surface is at
Z = 0**. Read that carefully before choosing a Z: assume the transform is the box centre
and you will conclude the ground is half a metre lower than it is, and bury everything you
emit inside the slab, where it renders as nothing at all.

So Z = 0 *is* the ground. Buildings sit on it (`base_cm: 0`), and the street stack is
already built in the first 20 cm above it:

```
+19  sidewalks, traffic islands, footways
+16  plazas
 +6  junction caps
 +4  carriageway ribbons          (FOSMBuildOptions::RibbonZOffsetCm, default 4)
  0  GROUND — slab top, building base
-100 slab bottom
```

Ground cover therefore goes in the narrow band **between 0 and the carriageway**, and it
is narrow on purpose: these surfaces are the ground, so they belong at the ground, not
hovering above it. Roughly a centimetre per nesting level:

```
+3.0  water surface (a fountain basin reads as water inside its rim)
+2.0  flowerbeds, pitches, playgrounds - the small specific things
+1.0  parks, gardens
+0.5  landuse - the general things
 0.0  slab
```

If a scene genuinely needs more separation than that, raise `RibbonZOffsetCm` and move the
whole street stack up rather than pushing ground cover below zero. Below zero is inside
the slab.

**Ground cover is the one thing that genuinely is flat.** Unlike a sidewalk — which is
raised, and therefore a prism with a curb face (`osm:roads`) — a lawn or a landuse patch
is level with the ground around it, so a `mesh` at a hair above zero is the right
primitive and has no edge to hang in the air. Water is the exception: a basin or pond has
a rim, so if the bank matters, emit the water surface slightly *below* the surrounding
park polygon rather than above it, and let the park read as the edge.

Those numbers are an example of a stack, not a mandate. What matters is that it is *a*
stack, that it is written down in the manifest, and that nothing shares a plane with
anything it overlaps.

## 6. What OSM will not give you: blocks

A city block is not an OSM object. In this extract three polygons carry
`landuse=commercial` for an area containing dozens of blocks — dense grid cities do not
tag their blocks, because the buildings and the streets already describe them.

So if you want blocks, derive them: the road centrelines form a planar graph, and a block
is a face of it, inset by half the adjacent street widths. That is real work and it is
optional. What is not acceptable is shipping three landuse polygons and calling the
ground done, or inventing block geometry and labelling it as data.

If you skip blocks, say so in the manifest, and let the slab plus the mapped ground cover
be the ground.

## 7. Report

Per class: polygons emitted, polygons excluded below grade, and the Z assigned to each
class. The Z table is the part a reviewer needs, because it is the only way to check the
stack without opening the scene.
