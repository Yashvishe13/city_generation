---
name: estimation
description: How to derive heights and widths OSM does not state, without inventing them. Load before writing the estimation part of a pipeline.
---

# Estimating what OSM does not state

Real extracts are incomplete, and incompleteness varies wildly by city. Midtown Manhattan
states `height` on 84% of buildings; Le Marais states it on **1 building out of 694**.
Chicago's Loop states it on 17%. No fixed rule survives that spread, so the estimator is
written per area, fitted on the area being converted.

**The failure to avoid**: taking a number measured in one city and applying it everywhere.
A previous pipeline carried `STOREY_M = 3.5`, fitted from Manhattan's height/levels ratio,
and then applied Manhattan storey heights to Bavarian roofs. It was not visible in the
output, only in the code.

## Order of preference

1. **Stated** — use the tag. `height`, `building:levels`, `width`, `lanes`.
2. **Fitted from this area** — learn the relationship from the features that *do* state it.
   - metres per storey: buildings tagging **both** `height` and `building:levels` give the
     ratio directly. Midtown has 57 such pairs; other areas have their own count, and some
     have none.
   - height from footprint: tagged heights against footprint area, optionally restricted
     to the same `building=*` type when that type has enough labelled peers.
   - carriageway width: areas tagging `width` give metres per lane and per-class defaults
     (Boston's financial district states width on 73% of road length; Midtown states it on
     none).
3. **Borrowed, and labelled as borrowed** — if this area cannot fit a value, another
   fetched area may supply it, but the label must say so:
   `building:levels*3.41m@fitted:munich_altstadt`. Never launder a borrowed number as if
   it were local.
4. **Refuse** — say the area has no signal rather than invent a number with no basis. Le
   Marais cannot yield metres-per-storey: 1 tagged height, 0 height/levels pairs. An
   honest gap beats a confident fabrication.

**Refusing a value is not the same as dropping the feature.** Footprint shape and
placement are the most heavily weighted part of the result, so a building whose height had
to be guessed still belongs in the scene — with its estimate labelled and counted. Deleting
50 buildings because their height was unknown removes 50 correct footprints to avoid 50
approximate heights, which is the wrong trade. Emit the volume, label the height honestly,
and put the count in the manifest.

## Prove the estimator is worth using

Fitting is easy; knowing whether it helps is the point.

- **Hold out and score**: hide each known value, predict it from the rest, and report
  median and mean absolute error.
- **Compare against the trivial baseline**: the area's global median. An estimator that
  does not beat it is not worth shipping — say so instead of shipping it.
- Worked example: on Midtown, kNN over log footprint area (k chosen by leave-one-out,
  type-restricted when a type had ≥7 labelled peers) scored **MedAE 6.85 m against the
  area-median baseline's 21.35 m**. That earned its place. The same code on Le Marais
  correctly refused to fit.
- Report what you tried and dropped. On Midtown, type medians were useless (nearly every
  building is `building=yes`) and spatial neighbours were misleading (a tower sits next to
  a loft). Negative results are worth writing down.

## Label everything

Every derived number carries its provenance in the node's `attrs`, so a reviewer can
separate measurement from assumption without reading code:

```
tag:height                     measured
building:levels*3.4m           one assumption, fitted here
lanes*3.25m                    one assumption, fitted here
class_default:residential=10m  a class-level assumption
knn[type=commercial k=7 n=12]  an estimate, with the fit that produced it
@fitted:<other_area>           borrowed, source named
```

Then summarise the distribution in the manifest: how many values came from each source.
That single table is what tells a reviewer how data-driven the reconstruction really is.

## Do not

- Do not hardcode a storey height, lane width, or default height as a module constant.
  Fit it, borrow it with a label, or refuse.
- Do not silently fall back to a global default when a fit fails — count the fallbacks and
  report them.
- Do not use randomness. Estimates must be reproducible.
