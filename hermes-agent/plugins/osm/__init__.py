"""osm - the contract an OSM->Unreal pipeline is written against, plus one verifier.

Almost everything this plugin offers is a *skill*, not a tool. Fetching an area,
measuring its tagging, and running the translation are things the agent writes into
`agent_scripts/<area>/pipeline.py` itself; the skills carry the knowledge those steps
need. Handing them over as tools instead produced a pipeline that could not run without
the tool that had already fetched for it, and that hardcoded the author's checkout path
because a tool had resolved it.

The single tool left, `osm_verify_scene`, exists because it must NOT be the agent's own
code: it re-derives the scene from the raw OSM extract rather than trusting the
pipeline's manifest, which is what catches a pipeline that is confidently wrong.
"""
from __future__ import annotations

from pathlib import Path

from plugins.osm.tools import osm_verify_scene

VERIFY_SCHEMA = {
    "name": "osm_verify_scene",
    "description": (
        "Check a generated scene.json against the contract AND against the original OSM "
        "extract, and report what is wrong. Re-derives independently from the source - "
        "reprojecting sample vertices, recomputing road bearings from lon/lat, counting "
        "source features - so it catches a pipeline that is confidently wrong, which "
        "reading the pipeline's own manifest cannot. Checks ring winding and shape, "
        "height above base, mesh index ranges, ribbon validity, projection accuracy, "
        "orientation, coverage and provenance labelling. Advisory: it reports findings "
        "with the offending node ids and a fix hint for each, so call it after producing "
        "a scene and fix what it reports before handing the data to the engine."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "area": {
                "type": "string",
                "description": "Area to verify, e.g. 'nyc_midtown'.",
            },
            "scene": {
                "type": "string",
                "description": "Path to a scene.json, instead of an area name.",
            },
            "raw_dir": {
                "type": "string",
                "description": "Directory holding the fetched source extract. Defaults to "
                               "the project's data/raw.",
            },
            "repo": {
                "type": "string",
                "description": "Project root, if not the default checkout.",
            },
        },
        "required": [],
    },
}

TOOLSET = "osm"


SKILLS_DIR = Path(__file__).resolve().parent / "skills"

# Explicit list, not a directory scan: a skill is only reachable if it is named here AND
# named verbatim in the task prompt. Plugin skills do not appear in the system prompt's
# <available_skills> index - they are opt-in loads, not always-on prompt weight - so a
# skill dropped from this tuple fails silently rather than loudly.
SKILLS = (
    "pipeline-plan",     # load first: how to plan, and what has gone wrong before
    "pipeline-shape",    # what the artifact must be: one file, no absolute paths
    "scene-contract",    # what Unreal reads
    "coordinates",       # WGS84 -> Unreal frame
    "fetching",          # writing the Overpass download yourself
    "inspection",        # measuring the area before interpreting it
    "roads",             # cross-section, the pedestrian realm, junctions
    "ground-cover",      # water, parks, landuse, and where the ground plane is
    "estimation",        # deriving what OSM does not state
)


def register(ctx) -> None:
    """Called by the Hermes plugin loader at startup."""
    for skill in SKILLS:
        skill_file = SKILLS_DIR / skill / "SKILL.md"
        if skill_file.is_file():
            ctx.register_skill(name=skill, path=skill_file)
    ctx.register_tool(
        name="osm_verify_scene",
        toolset=TOOLSET,
        schema=VERIFY_SCHEMA,
        handler=lambda params, **kw: osm_verify_scene(**params),
    )
