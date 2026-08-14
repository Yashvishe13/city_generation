"""Stage 3: WGS84 lon/lat -> local metric frame -> UE centimetres.

Projection: a Transverse Mercator centred on the area origin
(`+proj=tmerc +lat_0=<origin_lat> +lon_0=<origin_lon> +k=1 +units=m`).
Over an area of a few km the scale error is < 1e-6, so metres are true metres
and the local origin is exactly (0, 0).

UE axis convention used everywhere downstream:
    +X = North (cm), +Y = East (cm), +Z = Up (cm)
Top-down in the UE editor this renders north-up / east-right, matching a map.
"""
from __future__ import annotations

import math
from typing import Sequence

from pyproj import CRS, Transformer
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from .config import AreaConfig

UE_UNITS_PER_M = 100.0  # UE works in centimetres

# Drop degenerate footprints below this area (m^2) and collapse vertices
# closer together than this (m).
MIN_FOOTPRINT_AREA_M2 = 6.0
SIMPLIFY_TOLERANCE_M = 0.20


class LocalFrame:
    """lon/lat <-> local metres <-> UE centimetres for one area."""

    def __init__(self, origin_lat: float, origin_lon: float):
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.proj4 = (
            f"+proj=tmerc +lat_0={origin_lat} +lon_0={origin_lon} "
            "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )
        self.crs = CRS.from_proj4(self.proj4)
        self._fwd = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)

    def to_metres(self, lon: float, lat: float) -> tuple[float, float]:
        """-> (east_m, north_m) relative to origin."""
        return self._fwd.transform(lon, lat)

    def ring_to_metres(
        self, ring: Sequence[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        return [self.to_metres(lon, lat) for lon, lat in ring]

    @staticmethod
    def metres_to_ue(east_m: float, north_m: float) -> tuple[float, float]:
        """(east, north) metres -> (UE X, UE Y) centimetres."""
        return (north_m * UE_UNITS_PER_M, east_m * UE_UNITS_PER_M)


def clean_polygon(ring_m: Sequence[tuple[float, float]]) -> Polygon | None:
    """Validate/simplify a footprint in metric space. Returns CCW polygon or None."""
    if len(ring_m) < 4:
        return None
    poly = Polygon(ring_m)
    if not poly.is_valid:
        poly = poly.buffer(0)  # fixes self-intersections
        if poly.is_empty:
            return None
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
    if poly.area < MIN_FOOTPRINT_AREA_M2:
        return None
    poly = poly.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True)
    if poly.is_empty or poly.area < MIN_FOOTPRINT_AREA_M2:
        return None
    return orient(poly, sign=1.0)  # CCW exterior in (east, north)


def oriented_box(poly: Polygon) -> dict[str, float]:
    """Minimum-area rotated rectangle -> centre, extents, yaw.

    Lets a simple PCG static-mesh path place a rotated box per building before
    the full footprint extrusion path exists.
    """
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:4]
    (x0, y0), (x1, y1), (x2, y2) = coords[0], coords[1], coords[2]
    len_a = math.hypot(x1 - x0, y1 - y0)
    len_b = math.hypot(x2 - x1, y2 - y1)
    if len_a >= len_b:
        long_vec, length, width = (x1 - x0, y1 - y0), len_a, len_b
    else:
        long_vec, length, width = (x2 - x1, y2 - y1), len_b, len_a
    cx, cy = rect.centroid.x, rect.centroid.y
    # Yaw about UE +Z, measured from UE +X (north) towards +Y (east).
    yaw_deg = math.degrees(math.atan2(long_vec[0], long_vec[1]))
    return {
        "center_east_m": cx,
        "center_north_m": cy,
        "length_m": length,
        "width_m": width,
        "yaw_deg": (yaw_deg + 360.0) % 360.0,
    }


def build_frame(area: AreaConfig) -> LocalFrame:
    lat, lon = area.origin
    return LocalFrame(lat, lon)
