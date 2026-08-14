"""Stage 4: write UE-consumable artefacts (JSON + CSV DataTables + GeoJSON)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString

from . import parts as parts_mod
from .config import AreaConfig
from .project import LocalFrame, clean_polygon, oriented_box, UE_UNITS_PER_M

SCHEMA_VERSION = "osm2pcg/1"


def _r(v: float, nd: int = 1) -> float:
    return round(v, nd)


def _pack(points: list[tuple[float, float]]) -> str:
    """Polyline/ring -> compact string for a DataTable string column."""
    return "|".join(f"{_r(x)} {_r(y)}" for x, y in points)


def translate(
    features: dict[str, list[dict]], frame: LocalFrame
) -> tuple[dict[str, Any], dict[str, int]]:
    """Project every feature into UE centimetres and derive per-feature metadata.

    Returns (scene, building_part_stats).
    """
    # Project first, then resolve building:part vs parent envelopes in metric space.
    projected: list[dict[str, Any]] = []
    for src in features["buildings"]:
        poly = clean_polygon(frame.ring_to_metres(src["ring"]))
        if poly is not None:
            projected.append({"poly": poly, "is_part": src["is_part"], "src": src})

    resolved, part_stats = parts_mod.resolve(projected)
    print(f"[translate] building:part resolution {part_stats}")

    buildings: list[dict] = []
    for record in resolved:
        poly = record["poly"]
        b = record["src"]
        obb = oriented_box(poly)
        outline_ue = [
            frame.metres_to_ue(e, n) for e, n in list(poly.exterior.coords)[:-1]
        ]
        cx, cy = frame.metres_to_ue(poly.centroid.x, poly.centroid.y)
        holes = [
            [frame.metres_to_ue(e, n) for e, n in list(ring.coords)[:-1]]
            for ring in poly.interiors
        ]
        obb_x, obb_y = frame.metres_to_ue(obb["center_east_m"], obb["center_north_m"])
        buildings.append({
            "id": b["osm_id"],
            "kind": b["kind"],
            "name": b["name"],
            "is_part": b["is_part"],
            "height_cm": _r(b["height_m"] * UE_UNITS_PER_M),
            "base_cm": _r(b["min_height_m"] * UE_UNITS_PER_M),
            "height_source": b["height_source"],
            "area_m2": _r(poly.area, 2),
            "centroid": [_r(cx), _r(cy)],
            "obb": {
                "x": _r(obb_x),
                "y": _r(obb_y),
                "length_cm": _r(obb["length_m"] * UE_UNITS_PER_M),
                "width_cm": _r(obb["width_m"] * UE_UNITS_PER_M),
                "yaw_deg": _r(obb["yaw_deg"], 2),
            },
            "outline": [[_r(x), _r(y)] for x, y in outline_ue],
            "holes": [[[_r(x), _r(y)] for x, y in h] for h in holes],
        })

    roads: list[dict] = []
    for r in features["roads"]:
        line_m = LineString(frame.ring_to_metres(r["points"]))
        if line_m.length < 1.0:
            continue
        line_m = line_m.simplify(0.5, preserve_topology=False)
        pts_ue = [frame.metres_to_ue(e, n) for e, n in line_m.coords]
        roads.append({
            "id": r["osm_id"],
            "class": r["highway"],
            "name": r["name"],
            "width_cm": _r(r["width_m"] * UE_UNITS_PER_M),
            "length_cm": _r(line_m.length * UE_UNITS_PER_M),
            "layer": r["layer"],
            "bridge": r["bridge"],
            "tunnel": r["tunnel"],
            "points": [[_r(x), _r(y)] for x, y in pts_ue],
        })

    def _areas(key: str) -> list[dict]:
        out = []
        for f in features[key]:
            poly = clean_polygon(frame.ring_to_metres(f["ring"]))
            if poly is None:
                continue
            out.append({
                "id": f["osm_id"],
                "kind": f["kind"],
                "area_m2": _r(poly.area, 2),
                "outline": [
                    [_r(x), _r(y)]
                    for x, y in (
                        frame.metres_to_ue(e, n)
                        for e, n in list(poly.exterior.coords)[:-1]
                    )
                ],
            })
        return out

    scene = {
        "buildings": buildings,
        "roads": roads,
        "water": _areas("water"),
        "green": _areas("green"),
    }
    return scene, part_stats


def scene_bounds(scene: dict[str, Any]) -> dict[str, float]:
    xs: list[float] = []
    ys: list[float] = []
    for b in scene["buildings"]:
        for x, y in b["outline"]:
            xs.append(x)
            ys.append(y)
    for r in scene["roads"]:
        for x, y in r["points"]:
            xs.append(x)
            ys.append(y)
    if not xs:
        return {"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0}
    return {
        "min_x": _r(min(xs)), "min_y": _r(min(ys)),
        "max_x": _r(max(xs)), "max_y": _r(max(ys)),
    }


def write_all(
    scene: dict[str, Any],
    area: AreaConfig,
    frame: LocalFrame,
    out_dir: Path,
    ue_data_dir: Path | None = None,
    part_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": SCHEMA_VERSION,
        "area": area.to_dict(),
        "projection": {
            "source_crs": "EPSG:4326",
            "local_crs_proj4": frame.proj4,
            "origin_lat": frame.origin_lat,
            "origin_lon": frame.origin_lon,
            "ue_units_per_metre": UE_UNITS_PER_M,
            "axis_convention": "UE +X = North, +Y = East, +Z = Up (centimetres)",
        },
        "counts": {k: len(v) for k, v in scene.items()},
        "bounds_ue_cm": scene_bounds(scene),
        "height_sources": _height_source_counts(scene["buildings"]),
        "building_part_resolution": part_stats or {},
        "tallest_building_cm": max((b["height_cm"] for b in scene["buildings"]), default=0),
    }

    written: list[Path] = []
    for name, payload in (
        ("buildings.json", {"schema": SCHEMA_VERSION, "buildings": scene["buildings"]}),
        ("roads.json", {"schema": SCHEMA_VERSION, "roads": scene["roads"]}),
        ("areas.json", {"schema": SCHEMA_VERSION, "water": scene["water"], "green": scene["green"]}),
        ("city.json", {"schema": SCHEMA_VERSION, "manifest": manifest, **scene}),
        ("manifest.json", manifest),
    ):
        p = out_dir / name
        p.write_text(json.dumps(payload, separators=(",", ":")))
        written.append(p)

    written.append(_write_buildings_csv(scene["buildings"], out_dir / "buildings.csv"))
    written.append(_write_roads_csv(scene["roads"], out_dir / "roads.csv"))

    if ue_data_dir is not None:
        ue_data_dir.mkdir(parents=True, exist_ok=True)
        for p in written:
            (ue_data_dir / p.name).write_bytes(p.read_bytes())
        print(f"[export] mirrored {len(written)} files -> {ue_data_dir}")

    for p in written:
        print(f"[export] {p} ({p.stat().st_size / 1024:.0f} KB)")
    return manifest


def _height_source_counts(buildings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in buildings:
        key = b["height_source"].split("=")[0]
        counts[key] = counts.get(key, 0) + 1
    return counts


def _write_buildings_csv(buildings: list[dict], path: Path) -> Path:
    """DataTable-friendly CSV. `Outline` packs the footprint as 'x y|x y|...'."""
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "Name", "OsmId", "Kind", "HeightCm", "BaseCm", "HeightSource",
            "CentroidX", "CentroidY", "BoxX", "BoxY", "BoxLengthCm",
            "BoxWidthCm", "YawDeg", "AreaM2", "NumVerts", "Outline",
        ])
        for i, b in enumerate(buildings):
            w.writerow([
                f"B{i:05d}", b["id"], b["kind"], b["height_cm"], b["base_cm"],
                b["height_source"], b["centroid"][0], b["centroid"][1],
                b["obb"]["x"], b["obb"]["y"], b["obb"]["length_cm"],
                b["obb"]["width_cm"], b["obb"]["yaw_deg"], b["area_m2"],
                len(b["outline"]), _pack([tuple(p) for p in b["outline"]]),
            ])
    return path


def _write_roads_csv(roads: list[dict], path: Path) -> Path:
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "Name", "OsmId", "Class", "RoadName", "WidthCm", "LengthCm",
            "Layer", "NumPoints", "Points",
        ])
        for i, r in enumerate(roads):
            w.writerow([
                f"R{i:05d}", r["id"], r["class"], r["name"], r["width_cm"],
                r["length_cm"], r["layer"], len(r["points"]),
                _pack([tuple(p) for p in r["points"]]),
            ])
    return path


def write_geojson(features: dict[str, list[dict]], path: Path) -> Path:
    """Raw WGS84 features as GeoJSON, for QGIS / map overlay checks."""
    feats: list[dict] = []
    for b in features["buildings"]:
        feats.append({
            "type": "Feature",
            "properties": {
                "layer": "building", "osm_id": b["osm_id"],
                "height_m": b["height_m"], "height_source": b["height_source"],
                "kind": b["kind"], "name": b["name"],
            },
            "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in b["ring"]]]},
        })
    for r in features["roads"]:
        feats.append({
            "type": "Feature",
            "properties": {
                "layer": "road", "osm_id": r["osm_id"],
                "highway": r["highway"], "width_m": r["width_m"], "name": r["name"],
            },
            "geometry": {"type": "LineString", "coordinates": [list(p) for p in r["points"]]},
        })
    for key in ("water", "green"):
        for f in features[key]:
            feats.append({
                "type": "Feature",
                "properties": {"layer": key, "osm_id": f["osm_id"], "kind": f["kind"]},
                "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in f["ring"]]]},
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"[export] {path} ({len(feats)} features)")
    return path
