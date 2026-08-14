"""Stage 2: raw Overpass JSON -> typed feature dicts in WGS84 (lon/lat)."""
from __future__ import annotations

import re
from typing import Any, Iterable

from .config import (
    DEFAULT_HEIGHT_M,
    HEIGHT_BY_BUILDING_TYPE,
    METRES_PER_LEVEL,
    ROAD_WIDTH_M,
    AreaConfig,
)

_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
_FEET_INCHES = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*'\s*(\d+(?:\.\d+)?)?\s*\"?\s*$")


def parse_length_m(raw: str | None) -> float | None:
    """Parse an OSM length tag into metres. Handles m, ft, 12'6", bare numbers."""
    if not raw:
        return None
    s = str(raw).strip().lower()

    m = _FEET_INCHES.match(s)
    if m:
        feet = float(m.group(1))
        inches = float(m.group(2) or 0.0)
        return (feet * 12.0 + inches) * 0.0254

    unit_ft = "ft" in s or "feet" in s or "'" in s
    num = _NUM.search(s)
    if not num:
        return None
    val = float(num.group(0).replace(",", "."))
    if val <= 0:
        return None
    return val * 0.3048 if unit_ft else val


def parse_levels(raw: str | None) -> float | None:
    """building:levels can be '3', '3;4', '2.5'. Take the max sane value."""
    if not raw:
        return None
    vals = [float(v.replace(",", ".")) for v in _NUM.findall(str(raw))]
    vals = [v for v in vals if 0 < v < 200]
    return max(vals) if vals else None


def derive_height(tags: dict[str, str]) -> tuple[float, str]:
    """Return (height_m, source) for a building. Source is recorded for the report."""
    h = parse_length_m(tags.get("height")) or parse_length_m(tags.get("building:height"))
    if h:
        return h, "tag:height"

    levels = parse_levels(tags.get("building:levels"))
    if levels:
        roof = parse_levels(tags.get("roof:levels")) or 0.0
        return (levels + roof) * METRES_PER_LEVEL, "tag:levels"

    btype = (tags.get("building") or tags.get("building:part") or "").lower()
    if btype in HEIGHT_BY_BUILDING_TYPE:
        return HEIGHT_BY_BUILDING_TYPE[btype], f"estimate:type={btype}"

    return DEFAULT_HEIGHT_M, "estimate:default"


def min_height(tags: dict[str, str]) -> float:
    """building:min_level / min_height lifts a part off the ground."""
    mh = parse_length_m(tags.get("min_height"))
    if mh:
        return mh
    lv = parse_levels(tags.get("building:min_level"))
    return (lv or 0.0) * METRES_PER_LEVEL


def _ring(geom: list[dict[str, float]]) -> list[tuple[float, float]]:
    """Overpass geometry list -> [(lon, lat), ...]."""
    return [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]


def _close(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(ring) >= 2 and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return ring


def _is_closed(ring: list[tuple[float, float]]) -> bool:
    return len(ring) >= 4 and ring[0] == ring[-1]


def parse_elements(payload: dict[str, Any], area: AreaConfig) -> dict[str, list[dict]]:
    """Split raw Overpass elements into buildings / roads / water / green."""
    buildings: list[dict] = []
    roads: list[dict] = []
    water: list[dict] = []
    green: list[dict] = []
    allowed_roads = set(area.road_classes)

    for el in payload.get("elements", []):
        tags: dict[str, str] = el.get("tags") or {}
        etype = el.get("type")
        oid = el.get("id")

        if etype == "way":
            ring = _ring(el.get("geometry") or [])
        elif etype == "relation":
            ring = []
        else:
            continue

        if "building" in tags or "building:part" in tags:
            rings = _relation_outers(el) if etype == "relation" else ([ring] if ring else [])
            for r in rings:
                r = _close(r)
                if not _is_closed(r):
                    continue
                h, src = derive_height(tags)
                buildings.append({
                    "osm_id": oid,
                    "osm_type": etype,
                    "ring": r,
                    "height_m": round(h, 2),
                    "min_height_m": round(min_height(tags), 2),
                    "height_source": src,
                    "is_part": "building:part" in tags and "building" not in tags,
                    "kind": tags.get("building") or tags.get("building:part") or "yes",
                    "name": tags.get("name", ""),
                })
            continue

        if "highway" in tags:
            hw = tags["highway"]
            if hw not in allowed_roads or len(ring) < 2:
                continue
            layer = _int_or(tags.get("layer"), 0)
            roads.append({
                "osm_id": oid,
                "points": ring,
                "highway": hw,
                "name": tags.get("name", ""),
                "width_m": parse_length_m(tags.get("width")) or ROAD_WIDTH_M.get(hw, 7.0),
                "lanes": parse_levels(tags.get("lanes")) or 0,
                "oneway": tags.get("oneway", "no") == "yes",
                "layer": layer,
                "bridge": "bridge" in tags,
                "tunnel": "tunnel" in tags,
            })
            continue

        if tags.get("natural") == "water" or tags.get("waterway") == "riverbank":
            r = _close(ring)
            if _is_closed(r):
                water.append({"osm_id": oid, "ring": r, "kind": "water"})
            continue

        if tags.get("leisure") or tags.get("landuse"):
            r = _close(ring)
            if _is_closed(r):
                green.append({
                    "osm_id": oid,
                    "ring": r,
                    "kind": tags.get("leisure") or tags.get("landuse"),
                })

    return {"buildings": buildings, "roads": roads, "water": water, "green": green}


def _relation_outers(el: dict) -> list[list[tuple[float, float]]]:
    """Outer rings of a multipolygon relation returned with `out geom`."""
    out: list[list[tuple[float, float]]] = []
    for member in el.get("members") or []:
        if member.get("role") not in ("outer", ""):
            continue
        ring = _ring(member.get("geometry") or [])
        if len(ring) >= 3:
            out.append(ring)
    return out


def _int_or(raw: str | None, default: int) -> int:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return default


def summarize(features: dict[str, list[dict]]) -> dict[str, Any]:
    src_counts: dict[str, int] = {}
    for b in features["buildings"]:
        key = b["height_source"].split(":")[0] + ":" + b["height_source"].split(":")[1].split("=")[0]
        src_counts[key] = src_counts.get(key, 0) + 1
    return {
        "buildings": len(features["buildings"]),
        "roads": len(features["roads"]),
        "water": len(features["water"]),
        "green": len(features["green"]),
        "height_sources": src_counts,
    }


def iter_rings(features: dict[str, list[dict]]) -> Iterable[list[tuple[float, float]]]:
    for key in ("buildings", "water", "green"):
        for f in features[key]:
            yield f["ring"]
