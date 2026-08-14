"""Stage 1: fetch raw OSM data for a bbox from the Overpass API."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .config import AreaConfig, OVERPASS_ENDPOINTS

USER_AGENT = "osm2pcg/0.1 (UE PCG city reconstruction; contact: local dev)"


def build_query(area: AreaConfig) -> str:
    """Overpass QL: buildings, roads, water and parks inside the bbox."""
    s, w, n, e = area.bbox
    bbox = f"{s},{w},{n},{e}"
    return f"""
[out:json][timeout:180];
(
  way["building"]({bbox});
  relation["building"]["type"="multipolygon"]({bbox});
  way["building:part"]({bbox});
  way["highway"]({bbox});
  way["natural"="water"]({bbox});
  way["waterway"="riverbank"]({bbox});
  way["leisure"~"^(park|garden|pitch)$"]({bbox});
  way["landuse"~"^(grass|forest|meadow|recreation_ground)$"]({bbox});
);
out geom;
""".strip()


def fetch(area: AreaConfig, out_path: Path, force: bool = False) -> dict:
    """Download raw Overpass JSON, caching to out_path."""
    if out_path.exists() and not force:
        print(f"[fetch] cache hit: {out_path}")
        return json.loads(out_path.read_text())

    query = build_query(area)
    last_err: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            print(f"[fetch] POST {endpoint} bbox={area.bbox}")
            r = requests.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=300,
            )
            r.raise_for_status()
            payload = r.json()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload))
            print(f"[fetch] {len(payload.get('elements', []))} elements -> {out_path}")
            return payload
        except Exception as exc:  # noqa: BLE001 - try next mirror
            last_err = exc
            print(f"[fetch] {endpoint} failed: {exc}")
            time.sleep(2)
    raise RuntimeError(f"all Overpass endpoints failed: {last_err}")
