"""Advisory verification of a generated scene.json against the contract and the source.

The point of this module is that it does NOT trust the pipeline. It re-derives what it
can from the raw OSM extract - reprojecting sample vertices with its own reference
implementation, recomputing road bearings from lon/lat, counting source features - so a
pipeline that is confidently wrong is caught. A checker that reads the pipeline's own
manifest only confirms the pipeline agrees with itself.

Every check here corresponds to a fault that has actually occurred in this project:
clockwise rings extruding inside-out, an absolute top used as an extrusion length,
out-of-range triangle indices, silent drops, unlabelled invented values.

Advisory by design: it returns findings, it does not block anything.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable

# plugins/osm/verify_scene.py -> plugins -> hermes-agent -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = Path(os.getenv("CITYGEN_OSM_OUT_DIR") or PROJECT_ROOT / "data" / "raw")

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
R_MEAN = 6_371_008.8

KNOWN_KINDS = {"extrude", "mesh", "ribbon", "instance"}
# How far a re-projected vertex may sit from where the pipeline put it. Integer-centimetre
# rounding alone accounts for ~1 cm; anything past this is a projection disagreement.
PROJECTION_TOLERANCE_CM = 5.0
SAMPLE_VERTICES = 400


# --- ring validity ------------------------------------------------------------------
# Kept here rather than in a shared module: the pipeline under test writes its own
# version of this, and a verifier that imports the same helper the pipeline could have
# imported is checking a tautology.

def _orientation(a: list[float], b: list[float], c: list[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(p1, p2, p3, p4) -> bool:
    """Proper crossing test; shared endpoints do not count."""
    d1, d2 = _orientation(p3, p4, p1), _orientation(p3, p4, p2)
    d3, d4 = _orientation(p1, p2, p3), _orientation(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def ring_problems(ring: list[list[float]]) -> list[str]:
    """Faults that would break an extrusion: not closed, degenerate, self-crossing.

    Extruding a self-crossing ring produces inside-out or tangled solids, and OSM does
    contain them, so this has to be checked before geometry is generated - not after
    it looks wrong in the viewport.
    """
    problems: list[str] = []
    if len(ring) < 4:
        return ["fewer than 4 points"]
    if ring[0] != ring[-1]:
        problems.append("not closed")

    body = ring[:-1] if ring[0] == ring[-1] else ring
    if len(body) != len({tuple(p) for p in body}):
        problems.append("repeated vertex")

    segments = list(zip(body, body[1:] + body[:1]))
    count = len(segments)
    for i in range(count):
        # Skip adjacent segments: they legitimately share an endpoint.
        for j in range(i + 2, count - (1 if i == 0 else 0)):
            if _segments_cross(*segments[i], *segments[j]):
                problems.append("self-intersecting")
                return problems
    return problems


class Finding(dict):
    """One check result, shaped for an agent to act on rather than to read."""

    def __init__(self, name: str, ok: bool, detail: str, *,
                 severity: str = "error", offenders: Iterable[str] = (),
                 count: int | None = None, hint: str = ""):
        offender_list = [str(o) for o in offenders][:10]
        super().__init__(
            name=name,
            status="pass" if ok else "fail",
            severity=severity,
            detail=detail,
        )
        if offender_list:
            self["offenders"] = offender_list
        if count is not None:
            self["count"] = count
        if hint and not ok:
            self["hint"] = hint


def _reference_projector(origin_lat: float, origin_lon: float):
    """Independent lon/lat -> UE cm, from WGS84 radii of curvature at the origin."""
    phi0 = math.radians(origin_lat)
    meridional = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * math.sin(phi0) ** 2) ** 1.5
    normal = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(phi0) ** 2)

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = math.radians(lat - origin_lat) * meridional * 100.0   # +X North
        y = math.radians(lon - origin_lon) * normal * math.cos(phi0) * 100.0  # +Y East
        return x, y

    return project


def _signed_area(ring: list) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * R_MEAN * math.asin(math.sqrt(h))


def _source_paths(area: str, raw_dir: Path) -> tuple[Path, Path]:
    return raw_dir / f"{area}.geojson", raw_dir / f"{area}.fetch.json"


def verify_scene(scene_path: Path, area: str, raw_dir: Path | None = None) -> dict[str, Any]:
    raw = Path(raw_dir or DEFAULT_OUT_DIR)
    findings: list[Finding] = []

    scene = json.loads(Path(scene_path).read_text())
    nodes = scene.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return {
            "ok": False, "errors": 1, "warnings": 0, "scene": str(scene_path),
            "checks": [Finding("schema", False, "scene.json has no 'nodes' array",
                               hint="Emit {\"manifest\": {...}, \"nodes\": [...]}; see "
                                    "the osm:scene-contract skill.")],
        }

    # --- structure ------------------------------------------------------------------
    bad_kind = [n.get("id", "?") for n in nodes if n.get("kind") not in KNOWN_KINDS]
    findings.append(Finding(
        "kinds", not bad_kind,
        f"{len(bad_kind)} nodes use an unknown kind" if bad_kind
        else f"all {len(nodes)} nodes use known kinds",
        offenders=bad_kind, count=len(bad_kind) or None,
        hint=f"kind must be one of {sorted(KNOWN_KINDS)} - it is a geometric primitive, "
             "never a feature type"))

    extrudes = [n for n in nodes if n.get("kind") == "extrude"]
    meshes = [n for n in nodes if n.get("kind") == "mesh"]
    ribbons = [n for n in nodes if n.get("kind") == "ribbon"]

    missing = [n.get("id", "?") for n in extrudes
               if not n.get("outline") or "height_cm" not in n]
    missing += [n.get("id", "?") for n in meshes
                if not n.get("vertices") or not n.get("indices")]
    missing += [n.get("id", "?") for n in ribbons
                if not n.get("points") or not n.get("width_cm")]
    findings.append(Finding(
        "required_fields", not missing,
        f"{len(missing)} nodes are missing required geometry for their kind" if missing
        else "every node carries the fields its kind requires",
        offenders=missing, count=len(missing) or None,
        hint="extrude needs outline+height_cm, mesh needs vertices+indices, ribbon needs "
             "points+width_cm"))

    # --- rings ----------------------------------------------------------------------
    clockwise, broken = [], []
    for node in extrudes:
        ring = node.get("outline") or []
        if len(ring) < 3:
            broken.append(node.get("id", "?"))
            continue
        if ring[0] == ring[-1]:
            broken.append(node.get("id", "?"))
        if _signed_area([tuple(p) for p in ring]) < 0:
            clockwise.append(node.get("id", "?"))
    findings.append(Finding(
        "ring_winding", not clockwise,
        f"{len(clockwise)} exterior rings are clockwise; extrusion comes out inside-out"
        if clockwise else f"all {len(extrudes)} exterior rings are counter-clockwise",
        offenders=clockwise, count=len(clockwise) or None,
        hint="reverse any ring whose shoelace area is negative in (X, Y)"))
    findings.append(Finding(
        "ring_shape", not broken,
        f"{len(broken)} rings are degenerate or repeat their first vertex" if broken
        else "no degenerate or closed-duplicate rings",
        offenders=broken, count=len(broken) or None,
        hint="rings need >= 3 vertices and must NOT repeat the first vertex at the end"))

    self_intersecting = []
    for node in extrudes[:2000]:
        ring = [list(p) for p in (node.get("outline") or [])]
        if len(ring) >= 3 and "self-intersecting" in ring_problems(ring + [ring[0]]):
            self_intersecting.append(node.get("id", "?"))
    findings.append(Finding(
        "ring_self_intersection", not self_intersecting,
        f"{len(self_intersecting)} rings self-intersect" if self_intersecting
        else "no self-intersecting rings",
        offenders=self_intersecting, count=len(self_intersecting) or None,
        hint="a bow-tie ring extrudes to tangled geometry; repair or drop it"))

    # --- heights --------------------------------------------------------------------
    inverted = [n.get("id", "?") for n in extrudes
                if float(n.get("height_cm", 0)) <= float(n.get("base_cm", 0) or 0)]
    findings.append(Finding(
        "height_above_base", not inverted,
        f"{len(inverted)} volumes have height_cm <= base_cm" if inverted
        else "every volume rises above its base",
        offenders=inverted, count=len(inverted) or None,
        hint="height_cm is the ABSOLUTE TOP and base_cm the absolute bottom; a part from "
             "30 m to 80 m is base_cm 3000, height_cm 8000"))

    # --- meshes ---------------------------------------------------------------------
    out_of_range, degenerate = [], []
    for node in meshes:
        verts = node.get("vertices") or []
        for face in node.get("indices") or []:
            if any(not isinstance(i, int) or i < 0 or i >= len(verts) for i in face):
                out_of_range.append(node.get("id", "?"))
                break
            if len({tuple(verts[i]) for i in face}) < 3:
                degenerate.append(node.get("id", "?"))
                break
    findings.append(Finding(
        "mesh_indices", not out_of_range,
        f"{len(out_of_range)} meshes index vertices they do not have" if out_of_range
        else f"all {len(meshes)} meshes index within their own vertex list",
        offenders=out_of_range, count=len(out_of_range) or None,
        hint="indices are per-node: 0 <= i < len(vertices) of that same node"))
    findings.append(Finding(
        "mesh_degenerate", not degenerate,
        f"{len(degenerate)} meshes contain zero-area triangles" if degenerate
        else "no degenerate triangles",
        severity="warning", offenders=degenerate, count=len(degenerate) or None,
        hint="drop triangles whose three vertices are not distinct"))

    # --- ribbons --------------------------------------------------------------------
    bad_ribbon = [n.get("id", "?") for n in ribbons
                  if len(n.get("points") or []) < 2 or float(n.get("width_cm", 0)) <= 0]
    findings.append(Finding(
        "ribbon_shape", not bad_ribbon,
        f"{len(bad_ribbon)} ribbons have < 2 points or a non-positive width"
        if bad_ribbon else f"all {len(ribbons)} ribbons are well formed",
        offenders=bad_ribbon, count=len(bad_ribbon) or None,
        hint="a ribbon needs at least two points and a width greater than zero"))

    # --- provenance ------------------------------------------------------------------
    unlabelled = [n.get("id", "?") for n in extrudes if not (n.get("attrs") or {}).get("height_source")]
    findings.append(Finding(
        "provenance", not unlabelled,
        f"{len(unlabelled)} volumes do not say where their height came from" if unlabelled
        else "every volume names the source of its height",
        severity="warning", offenders=unlabelled, count=len(unlabelled) or None,
        hint="set attrs.height_source per node (tag:height, building:levels*Xm, an "
             "estimate with its fit, or @fitted:<area> when borrowed)"))

    # --- against the source ----------------------------------------------------------
    geojson_path, fetch_path = _source_paths(area, raw)
    if not geojson_path.is_file() or not fetch_path.is_file():
        findings.append(Finding(
            "source_available", False,
            f"no source extract at {geojson_path} - geometry could not be checked "
            "against OSM", severity="warning",
            hint="run the fetch for this area so verification can re-derive from source"))
    else:
        findings.extend(_verify_against_source(scene, nodes, geojson_path, fetch_path))

    errors = sum(1 for f in findings if f["status"] == "fail" and f["severity"] == "error")
    warnings = sum(1 for f in findings if f["status"] == "fail" and f["severity"] == "warning")
    return {
        "ok": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "scene": str(scene_path),
        "node_counts": {"extrude": len(extrudes), "mesh": len(meshes),
                        "ribbon": len(ribbons), "total": len(nodes)},
        "checks": findings,
    }


def _verify_against_source(scene: dict, nodes: list, geojson_path: Path,
                           fetch_path: Path) -> list[Finding]:
    """Re-derive from the raw extract. This is what makes the check independent."""
    findings: list[Finding] = []
    features = json.loads(geojson_path.read_text()).get("features", [])
    fetch = json.loads(fetch_path.read_text())
    south, west, north, east = fetch["bbox_requested_south_west_north_east"]
    origin_lat, origin_lon = (south + north) / 2, (west + east) / 2

    manifest_origin = (scene.get("manifest") or {}).get("origin") or {}
    stated_lat = float(manifest_origin.get("lat", origin_lat))
    stated_lon = float(manifest_origin.get("lon", origin_lon))
    origin_off_m = _haversine_m((stated_lon, stated_lat), (origin_lon, origin_lat))
    findings.append(Finding(
        "origin", origin_off_m < 1.0,
        f"manifest origin is {origin_off_m:.1f} m from the requested bbox centre"
        if origin_off_m >= 1.0 else "origin matches the requested bbox centre",
        hint="the origin is the centre of bbox_requested (not the buffered bbox)"))

    project = _reference_projector(origin_lat, origin_lon)

    # Vertex-level projection check: match source polygons to extrude nodes by id suffix.
    by_osm_id = {}
    for feature in features:
        props = feature.get("properties") or {}
        if feature["geometry"]["type"] == "Polygon":
            by_osm_id.setdefault(str(props.get("osm_id")), feature)

    deviations: list[float] = []
    for node in nodes:
        if node.get("kind") != "extrude" or len(deviations) > SAMPLE_VERTICES:
            continue
        # Ids are the pipeline's choice, so do not depend on one convention: prefer an
        # explicit attrs.osm_id, and otherwise take the trailing digits of the id.
        attrs = node.get("attrs") or {}
        candidate = attrs.get("osm_id")
        if candidate is None:
            trailing = re.search(r"(\d+)\D*$", str(node.get("id", "")))
            candidate = trailing.group(1) if trailing else None
        source = by_osm_id.get(str(candidate)) if candidate is not None else None
        if not source:
            continue
        ring = source["geometry"]["coordinates"][0]
        ring = ring[:-1] if ring and ring[0] == ring[-1] else ring
        emitted = node.get("outline") or []
        if len(ring) != len(emitted):
            continue
        for lon, lat in ring:
            rx, ry = project(lon, lat)
            deviations.append(min(math.dist((rx, ry), (float(x), float(y)))
                                  for x, y in emitted))

    if deviations:
        worst = max(deviations)
        findings.append(Finding(
            "projection", worst <= PROJECTION_TOLERANCE_CM,
            f"worst vertex deviates {worst:.1f} cm from an independent WGS84 "
            f"tangent-plane projection ({len(deviations)} vertices sampled)",
            hint="check units (centimetres), the origin, and that +X is North and +Y is "
                 "East; do not use 111320*cos(lat) as the projection"))
    else:
        findings.append(Finding(
            "projection", False,
            "could not match any emitted outline back to a source polygon",
            severity="warning",
            hint="carry the source id per node (attrs.osm_id, or an id ending in the OSM "
                 "id) so emitted geometry can be checked against the source"))

    # Orientation: bearings recomputed from lon/lat versus bearings of the emitted ribbons.
    source_bearings = []
    for feature in features:
        props = feature.get("properties") or {}
        if not props.get("highway") or feature["geometry"]["type"] != "LineString":
            continue
        coords = feature["geometry"]["coordinates"]
        if len(coords) < 2:
            continue
        if _haversine_m(tuple(coords[0]), tuple(coords[-1])) < 50:
            continue
        x0, y0 = project(*coords[0])
        x1, y1 = project(*coords[-1])
        source_bearings.append(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180)

    emitted_bearings = []
    for node in nodes:
        if node.get("kind") != "ribbon":
            continue
        points = node.get("points") or []
        if len(points) < 2:
            continue
        dx = float(points[-1][0]) - float(points[0][0])
        dy = float(points[-1][1]) - float(points[0][1])
        if math.hypot(dx, dy) < 5000:
            continue
        emitted_bearings.append(math.degrees(math.atan2(dy, dx)) % 180)

    if source_bearings and emitted_bearings:
        source_bearings.sort()
        emitted_bearings.sort()
        src = source_bearings[len(source_bearings) // 2]
        emt = emitted_bearings[len(emitted_bearings) // 2]
        delta = min(abs(src - emt), 180 - abs(src - emt))
        findings.append(Finding(
            "orientation", delta < 5.0,
            f"median road bearing {emt:.1f} deg vs {src:.1f} deg recomputed from source "
            f"(delta {delta:.1f} deg)",
            hint="a large delta means the axes are swapped or mirrored: +X is North, "
                 "+Y is East"))

    # Present in the source but absent from the scene: the failure a per-node check
    # cannot see, because every node it DID emit may be perfectly valid. A scene with
    # zero roads passed every other check here until this was added.
    source_roads = sum(1 for f in features
                       if (f.get("properties") or {}).get("highway")
                       and f["geometry"]["type"] == "LineString")
    emitted_ribbons = sum(1 for n in nodes if n.get("kind") == "ribbon")
    findings.append(Finding(
        "road_coverage", not (source_roads > 0 and emitted_ribbons == 0),
        f"the source has {source_roads} highway ways but the scene has no ribbon nodes"
        if source_roads > 0 and emitted_ribbons == 0
        else f"{emitted_ribbons} ribbons for {source_roads} source highway ways",
        offenders=(), count=None,
        hint="emit the road network as ribbon nodes, or state in the manifest why this "
             "area deliberately has none"))

    source_roof_shapes = sum(1 for f in features
                             if (f.get("properties") or {}).get("roof:shape")
                             and (f.get("properties") or {}).get("roof:shape") != "flat")
    emitted_meshes = sum(1 for n in nodes if n.get("kind") == "mesh")
    findings.append(Finding(
        "roof_coverage", not (source_roof_shapes > 0 and emitted_meshes == 0),
        f"the source tags {source_roof_shapes} non-flat roof shapes but the scene has no "
        f"mesh nodes" if source_roof_shapes > 0 and emitted_meshes == 0
        else f"{emitted_meshes} meshes for {source_roof_shapes} non-flat roof shapes",
        severity="warning",
        hint="build the tagged roof forms as mesh nodes, or record in the manifest that "
             "they were deliberately left flat"))

    source_buildings = sum(1 for f in features
                           if "building" in (f.get("properties") or {})
                           or "building:part" in (f.get("properties") or {}))
    emitted = sum(1 for n in nodes if n.get("kind") == "extrude")
    kept = emitted / source_buildings if source_buildings else 0
    findings.append(Finding(
        "coverage", kept >= 0.5,
        f"{emitted} volumes from {source_buildings} source building features "
        f"({kept * 100:.0f}%)",
        severity="warning",
        hint="parts resolution legitimately reduces the count, but a large drop with no "
             "explanation in the manifest usually means features were lost"))

    # Height provenance: the failure every geometric check here passes.
    #
    # A scene whose footprints were all correct, all counter-clockwise, all above their
    # base, and whose every height was one invented constant validated clean until this
    # was added. The pipeline had read tags from the wrong nesting level, lost 606 stated
    # heights, and labelled all 1777 volumes "median_fallback:45". Nothing about the
    # geometry can show that - the shapes really were right. Only the source can, by
    # asking whether the heights claim to come from tags the source actually carries.
    building_features = [f for f in features
                         if "building" in (f.get("properties") or {})
                         or "building:part" in (f.get("properties") or {})]
    source_tagged = sum(1 for f in building_features
                        if (f.get("properties") or {}).get("height")
                        or (f.get("properties") or {}).get("building:levels"))
    source_share = source_tagged / len(building_features) if building_features else 0.0

    extrudes_here = [n for n in nodes if n.get("kind") == "extrude"]
    # Both prefixes mean "derived from a tag stated on this feature": tag:height reads it
    # directly, building:levels*Xm applies a fitted ratio to a stated storey count. The
    # source denominator counts the same two tags, so the shares are comparable.
    stated = [n for n in extrudes_here
              if str((n.get("attrs") or {}).get("height_source", ""))
              .startswith(("tag:", "building:levels"))]
    emitted_share = len(stated) / len(extrudes_here) if extrudes_here else 0.0

    sources: dict[str, int] = {}
    for node in extrudes_here:
        label = str((node.get("attrs") or {}).get("height_source", "(none)"))
        # Collapse a fit's parameters so the histogram stays readable.
        sources[label.split("[")[0]] = sources.get(label.split("[")[0], 0) + 1
    top = ", ".join(f"{k} {v}" for k, v in
                    sorted(sources.items(), key=lambda kv: -kv[1])[:4])

    # Only meaningful where the source states something worth reading. An area that
    # genuinely tags almost nothing (Le Marais: 1 height in 694) must not be failed for
    # honestly estimating everything.
    worth_checking = source_share >= 0.2
    findings.append(Finding(
        "height_provenance", not worth_checking or emitted_share >= source_share * 0.5,
        f"{emitted_share * 100:.0f}% of volumes cite a stated tag as their height source "
        f"but {source_share * 100:.0f}% of source building features carry height or "
        f"building:levels [{top}]",
        count=len(extrudes_here) - len(stated) or None,
        hint="the source states these heights and the scene is not using them, which is "
             "what reading tags from the wrong nesting level looks like: the geometry "
             "stays correct and every height becomes a constant. Print the provenance "
             "histogram after parsing and compare it against the tag coverage you "
             "measured"))
    return findings
