"""Resolve OSM `building` outlines against their `building:part` volumes.

OSM's Simple 3D Buildings scheme lets a building carry `building:part` polygons that
describe its actual massing (setbacks, towers, wings). The parent `building` outline is
then only a footprint envelope: extruding both the parent *and* its parts produces
double geometry and turns small ornamental parts into free-standing needles.

Rule applied here, per the spec:
  * a parent whose footprint is substantially covered by its parts is dropped - the
    parts already describe the volume;
  * a parent with no (or negligible) parts is kept and its stray parts dropped;
  * parts below a minimum area are dropped as ornaments regardless.

https://wiki.openstreetmap.org/wiki/Simple_3D_Buildings
"""
from __future__ import annotations

from typing import Any, Sequence

from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

# A parent is superseded once its parts cover this fraction of its footprint.
PART_COVERAGE_THRESHOLD = 0.55
# Parts smaller than this are ornaments (spires, vents, parapet details), not massing.
MIN_PART_AREA_M2 = 40.0


def resolve(records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter a list of records that each carry `poly` (shapely) and `is_part` (bool).

    Returns (kept records, stats) and never mutates the inputs.
    """
    parents = [r for r in records if not r["is_part"]]
    parts = [r for r in records if r["is_part"]]

    stats = {
        "parents_in": len(parents),
        "parts_in": len(parts),
        "parts_dropped_small": 0,
        "parents_dropped_superseded": 0,
        "parts_dropped_orphan": 0,
    }

    kept_parts = []
    for part in parts:
        if part["poly"].area < MIN_PART_AREA_M2:
            stats["parts_dropped_small"] += 1
        else:
            kept_parts.append(part)

    if not kept_parts:
        return parents, stats

    tree = STRtree([p["poly"] for p in kept_parts])
    part_used = [False] * len(kept_parts)
    kept_parents: list[dict[str, Any]] = []

    for parent in parents:
        poly: Polygon = parent["poly"]
        candidates = [int(i) for i in tree.query(poly)]
        overlaps = []
        for i in candidates:
            inter = kept_parts[i]["poly"].intersection(poly)
            # Require a real overlap, not a shared edge with the neighbour next door.
            if not inter.is_empty and inter.area > 0.25 * kept_parts[i]["poly"].area:
                overlaps.append(i)

        if not overlaps:
            kept_parents.append(parent)
            continue

        covered = unary_union([kept_parts[i]["poly"] for i in overlaps]).intersection(poly).area
        if poly.area > 0 and covered / poly.area >= PART_COVERAGE_THRESHOLD:
            # Parts describe this building's massing; the envelope would double it.
            stats["parents_dropped_superseded"] += 1
            for i in overlaps:
                part_used[i] = True
        else:
            # Sparse parts: trust the parent envelope and discard the fragments.
            kept_parents.append(parent)

    final_parts = []
    for i, part in enumerate(kept_parts):
        if part_used[i]:
            final_parts.append(part)
        else:
            stats["parts_dropped_orphan"] += 1

    stats["kept"] = len(kept_parents) + len(final_parts)
    return kept_parents + final_parts, stats
