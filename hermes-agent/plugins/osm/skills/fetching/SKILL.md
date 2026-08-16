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

**Key the cache on the query, not on the filename.** A cache that is reused whenever the
file merely exists is a silent-failure machine: widen the selectors to pick up parks and
water, re-run, and you get the old narrow extract back, emit no ground cover, and report
success — the pipeline did everything right against data that predates the change. The
sidecar already records `selectors`, `bbox_requested`, `buffer_m` and `date_pinned`.
Compare all four against what this run is asking for, and re-fetch if any differ. Say in
the log which one changed, so a re-download is never a mystery.

The sidecar carries enough for a reviewer to re-run your fetch: `area`,
`bbox_requested_south_west_north_east`, `bbox_fetched_south_west_north_east`, `buffer_m`,
`date_pinned`, `endpoint`, `fetched_utc`, the `osm3s` copyright block Overpass returns,
`element_count`, `selectors`, the exact `query`, and
`"Data (c) OpenStreetMap contributors, ODbL 1.0"`.

`bbox_requested` is the one that matters downstream: **the origin is the centre of the
requested bbox**, so buffering must never move it (`osm:coordinates`). Buffer with
`buffer_m` — around 150 m — so features straddling the boundary come back whole rather
than arriving as fragments.

Overpass returns any intersecting way *in full*, so what comes back always covers more
ground than the box you asked for. That is the API, and boundary features arriving
complete is the point of the buffer. Record the extent you actually emit in the manifest
next to `bbox_requested` so the difference is visible rather than surprising.

## Areas

Presets live in `data/areas.json`, keyed by name, each `{"bbox": [south, west, north,
east], "note": "..."}`. Read it from `REPO_ROOT`; the notes say what each area's tagging
is actually like and why it was chosen. Any bbox works — the presets are convenience,
not a closed set.
