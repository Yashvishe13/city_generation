# docs/agent-prompts/

The prompts fed to the coding agent, kept so that any generated artifact can be traced
back to the brief that produced it.

**Only `task_pipeline_nyc_midtown.txt` is current.** Everything else is an archive of an
earlier round and will not run as written: those prompts name analysis tools
(`osm_fetch_area`, `osm_list_areas`, `osm_tag_stats`, `osm_quality_check`,
`osm_run_pipeline`) that no longer exist, and target a `scripts/convert_to_ue.py` layout
that no longer exists either. They are kept because the failures they document — and the
fix rounds that followed — are why the skills say what they say.

| Prompt | Round |
|---|---|
| `task_pipeline_nyc_midtown.txt` | **current** — skills-only harness, self-contained pipeline |
| `pipeline_v2_thin_brief.txt`, `pipeline_v2_fix_round.txt`, `pipeline_fix_rings.txt` | gen 2 — skill-driven, `agent_scripts/<area>/pipeline.py`, verifier fix rounds |
| `pipeline_step1_analyse_and_extrudes.txt`, `pipeline_step2_roads_and_roofs.txt` | gen 2 — the split into steps, because one call outlasted the upstream timeout |
| `task_buildings.txt`, `task_roads.txt`, `task_roofs.txt`, `task_estimators.txt`, `task_est_h.txt` | gen 1 — hand-decomposed tasks writing `scripts/convert_to_ue.py` |

Run one with `tools/agent_task.sh <prompt-file> --expect <artifact> --verify-cmd <cmd>`.
