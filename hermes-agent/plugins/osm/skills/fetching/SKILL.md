---
name: fetching
description: Downloading an OSM area from Overpass inside your own pipeline - query, mirrors, truncation, relations, cache and provenance. Load before writing the fetch stage.
---

# Fetching the source data

There is no tool that downloads for you. The fetch is the first stage of your pipeline
and you write it, in the standard library, with `urllib.request`. It is about eighty
lines. What follows is what this project learned the hard way about each of them.

## The design rule: fetch preserves, it does not interpret

Nothing is filtered, renamed or parsed at download time. Every OSM tag survives into the
GeoJSON exactly as mapped — 229 distinct keys for the Chicago Loop area. What a `height`
means, which road classes matter, whether a `building:part` supersedes its parent: all
later decisions. If the download made them, changing your mind would mean re-fetching,
and Overpass is the slowest thing in the pipeline.

## The query

```python
settings = f"[out:json][timeout:{timeout_s}]"        # + f'[date:"{date}"]' to pin
body = "\n".join(f"  {sel}({s},{w},{n},{e});" for sel in selectors)
query = f"{settings};\n(\n{body}\n);\nout geom;"
```

`out geom` inlines way coordinates *and* relation member coordinates, so the response is
self-contained — no second pass to resolve node ids.

The default selectors, which are selectors and not semantics:

```
way["building"]   way["building:part"]   relation["building"]   relation["building:part"]   way["highway"]
```

Everything matching comes back with all of its tags. Widen coverage (water, landuse,
rail) by adding a selector; never by filtering here.

`[date:"2026-08-01T00:00:00Z"]` pins the snapshot so a re-run returns identical data,
which is what makes a determinism claim survive OSM being edited under you.

## Mirrors, retries, and the failure that looks like success

```
https://overpass-api.de/api/interpreter
https://overpass.kumi.systems/api/interpreter
https://overpass.osm.ch/api/interpreter
```

Two attempts per endpoint, then the next. Back off on 429 and 504 (5 s × attempt); on a
URLError, timeout or unparseable body, pause briefly and move on. Send a `User-Agent`
naming the project — mirrors throttle anonymous clients harder.

**Overpass reports partial results at HTTP 200.** A truncated query comes back as a
perfectly valid JSON body carrying a `remark` field. Treat a `remark`, or an empty
`elements` list, as failure and try the next mirror — never as data. A half-downloaded
area that silently converts is a city with a bite taken out of it and no error anywhere.

## Overpass JSON → GeoJSON

- **Closed ways are ambiguous.** A closed `highway` is a loop road; a closed `building`
  is a footprint. Resolve it: `area=yes` forces the area reading; anything with `highway`
  or `barrier` stays a line; otherwise a ring of ≥4 points whose ends match is an area.
- **Relations** need no extra request thanks to `out geom`. Members with role `inner` are
  holes, everything else is outer. One outer → `Polygon` with the inners after it;
  several outers → `MultiPolygon`. Attributing a hole to a *specific* outer needs
  point-in-polygon, which is geometry work for a later stage.
- **Untagged elements** are Overpass filling in geometry; skip them and count them.
- Count every skip by reason. Nothing is dropped silently, at any stage.

**Decide the property shape once and read it back the same way.** The convention here is
flat: tags go directly into `properties`, with the element identity prefixed so it cannot
collide with a real tag.

```json
{"type": "Feature",
 "properties": {"osm_id": 123, "osm_type": "way", "building": "yes", "height": "128"},
 "geometry": {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}}
```

This has already cost a run: one stage read `tags = properties`, another read
`tags = properties.get("tags", {})`, the second returned empty, and 606 stated heights
vanished into a fallback constant with nothing failing. Pick the shape, and after parsing
print how many features carried `height` — if that number does not match what you
measured, you are reading the wrong level.

## Cache and provenance

Write three files into `data/raw/`, resolved from `REPO_ROOT`, never absolute:

| file | content |
|---|---|
| `osm_<area>.json` | the raw Overpass payload, untouched |
| `<area>.geojson` | the converted features, all tags preserved |
| `<area>.fetch.json` | provenance |

Reuse them on every run unless `--force`. A cached result must report the bbox it
*actually* covers, not the one this invocation asked for — read it back out of the
sidecar rather than assuming.

The sidecar carries enough for a reviewer to re-run your fetch: `area`,
`bbox_requested_south_west_north_east`, `bbox_fetched_south_west_north_east`, `buffer_m`,
`date_pinned`, `endpoint`, `fetched_utc`, the `osm3s` copyright block Overpass returns,
`element_count`, `selectors`, the exact `query`, and
`"Data (c) OpenStreetMap contributors, ODbL 1.0"`.

`bbox_requested` is the one that matters downstream: **the origin is the centre of the
requested bbox**, so buffering must never move it (`osm:coordinates`). Buffer with
`buffer_m` — around 150 m — so features straddling the boundary come back whole rather
than arriving as fragments.

## The extent you get back is larger than the extent you asked for

Overpass returns any way that *intersects* the query box **in its entirety**, so a 150 m
buffer does not give you a 150 m margin — it gives you every long avenue and every large
feature that so much as clips the corner, at full length.

`out geom(south,west,north,east)` exists and clips server-side, but it only filters
*existing* vertices: it cannot synthesise a vertex on the boundary, so a segment that
crosses keeps its far endpoint, and on a straight avenue consecutive nodes can be hundreds
of metres apart. Measured on Midtown it took the extent from 6.2x the requested area to
2.3x, not to 1x. Applied to buildings it is worse than useless - it truncates footprints
into **broken rings**.

**Do not build a clipping stage.** Keeping boundary features whole is the correct
behaviour and is what the buffer was bought for; a footprint cut in half is an open prism
and a worse error than a little margin. Record the emitted extent alongside
`bbox_requested` in the manifest so the difference is visible, and leave it there.

What is *not* acceptable is a handful of enormous features silently setting the extent. On
this project three did: Grand Central Terminal, Times Square-42nd Street and 34th
Street-Herald Square, each tagged `building=train_station` with `location=underground` and
`layer=-1`/`-2`, spanning up to 737 m, extruded as though they stood on the street. Those
three took the scene to ~6x the requested area on their own, and the boundary had almost
nothing to do with it.

That is a below-grade bug, not a boundary bug - the exclusion rule in `osm:roads` applies
just as much to buildings. **If your emitted extent is several times the request, find the
largest few features and read their tags before assuming the boundary is at fault.**

## Areas

Presets live in `data/areas.json`, keyed by name, each `{"bbox": [south, west, north,
east], "note": "..."}`. Read it from `REPO_ROOT`; the notes say what each area's tagging
is actually like and why it was chosen. Any bbox works — the presets are convenience,
not a closed set.
