---
name: pipeline-plan
description: How to plan and validate an OSM→Unreal pipeline before and after writing it. Load first, before any other skill, when generating a pipeline for an area.
---

# Planning a pipeline for an area

The pipeline you write is judged on how closely the generated city matches the real one:
footprint shape and placement, plausible heights, road-network coverage and alignment,
and correct scale, orientation and georegistration. Everything below serves that.

Write the plan before the code. Guessing at the data and fixing it afterwards costs more
than measuring it first, and the measurements decide most of the design.

Load these next, in this order: `osm:pipeline-shape` (what the artifact must be),
`osm:scene-contract` (what to emit), `osm:coordinates` (how to project),
`osm:fetching` (how to download), `osm:inspection` (what to measure),
`osm:roads` (the street network), `osm:ground-cover` (water, parks, landuse),
`osm:estimation` (how to derive what OSM does not state).

Weight your effort the way the grading does. Footprints and heights are one half; the
**street network is the other**, and it is the half this project has repeatedly
under-built while the buildings came out fine.

## 1. Inventory the area before deciding anything

Load `osm:fetching` and `osm:inspection`, and write the download and the measurements as
the first two stages of your own pipeline — there is no tool that does either. The
inventory numbers are your pipeline's output, not a tool's:

- how many buildings, and what fraction state `height`, `building:levels`, neither;
- how many `building:part` volumes, and whether they overlap parents;
- what `roof:shape` values exist and how many are non-flat;
- which highway classes are present, how many state `width` or `lanes`;
- whether any footprint is unextrudable (self-intersecting, degenerate, open).

Tagging habits differ enormously between cities. Midtown Manhattan states `height` on 84%
of buildings; Le Marais states it on 1 building in 694. A rule that works in one is
useless in the other, which is why this is measured per area rather than assumed.

## 2. Write `agent_scripts/<area>/PLAN.md` before the code

Short, concrete, and it must answer:

- **Inventory** — the numbers above.
- **Mapping** — which OSM features become which contract primitive (`extrude`, `mesh`,
  `ribbon`), and which are deliberately excluded, with the reason.
- **Fits** — what you will fit from this area's data, and from what sample size.
- **Fallbacks** — what happens when a value cannot be fitted, and how it will be labelled.
- **Overlap plan** — which surfaces could end up coplanar, and how you will separate them
  (see below).
- **Acceptance** — the checks you will run, and what result counts as done.

The plan is also what a reviewer reads to understand the choices, so justify them rather
than merely listing them.

## 3. Failures this project has actually hit

Each of these validated cleanly and still produced a worse city. They are the specific
things to design against.

**Sidewalks laid over roads.** Including every `highway` class put 371 pedestrian ways
(footway, steps, pedestrian) into a 436-ribbon network at the same height as the
carriageway, and the whole area shimmered with z-fighting.

**Then over-correcting: dropping the pedestrian realm entirely.** The next pipeline read
that as "a road network means the driveable classes" and excluded 1062 of 1245 highway
features as one undifferentiated lump — including 453 mapped sidewalks, 59 plaza polygons
and 9 pedestrian streets. Midtown shipped with no pedestrian surface at all. Both
failures come from treating `highway` as one thing. It is not: the data labels these
subsets, and the fix is a curb height, not an exclusion. See `osm:roads`.

**Dropping buildings that lack a height.** Refusing to invent a height is right; deleting
the building is not. Footprint fidelity is the most heavily weighted thing being judged,
so a footprint with an honestly-labelled fallback height beats a hole in the city. Keep
the volume, label the estimate, and count it in the manifest.

**Extruding both a parent outline and its parts.** `building:part` volumes overlap the
`building` outline they belong to. Building both doubles every tower and buries the
setbacks inside a slab. Resolve which one describes the massing.

**Adding `roof:height` on top of the total height.** In Simple 3D Buildings the roof is
*contained* in `height`. Walls stop at `height - roof:height`; adding them makes every
roofed building too tall.

**Modelling only the easy roof shapes.** Covering `pyramidal` and letting gabled, hipped,
skillion and mansard fall back to flat loses most of the roof detail an area states.
Model what the area actually tags, and count what you could not.

**Claiming a check you did not run.** A report saying "verifier passes" when the verifier
was never invoked is worse than no report, because it removes the reason to look. Run it,
then quote it. The same goes for a `--verify` mode that prints "checks passed" without
evaluating anything — one shipped here, and it exited 0 on a scene whose every height was
a fabricated constant.

**Reading tags from the wrong level.** One stage read `tags = properties`, another read
`tags = properties.get("tags", {})`. Only one can be right; the second returned empty, so
all 606 stated heights were lost and every building in the delivered scene carried
`"height_source": "median_fallback:45"`. The verifier passed it — the geometry was fine,
only the meaning was gone. **After parsing, print the provenance histogram and compare it
against the coverage you measured.** 0% `tag:height` where inspection said 84% is the bug
announcing itself, for free, in one line.

**A fallback constant with no origin.** The same pipeline used a literal `45.0` labelled
`median_fallback:45` — 45 was not the median of anything. A provenance label naming a
computation that never happened is worse than an honest `default:45m`, because it survives
review by looking like a measurement.

## 4. Geometry that validates but renders wrong

The verifier checks each node in isolation. These are failures *between* nodes:

- **Coplanar overlapping surfaces z-fight.** Two flat things at the same Z covering the
  same ground will dither against each other. The engine cannot resolve it; only
  separation can. Give overlapping classes distinct heights, or do not emit both.
- **Ways that cross without touching** — bridges and tunnels carry `layer`. A tunnel drawn
  at street level paves over the road above it.
- **Duplicate geometry** — the same feature emitted twice (for example once as a way and
  once through a relation) is invisible in validation and obvious on screen.

## 5. Finish by verifying, then iterate

Run the pipeline, run its own `--verify` self-checks, then call `osm_verify_scene` — the
one tool this plugin still provides — and fix what it reports. Note that it checks
**height provenance** against the source as well as geometry: if the extract states
heights and your `height_source` labels do not use them, it fails, because that is what
reading tags from the wrong level looks like from outside. It re-derives from the
original OSM extract rather than trusting your manifest, so it catches a projection or
orientation error that looks perfectly consistent from inside your own code.

Then confirm a second run is byte-identical, and report what you actually observed —
including what you could not do and what you left out. An honest gap can be fixed; a
false claim of completeness cannot.
