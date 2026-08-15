#!/usr/bin/env bash
# Run the scene verifier for an area; exit non-zero if it reports errors.
#
# Used as `agent_task.sh --verify-cmd`, so whether a generation round is accepted depends
# on running the checks here, never on the agent's account of having run them.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AREA="${1:-nyc_midtown}"
PYTHON="$("$REPO_ROOT/tools/find_python.sh")" || exit 2

cd "$REPO_ROOT/hermes-agent" || exit 2

"$PYTHON" - "$AREA" <<'PY'
import json
import sys

sys.path.insert(0, ".")
import plugins.osm as osm


class Ctx:
    """Minimal plugin context: enough to collect the tools without a running agent."""

    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = handler

    def register_skill(self, **kwargs):
        pass


ctx = Ctx()
osm.register(ctx)

report = json.loads(ctx.tools["osm_verify_scene"]({"area": sys.argv[1]}))
if not report.get("success"):
    print("verifier could not run:", report.get("error"))
    raise SystemExit(2)

print(f"ok={report['ok']} errors={report['errors']} warnings={report['warnings']} "
      f"nodes={report['node_counts']}")
for check in report["checks"]:
    if check["status"] != "pass":
        print(f"  [{check['severity']}] {check['name']}: {check['detail']}")
        if check.get("hint"):
            print(f"      hint: {check['hint']}")

raise SystemExit(0 if report["ok"] else 1)
PY
