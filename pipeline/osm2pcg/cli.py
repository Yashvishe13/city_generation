"""osm2pcg CLI: fetch -> parse -> project -> export, in one reproducible run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import export as export_mod
from . import fetch as fetch_mod
from . import parse as parse_mod
from . import preview as preview_mod
from .config import AREAS, DEFAULT_AREA, AreaConfig
from .project import build_frame

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW = REPO_ROOT / "data" / "raw"
DEFAULT_OUT = REPO_ROOT / "data" / "out"
DEFAULT_UE_DATA = REPO_ROOT / "UnrealProject" / "Content" / "Data"


def resolve_area(args: argparse.Namespace) -> AreaConfig:
    if args.bbox:
        s, w, n, e = args.bbox
        return AreaConfig(name=args.name or "custom", south=s, west=w, north=n, east=e,
                          note="custom bbox from CLI")
    if args.area not in AREAS:
        sys.exit(f"unknown area '{args.area}'. known: {', '.join(AREAS)}")
    return AREAS[args.area]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="osm2pcg",
        description="Translate an OpenStreetMap area into UE PCG-consumable data.",
    )
    ap.add_argument("--area", default=DEFAULT_AREA,
                    help=f"preset area name ({', '.join(AREAS)})")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("S", "W", "N", "E"),
                    help="custom bbox in WGS84 degrees, overrides --area")
    ap.add_argument("--name", help="name for a custom bbox")
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--ue-data-dir", type=Path, default=DEFAULT_UE_DATA,
                    help="mirror exports into the UE project (set to '' to skip)")
    ap.add_argument("--force-fetch", action="store_true",
                    help="ignore the cached Overpass response")
    ap.add_argument("--no-preview", action="store_true",
                    help="skip the matplotlib overhead PNG")
    args = ap.parse_args(argv)

    area = resolve_area(args)
    print(f"[run] area={area.name} bbox={area.bbox} origin={area.origin}")

    raw_path = args.raw_dir / f"osm_{area.name}.json"
    payload = fetch_mod.fetch(area, raw_path, force=args.force_fetch)

    features = parse_mod.parse_elements(payload, area)
    print(f"[parse] {parse_mod.summarize(features)}")

    export_mod.write_geojson(features, args.raw_dir / f"{area.name}.geojson")

    frame = build_frame(area)
    scene, part_stats = export_mod.translate(features, frame)

    out_dir = args.out_dir / area.name
    ue_dir = args.ue_data_dir if str(args.ue_data_dir) else None
    manifest = export_mod.write_all(
        scene, area, frame, out_dir, ue_data_dir=ue_dir, part_stats=part_stats)
    print("[run] manifest:\n" + json.dumps(manifest, indent=2))

    if not args.no_preview:
        preview_mod.render(
            scene,
            REPO_ROOT / "docs" / f"preview_{area.name}.png",
            title=f"{area.name} - translated OSM (overhead, north up)",
        )

    print("[run] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
