---
name: coordinates
description: Projecting OSM lon/lat into Unreal world coordinates. Load before writing any code that converts geometry.
---

# Coordinates: WGS84 → Unreal

Getting this wrong is the failure that looks like success: the city renders, and it is
mirrored, rotated, or 30% too wide. Verify numerically, do not eyeball it.

## The frame

- **Origin**: centre of the *requested* bbox (`bbox_requested_south_west_north_east` in
  `<area>.fetch.json`), not the fetched/buffered one. Buffering must not move the origin.
- **Units**: centimetres. Metres × 100.
- **Axes**: `+X = North`, `+Y = East`, `+Z = Up`.

The axis mapping matters: with `+X = North` a top-down view in the editor reads north-up
and east-right, matching a map. Swapping them mirrors the city, which is easy to miss on a
grid and obvious on a river.

## The projection

A local tangent plane at the origin, using the WGS84 radii of curvature. Over an area of a
few hundred metres this is accurate to well under a centimetre — better than the data.

```python
A, F = 6378137.0, 1 / 298.257223563      # WGS84
E2 = F * (2 - F)
phi0 = math.radians(origin_lat)
M = A * (1 - E2) / (1 - E2 * math.sin(phi0) ** 2) ** 1.5   # meridional radius
N = A / math.sqrt(1 - E2 * math.sin(phi0) ** 2)            # normal radius

x_cm = math.radians(lat - origin_lat) * M * 100.0                    # +X North
y_cm = math.radians(lon - origin_lon) * N * math.cos(phi0) * 100.0   # +Y East
```

Do **not** use `111320 * cos(lat)` as a shortcut — it ignores the ellipsoid and drifts
about 0.1–0.2% across a kilometre, which is metres of error on a city block.

`pyproj` and `shapely` are **not installed**. Standard library only.

## Prove it rather than claim it

Before emitting anything, check the projection against an independent measure and print
the result:

- **Scale**: take two far-apart points, compare their projected distance against the
  haversine distance of the same lon/lat pair. Expect < 0.05% error.
- **Orientation**: a known street's bearing should match reality — Manhattan's avenues run
  ~29° east of north, so a long road's `atan2(dY, dX)` should land near 29° or 119°.
- **Extent**: the projected bounding box should be about `(north - south) × 111320` m
  tall. Wildly off means the axes are swapped or degrees leaked through unconverted.

## Rounding

Round to whole centimetres on output. It keeps files small and makes byte-identical reruns
easy to confirm; sub-centimetre precision is meaningless against OSM's own accuracy.
