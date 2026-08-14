"""Optional overhead preview PNG of the translated scene (matplotlib).

Used as the "generated data" half of the report's side-by-side comparison and as
a fast sanity check that projection/orientation are right before opening UE.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def render(scene: dict[str, Any], path: Path, title: str = "") -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection, PolyCollection
    except ImportError:
        print("[preview] matplotlib not installed - skipping (pip install matplotlib)")
        return None

    fig, ax = plt.subplots(figsize=(10, 10), dpi=120)
    ax.set_facecolor("#f2efe9")

    if scene.get("green"):
        ax.add_collection(PolyCollection(
            [a["outline"] for a in scene["green"] if len(a["outline"]) >= 3],
            facecolors="#c8e6a0", edgecolors="none", zorder=1,
        ))
    if scene.get("water"):
        ax.add_collection(PolyCollection(
            [a["outline"] for a in scene["water"] if len(a["outline"]) >= 3],
            facecolors="#aad3df", edgecolors="none", zorder=2,
        ))

    if scene.get("roads"):
        # Width in points scaled roughly to real width for visual comparison.
        segs, widths = [], []
        for r in scene["roads"]:
            if len(r["points"]) >= 2:
                segs.append(r["points"])
                widths.append(max(0.6, r["width_cm"] / 100.0 * 0.35))
        ax.add_collection(LineCollection(
            segs, colors="#8f8f8f", linewidths=widths, zorder=3,
        ))

    if scene.get("buildings"):
        tallest = max((b["height_cm"] for b in scene["buildings"]), default=1.0) or 1.0
        polys, colors = [], []
        for b in scene["buildings"]:
            if len(b["outline"]) < 3:
                continue
            polys.append(b["outline"])
            t = min(1.0, b["height_cm"] / tallest)
            # dark = tall, light = short
            colors.append((0.75 - 0.55 * t, 0.72 - 0.55 * t, 0.70 - 0.50 * t))
        ax.add_collection(PolyCollection(
            polys, facecolors=colors, edgecolors="#5a5a5a", linewidths=0.3, zorder=4,
        ))

    ax.autoscale_view()
    ax.set_aspect("equal")
    # UE X = North -> vertical axis, UE Y = East -> horizontal axis (north up).
    ax.set_xlabel("UE Y / East (cm)")
    ax.set_ylabel("UE X / North (cm)")
    ax.set_title(title or "Translated scene (overhead, north up)")
    # Swap axes so north is up: plot expects (x=Y_ue, y=X_ue); collections were
    # built as (X_ue, Y_ue), so transpose by flipping the data limits instead.
    _transpose_collections(ax)
    ax.autoscale_view()

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"[preview] {path}")
    return path


def _transpose_collections(ax) -> None:
    """Swap (X,Y) of every collection so UE North points up on screen."""
    for coll in ax.collections:
        if hasattr(coll, "get_paths"):
            for p in coll.get_paths():
                p.vertices = p.vertices[:, ::-1]
    ax.relim()
