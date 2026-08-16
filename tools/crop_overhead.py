#!/usr/bin/env python3
"""Crop the UE overhead capture to the requested bbox, and rasterise the OSM panel to match.

The point is a side-by-side that can actually be compared: same ground, same extent, same
pixel size, north up in both. Without this the two halves are a perspective screenshot and
a vector map at unrelated scales, which invites the eye to compare the wrong things.

Geometry of the capture (see UnrealProject/Scripts/overhead_shot.py): the editor viewport
renders at ~90 deg FOV, so at camera height Z the visible half-width on the ground is Z.
Pixels per metre is therefore SHOT_PX / (2 * Z), and the requested bbox is a centred crop.

    tools/crop_overhead.py [--area nyc_midtown] [--camera-m 1200]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def half_extent_m(bbox: list[float]) -> tuple[float, float]:
    """Half-height and half-width of the bbox in metres, on the project's tangent plane."""
    south, west, north, east = bbox
    lat0 = (south + north) / 2.0
    phi = math.radians(lat0)
    meridional = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * math.sin(phi) ** 2) ** 1.5
    normal = WGS84_A / math.sqrt(1 - WGS84_E2 * math.sin(phi) ** 2)
    half_ns = math.radians((north - south) / 2.0) * meridional
    half_ew = math.radians((east - west) / 2.0) * normal * math.cos(phi)
    return half_ns, half_ew


def rasterise_svg(svg: Path, out: Path, width_px: int) -> bool:
    """SVG -> PNG using whatever the machine has. Returns False if nothing worked."""
    with tempfile.TemporaryDirectory() as tmp:
        # qlmanage ships with macOS and needs no install; it writes <name>.svg.png.
        subprocess.run(["qlmanage", "-t", "-s", str(width_px), "-o", tmp, str(svg)],
                       capture_output=True)
        made = Path(tmp) / f"{svg.name}.png"
        if made.is_file():
            from PIL import Image
            img = Image.open(made).convert("RGB").resize((width_px, width_px),
                                                         Image.LANCZOS)
            img.save(out)
            return True
    return False


def main() -> int:
    from PIL import Image

    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="nyc_midtown")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--camera-m", type=float, default=1200.0,
                    help="camera height used for the capture, metres")
    ap.add_argument("--extent-m", type=float, default=None,
                    help="width of the crop in metres. Defaults to the requested bbox; "
                         "pass a larger value for a wide view of the whole extract")
    ap.add_argument("--suffix", default="",
                    help="appended to the output names, e.g. _wide")
    args = ap.parse_args()

    repo = Path(args.repo or os.environ.get("CITYGEN_REPO")
                or Path(__file__).resolve().parents[1])
    shot = repo / "UnrealProject" / "Saved" / "Screenshots" / "MacEditor" / "overhead_ue.png"
    if not shot.is_file():
        print(f"no capture at {shot}\n"
              f"take one first: UnrealEditor CityGen.uproject "
              f"-ExecCmds=\"py UnrealProject/Scripts/overhead_shot.py\"", file=sys.stderr)
        return 2

    fetch = json.loads((repo / "data" / "raw" / f"{args.area}.fetch.json").read_text())
    half_ns, half_ew = half_extent_m(fetch["bbox_requested_south_west_north_east"])

    img = Image.open(shot)
    px_per_m = img.width / (2.0 * args.camera_m)
    cx, cy = img.width / 2.0, img.height / 2.0

    # A wider crop trades the bbox framing for showing the whole extract. The capture only
    # holds 2 * camera_m of ground, so anything past that is outside the frame entirely.
    if args.extent_m:
        half_ns = half_ew = args.extent_m / 2.0
        if args.extent_m > 2.0 * args.camera_m:
            print(f"--extent-m {args.extent_m:.0f} exceeds the {2*args.camera_m:.0f} m the "
                  f"capture covers; clamping", file=sys.stderr)
            half_ns = half_ew = args.camera_m

    # +X North is up in the capture (yaw 0, pitch -90), so north-south maps to image Y.
    half_x_px = half_ns * px_per_m
    half_y_px = half_ew * px_per_m
    box = (round(cx - half_y_px), round(cy - half_x_px),
           round(cx + half_y_px), round(cy + half_x_px))
    crop = img.crop(box).convert("RGB")

    docs = repo / "docs"
    out = docs / f"overhead_ue{args.suffix}.png"
    crop.save(out)
    print(f"cropped {img.width}x{img.height} -> {crop.width}x{crop.height} "
          f"({2*half_ns:.0f} x {2*half_ew:.0f} m at {px_per_m:.2f} px/m) -> {out}")

    # The OSM panel, matched to the same ground extent AND the same pixels per metre.
    #
    # render_overhead.py draws onto a square canvas covering +/- max(half_ns, half_ew) on
    # both axes, so it shows slightly more east-west than the capture does. Rasterise it at
    # the capture's scale and take the same centred window, or the two panels sit at
    # different scales and the comparison quietly misleads.
    osm_svg = docs / f"overhead_osm{args.suffix}.svg"
    if osm_svg.is_file():
        square_m = 2.0 * max(half_ns, half_ew)
        square_px = round(square_m * px_per_m)
        tmp_png = docs / "_osm_square.png"
        if rasterise_svg(osm_svg, tmp_png, square_px):
            square = Image.open(tmp_png)
            left = round((square.width - crop.width) / 2.0)
            top = round((square.height - crop.height) / 2.0)
            square.crop((left, top, left + crop.width, top + crop.height)).save(
                docs / f"overhead_osm{args.suffix}.png")
            tmp_png.unlink()
            print(f"rasterised {osm_svg.name} at {square_px}px -> centred "
                  f"{crop.width}x{crop.height} window, same {px_per_m:.2f} px/m")
        else:
            print("could not rasterise the OSM SVG; the report can reference the SVG",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
