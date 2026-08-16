#!/usr/bin/env python3
"""OSM -> Unreal pipeline for nyc_midtown. Standard library only.

fetch (Overpass, cached) -> inspect -> fit -> project -> resolve parts
-> emit data/ue/<area>/scene.json -> self-check
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants that are definitions, not fitted estimates
# ---------------------------------------------------------------------------
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
R_MEAN_M = 6371008.8
CM_PER_M = 100.0

SELECTORS = (
    'way["building"]',
    'way["building:part"]',
    'relation["building"]',
    'relation["building:part"]',
    'way["highway"]',
    'way["leisure"]',
    'relation["leisure"]',
    'way["landuse"]',
    'relation["landuse"]',
    'way["natural"]',
    'way["water"]',
    'way["waterway"]',
    'way["amenity"="parking"]',
    'way["railway"]',
)
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
)
USER_AGENT = "citygen-osm-pipeline/nyc_midtown"
DATE_PINNED = "2026-08-15T00:00:00Z"
BUFFER_M = 150.0
TIMEOUT_S = 180
OVERPASS_TIMEOUT_S = 90

DRIVEABLE = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "residential",
        "unclassified",
        "living_street",
        "service",
    }
)
NONFLAT_ROOFS = frozenset(
    {"pyramidal", "skillion", "gabled", "hipped", "dome", "mansard", "round", "onion"}
)
# NYCDOT Street Design Manual typical widths. Not fitted here: this extract
# states width on zero driveable ways and zero sidewalks.
NYCDOT_LANE_M = 3.05
NYCDOT_PARK_M = 2.44
NYCDOT_BIKE_LANE_M = 1.52
NYCDOT_BIKE_TRACK_M = 2.44
NYCDOT_SIDEWALK_M = 4.57
NYCDOT_FOOTWAY_M = 1.83
SERVICE_LANE_FALLBACK = 1.0
# Engine ribbons sit at RibbonZOffsetCm + layer * LayerSpacingCm (4 + layer*400).
# A 15 cm curb cannot be a ribbon, so the pedestrian plane is a mesh.
CURB_Z_CM = 19
PLAZA_Z_CM = 16
JUNCTION_LIFT_CM = 2
# Ground cover sits in the 0..4 cm band between the slab top (Z=0) and the
# carriageway (RibbonZOffsetCm = 4). Each class has its own Z so nested
# Bryant Park polygons do not z-fight. Nothing ground-cover goes below 0:
# the slab is Origin=Base at Z=-100, so its top is Z=0.
GROUND_Z_CM = {
    "landuse": 1,
    "parking": 1,
    "park": 2,
    "garden": 2,
    "pitch": 3,
    "playground": 3,
    "flowerbed": 3,
    "sand": 3,
    "water": 3,
}
KNN_K_CANDIDATES = (3, 5, 7, 9, 11, 15)
KNN_TYPE_MIN = 7

DISTRICT_LANDUSE = frozenset(
    {
        "commercial",
        "retail",
        "industrial",
        "residential",
        "construction",
        "brownfield",
        "railway",
        "education",
        "institutional",
    }
)
IDENTITY_KEYS = frozenset({"osm_id", "osm_type"})


# ---------------------------------------------------------------------------
# Repo / CLI
# ---------------------------------------------------------------------------
def resolve_repo(args_repo: str | None) -> Path:
    raw = args_repo or os.environ.get("CITYGEN_REPO")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2]


def relpath(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OSM to Unreal scene for one area")
    p.add_argument("--area", default="nyc_midtown")
    p.add_argument("--repo", default=None, help="project root (honoured)")
    p.add_argument("--force", action="store_true", help="re-download Overpass cache")
    p.add_argument("--verify", action="store_true", help="run assertions after emit")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _wgs84_radii(origin_lat: float) -> tuple[float, float]:
    phi0 = math.radians(origin_lat)
    meridional = WGS84_A * (1.0 - WGS84_E2) / (1.0 - WGS84_E2 * math.sin(phi0) ** 2) ** 1.5
    normal = WGS84_A / math.sqrt(1.0 - WGS84_E2 * math.sin(phi0) ** 2)
    return meridional, normal


def make_projector(origin_lat: float, origin_lon: float):
    meridional, normal = _wgs84_radii(origin_lat)
    phi0 = math.radians(origin_lat)
    cos0 = math.cos(phi0)

    def project_cm(lon: float, lat: float) -> tuple[float, float]:
        x = math.radians(lat - origin_lat) * meridional * CM_PER_M
        y = math.radians(lon - origin_lon) * normal * cos0 * CM_PER_M
        return x, y

    return project_cm


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    rlon1, rlat1, rlon2, rlat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    h = (
        math.sin((rlat2 - rlat1) / 2.0) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin((rlon2 - rlon1) / 2.0) ** 2
    )
    return 2.0 * R_MEAN_M * math.asin(math.sqrt(min(1.0, h)))


def vincenty_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """WGS84 inverse geodesic (Vincenty). Independent of the local tangent plane."""
    if lon1 == lon2 and lat1 == lat2:
        return 0.0
    b = WGS84_A * (1.0 - WGS84_F)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    L = math.radians(lon2 - lon1)
    u1 = math.atan((1.0 - WGS84_F) * math.tan(phi1))
    u2 = math.atan((1.0 - WGS84_F) * math.tan(phi2))
    sin_u1, cos_u1 = math.sin(u1), math.cos(u1)
    sin_u2, cos_u2 = math.sin(u2), math.cos(u2)
    lam = L
    cos2_alpha = 0.0
    sin_sigma = cos_sigma = sigma = cos_2sm = 0.0
    for _ in range(50):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(
            cos_u2 * sin_lam,
            cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam,
        )
        if sin_sigma == 0.0:
            return 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos2_alpha = 1.0 - sin_alpha * sin_alpha
        cos_2sm = cos_sigma - 2.0 * sin_u1 * sin_u2 / cos2_alpha if cos2_alpha else 0.0
        c = WGS84_F / 16.0 * cos2_alpha * (2.0 + WGS84_F * (4.0 - 3.0 * cos2_alpha))
        lam_prev = lam
        lam = L + (1.0 - c) * WGS84_F * sin_alpha * (
            sigma
            + c * sin_sigma * (cos_2sm + c * cos_sigma * (-1.0 + 2.0 * cos_2sm * cos_2sm))
        )
        if abs(lam - lam_prev) < 1e-12:
            break
    u2s = cos2_alpha * (WGS84_A * WGS84_A - b * b) / (b * b)
    aa = 1.0 + u2s / 16384.0 * (4096.0 + u2s * (-768.0 + u2s * (320.0 - 175.0 * u2s)))
    bb = u2s / 1024.0 * (256.0 + u2s * (-128.0 + u2s * (74.0 - 47.0 * u2s)))
    dsigma = bb * sin_sigma * (
        cos_2sm
        + bb
        / 4.0
        * (
            cos_sigma * (-1.0 + 2.0 * cos_2sm * cos_2sm)
            - bb / 6.0 * cos_2sm * (-3.0 + 4.0 * sin_sigma * sin_sigma) * (-3.0 + 4.0 * cos_2sm * cos_2sm)
        )
    )
    return b * aa * (sigma - dsigma)


def open_ring(coords: list) -> list:
    if coords and coords[0] == coords[-1]:
        return list(coords[:-1])
    return list(coords)


def signed_area(ring: list) -> float:
    total = 0.0
    n = len(ring)
    if n < 3:
        return 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def ensure_ccw(ring: list) -> list:
    if signed_area(ring) < 0:
        return list(reversed(ring))
    return list(ring)


def centroid_xy(ring: list) -> tuple[float, float]:
    a = signed_area(ring)
    if abs(a) < 1e-12:
        return (
            sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring),
        )
    cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        c = x1 * y2 - x2 * y1
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    return cx / (6.0 * a), cy / (6.0 * a)


def point_in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_cross(p1, p2, p3, p4) -> bool:
    d1, d2 = orientation(p3, p4, p1), orientation(p3, p4, p2)
    d3, d4 = orientation(p1, p2, p3), orientation(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def ring_problems(body: list) -> list[str]:
    problems: list[str] = []
    if len(body) < 3:
        return ["degenerate"]
    if len(body) != len({(p[0], p[1]) for p in body}):
        problems.append("repeated_vertex")
    segs = list(zip(body, body[1:] + body[:1]))
    n = len(segs)
    for i in range(n):
        for j in range(i + 2, n - (1 if i == 0 else 0)):
            if segments_cross(*segs[i], *segs[j]):
                problems.append("self_intersecting")
                return problems
    return problems


def rcm(value: float) -> int:
    return int(round(value))


# ---------------------------------------------------------------------------
# Tag parsing
# ---------------------------------------------------------------------------
def parse_metres(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace(",", ".")
    if not s:
        return None
    if "ft" in s or "foot" in s or "feet" in s or "'" in s:
        num = "".join(ch if (ch.isdigit() or ch in ".-") else " " for ch in s)
        parts = [p for p in num.split() if p not in ("-", ".")]
        try:
            v = float(parts[0]) * 0.3048
        except (ValueError, IndexError):
            return None
        return v if v > 0 else None
    cleaned = (
        s.replace("metres", " ")
        .replace("meters", " ")
        .replace("meter", " ")
        .replace("m", " ")
        .strip()
    )
    try:
        v = float(cleaned.split()[0])
    except (ValueError, IndexError):
        return None
    return v if v > 0 else None


def parse_number(raw) -> float | None:
    if raw is None:
        return None
    try:
        v = float(str(raw).strip().replace(",", "."))
    except ValueError:
        return None
    return v


def tags_of(props: dict) -> dict:
    """Flat GeoJSON properties. Never look for a nested 'tags' object."""
    return props


def feature_height_m(props: dict) -> float | None:
    return parse_metres(props.get("height")) or parse_metres(props.get("building:height"))


def feature_levels(props: dict) -> float | None:
    v = parse_number(props.get("building:levels"))
    if v is None or v == 0:
        return None
    return v


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def buffer_bbox(south, west, north, east, buffer_m: float) -> list[float]:
    lat0 = (south + north) / 2.0
    meridional, normal = _wgs84_radii(lat0)
    dlat = (buffer_m / meridional) * (180.0 / math.pi)
    dlon = (buffer_m / (normal * math.cos(math.radians(lat0)))) * (180.0 / math.pi)
    return [south - dlat, west - dlon, north + dlat, east + dlon]


def build_query(fetched_bbox: list[float], timeout_s: int, date_pinned: str) -> str:
    s, w, n, e = fetched_bbox
    settings = f'[out:json][timeout:{timeout_s}][date:"{date_pinned}"]'
    body = "\n".join(f"  {sel}({s},{w},{n},{e});" for sel in SELECTORS)
    return f"{settings};\n(\n{body}\n);\nout geom;"


def overpass_request(endpoint: str, query: str) -> dict:
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=OVERPASS_TIMEOUT_S) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("overpass body is not an object")
    if data.get("remark"):
        raise ValueError(f"overpass remark: {data['remark']}")
    elements = data.get("elements")
    if not elements:
        raise ValueError("overpass returned no elements")
    return data


def download_overpass(query: str) -> tuple[dict, str]:
    last_err: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(1, 3):
            try:
                return overpass_request(endpoint, query), endpoint
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code in (429, 504):
                    time.sleep(5.0 * attempt)
                    continue
                time.sleep(1.0)
                break
            except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                time.sleep(1.0)
                break
    raise RuntimeError(f"all Overpass mirrors failed: {last_err}")


def _pts_from_geom(geom: list) -> list[list[float]]:
    return [[float(nd["lon"]), float(nd["lat"])] for nd in geom]


def way_geometry(el: dict) -> tuple[str, list] | None:
    tags = el.get("tags") or {}
    geom = el.get("geometry") or []
    if len(geom) < 2:
        return None
    pts = _pts_from_geom(geom)
    closed = len(pts) >= 4 and pts[0] == pts[-1]
    if tags.get("area") == "yes":
        kind = "area" if closed else "line"
    elif "highway" in tags or "barrier" in tags:
        kind = "line"
    elif closed:
        kind = "area"
    else:
        kind = "line"
    if kind == "area":
        return "Polygon", [pts]
    return "LineString", pts


def relation_geometry(el: dict) -> tuple[str, list] | None:
    outers: list[list] = []
    inners: list[list] = []
    for mem in el.get("members") or []:
        if mem.get("type") != "way" or "geometry" not in mem:
            continue
        pts = _pts_from_geom(mem["geometry"])
        if len(pts) < 2:
            continue
        if pts[0] != pts[-1] and len(pts) >= 3:
            pts = pts + [pts[0]]
        if mem.get("role") == "inner":
            inners.append(pts)
        else:
            outers.append(pts)
    if not outers:
        return None
    if len(outers) == 1:
        rings = [outers[0]]
        oc = open_ring(outers[0])
        for inner in inners:
            ic = open_ring(inner)
            if ic and point_in_ring(*centroid_xy(ic), oc):
                rings.append(inner)
        return "Polygon", rings
    polygons = []
    for outer in outers:
        oc = open_ring(outer)
        rings = [outer]
        for inner in inners:
            ic = open_ring(inner)
            if ic and point_in_ring(*centroid_xy(ic), oc):
                rings.append(inner)
        polygons.append(rings)
    return "MultiPolygon", polygons


def overpass_to_geojson(payload: dict) -> tuple[dict, dict]:
    skip = Counter()
    features = []
    for el in payload.get("elements") or []:
        tags = el.get("tags")
        if not tags:
            skip["untagged_geometry"] += 1
            continue
        etype = el.get("type")
        if etype == "way":
            parsed = way_geometry(el)
        elif etype == "relation":
            parsed = relation_geometry(el)
        else:
            skip["node_or_other"] += 1
            continue
        if parsed is None:
            skip["empty_geometry"] += 1
            continue
        gtype, coords = parsed
        props = {"osm_id": el["id"], "osm_type": etype}
        for key, val in tags.items():
            if key not in IDENTITY_KEYS:
                props[key] = val
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": gtype, "coordinates": coords},
            }
        )
    features.sort(key=lambda f: (f["properties"]["osm_type"], f["properties"]["osm_id"]))
    geojson = {"type": "FeatureCollection", "features": features}
    return geojson, dict(skip)


def load_area_bbox(repo: Path, area: str) -> list[float]:
    areas_path = repo / "data" / "areas.json"
    data = json.loads(areas_path.read_text(encoding="utf-8"))
    if area not in data or not isinstance(data[area], dict) or "bbox" not in data[area]:
        raise SystemExit(f"area {area!r} not in data/areas.json")
    return list(data[area]["bbox"])


def _floats_close(a, b) -> bool:
    if a is None or b is None:
        return False
    try:
        aa = [float(x) for x in a]
        bb = [float(x) for x in b]
    except (TypeError, ValueError):
        return False
    if len(aa) != len(bb):
        return False
    return all(abs(x - y) < 1e-9 for x, y in zip(aa, bb))


def cache_mismatches(sidecar: dict, wanted: dict) -> list[str]:
    """Reuse the cache only when the query itself matches, not just the filename."""
    reasons = []
    if list(sidecar.get("selectors") or []) != list(wanted["selectors"]):
        reasons.append("selectors")
    if not _floats_close(
        sidecar.get("bbox_requested_south_west_north_east"),
        wanted["bbox_requested_south_west_north_east"],
    ):
        reasons.append("bbox_requested")
    try:
        buf = float(sidecar.get("buffer_m"))
    except (TypeError, ValueError):
        buf = None
    if buf is None or abs(buf - float(wanted["buffer_m"])) > 1e-6:
        reasons.append("buffer_m")
    if sidecar.get("date_pinned") != wanted["date_pinned"]:
        reasons.append("date_pinned")
    return reasons


def fetch_stage(repo: Path, area: str, force: bool) -> tuple[dict, dict, str, str]:
    raw_dir = repo / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    geojson_rel = f"data/raw/{area}.geojson"
    fetch_rel = f"data/raw/{area}.fetch.json"
    osm_rel = f"data/raw/osm_{area}.json"
    geojson_path = repo / geojson_rel
    fetch_path = repo / fetch_rel
    osm_path = repo / osm_rel

    bbox_req = load_area_bbox(repo, area)
    south, west, north, east = [float(v) for v in bbox_req]
    bbox_fetch = buffer_bbox(south, west, north, east, BUFFER_M)
    query = build_query(bbox_fetch, TIMEOUT_S, DATE_PINNED)
    wanted = {
        "selectors": list(SELECTORS),
        "bbox_requested_south_west_north_east": [south, west, north, east],
        "buffer_m": BUFFER_M,
        "date_pinned": DATE_PINNED,
    }

    if geojson_path.is_file() and fetch_path.is_file() and not force:
        sidecar = json.loads(fetch_path.read_text(encoding="utf-8"))
        mismatches = cache_mismatches(sidecar, wanted)
        if not mismatches:
            geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
            print(f"fetch: cache hit {geojson_rel} ({sidecar.get('element_count')} elements)")
            return geojson, sidecar, geojson_rel, fetch_rel
        print(f"fetch: cache stale ({', '.join(mismatches)}); re-downloading")

    print(f"fetch: downloading {area} from Overpass (buffer {BUFFER_M} m, date {DATE_PINNED})")
    payload, endpoint = download_overpass(query)
    geojson, convert_skip = overpass_to_geojson(payload)
    osm3s = payload.get("osm3s") or {}
    sidecar = {
        "area": area,
        "bbox_requested_south_west_north_east": bbox_req,
        "bbox_fetched_south_west_north_east": bbox_fetch,
        "buffer_m": BUFFER_M,
        "date_pinned": DATE_PINNED,
        "source": "OpenStreetMap via Overpass API",
        "endpoint": endpoint,
        "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "osm3s": osm3s,
        "element_count": len(payload.get("elements") or []),
        "feature_count": len(geojson["features"]),
        "convert_skipped": convert_skip,
        "selectors": list(SELECTORS),
        "query": query,
        "licence": "Data (c) OpenStreetMap contributors, ODbL 1.0",
    }
    osm_path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True), encoding="utf-8")
    geojson_path.write_text(
        json.dumps(geojson, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    fetch_path.write_text(
        json.dumps(sidecar, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"fetch: wrote {osm_rel}, {geojson_rel}, {fetch_rel}")
    return geojson, sidecar, geojson_rel, fetch_rel


# ---------------------------------------------------------------------------
# Inspect / fit
# ---------------------------------------------------------------------------
def polygon_outers(geom: dict) -> list[list]:
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon" and coords:
        return [open_ring(coords[0])]
    if gtype == "MultiPolygon":
        return [open_ring(poly[0]) for poly in coords if poly]
    return []


def polygon_hole_count(geom: dict) -> int:
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        return max(0, len(coords) - 1)
    if gtype == "MultiPolygon":
        return sum(max(0, len(poly) - 1) for poly in coords)
    return 0


def parse_level_n(raw) -> float | None:
    """First numeric token of OSM level=* (may be '-1' or '-1;0')."""
    if raw is None:
        return None
    text = str(raw).strip().replace(",", ".")
    if not text:
        return None
    token = text.split(";")[0].strip()
    try:
        return float(token)
    except ValueError:
        return None


def below_grade_reason(props: dict) -> str | None:
    """One test for every class. First match wins. None means at grade."""
    loc = props.get("location")
    if loc == "underground":
        return "location=underground"
    layer_n = parse_number(props.get("layer"))
    if layer_n is not None and layer_n < 0:
        return "layer<0"
    tunnel = props.get("tunnel")
    if tunnel and tunnel != "no":
        return "tunnel"
    if props.get("indoor") == "yes":
        return "indoor=yes"
    level_n = parse_level_n(props.get("level"))
    if level_n is not None and level_n < 0:
        return "level<0"
    return None


def is_below_grade(rec: dict) -> bool:
    props = rec.get("props")
    if not isinstance(props, dict):
        props = rec
    return below_grade_reason(props) is not None


def classify_highways(roads: list) -> dict:
    """Split highways the way the tags already split them. Order is exclusive."""
    buckets = defaultdict(list)
    for rec in roads:
        hw = rec["highway"]
        if hw in DRIVEABLE and rec["area_yes"]:
            buckets["driveable_area"].append(rec)
        elif hw in DRIVEABLE:
            buckets["driveable_line"].append(rec)
        elif hw == "elevator":
            buckets["elevator"].append(rec)
        elif is_below_grade(rec):
            buckets["below_grade"].append(rec)
        elif hw == "steps":
            buckets["steps"].append(rec)
        elif rec["area_yes"]:
            buckets["plaza_area"].append(rec)
        elif rec.get("footway") == "crossing" or hw == "crossing":
            buckets["crossing"].append(rec)
        elif rec.get("footway") == "sidewalk":
            buckets["sidewalk"].append(rec)
        elif rec.get("footway") == "traffic_island":
            buckets["traffic_island"].append(rec)
        elif hw == "pedestrian":
            buckets["pedestrian_line"].append(rec)
        elif hw == "cycleway":
            buckets["cycleway"].append(rec)
        elif hw == "footway":
            buckets["generic_footway"].append(rec)
        else:
            buckets[f"other:{hw}"].append(rec)
    return dict(sorted(buckets.items(), key=lambda kv: kv[0]))


def classify_ground_class(props: dict) -> str | None:
    """Most specific surface class. Used for Z and for the report."""
    leisure = props.get("leisure")
    landuse = props.get("landuse")
    natural = props.get("natural")
    amenity = props.get("amenity")
    water = props.get("water")
    waterway = props.get("waterway")
    if natural == "water" or water or waterway in {"riverbank", "dock", "basin"}:
        return "water"
    if amenity == "fountain":
        return "water"
    if landuse == "flowerbed" or leisure == "garden" and landuse == "flowerbed":
        return "flowerbed"
    if landuse == "flowerbed":
        return "flowerbed"
    if leisure == "pitch":
        return "pitch"
    if leisure == "playground":
        return "playground"
    if natural == "sand":
        return "sand"
    if leisure == "park":
        return "park"
    if leisure == "garden":
        return "garden"
    if amenity == "parking":
        return "parking"
    if landuse in DISTRICT_LANDUSE:
        return None
    if landuse:
        return "landuse"
    if leisure:
        return "park"
    if natural:
        return None
    return None


def ground_cover_record(props: dict, geom: dict, gtype: str, project_cm):
    klass = classify_ground_class(props)
    if klass is None:
        return None
    outers = polygon_outers(geom)
    if not outers:
        return {
            "props": props,
            "osm_id": props.get("osm_id"),
            "osm_type": props.get("osm_type"),
            "klass": klass,
            "gtype": gtype,
            "ring_xy": None,
            "coords_ll": geom.get("coordinates") if gtype == "LineString" else None,
            "below_reason": below_grade_reason(props),
            "linear": True,
        }
    rings_xy = [[project_cm(lon, lat) for lon, lat in outer] for outer in outers]
    ring = max(rings_xy, key=lambda r: abs(signed_area(r)))
    return {
        "props": props,
        "osm_id": props.get("osm_id"),
        "osm_type": props.get("osm_type"),
        "klass": klass,
        "gtype": gtype,
        "ring_xy": ring,
        "holes": polygon_hole_count(geom),
        "below_reason": below_grade_reason(props),
        "linear": False,
        "leisure": props.get("leisure"),
        "landuse": props.get("landuse"),
        "natural": props.get("natural"),
    }


def inspect_and_index(features: list, project_cm) -> dict:
    buildings = []
    parts = []
    roads = []
    ground = []
    rails = []
    district_landuse = 0
    other = 0
    holes = 0
    ring_issue = Counter()
    key_counts: Counter = Counter()
    height_formats = Counter()

    for feat in features:
        props = tags_of(feat.get("properties") or {})
        for key in props:
            key_counts[key] += 1
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        has_b = "building" in props
        has_p = "building:part" in props
        raw_h = props.get("height")
        if raw_h is not None:
            s = str(raw_h)
            height_formats[
                "unitish" if any(ch.isalpha() or ch in "'\"" for ch in s) else "num"
            ] += 1

        if has_b or has_p:
            outers = polygon_outers(geom)
            if not outers:
                ring_issue["no_polygon"] += 1
                continue
            # largest outer for MultiPolygon
            rings_xy = []
            for outer_ll in outers:
                xy = [project_cm(lon, lat) for lon, lat in outer_ll]
                rings_xy.append(xy)
            rings_xy.sort(key=lambda r: abs(signed_area(r)), reverse=True)
            ring = rings_xy[0]
            outer_ll = max(
                outers,
                key=lambda r: abs(signed_area([project_cm(lon, lat) for lon, lat in r])),
            )
            holes += polygon_hole_count(geom)
            if len(ring) < 3:
                ring_issue["degenerate"] += 1
            for prob in ring_problems(ring):
                ring_issue[prob] += 1
            rec = {
                "props": props,
                "osm_id": props.get("osm_id"),
                "osm_type": props.get("osm_type"),
                "ring_ll": outer_ll,
                "ring_xy": ring,
                "area_m2": abs(signed_area(ring)) / (CM_PER_M * CM_PER_M),
                "centroid": centroid_xy(ring),
                "height_m": feature_height_m(props),
                "levels": feature_levels(props),
                "min_h": parse_metres(props.get("min_height")),
                "min_level": parse_number(props.get("building:min_level")),
                "roof_shape": props.get("roof:shape"),
                "roof_h": parse_metres(props.get("roof:height")),
                "roof_dir": props.get("roof:direction"),
                "roof_orient": props.get("roof:orientation"),
                "btype": props.get("building") if has_b else props.get("building:part"),
                "is_parent": has_b,
                "is_part": has_p and not has_b,
                "holes": polygon_hole_count(geom),
                "below_reason": below_grade_reason(props),
            }
            if rec["is_part"]:
                parts.append(rec)
            else:
                buildings.append(rec)
        elif props.get("highway"):
            layer_n = parse_number(props.get("layer"))
            rec = {
                "props": props,
                "osm_id": props.get("osm_id"),
                "osm_type": props.get("osm_type"),
                "highway": props.get("highway"),
                "gtype": gtype,
                "lanes": parse_number(props.get("lanes")),
                "lanes_bus": parse_number(props.get("lanes:bus")),
                "width_m": parse_metres(props.get("width")),
                "layer": props.get("layer"),
                "layer_n": int(layer_n) if layer_n is not None else None,
                "bridge": props.get("bridge"),
                "tunnel": props.get("tunnel"),
                "indoor": props.get("indoor"),
                "location": props.get("location"),
                "level": props.get("level"),
                "footway": props.get("footway"),
                "area_yes": props.get("area") == "yes" or gtype in ("Polygon", "MultiPolygon"),
                "coords_ll": geom.get("coordinates") if gtype == "LineString" else None,
                "poly_ll": geom.get("coordinates") if gtype in ("Polygon", "MultiPolygon") else None,
            }
            roads.append(rec)
        elif (
            props.get("leisure")
            or props.get("landuse")
            or props.get("natural")
            or props.get("water")
            or props.get("waterway")
            or props.get("amenity") == "parking"
        ):
            rec = ground_cover_record(props, geom, gtype, project_cm)
            if rec is not None:
                ground.append(rec)
            elif props.get("landuse") in DISTRICT_LANDUSE:
                district_landuse += 1
            else:
                other += 1
        elif props.get("railway"):
            rec = {
                "props": props,
                "osm_id": props.get("osm_id"),
                "osm_type": props.get("osm_type"),
                "railway": props.get("railway"),
                "gtype": gtype,
                "coords_ll": geom.get("coordinates") if gtype == "LineString" else None,
                "poly_ll": geom.get("coordinates") if gtype in ("Polygon", "MultiPolygon") else None,
                "below_reason": below_grade_reason(props),
            }
            rails.append(rec)
        else:
            other += 1

    n_b = len(buildings)
    n_h = sum(1 for b in buildings if b["height_m"] is not None)
    n_l = sum(1 for b in buildings if b["levels"] is not None)
    n_both = sum(1 for b in buildings if b["height_m"] is not None and b["levels"] is not None)
    n_neither = sum(1 for b in buildings if b["height_m"] is None and b["levels"] is None)
    n_ph = sum(1 for p in parts if p["height_m"] is not None)
    driveable = [r for r in roads if r["highway"] in DRIVEABLE and not r["area_yes"]]
    subsets = classify_highways(roads)
    below_b = [b for b in buildings if b.get("below_reason")]
    below_p = [p for p in parts if p.get("below_reason")]
    print("=== INSPECT ===")
    print(f"features {len(features)} buildings {n_b} parts {len(parts)} roads {len(roads)} ground {len(ground)} railway {len(rails)} other {other}")
    frac = (100.0 * n_h / n_b) if n_b else 0.0
    print(f"parent height tags {n_h}/{n_b} = {frac:.1f}%  (expect ~84-85%)")
    print(f"parent levels {n_l} both {n_both} neither {n_neither}")
    print(f"part height tags {n_ph}/{len(parts)} = {(100.0 * n_ph / len(parts) if parts else 0):.1f}%")
    print(f"holes {holes} ring_issues {dict(ring_issue)}")
    print(f"roof shapes buildings {Counter(b['roof_shape'] for b in buildings)}")
    print(f"roof shapes parts {Counter(p['roof_shape'] for p in parts)}")
    print(f"highway classes {Counter(r['highway'] for r in roads)}")
    print(
        f"driveable {len(driveable)} width "
        f"{sum(1 for r in driveable if r['width_m'])} lanes "
        f"{sum(1 for r in driveable if r['lanes'])}"
    )
    print("highway subsets:")
    for name, group in subsets.items():
        print(f"  {name}: {len(group)}")
    print("=== BELOW GRADE ===")
    print(f"buildings {len(below_b)}: " + ", ".join(
        f"{b.get('osm_type')}/{b.get('osm_id')} {b.get('btype')} {b.get('below_reason')} area={b.get('area_m2'):.0f}m2"
        for b in below_b
    ) if below_b else "buildings 0")
    print(f"parts {len(below_p)}")
    print(f"highways below-grade bucket {len(subsets.get('below_grade') or [])}")
    print(f"railway {Counter(r['railway'] for r in rails)} below {sum(1 for r in rails if r.get('below_reason'))}")
    print("=== GROUND COVER ===")
    print(f"leisure {Counter(g['props'].get('leisure') for g in ground if g['props'].get('leisure'))}")
    print(f"landuse {Counter(g['props'].get('landuse') for g in ground if g['props'].get('landuse'))}")
    print(f"natural {Counter(g['props'].get('natural') for g in ground if g['props'].get('natural'))}")
    print(f"klass {Counter(g['klass'] for g in ground)} linear {sum(1 for g in ground if g.get('linear'))}")
    print(f"district-scale landuse skipped {district_landuse}")
    print(f"top keys {key_counts.most_common(20)}")
    print(f"height formats {dict(height_formats)}")
    if n_b and frac < 70.0:
        raise SystemExit(
            f"parser sanity failed: parent height coverage {frac:.1f}% "
            f"(expected ~84%). Tags are probably being read from the wrong level."
        )
    return {
        "buildings": buildings,
        "parts": parts,
        "roads": roads,
        "driveable": driveable,
        "subsets": subsets,
        "ground": ground,
        "rails": rails,
        "n_parent_height": n_h,
        "n_parent": n_b,
        "parent_height_frac": frac,
        "holes": holes,
        "ring_issue": dict(ring_issue),
        "key_counts": key_counts,
        "below_grade_buildings": below_b,
        "below_grade_parts": below_p,
        "district_landuse_skipped": district_landuse,
    }


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def fit_models(inventory: dict) -> dict:
    buildings = inventory["buildings"]
    parts = inventory["parts"]
    driveable = inventory["driveable"]

    pairs = []
    for rec in buildings:
        if rec["height_m"] and rec["levels"] and rec["levels"] > 0:
            pairs.append(rec["height_m"] / rec["levels"])
    pairs.sort()
    storey_m = median_or_none(pairs)
    storey_src = (
        f"fitted:nyc_midtown_median_height/levels_n={len(pairs)}"
        if storey_m is not None
        else "unavailable"
    )

    labelled = [b for b in buildings if b["height_m"] and b["area_m2"] > 1.0]
    labelled.sort(key=lambda b: (b["osm_type"] or "", b["osm_id"] or 0))
    area_median_m = median_or_none([b["height_m"] for b in labelled])

    def knn_pred(target, pool, k: int) -> float | None:
        peers = [x for x in pool if x["btype"] == target["btype"] and x is not target]
        use = peers if len(peers) >= KNN_TYPE_MIN else [x for x in pool if x is not target]
        if not use:
            return None
        ta = math.log(max(target["area_m2"], 1.0))
        scored = []
        for x in use:
            d = abs(math.log(max(x["area_m2"], 1.0)) - ta)
            scored.append((d, x["osm_type"] or "", x["osm_id"] or 0, x["height_m"]))
        scored.sort()
        take = scored[:k]
        return float(statistics.median(h for _, _, _, h in take))

    def loo_medae(k: int) -> float | None:
        if len(labelled) < k + 1:
            return None
        errs = []
        for i, b in enumerate(labelled):
            rest = labelled[:i] + labelled[i + 1 :]
            pred = knn_pred(b, rest, k)
            if pred is None:
                continue
            errs.append(abs(pred - b["height_m"]))
        if not errs:
            return None
        return float(statistics.median(errs))

    baseline_errs = []
    for i, b in enumerate(labelled):
        rest = [x["height_m"] for j, x in enumerate(labelled) if j != i]
        if not rest:
            continue
        baseline_errs.append(abs(statistics.median(rest) - b["height_m"]))
    baseline_medae = float(statistics.median(baseline_errs)) if baseline_errs else None

    knn_scores = []
    for k in KNN_K_CANDIDATES:
        medae = loo_medae(k)
        if medae is not None:
            knn_scores.append((medae, k))
    knn_scores.sort()
    knn_k = knn_scores[0][1] if knn_scores else None
    knn_medae = knn_scores[0][0] if knn_scores else None
    knn_ok = (
        knn_k is not None
        and knn_medae is not None
        and baseline_medae is not None
        and knn_medae < baseline_medae
    )

    class_lanes: dict[str, float] = {}
    class_lane_n: dict[str, int] = {}
    by_class: dict[str, list[float]] = defaultdict(list)
    for r in driveable:
        if r["lanes"] and r["lanes"] > 0:
            by_class[r["highway"]].append(r["lanes"])
    for hw, vals in by_class.items():
        class_lanes[hw] = float(statistics.median(vals))
        class_lane_n[hw] = len(vals)

    print("=== FIT ===")
    print(f"storey_m {storey_m} n={len(pairs)} {storey_src}")
    print(f"area_median_m {area_median_m} n={len(labelled)} baseline_MedAE={baseline_medae}")
    print(f"knn k={knn_k} MedAE={knn_medae} used={knn_ok} scores={knn_scores}")
    print(f"class_lanes {class_lanes} n={class_lane_n}")
    print(f"lane_width_m {NYCDOT_LANE_M} source=nycdot_travel_lane (0 driveable width tags)")

    return {
        "storey_m": storey_m,
        "storey_n": len(pairs),
        "storey_src": storey_src,
        "area_median_m": area_median_m,
        "area_median_n": len(labelled),
        "baseline_medae": baseline_medae,
        "knn_ok": knn_ok,
        "knn_k": knn_k,
        "knn_medae": knn_medae,
        "knn_scores": knn_scores,
        "labelled": labelled,
        "class_lanes": class_lanes,
        "class_lane_n": class_lane_n,
        "lane_m": NYCDOT_LANE_M,
        "lane_src": "nycdot_travel_lane:3.05m",
    }


def assign_parts(buildings: list, parts: list) -> None:
    for b in buildings:
        b["child_parts"] = []
    for part in parts:
        cx, cy = part["centroid"]
        cands = []
        for b in buildings:
            if point_in_ring(cx, cy, b["ring_xy"]):
                cands.append(b)
        if not cands:
            part["parent"] = None
            continue
        cands.sort(key=lambda b: (b["area_m2"], b["osm_type"] or "", b["osm_id"] or 0))
        parent = cands[0]
        part["parent"] = parent
        parent["child_parts"].append(part)


# ---------------------------------------------------------------------------
# Heights / widths
# ---------------------------------------------------------------------------
def resolve_vertical(rec: dict, fits: dict) -> tuple[float, float, str]:
    """Return (base_m, top_m, height_source). top is the absolute top of the volume."""
    storey = fits["storey_m"]
    base = rec["min_h"] if rec["min_h"] is not None else None
    if base is None and rec["min_level"] is not None and storey is not None:
        base = rec["min_level"] * storey
        base_note = "building:min_level"
    else:
        base_note = "min_height" if rec["min_h"] is not None else "ground"
    if base is None:
        base = 0.0

    top: float | None
    src: str | None
    if rec["height_m"] is not None:
        top = rec["height_m"]
        src = "tag:height"
    elif rec["levels"] is not None and storey is not None:
        top = rec["levels"] * storey
        src = f"building:levels*{_fmt_m(storey)}m"
    else:
        top = None
        src = None

    if top is None and rec.get("is_parent") and fits["knn_ok"] and rec["area_m2"] > 1.0:
        pred = None
        labelled = fits["labelled"]
        k = fits["knn_k"]
        peers = [x for x in labelled if x["btype"] == rec["btype"]]
        pool = peers if len(peers) >= KNN_TYPE_MIN else labelled
        if pool:
            ta = math.log(max(rec["area_m2"], 1.0))
            scored = []
            for x in pool:
                if x is rec:
                    continue
                d = abs(math.log(max(x["area_m2"], 1.0)) - ta)
                scored.append((d, x["osm_type"] or "", x["osm_id"] or 0, x["height_m"]))
            scored.sort()
            take = scored[:k]
            if take:
                pred = float(statistics.median(h for _, _, _, h in take))
        if pred is not None:
            top = pred
            typ = rec["btype"] or "yes"
            src = f"knn[type={typ} k={k} n={len(pool)}]"

    if top is None and fits["area_median_m"] is not None:
        top = fits["area_median_m"]
        src = f"area_median:{_fmt_m(fits['area_median_m'])}m"

    if top is None:
        top = 10.0
        src = "refuse_default:10m_no_signal"

    if top <= base:
        # Still emit a volume: lift the top just above the base and say so.
        top = base + 3.0
        src = f"{src}+raised_above_base"

    rec["_base_note"] = base_note
    return base, top, src


def _fmt_m(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text


def way_layer(rec: dict) -> int:
    if rec.get("layer_n") is not None:
        return int(rec["layer_n"])
    if rec.get("tunnel") and rec["tunnel"] != "no":
        return -1
    if rec.get("bridge") and rec["bridge"] != "no":
        return 1
    return 0


def cycleway_value(props: dict, side: str) -> str | None:
    return props.get(f"cycleway:{side}") or props.get("cycleway:both")


def extra_cross_section_m(props: dict) -> tuple[float, list[str]]:
    extra = 0.0
    bits: list[str] = []
    bus = parse_number(props.get("lanes:bus"))
    if bus and bus > 0:
        extra += bus * NYCDOT_LANE_M
        bits.append(f"lanes:bus*{_fmt_m(bus)}")
    for side in ("left", "right"):
        park = props.get(f"parking:{side}")
        if park == "lane":
            extra += NYCDOT_PARK_M
            bits.append(f"parking:{side}=lane")
        cyc = cycleway_value(props, side)
        if cyc == "lane":
            extra += NYCDOT_BIKE_LANE_M
            bits.append(f"cycleway:{side}=lane")
        elif cyc == "track":
            extra += NYCDOT_BIKE_TRACK_M
            bits.append(f"cycleway:{side}=track")
    both = props.get("cycleway")
    if both in ("lane", "track") and not any(
        cycleway_value(props, side) for side in ("left", "right")
    ):
        extra += NYCDOT_BIKE_LANE_M if both == "lane" else NYCDOT_BIKE_TRACK_M
        bits.append(f"cycleway={both}")
    return extra, bits


def resolve_width(rec: dict, fits: dict) -> tuple[int, str]:
    props = rec["props"]
    lanes = rec["lanes"]
    hw = rec["highway"]
    lane_m = fits["lane_m"]
    extra_m, extra_bits = extra_cross_section_m(props)
    extra_label = ("+" + "+".join(extra_bits)) if extra_bits else ""
    if rec["width_m"]:
        return rcm((rec["width_m"] + extra_m) * CM_PER_M), "tag:width" + extra_label
    if lanes and lanes > 0:
        return (
            rcm((lanes * lane_m + extra_m) * CM_PER_M),
            f"lanes*{_fmt_m(lane_m)}m@{fits['lane_src']}{extra_label}",
        )
    if hw in fits["class_lanes"]:
        n = fits["class_lanes"][hw]
        return (
            rcm((n * lane_m + extra_m) * CM_PER_M),
            f"class_median_lanes:{hw}={_fmt_m(n)}*{_fmt_m(lane_m)}m@{fits['lane_src']}{extra_label}",
        )
    n = SERVICE_LANE_FALLBACK
    return (
        rcm((n * lane_m + extra_m) * CM_PER_M),
        f"class_fallback_lanes:{hw}={_fmt_m(n)}*{_fmt_m(lane_m)}m@{fits['lane_src']}{extra_label}",
    )


# ---------------------------------------------------------------------------
# Roofs
# ---------------------------------------------------------------------------
def principal_frame(ring: list):
    cx, cy = centroid_xy(ring)
    sxx = syy = sxy = 0.0
    for x, y in ring:
        dx, dy = x - cx, y - cy
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy
    theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    ux, uy = math.cos(theta), math.sin(theta)
    vx, vy = -uy, ux
    return (cx, cy), (ux, uy), (vx, vy)


def uv_of(x, y, origin, u, v) -> tuple[float, float]:
    dx, dy = x - origin[0], y - origin[1]
    return dx * u[0] + dy * u[1], dx * v[0] + dy * v[1]


def parse_direction_deg(raw) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        compass = {
            "n": 0.0,
            "ne": 45.0,
            "e": 90.0,
            "se": 135.0,
            "s": 180.0,
            "sw": 225.0,
            "w": 270.0,
            "nw": 315.0,
        }
        return compass.get(str(raw).strip().lower())


def roof_z_fn(rec: dict, eaves_cm: float, top_cm: float, ring: list):
    shape = rec["roof_shape"]
    origin, u, v = principal_frame(ring)
    if rec["roof_orient"] == "across":
        u, v = v, u
    uvs = [uv_of(x, y, origin, u, v) for x, y in ring]
    umax = max(abs(uu) for uu, _ in uvs) or 1.0
    vmax = max(abs(vv) for _, vv in uvs) or 1.0
    rh = top_cm - eaves_cm

    if shape in ("pyramidal", "dome", "onion", "round"):
        rmax = max(math.hypot(uu, vv) for uu, vv in uvs) or 1.0

        def z_pyr(x, y):
            uu, vv = uv_of(x, y, origin, u, v)
            t = min(1.0, math.hypot(uu, vv) / rmax)
            if shape == "dome":
                lift = rh * math.sqrt(max(0.0, 1.0 - t * t))
            else:
                lift = rh * (1.0 - t)
            return eaves_cm + lift

        return z_pyr, origin

    if shape == "skillion":
        deg = parse_direction_deg(rec["roof_dir"])
        if deg is None:
            # fall down the shorter principal axis
            dx, dy = v
        else:
            rad = math.radians(deg)
            dx, dy = math.cos(rad), math.sin(rad)  # +X north, +Y east
        projs = [x * dx + y * dy for x, y in ring]
        pmin, pmax = min(projs), max(projs)
        span = (pmax - pmin) or 1.0

        def z_sk(x, y):
            t = (x * dx + y * dy - pmin) / span  # 0 high, 1 low if dir is downslope
            return top_cm - rh * t

        return z_sk, origin

    if shape in ("gabled",):

        def z_gab(x, y):
            _, vv = uv_of(x, y, origin, u, v)
            t = min(1.0, abs(vv) / vmax)
            return top_cm - rh * t

        return z_gab, origin

    # hipped / mansard
    def z_hip(x, y):
        uu, vv = uv_of(x, y, origin, u, v)
        t = min(1.0, max(abs(uu) / umax, abs(vv) / vmax))
        return top_cm - rh * t

    return z_hip, origin


def fan_triangulate(n: int) -> list[list[int]]:
    if n < 3:
        return []
    return [[0, i, i + 1] for i in range(1, n - 1)]


def build_roof_mesh(rec: dict, ring_xy: list, eaves_cm: float, top_cm: float, nid: str):
    if rec["roof_shape"] not in NONFLAT_ROOFS:
        return None
    if top_cm - eaves_cm < 1:
        return None
    ring = ensure_ccw([(rcm(x), rcm(y)) for x, y in ring_xy])
    if len(ring) < 3:
        return None
    z_fn, origin = roof_z_fn(rec, eaves_cm, top_cm, ring)
    if rec["roof_shape"] in ("pyramidal", "onion"):
        verts = [[x, y, rcm(eaves_cm)] for x, y in ring]
        apex = [rcm(origin[0]), rcm(origin[1]), rcm(top_cm)]
        # collapse if apex coincides with a vertex
        verts.append(apex)
        n = len(ring)
        faces = []
        for i in range(n):
            a, b, c = i, (i + 1) % n, n
            if len({tuple(verts[a]), tuple(verts[b]), tuple(verts[c])}) == 3:
                faces.append([a, b, c])
        if not faces:
            return None
    else:
        verts = [[x, y, rcm(z_fn(x, y))] for x, y in ring]
        cx, cy = centroid_xy(ring)
        verts.append([rcm(cx), rcm(cy), rcm(z_fn(cx, cy))])
        n = len(ring)
        faces = []
        for i in range(n):
            a, b, c = i, (i + 1) % n, n
            if len({tuple(verts[a]), tuple(verts[b]), tuple(verts[c])}) == 3:
                faces.append([a, b, c])
        if not faces:
            return None
    return {
        "id": nid,
        "kind": "mesh",
        "vertices": verts,
        "indices": faces,
        "tags": ["roof"],
        "attrs": {
            "shape": rec["roof_shape"],
            "osm_id": rec["osm_id"],
            "roof_source": "tag:roof:shape+tag:roof:height",
        },
    }


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
def emit_extrude(rec: dict, ring_xy: list, base_cm: int, height_cm: int, tags: list, attrs: dict, nid: str):
    outline = ensure_ccw([[rcm(x), rcm(y)] for x, y in ring_xy])
    # drop consecutive duplicates after rounding
    cleaned = []
    for pt in outline:
        if not cleaned or pt != cleaned[-1]:
            cleaned.append(pt)
    if cleaned and cleaned[0] == cleaned[-1]:
        cleaned = cleaned[:-1]
    if len(cleaned) < 3:
        return None
    if signed_area(cleaned) < 0:
        cleaned = list(reversed(cleaned))
    if height_cm <= base_cm:
        return None
    return {
        "id": nid,
        "kind": "extrude",
        "outline": cleaned,
        "base_cm": int(base_cm),
        "height_cm": int(height_cm),
        "tags": tags,
        "attrs": attrs,
    }


def emit_ribbon(rec: dict, project_cm, fits: dict):
    coords = rec["coords_ll"] or []
    if len(coords) < 2:
        return None, "short_road"
    points = []
    for lon, lat in coords:
        x, y = project_cm(lon, lat)
        pt = [rcm(x), rcm(y)]
        if not points or pt != points[-1]:
            points.append(pt)
    if len(points) < 2:
        return None, "collapsed_road"
    width_cm, wsrc = resolve_width(rec, fits)
    if width_cm <= 0:
        return None, "nonpositive_width"
    tags = ["road", rec["highway"]]
    if rec["tunnel"] and rec["tunnel"] != "no":
        tags.append("tunnel")
    if rec["bridge"] and rec["bridge"] != "no":
        tags.append("bridge")
    attrs = {
        "width_source": wsrc,
        "osm_id": rec["osm_id"],
        "layer": way_layer(rec),
    }
    if rec["tunnel"] and rec["tunnel"] != "no":
        attrs["tunnel"] = rec["tunnel"]
    if rec["bridge"] and rec["bridge"] != "no":
        attrs["bridge"] = rec["bridge"]
    return {
        "id": f"w/{rec['osm_id']}",
        "kind": "ribbon",
        "points": points,
        "width_cm": int(width_cm),
        "tags": tags,
        "attrs": attrs,
        "_layer": way_layer(rec),
        "_section": (rec["highway"], int(width_cm), way_layer(rec)),
        "_osm_ids": [rec["osm_id"]],
    }, None


def project_line(coords_ll, project_cm) -> list:
    points = []
    for lon, lat in coords_ll:
        x, y = project_cm(lon, lat)
        pt = [rcm(x), rcm(y)]
        if not points or pt != points[-1]:
            points.append(pt)
    return points


def polyline_length(points: list) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


def pt_key(pt) -> tuple[int, int]:
    return (int(pt[0]), int(pt[1]))


def trim_polyline(points: list, from_start: bool, dist_cm: float) -> list:
    if len(points) < 2 or dist_cm <= 0:
        return points
    pts = list(points) if from_start else list(reversed(points))
    remaining = dist_cm
    i = 0
    while i < len(pts) - 1 and remaining > 0:
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            i += 1
            continue
        if length > remaining:
            t = remaining / length
            new_pt = [rcm(pts[i][0] + t * dx), rcm(pts[i][1] + t * dy)]
            trimmed = [new_pt] + pts[i + 1 :]
            return trimmed if from_start else list(reversed(trimmed))
        remaining -= length
        i += 1
    stub = pts[-2:] if len(pts) >= 2 else pts
    return stub if from_start else list(reversed(stub))


def endpoint_index(ribbons: list) -> dict:
    index = defaultdict(list)
    for i, node in enumerate(ribbons):
        pts = node["points"]
        if len(pts) < 2:
            continue
        index[pt_key(pts[0])].append((i, True))
        index[pt_key(pts[-1])].append((i, False))
    return index


def merge_same_section(ribbons: list) -> tuple[list, int]:
    """Join consecutive same-cross-section ways. Removes seam overlaps."""
    merged = 0
    while True:
        index = endpoint_index(ribbons)
        did = False
        for key, hits in index.items():
            if len(hits) != 2:
                continue
            (i, i_start), (j, j_start) = hits
            if i == j:
                continue
            a, b = ribbons[i], ribbons[j]
            if a["_section"] != b["_section"]:
                continue
            a_pts = list(a["points"])
            b_pts = list(b["points"])
            if i_start:
                a_pts = list(reversed(a_pts))
            if not j_start:
                b_pts = list(reversed(b_pts))
            combined = a_pts + b_pts[1:]
            cleaned = []
            for pt in combined:
                if not cleaned or pt != cleaned[-1]:
                    cleaned.append(pt)
            if len(cleaned) < 2:
                continue
            ids = sorted(set(str(x) for x in (a.get("_osm_ids") or [a["attrs"].get("osm_id")]) + (b.get("_osm_ids") or [b["attrs"].get("osm_id")])))
            keep = min(i, j)
            drop = max(i, j)
            node = ribbons[keep]
            node["points"] = cleaned
            node["_osm_ids"] = [int(x) if str(x).isdigit() else x for x in ids]
            node["id"] = "w/" + "+".join(str(x) for x in node["_osm_ids"])
            node["attrs"]["merged_from"] = node["_osm_ids"]
            del ribbons[drop]
            merged += 1
            did = True
            break
        if not did:
            break
    return ribbons, merged


def convex_hull(points: list) -> list:
    uniq = sorted({(int(p[0]), int(p[1])) for p in points})
    if len(uniq) <= 2:
        return [[x, y] for x, y in uniq]
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower = []
    for p in uniq:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(uniq):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return [[x, y] for x, y in hull]


def end_corners(points: list, at_start: bool, half_w: float) -> list:
    if len(points) < 2:
        return []
    if at_start:
        end, nxt = points[0], points[1]
    else:
        end, nxt = points[-1], points[-2]
    dx, dy = end[0] - nxt[0], end[1] - nxt[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * half_w, dx / length * half_w
    return [[end[0] + nx, end[1] + ny], [end[0] - nx, end[1] - ny]]


def resolve_junctions(ribbons: list) -> tuple[list, list, int]:
    """Trim ribbons at shared endpoints and emit one junction mesh per node."""
    index = endpoint_index(ribbons)
    junctions = {k: hits for k, hits in index.items() if len(hits) >= 2}
    meshes = []
    resolved = 0
    for key, hits in sorted(junctions.items()):
        involved = []
        for idx, at_start in hits:
            node = ribbons[idx]
            others = [ribbons[j]["width_cm"] for j, _ in hits if j != idx]
            trim = 0.5 * max(others) if others else 0.0
            if polyline_length(node["points"]) <= trim + 80:
                continue
            node["points"] = trim_polyline(node["points"], at_start, trim)
            involved.append((node, at_start))
        corners = []
        for node, at_start in involved:
            corners.extend(end_corners(node["points"], at_start, node["width_cm"] / 2.0))
        hull = ensure_ccw(convex_hull(corners)) if len(corners) >= 3 else []
        if len(hull) < 3:
            continue
        layers = [node["_layer"] for node, _ in involved]
        layer = min(layers) if layers else 0
        z_cm = 4 + layer * 400 + JUNCTION_LIFT_CM
        verts = [[rcm(x), rcm(y), int(z_cm)] for x, y in hull]
        faces = fan_triangulate(len(verts))
        faces = [f for f in faces if len({tuple(verts[i]) for i in f}) == 3]
        if not faces:
            continue
        meshes.append(
            {
                "id": f"j/{key[0]}_{key[1]}",
                "kind": "mesh",
                "vertices": verts,
                "indices": faces,
                "tags": ["junction", "road"],
                "attrs": {
                    "layer": layer,
                    "degree": len(hits),
                    "resolution": "trim_and_cap",
                },
            }
        )
        resolved += 1
    return ribbons, meshes, resolved


def polyline_strip_mesh(points, width_cm, z_cm, nid, tags, attrs):
    if len(points) < 2 or width_cm <= 0:
        return None
    verts = []
    faces = []
    half = width_cm / 2.0
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1.0:
            continue
        nx, ny = -dy / length * half, dx / length * half
        base = len(verts)
        # 0 left0, 1 right0, 2 right1, 3 left1 — CCW from +Z
        verts.append([rcm(x0 + nx), rcm(y0 + ny), int(z_cm)])
        verts.append([rcm(x0 - nx), rcm(y0 - ny), int(z_cm)])
        verts.append([rcm(x1 - nx), rcm(y1 - ny), int(z_cm)])
        verts.append([rcm(x1 + nx), rcm(y1 + ny), int(z_cm)])
        faces.append([base, base + 3, base + 2])
        faces.append([base, base + 2, base + 1])
    if not faces:
        return None
    return {
        "id": nid,
        "kind": "mesh",
        "vertices": verts,
        "indices": faces,
        "tags": tags,
        "attrs": attrs,
    }


def point_in_tri(p, a, b, c) -> bool:
    d1 = orientation(p, a, b)
    d2 = orientation(p, b, c)
    d3 = orientation(p, c, a)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def earclip(ring: list) -> list:
    ring = ensure_ccw([[rcm(x), rcm(y)] for x, y in ring])
    cleaned = []
    for pt in ring:
        if not cleaned or pt != cleaned[-1]:
            cleaned.append(pt)
    if cleaned and cleaned[0] == cleaned[-1]:
        cleaned = cleaned[:-1]
    n = len(cleaned)
    if n < 3:
        return cleaned, []
    idx = list(range(n))
    faces = []
    guard = 0
    while len(idx) > 3 and guard < n * n + 10:
        guard += 1
        clipped = False
        m = len(idx)
        for i in range(m):
            i0, i1, i2 = idx[(i - 1) % m], idx[i], idx[(i + 1) % m]
            a, b, c = cleaned[i0], cleaned[i1], cleaned[i2]
            if orientation(a, b, c) <= 0:
                continue
            if any(
                j not in (i0, i1, i2) and point_in_tri(cleaned[j], a, b, c)
                for j in idx
            ):
                continue
            faces.append([i0, i1, i2])
            del idx[i]
            clipped = True
            break
        if not clipped:
            break
    if len(idx) == 3:
        faces.append(idx)
    return cleaned, faces


def polygon_mesh(ring_xy, z_cm, nid, tags, attrs):
    ring, faces = earclip(ring_xy)
    if len(ring) < 3:
        return None
    if not faces:
        cx, cy = centroid_xy(ring)
        verts = [[x, y, int(z_cm)] for x, y in ring]
        verts.append([rcm(cx), rcm(cy), int(z_cm)])
        apex = len(verts) - 1
        faces = []
        for i in range(len(ring)):
            faces.append([i, (i + 1) % len(ring), apex])
    else:
        verts = [[x, y, int(z_cm)] for x, y in ring]
    faces = [f for f in faces if len({tuple(verts[i]) for i in f}) == 3]
    if not faces:
        return None
    return {
        "id": nid,
        "kind": "mesh",
        "vertices": verts,
        "indices": faces,
        "tags": tags,
        "attrs": attrs,
    }


def _sorted_recs(recs: list) -> list:
    return sorted(recs, key=lambda r: (r.get("osm_type") or "", r.get("osm_id") or 0))


def polyline_outline(points: list, width_cm: float) -> list | None:
    """Closed kerb-to-kerb ring for a centreline strip, used as an extrude outline."""
    if len(points) < 2 or width_cm <= 0:
        return None
    half = width_cm / 2.0
    left = []
    right = []
    n = len(points)
    for i in range(n):
        if i == 0:
            dx = points[1][0] - points[0][0]
            dy = points[1][1] - points[0][1]
        elif i == n - 1:
            dx = points[-1][0] - points[-2][0]
            dy = points[-1][1] - points[-2][1]
        else:
            dx1 = points[i][0] - points[i - 1][0]
            dy1 = points[i][1] - points[i - 1][1]
            dx2 = points[i + 1][0] - points[i][0]
            dy2 = points[i + 1][1] - points[i][1]
            l1 = math.hypot(dx1, dy1) or 1.0
            l2 = math.hypot(dx2, dy2) or 1.0
            dx = dx1 / l1 + dx2 / l2
            dy = dy1 / l1 + dy2 / l2
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length * half, dx / length * half
        left.append([points[i][0] + nx, points[i][1] + ny])
        right.append([points[i][0] - nx, points[i][1] - ny])
    return left + list(reversed(right))


def emit_pedestrian_strips(recs, project_cm, width_m, width_src, z_cm, tag, prefix, skipped):
    """Curb prism: extrude from the slab (0) up to z_cm so the face is a kerb."""
    nodes = []
    for rec in _sorted_recs(recs):
        coords = rec.get("coords_ll") or []
        points = project_line(coords, project_cm)
        if len(points) < 2:
            skipped[f"{tag}_collapsed"] += 1
            continue
        outline = polyline_outline(points, width_m * CM_PER_M)
        if outline is None:
            skipped[f"{tag}_outline_failed"] += 1
            continue
        if ring_problems(outline):
            skipped[f"{tag}_bad_ring"] += 1
            continue
        node = emit_extrude(
            rec,
            outline,
            0,
            int(z_cm),
            [tag, rec["highway"]],
            {
                "height_source": f"curb:{int(z_cm)}cm",
                "width_source": width_src,
                "osm_id": rec["osm_id"],
                "z_cm": int(z_cm),
            },
            f"{prefix}/{rec['osm_id']}",
        )
        if node is None:
            skipped[f"{tag}_extrude_failed"] += 1
        elif ring_problems(node["outline"]):
            skipped[f"{tag}_bad_ring"] += 1
        else:
            nodes.append(node)
    return nodes


def emit_plazas(recs, project_cm, skipped):
    nodes = []
    for rec in _sorted_recs(recs):
        poly = rec.get("poly_ll")
        if not poly:
            skipped["plaza_no_polygon"] += 1
            continue
        if rec["gtype"] == "Polygon":
            outers = [open_ring(poly[0])] if poly else []
        else:
            outers = [open_ring(p[0]) for p in poly if p]
        if not outers:
            skipped["plaza_no_polygon"] += 1
            continue
        if rec.get("holes") or (rec["gtype"] == "Polygon" and len(poly) > 1):
            skipped["plaza_interior_ring_ignored"] += max(0, len(poly) - 1)
        ring_xy = max(
            ([project_cm(lon, lat) for lon, lat in outer] for outer in outers),
            key=lambda r: abs(signed_area(r)),
        )
        if ring_problems(ring_xy):
            skipped["plaza_bad_ring"] += 1
            continue
        node = emit_extrude(
            rec,
            ring_xy,
            0,
            PLAZA_Z_CM,
            ["plaza", rec["highway"]],
            {
                "height_source": f"plaza:{PLAZA_Z_CM}cm",
                "width_source": "area_polygon",
                "osm_id": rec["osm_id"],
                "z_cm": PLAZA_Z_CM,
            },
            f"a/{rec['osm_id']}",
        )
        if node is None:
            skipped["plaza_extrude_failed"] += 1
        else:
            nodes.append(node)
    return nodes


def emit_street_network(inventory: dict, fits: dict, skipped: Counter, width_sources: Counter):
    project_cm = inventory["project_cm"]
    subsets = inventory["subsets"]
    report = {}
    nodes = []

    driveable = list(subsets.get("driveable_line") or [])
    driveable.sort(key=lambda r: (r["osm_type"] or "", r["osm_id"] or 0))
    ribbons = []
    for rec in driveable:
        node, reason = emit_ribbon(rec, project_cm, fits)
        if node is None:
            skipped[reason or "ribbon_rejected"] += 1
            continue
        ribbons.append(node)
        width_sources[node["attrs"]["width_source"]] += 1
    report["driveable_line_source"] = len(driveable)
    report["driveable_ribbons_before_merge"] = len(ribbons)

    ribbons, n_merged = merge_same_section(ribbons)
    ribbons, junction_meshes, n_junc = resolve_junctions(ribbons)
    report["collinear_merges"] = n_merged
    report["junctions_resolved"] = n_junc
    # drop internal keys before emit
    for node in ribbons:
        node.pop("_layer", None)
        node.pop("_section", None)
        node.pop("_osm_ids", None)
        if polyline_length(node["points"]) < 1:
            skipped["ribbon_too_short_after_trim"] += 1
            continue
        nodes.append(node)
    nodes.extend(junction_meshes)

    sidewalk_src = f"borrowed:nycdot_commercial_sidewalk:{NYCDOT_SIDEWALK_M}m"
    foot_src = f"borrowed:nycdot_min_clear_path:{NYCDOT_FOOTWAY_M}m"
    cycle_src = f"borrowed:nycdot_cycle_track:{NYCDOT_BIKE_TRACK_M}m"

    sidewalks = emit_pedestrian_strips(
        subsets.get("sidewalk") or [],
        project_cm,
        NYCDOT_SIDEWALK_M,
        sidewalk_src,
        CURB_Z_CM,
        "sidewalk",
        "s",
        skipped,
    )
    islands = emit_pedestrian_strips(
        subsets.get("traffic_island") or [],
        project_cm,
        NYCDOT_FOOTWAY_M,
        foot_src,
        CURB_Z_CM,
        "traffic_island",
        "i",
        skipped,
    )
    ped_lines = emit_pedestrian_strips(
        subsets.get("pedestrian_line") or [],
        project_cm,
        NYCDOT_SIDEWALK_M,
        sidewalk_src,
        CURB_Z_CM,
        "pedestrian",
        "e",
        skipped,
    )
    generic = emit_pedestrian_strips(
        subsets.get("generic_footway") or [],
        project_cm,
        NYCDOT_FOOTWAY_M,
        foot_src,
        CURB_Z_CM,
        "footway",
        "f",
        skipped,
    )
    plazas = emit_plazas(subsets.get("plaza_area") or [], project_cm, skipped)

    cycle_ribbons = 0
    for rec in _sorted_recs(subsets.get("cycleway") or []):
        coords = rec.get("coords_ll") or []
        points = project_line(coords, project_cm)
        if len(points) < 2:
            skipped["cycleway_collapsed"] += 1
            continue
        width_cm = rcm(NYCDOT_BIKE_TRACK_M * CM_PER_M)
        nodes.append(
            {
                "id": f"c/{rec['osm_id']}",
                "kind": "ribbon",
                "points": points,
                "width_cm": int(width_cm),
                "tags": ["cycleway", "road"],
                "attrs": {
                    "width_source": cycle_src,
                    "osm_id": rec["osm_id"],
                    "layer": way_layer(rec),
                },
            }
        )
        width_sources[cycle_src] += 1
        cycle_ribbons += 1

    nodes.extend(sidewalks)
    nodes.extend(islands)
    nodes.extend(ped_lines)
    nodes.extend(generic)
    nodes.extend(plazas)

    excluded = {
        "below_grade_indoor_tunnel_or_layer_lt_0": len(subsets.get("below_grade") or []),
        "crossing_on_carriageway": len(subsets.get("crossing") or []),
        "steps_not_a_flat_strip": len(subsets.get("steps") or []),
        "elevator_vertical_connector": len(subsets.get("elevator") or []),
        "driveable_area_not_carriageway": len(subsets.get("driveable_area") or []),
    }
    for key, recs in subsets.items():
        if key.startswith("other:"):
            excluded[f"excluded_{key}"] = len(recs)
    for reason, count in excluded.items():
        skipped[reason] += count

    report.update(
        {
            "sidewalk_emitted": len(sidewalks),
            "sidewalk_source": len(subsets.get("sidewalk") or []),
            "traffic_island_emitted": len(islands),
            "pedestrian_line_emitted": len(ped_lines),
            "generic_footway_emitted": len(generic),
            "plaza_emitted": len(plazas),
            "plaza_source": len(subsets.get("plaza_area") or []),
            "cycleway_ribbons": cycle_ribbons,
            "excluded": excluded,
        }
    )
    print("=== STREET NETWORK ===")
    for key in sorted(report):
        print(f"  {key}: {report[key]}")
    return nodes, report


def emit_ground_cover(inventory: dict, skipped: Counter) -> tuple[list, dict]:
    nodes = []
    emitted = Counter()
    excluded = Counter()
    z_used = {}
    for rec in _sorted_recs(inventory.get("ground") or []):
        if rec.get("below_reason"):
            excluded[f"ground_{rec['klass']}_{rec['below_reason']}"] += 1
            skipped[f"ground_below_grade_{rec['below_reason']}"] += 1
            continue
        if rec.get("linear") or not rec.get("ring_xy"):
            skipped[f"ground_{rec['klass']}_not_a_polygon"] += 1
            excluded[f"ground_{rec['klass']}_linear"] += 1
            continue
        if rec.get("holes"):
            skipped["ground_interior_ring_ignored"] += rec["holes"]
        if ring_problems(rec["ring_xy"]):
            skipped[f"ground_{rec['klass']}_bad_ring"] += 1
            continue
        z_cm = int(GROUND_Z_CM[rec["klass"]])
        if z_cm <= 0 or z_cm >= 4:
            skipped[f"ground_{rec['klass']}_z_out_of_band"] += 1
            continue
        node = polygon_mesh(
            rec["ring_xy"],
            z_cm,
            f"g/{rec['osm_id']}",
            ["ground", rec["klass"]],
            {
                "osm_id": rec["osm_id"],
                "z_cm": z_cm,
                "ground_class": rec["klass"],
            },
        )
        if node is None:
            skipped[f"ground_{rec['klass']}_mesh_failed"] += 1
            continue
        nodes.append(node)
        emitted[rec["klass"]] += 1
        z_used[rec["klass"]] = z_cm

    rail_emitted = 0
    for rec in _sorted_recs(inventory.get("rails") or []):
        reason = rec.get("below_reason")
        if rec.get("railway") == "subway" and not reason:
            reason = "railway=subway"
        if reason:
            skipped[f"railway_{reason}"] += 1
            excluded[f"railway_{rec.get('railway')}_{reason}"] += 1
            continue
        coords = rec.get("coords_ll") or []
        if rec.get("gtype") != "LineString" or len(coords) < 2:
            skipped["railway_not_a_line"] += 1
            excluded[f"railway_{rec.get('railway')}_not_line"] += 1
            continue
        project_cm = inventory["project_cm"]
        points = project_line(coords, project_cm)
        if len(points) < 2:
            skipped["railway_collapsed"] += 1
            continue
        nodes.append(
            {
                "id": f"t/{rec['osm_id']}",
                "kind": "ribbon",
                "points": points,
                "width_cm": rcm(1.435 * CM_PER_M),
                "tags": ["railway", rec["railway"]],
                "attrs": {
                    "width_source": "standard_gauge:1.435m",
                    "osm_id": rec["osm_id"],
                    "layer": 0,
                },
            }
        )
        rail_emitted += 1

    report = {
        "emitted": dict(emitted),
        "excluded": dict(excluded),
        "z_cm": dict(sorted(z_used.items())),
        "railway_at_grade": rail_emitted,
        "blocks": "not derived; this extract does not tag city blocks",
    }
    print("=== GROUND COVER EMIT ===")
    for key in sorted(report):
        print(f"  {key}: {report[key]}")
    return nodes, report


def build_scene(inventory: dict, fits: dict, sidecar: dict, area: str, geojson_rel: str) -> dict:
    skipped = Counter()
    nodes = []
    height_sources = Counter()
    width_sources = Counter()
    roof_shapes_emitted = Counter()
    roof_shapes_skipped = Counter()

    assign_parts(inventory["buildings"], inventory["parts"])
    parents_replaced = 0

    def handle_volume(rec: dict, kind_tag: str, prefix: str):
        nonlocal parents_replaced
        if rec.get("below_reason"):
            skipped[f"below_grade_{kind_tag}_{rec['below_reason']}"] += 1
            return
        if kind_tag == "building" and rec.get("child_parts"):
            skipped["parent_replaced_by_parts"] += 1
            parents_replaced += 1
            return
        probs = ring_problems(rec["ring_xy"])
        if "degenerate" in probs:
            skipped["degenerate_ring"] += 1
            return
        if "self_intersecting" in probs:
            skipped["self_intersecting_ring"] += 1
            return
        if rec.get("holes"):
            skipped["interior_ring_ignored"] += rec["holes"]

        base_m, top_m, hsrc = resolve_vertical(rec, fits)
        roof_h = rec["roof_h"] if rec["roof_shape"] in NONFLAT_ROOFS else None
        wall_top_m = top_m
        roof_mesh = None
        if rec["roof_shape"] in NONFLAT_ROOFS:
            if roof_h is None:
                skipped[f"roof_{rec['roof_shape']}_no_roof_height"] += 1
                roof_shapes_skipped[rec["roof_shape"]] += 1
            else:
                span = top_m - base_m
                rh = min(roof_h, span)
                eaves_m = top_m - rh
                if eaves_m <= base_m + 0.005:
                    # roof consumes the volume: mesh only
                    roof_mesh = build_roof_mesh(
                        rec,
                        rec["ring_xy"],
                        base_m * CM_PER_M,
                        top_m * CM_PER_M,
                        f"r/{rec['osm_id']}",
                    )
                    wall_top_m = None
                else:
                    wall_top_m = eaves_m
                    roof_mesh = build_roof_mesh(
                        rec,
                        rec["ring_xy"],
                        eaves_m * CM_PER_M,
                        top_m * CM_PER_M,
                        f"r/{rec['osm_id']}",
                    )
                if roof_mesh is None:
                    skipped[f"roof_{rec['roof_shape']}_mesh_failed"] += 1
                    roof_shapes_skipped[rec["roof_shape"]] += 1
                    wall_top_m = top_m

        if wall_top_m is not None:
            node = emit_extrude(
                rec,
                rec["ring_xy"],
                rcm(base_m * CM_PER_M),
                rcm(wall_top_m * CM_PER_M),
                [kind_tag],
                {
                    "height_source": hsrc,
                    "osm_id": rec["osm_id"],
                    "roof:shape": rec["roof_shape"] or "none",
                    "base_source": rec.get("_base_note", "ground"),
                },
                f"{prefix}/{rec['osm_id']}",
            )
            if node is None:
                skipped["extrude_rejected"] += 1
            else:
                nodes.append(node)
                height_sources[hsrc] += 1
        if roof_mesh is not None:
            nodes.append(roof_mesh)
            roof_shapes_emitted[rec["roof_shape"]] += 1

    for rec in inventory["parts"]:
        handle_volume(rec, "building:part", "p")
    for rec in inventory["buildings"]:
        handle_volume(rec, "building", "b")

    street_nodes, street_report = emit_street_network(inventory, fits, skipped, width_sources)
    nodes.extend(street_nodes)
    cover_nodes, cover_report = emit_ground_cover(inventory, skipped)
    nodes.extend(cover_nodes)
    if inventory.get("district_landuse_skipped"):
        skipped["district_scale_landuse"] += inventory["district_landuse_skipped"]

    nodes.sort(key=lambda n: (n["kind"], n["id"]))
    counts = {
        "extrude": sum(1 for n in nodes if n["kind"] == "extrude"),
        "mesh": sum(1 for n in nodes if n["kind"] == "mesh"),
        "ribbon": sum(1 for n in nodes if n["kind"] == "ribbon"),
        "total": len(nodes),
    }
    south, west, north, east = sidecar["bbox_requested_south_west_north_east"]
    origin_lat = (south + north) / 2.0
    origin_lon = (west + east) / 2.0
    assumptions = {
        "storey_m": {
            "value": fits["storey_m"],
            "n": fits["storey_n"],
            "source": fits["storey_src"],
        },
        "area_median_height_m": {
            "value": fits["area_median_m"],
            "n": fits["area_median_n"],
            "loo_medae_m": fits["baseline_medae"],
        },
        "knn_log_area": {
            "used": fits["knn_ok"],
            "k": fits["knn_k"],
            "loo_medae_m": fits["knn_medae"],
            "baseline_medae_m": fits["baseline_medae"],
            "type_min_peers": KNN_TYPE_MIN,
            "note": "type medians dropped; spatial kNN not used (tower next to loft)",
        },
        "lane_width_m": {
            "value": fits["lane_m"],
            "source": fits["lane_src"],
            "note": "zero driveable width tags in this extract; not a local fit",
        },
        "parking_lane_m": {
            "value": NYCDOT_PARK_M,
            "source": "nycdot_parking_lane:2.44m",
        },
        "bike_lane_m": {"value": NYCDOT_BIKE_LANE_M, "source": "nycdot_bike_lane:1.52m"},
        "bike_track_m": {"value": NYCDOT_BIKE_TRACK_M, "source": "nycdot_cycle_track:2.44m"},
        "sidewalk_m": {
            "value": NYCDOT_SIDEWALK_M,
            "source": "nycdot_commercial_sidewalk:4.57m",
        },
        "footway_m": {
            "value": NYCDOT_FOOTWAY_M,
            "source": "nycdot_min_clear_path:1.83m",
        },
        "class_median_lanes": {
            "values": fits["class_lanes"],
            "n": fits["class_lane_n"],
            "service_fallback_lanes": SERVICE_LANE_FALLBACK,
        },
        "driveable_classes": sorted(DRIVEABLE),
        "pedestrian_z_cm": {"curb": CURB_Z_CM, "plaza": PLAZA_Z_CM},
        "ground_cover_z_cm": dict(sorted(GROUND_Z_CM.items())),
        "ground_cover": cover_report,
        "below_grade_test": "location=underground | layer<0 | tunnel=* | indoor=yes | level<0",
        "below_grade_buildings": [
            {
                "osm_type": b.get("osm_type"),
                "osm_id": b.get("osm_id"),
                "reason": b.get("below_reason"),
                "building": b.get("btype"),
                "area_m2": round(b.get("area_m2") or 0.0, 1),
            }
            for b in inventory.get("below_grade_buildings") or []
        ],
        "city_blocks": "not derived; this extract does not tag blocks",
        "junctions": {
            "method": "merge same-section runs, then trim-and-cap shared endpoints",
            "resolved": street_report.get("junctions_resolved"),
            "merges": street_report.get("collinear_merges"),
        },
        "street_network": street_report,
        "part_resolution": "suppress parent outline when >=1 part centroid is inside it",
        "dual_building_and_part": "classified as parent, not as a part",
        "roof_height_contained_in_height": True,
        "interior_rings": "exterior only per contract; counted in skipped",
        "parent_height_tag_coverage_pct": inventory["parent_height_frac"],
        "buffer_m": BUFFER_M,
        "date_pinned": sidecar.get("date_pinned"),
        "sidewalk_separate_is_pointer": "sidewalk:both=separate does not synthesise geometry",
    }
    manifest = {
        "area": area,
        "origin": {"lat": origin_lat, "lon": origin_lon},
        "projection": {
            "type": "WGS84_local_tangent",
            "ellipsoid": "WGS84",
            "units": "cm",
            "axis_convention": "+X North, +Y East, +Z Up",
        },
        "units": "cm",
        "axis_convention": "+X North, +Y East, +Z Up",
        "counts": counts,
        "skipped": dict(sorted(skipped.items())),
        "assumptions": assumptions,
        "provenance": {
            "height_source": dict(sorted(height_sources.items())),
            "width_source": dict(sorted(width_sources.items())),
            "roof_mesh_emitted": dict(sorted(roof_shapes_emitted.items())),
            "roof_mesh_skipped": dict(sorted(roof_shapes_skipped.items())),
        },
        "source": {
            "geojson": geojson_rel,
            "fetch": geojson_rel.replace(".geojson", ".fetch.json"),
            "licence": "Data (c) OpenStreetMap contributors, ODbL 1.0",
        },
        "parents_replaced_by_parts": parents_replaced,
    }
    print("=== PROVENANCE HISTOGRAM ===")
    building_nodes = [
        n
        for n in nodes
        if n["kind"] == "extrude" and set(n.get("tags") or []) & {"building", "building:part"}
    ]
    bsrc = Counter((n.get("attrs") or {}).get("height_source", "(none)") for n in building_nodes)
    total_h = sum(bsrc.values()) or 1
    for key, n in bsrc.most_common():
        print(f"  height {key}: {n} ({100.0 * n / total_h:.1f}%)")
    tag_n = sum(n for k, n in bsrc.items() if k == "tag:height")
    print(
        f"tag:height {tag_n}/{total_h} = {100.0 * tag_n / total_h:.1f}% of building extrudes "
        f"(parent tag coverage was {inventory['parent_height_frac']:.1f}%; "
        f"parts are ~99.5% tagged so emit share should stay high)"
    )
    if tag_n / total_h < 0.70:
        raise SystemExit(
            "provenance sanity failed: almost no tag:height on emitted building volumes"
        )
    print(f"all extrude height_source {dict(height_sources)}")
    print(f"width sources {dict(width_sources)}")
    print(f"roofs emitted {dict(roof_shapes_emitted)} skipped {dict(roof_shapes_skipped)}")
    print(f"skipped {dict(skipped)}")
    print(f"counts {counts}")
    ns_m, ew_m = scene_extent_m(nodes)
    req_ns = vincenty_m(origin_lon, south, origin_lon, north)
    req_ew = vincenty_m(west, origin_lat, east, origin_lat)
    print(
        f"emitted extent {ns_m:.1f} x {ew_m:.1f} m (NS x EW) vs requested bbox "
        f"{req_ns:.1f} x {req_ew:.1f} m"
    )
    if ns_m > req_ns * 2.5 or ew_m > req_ew * 2.5:
        print(
            "WARNING: emitted extent is much larger than the requested bbox; "
            "a below-grade station may have leaked through"
        )
    manifest["extent_m"] = {
        "emitted_ns": round(ns_m, 2),
        "emitted_ew": round(ew_m, 2),
        "requested_ns": round(req_ns, 2),
        "requested_ew": round(req_ew, 2),
    }
    manifest["provenance"]["height_source"] = dict(sorted(bsrc.items()))
    return {"manifest": manifest, "nodes": nodes}


def dump_scene(path: Path, scene: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(scene, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    path.write_text(text, encoding="utf-8")


def scene_extent_m(nodes: list) -> tuple[float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for node in nodes:
        kind = node.get("kind")
        if kind == "extrude":
            for x, y in node.get("outline") or []:
                xs.append(float(x))
                ys.append(float(y))
        elif kind == "mesh":
            for vert in node.get("vertices") or []:
                xs.append(float(vert[0]))
                ys.append(float(vert[1]))
        elif kind == "ribbon":
            for x, y in node.get("points") or []:
                xs.append(float(x))
                ys.append(float(y))
    if not xs:
        return 0.0, 0.0
    return (max(xs) - min(xs)) / CM_PER_M, (max(ys) - min(ys)) / CM_PER_M


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------
def fail(failures: list, name: str, detail: str) -> None:
    failures.append(f"{name}: {detail}")


def self_check(scene: dict, sidecar: dict, scene_text: str) -> None:
    failures: list[str] = []
    nodes = scene["nodes"]
    manifest = scene["manifest"]
    origin = manifest["origin"]
    project = make_projector(origin["lat"], origin["lon"])
    ox, oy = project(origin["lon"], origin["lat"])
    if abs(ox) > 1.0 or abs(oy) > 1.0:
        fail(failures, "origin_projection", f"origin projected to ({ox:.3f},{oy:.3f}) not (0,0)")

    extrudes = [n for n in nodes if n["kind"] == "extrude"]
    meshes = [n for n in nodes if n["kind"] == "mesh"]
    ribbons = [n for n in nodes if n["kind"] == "ribbon"]
    counts = manifest["counts"]
    if counts["extrude"] != len(extrudes) or counts["mesh"] != len(meshes) or counts["ribbon"] != len(ribbons):
        fail(failures, "counts", f"manifest {counts} != actual e{len(extrudes)} m{len(meshes)} r{len(ribbons)}")

    for n in extrudes:
        ring = n.get("outline") or []
        if len(ring) < 3:
            fail(failures, "ring_short", n["id"])
            continue
        if ring[0] == ring[-1]:
            fail(failures, "ring_closed_duplicate", n["id"])
        if signed_area(ring) < 0:
            fail(failures, "ring_cw", n["id"])
        if n["height_cm"] <= (n.get("base_cm") or 0):
            fail(failures, "height_not_above_base", f"{n['id']} {n['height_cm']} <= {n.get('base_cm')}")
        if not (n.get("attrs") or {}).get("height_source"):
            fail(failures, "missing_height_source", n["id"])

    for n in meshes:
        verts = n.get("vertices") or []
        for face in n.get("indices") or []:
            if any(not isinstance(i, int) or i < 0 or i >= len(verts) for i in face):
                fail(failures, "mesh_index", n["id"])
                break

    for n in ribbons:
        if len(n.get("points") or []) < 2 or n.get("width_cm", 0) <= 0:
            fail(failures, "ribbon", n["id"])

    south, west, north, east = sidecar["bbox_requested_south_west_north_east"]
    origin_lat = (south + north) / 2.0
    origin_lon = (west + east) / 2.0
    ns0 = project(origin_lon, south)
    ns1 = project(origin_lon, north)
    ns_proj = math.hypot(ns1[0] - ns0[0], ns1[1] - ns0[1]) / CM_PER_M
    ns_ref = vincenty_m(origin_lon, south, origin_lon, north)
    ew0 = project(west, origin_lat)
    ew1 = project(east, origin_lat)
    ew_proj = math.hypot(ew1[0] - ew0[0], ew1[1] - ew0[1]) / CM_PER_M
    ew_ref = vincenty_m(west, origin_lat, east, origin_lat)
    ns_err = abs(ns_proj - ns_ref) / ns_ref if ns_ref else 1.0
    ew_err = abs(ew_proj - ew_ref) / ew_ref if ew_ref else 1.0
    print(
        f"projection scale vs Vincenty NS {ns_err * 100:.4f}% ({ns_proj:.2f}/{ns_ref:.2f} m) "
        f"EW {ew_err * 100:.4f}% ({ew_proj:.2f}/{ew_ref:.2f} m)"
    )
    if ns_err >= 0.0005 or ew_err >= 0.0005:
        fail(failures, "scale", f"NS {ns_err * 100:.4f}% EW {ew_err * 100:.4f}% >= 0.05%")

    # orientation: long driveable ribbon vs ~29° / 119° Manhattan grid
    bearings = []
    for n in ribbons:
        pts = n["points"]
        dx = pts[-1][0] - pts[0][0]
        dy = pts[-1][1] - pts[0][1]
        if math.hypot(dx, dy) < 8000:
            continue
        bearings.append(math.degrees(math.atan2(dy, dx)) % 180.0)
    if bearings:
        med = statistics.median(bearings)
        # 29° avenues or 119° streets
        dist = min(abs(med - 29.0), abs(med - 119.0), abs(med - 0.0), abs(med - 90.0))
        print(f"median long-ribbon bearing {med:.1f} deg (nearest grid delta {dist:.1f})")

    if "/Users/" in scene_text or "/home/" in scene_text or "/opt/" in scene_text:
        fail(failures, "absolute_path", "scene.json contains an absolute path")

    ox_lat = (south + north) / 2.0
    ox_lon = (west + east) / 2.0
    if abs(origin["lat"] - ox_lat) > 1e-12 or abs(origin["lon"] - ox_lon) > 1e-12:
        fail(failures, "origin_centre", "manifest origin is not requested-bbox centre")

    if not extrudes:
        fail(failures, "empty_extrudes", "no building volumes")
    if not ribbons:
        fail(failures, "empty_ribbons", "no roads")

    street = (manifest.get("assumptions") or {}).get("street_network") or {}
    sidewalks = int(street.get("sidewalk_emitted") or 0)
    plazas = int(street.get("plaza_emitted") or 0)
    sidewalk_src = int(street.get("sidewalk_source") or 0)
    if sidewalk_src >= 100 and sidewalks < 0.8 * sidewalk_src:
        fail(
            failures,
            "sidewalks_dropped",
            f"emitted {sidewalks} sidewalks from {sidewalk_src} mapped ways",
        )
    if int(street.get("plaza_source") or 0) >= 10 and plazas == 0:
        fail(failures, "plazas_dropped", "plaza polygons were not emitted")
    skipped = manifest.get("skipped") or {}
    if "highway_not_driveable" in skipped and sidewalks == 0:
        fail(failures, "lump_exclusion", "non-driveable ways were dropped as one lump")
    if "below_grade_indoor_tunnel_or_layer_lt_0" not in skipped:
        fail(failures, "below_grade_uncounted", "below-grade pedestrian ways were not counted")
    if "crossing_on_carriageway" not in skipped:
        fail(failures, "crossings_uncounted", "crossings were not counted")
    if not any(k.startswith("below_grade_building") for k in skipped):
        fail(failures, "below_grade_buildings_uncounted", "below-grade buildings were not counted")
    cover = (manifest.get("assumptions") or {}).get("ground_cover") or {}
    z_table = cover.get("z_cm") or (manifest.get("assumptions") or {}).get("ground_cover_z_cm") or {}
    for klass, z_cm in z_table.items():
        if float(z_cm) <= 0 or float(z_cm) >= 4:
            fail(failures, "ground_z_band", f"{klass} at Z={z_cm} is not in (0, 4) cm")
    if not cover.get("emitted"):
        fail(failures, "ground_cover_missing", "no ground-cover polygons were emitted")
    huge_buildings = []
    for n in extrudes:
        tags = set(n.get("tags") or [])
        if not tags & {"building", "building:part"}:
            continue
        ring = n.get("outline") or []
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        span_m = max(max(xs) - min(xs), max(ys) - min(ys)) / CM_PER_M
        if span_m > 400:
            huge_buildings.append(f"{n['id']} {span_m:.0f}m")
    if huge_buildings:
        fail(
            failures,
            "huge_building",
            "building span > 400 m (likely a below-grade station at grade): "
            + ", ".join(huge_buildings[:5]),
        )

    if failures:
        print("VERIFY FAILED")
        for item in failures:
            print(f"  {item}")
        raise SystemExit(1)
    print("VERIFY OK")


def prove_projection(sidecar: dict) -> None:
    south, west, north, east = sidecar["bbox_requested_south_west_north_east"]
    origin_lat = (south + north) / 2.0
    origin_lon = (west + east) / 2.0
    project = make_projector(origin_lat, origin_lon)
    x0, y0 = project(origin_lon, origin_lat)
    print(f"projection origin -> ({x0:.4f}, {y0:.4f}) cm")
    # NS extent
    xn, _ = project(origin_lon, north)
    xs, _ = project(origin_lon, south)
    ns_m = abs(xn - xs) / CM_PER_M
    ns_approx = (north - south) * 111320.0
    print(f"projected NS {ns_m:.2f} m vs 111320*dlat {ns_approx:.2f} m")
    hav = vincenty_m(west, south, east, north)
    p0 = project(west, south)
    p1 = project(east, north)
    proj = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / CM_PER_M
    print(f"corner-to-corner {proj:.2f} m vs Vincenty {hav:.2f} m ({abs(proj - hav) / hav * 100:.4f}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = resolve_repo(args.repo)
    area = args.area
    geojson, sidecar, geojson_rel, fetch_rel = fetch_stage(repo, area, args.force)
    south, west, north, east = sidecar["bbox_requested_south_west_north_east"]
    origin_lat = (south + north) / 2.0
    origin_lon = (west + east) / 2.0
    project_cm = make_projector(origin_lat, origin_lon)
    prove_projection(sidecar)
    inventory = inspect_and_index(geojson["features"], project_cm)
    inventory["project_cm"] = project_cm
    fits = fit_models(inventory)
    scene = build_scene(inventory, fits, sidecar, area, geojson_rel)
    out_rel = f"data/ue/{area}/scene.json"
    out_path = repo / out_rel
    dump_scene(out_path, scene)
    print(f"wrote {out_rel} nodes={len(scene['nodes'])}")
    if args.verify:
        text = out_path.read_text(encoding="utf-8")
        self_check(scene, sidecar, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
