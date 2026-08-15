#!/usr/bin/env python3
"""Overhead SVGs for the report: the OSM source and the generated scene, same frame.

Two renders of the same ground, drawn with one projection and one viewport so they can
be laid side by side and compared honestly:

  docs/overhead_osm.svg    straight from data/raw/<area>.geojson (the source)
  docs/overhead_scene.svg  straight from data/ue/<area>/scene.json (what UE reads)

Standard library only, like everything else in the translation path. Deterministic:
same inputs, same bytes.

    tools/render_overhead.py [--area nyc_midtown] [--repo PATH] [--pad-m 0]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)

PX = 1400          # square canvas
MARGIN = 8

# Light-on-dark reads better for a night-ish massing diagram and keeps the two panels
# legible next to a screenshot. Roads first, then ground cover, then buildings on top.
STYLE = {
    "bg":        "#0f1115",
    "frame":     "#2a2f3a",
    "road":      "#3a4250",
    "road_minor":"#2c333e",
    "src_road":  "#5b6675",
    "src_minor": "#39414e",
    "ped":       "#232a34",
    "green":     "#1e3326",
    "water":     "#16324a",
    "wall":      "#8b93a3",
    "roof":      "#c8cfdb",
    "label":     "#7e8798",
}


def projector(origin_lat: float, origin_lon: float):
    """lon/lat -> centimetres, +X North, +Y East (the project's frame)."""
    phi0 = math.radians(origin_lat)
    meridional = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * math.sin(phi0) ** 2) ** 1.5
    normal = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(phi0) ** 2)

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = math.radians(lat - origin_lat) * meridional * 100.0
        y = math.radians(lon - origin_lon) * normal * math.cos(phi0) * 100.0
        return x, y

    return project


class View:
    """Maps scene cm to SVG pixels. +X North is up; +Y East is right."""

    def __init__(self, half_x_cm: float, half_y_cm: float):
        self.half = max(half_x_cm, half_y_cm)
        self.scale = (PX / 2 - MARGIN) / self.half

    def pt(self, x_cm: float, y_cm: float) -> tuple[float, float]:
        # SVG y grows downward, so North (+X) must be negated to point up.
        return (PX / 2 + y_cm * self.scale, PX / 2 - x_cm * self.scale)

    def path(self, points, close=True) -> str:
        if not points:
            return ""
        d = []
        for i, (x, y) in enumerate(points):
            px, py = self.pt(x, y)
            d.append(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}")
        if close:
            d.append("Z")
        return "".join(d)


def _ring_area_cm2(ring) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def header(title: str, subtitle: str) -> list[str]:
    """Canvas only. The caption is drawn last, by caption(), so geometry cannot cover it."""
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{PX}" height="{PX}" '
        f'viewBox="0 0 {PX} {PX}" role="img" aria-label="{title}">',
        f'<rect width="{PX}" height="{PX}" fill="{STYLE["bg"]}"/>',
    ]


def caption(title: str, subtitle: str) -> list[str]:
    return [
        f'<rect x="0" y="0" width="{PX}" height="72" fill="{STYLE["bg"]}" '
        f'fill-opacity="0.82"/>',
        f'<text x="{MARGIN + 10}" y="34" fill="#d8dee9" '
        f'font-family="ui-monospace,Menlo,monospace" font-size="19">{title}</text>',
        f'<text x="{MARGIN + 10}" y="58" fill="{STYLE["label"]}" '
        f'font-family="ui-monospace,Menlo,monospace" font-size="13">{subtitle}</text>',
    ]


def scalebar(view: View, metres: float = 100.0) -> list[str]:
    px = metres * 100.0 * view.scale
    x0, y0 = MARGIN + 12, PX - 26
    return [
        f'<line x1="{x0}" y1="{y0}" x2="{x0 + px:.1f}" y2="{y0}" '
        f'stroke="{STYLE["label"]}" stroke-width="2"/>',
        f'<text x="{x0}" y="{y0 - 8}" fill="{STYLE["label"]}" '
        f'font-family="ui-monospace,Menlo,monospace" font-size="12">{metres:.0f} m</text>',
        f'<text x="{PX - MARGIN - 78}" y="{y0}" fill="{STYLE["label"]}" '
        f'font-family="ui-monospace,Menlo,monospace" font-size="13">N &#8593;</text>',
    ]


def frame(view: View, half_x_cm: float, half_y_cm: float) -> list[str]:
    """The requested bbox, so both panels show what was actually asked for."""
    a = view.pt(half_x_cm, -half_y_cm)
    b = view.pt(-half_x_cm, half_y_cm)
    return [f'<rect x="{a[0]:.1f}" y="{a[1]:.1f}" width="{b[0] - a[0]:.1f}" '
            f'height="{b[1] - a[1]:.1f}" fill="none" stroke="{STYLE["frame"]}" '
            f'stroke-width="1.5" stroke-dasharray="7 5"/>']


DRIVEABLE = {"primary", "secondary", "tertiary", "residential", "service",
             "unclassified", "living_street", "trunk", "primary_link",
             "secondary_link", "tertiary_link", "trunk_link"}
GREEN_KEYS = (("leisure", {"park", "garden", "pitch", "playground", "recreation_ground"}),
              ("landuse", {"grass", "flowerbed", "recreation_ground", "forest"}))


def render_osm(geojson_path: Path, origin, half_x, half_y, note) -> str:
    features = json.loads(geojson_path.read_text())["features"]
    project = projector(*origin)
    view = View(half_x, half_y)
    out = header("OpenStreetMap source", note)
    cap = caption("OpenStreetMap source  (roads are centrelines)", note)
    roads, minor, greens, waters, builds = [], [], [], [], []

    for feature in features:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        gtype, coords = geom.get("type"), geom.get("coordinates")
        if not coords:
            continue

        def ring_to_scene(ring):
            pts = [project(lon, lat) for lon, lat in ring]
            return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts

        if gtype == "LineString" and props.get("highway"):
            pts = ring_to_scene(coords)
            # Source roads are centrelines with no width; draw them heavy enough
            # to read as a grid, and let the caption say they are centrelines.
            width = 5.0 if props["highway"] in DRIVEABLE else 1.1
            target = roads if props["highway"] in DRIVEABLE else minor
            target.append(f'<path d="{view.path(pts, close=False)}" fill="none" '
                          f'stroke-width="{width}" stroke-linecap="round"/>')
            continue

        polys = []
        if gtype == "Polygon":
            polys = [coords[0]]
        elif gtype == "MultiPolygon":
            polys = [poly[0] for poly in coords]
        if not polys:
            continue

        is_green = any(props.get(k) in vals for k, vals in GREEN_KEYS)
        is_water = props.get("natural") == "water" or props.get("water")
        is_build = "building" in props or "building:part" in props
        for ring in polys:
            d = view.path(ring_to_scene(ring))
            if is_water:
                waters.append(f'<path d="{d}"/>')
            elif is_green:
                greens.append(f'<path d="{d}"/>')
            elif is_build:
                builds.append(f'<path d="{d}"/>')

    out.append(f'<g fill="{STYLE["green"]}">{"".join(greens)}</g>')
    out.append(f'<g fill="{STYLE["water"]}">{"".join(waters)}</g>')
    out.append(f'<g stroke="{STYLE["src_minor"]}">{"".join(minor)}</g>')
    out.append(f'<g stroke="{STYLE["src_road"]}">{"".join(roads)}</g>')
    out.append(f'<g fill="{STYLE["wall"]}" fill-opacity="0.85">{"".join(builds)}</g>')
    out += frame(view, half_x, half_y) + cap + scalebar(view) + ["</svg>"]
    return "\n".join(out)


def render_scene(scene_path: Path, half_x, half_y, note) -> str:
    scene = json.loads(scene_path.read_text())
    nodes = scene["nodes"]
    view = View(half_x, half_y)
    out = header("Generated scene (scene.json)", note)
    cap = caption("Generated scene  (roads at derived width)", note)

    ribbons, meshes_flat, meshes_green, builds = [], [], [], []
    for node in nodes:
        kind, tags = node.get("kind"), set(node.get("tags") or [])
        if kind == "ribbon":
            width_px = max(1.0, node.get("width_cm", 300) * view.scale)
            ribbons.append(f'<path d="{view.path(node["points"], close=False)}" '
                           f'fill="none" stroke-width="{width_px:.2f}" '
                           f'stroke-linecap="round" stroke-linejoin="round"/>')
        elif kind == "mesh":
            if "roof" in tags:
                continue                      # roofs sit on their own volume
            # Outline the triangle fan cheaply: draw each triangle flat.
            verts = node.get("vertices") or []
            tris = []
            for tri in node.get("indices") or []:
                pts = [(verts[i][0], verts[i][1]) for i in tri if i < len(verts)]
                if len(pts) == 3:
                    tris.append(view.path(pts))
            body = f'<path d="{"".join(tris)}"/>'
            (meshes_green if tags & {"park", "garden", "grass"} else
             meshes_flat).append(body)
        elif kind == "extrude":
            outline = node.get("outline") or []
            if len(outline) >= 3:
                # Shade by height so the massing reads, the way a map cannot show it.
                h = (node.get("height_cm", 0) - node.get("base_cm", 0)) / 100.0
                t = min(1.0, math.log10(max(h, 1.0)) / 2.6)
                grey = int(0x6a + t * (0xe8 - 0x6a))
                builds.append(f'<path d="{view.path(outline)}" '
                              f'fill="#{grey:02x}{grey:02x}{min(255, grey + 8):02x}"/>')

    out.append(f'<g fill="{STYLE["green"]}">{"".join(meshes_green)}</g>')
    out.append(f'<g fill="{STYLE["ped"]}">{"".join(meshes_flat)}</g>')
    out.append(f'<g stroke="{STYLE["road"]}">{"".join(ribbons)}</g>')
    out.append(f'<g>{"".join(builds)}</g>')
    out += frame(view, half_x, half_y) + cap + scalebar(view) + ["</svg>"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="nyc_midtown")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--pad-m", type=float, default=0.0,
                    help="extra margin beyond the requested bbox, metres")
    args = ap.parse_args()

    repo = Path(args.repo or os.environ.get("CITYGEN_REPO")
                or Path(__file__).resolve().parents[1])
    raw = repo / "data" / "raw"
    fetch = json.loads((raw / f"{args.area}.fetch.json").read_text())
    south, west, north, east = fetch["bbox_requested_south_west_north_east"]
    origin = ((south + north) / 2, (west + east) / 2)

    project = projector(*origin)
    corner_x, corner_y = project(east, north)
    half_x = abs(corner_x) + args.pad_m * 100.0
    half_y = abs(corner_y) + args.pad_m * 100.0

    note = (f"{args.area}  bbox {south},{west},{north},{east}  "
            f"{2 * half_x / 100:.0f} x {2 * half_y / 100:.0f} m  "
            f"+X North / +Y East")

    docs = repo / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "overhead_osm.svg").write_text(
        render_osm(raw / f"{args.area}.geojson", origin, half_x, half_y, note))
    (docs / "overhead_scene.svg").write_text(
        render_scene(repo / "data" / "ue" / args.area / "scene.json",
                     half_x, half_y, note))
    print(f"wrote {docs/'overhead_osm.svg'}")
    print(f"wrote {docs/'overhead_scene.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
