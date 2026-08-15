"""Tool handler for the osm plugin. Returns a JSON string.

One tool only, deliberately. Fetching, inspecting and running are things the agent
writes into its own pipeline (see the osm:fetching, osm:inspection and
osm:pipeline-shape skills); handing them over as tools produced pipelines that could not
run without the tool that fed them.

Verification stays a tool because it must not be the agent's own code: it re-derives the
scene from the raw OSM extract rather than trusting the pipeline's manifest, so it
catches a pipeline that is confidently wrong.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plugins.osm.verify_scene import verify_scene


def _fail(message: str, **extra: Any) -> str:
    return json.dumps({"success": False, "error": message, **extra})


def osm_verify_scene(area: str | None = None,
                     scene: str | None = None,
                     repo: str | None = None,
                     raw_dir: str | None = None,
                     **kwargs) -> str:
    del kwargs
    root = Path(repo) if repo else Path(__file__).resolve().parents[3]
    if not area and not scene:
        return _fail("name an area (or pass scene=<path to scene.json>)")
    path = Path(scene) if scene else root / "data" / "ue" / area / "scene.json"
    if not path.is_file():
        return _fail(f"no scene.json at {path}",
                     hint="Run the area's pipeline first: "
                          f"python3 agent_scripts/{area or '<area>'}/pipeline.py "
                          f"--area {area or '<area>'}")
    try:
        report = verify_scene(path, area or path.parent.name,
                              Path(raw_dir) if raw_dir else None)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return _fail(f"{type(exc).__name__}: {exc}")
    return json.dumps({"success": True, **report})
