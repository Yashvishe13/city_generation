#!/usr/bin/env bash
# Stage a translated area into the UE project's area-neutral data slot.
#   tools/stage_area.sh [area]      default: whatever --area the converter defaults to
#
# The UE side never names an area: it reads Content/Data/City. Switching city is a
# re-translate plus a re-stage, with no C++ or asset edits.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AREA="${1:-nyc_midtown}"
PYTHON="$("$REPO_ROOT/tools/find_python.sh")" || exit 2
SRC="$REPO_ROOT/data/ue/$AREA"
DEST="$REPO_ROOT/UnrealProject/Content/Data/City"

[[ -f "$SRC/scene.json" ]] || {
  echo "no scene at $SRC/scene.json (run agent_scripts/$AREA/pipeline.py --area $AREA)" >&2
  exit 1
}
mkdir -p "$DEST"
rm -f "$DEST"/*.json
cp "$SRC"/*.json "$DEST"/
echo "staged $AREA -> Content/Data/City"
# The manifest lives inside scene.json; report what the engine will actually read.
"$PYTHON" -c '
import json, sys
scene = json.load(open(sys.argv[1]))
manifest = scene.get("manifest", {})
kinds = {}
for node in scene.get("nodes", []):
    kinds[node.get("kind")] = kinds.get(node.get("kind"), 0) + 1
origin = manifest.get("origin", {})
print("  area  ", manifest.get("area"))
print("  origin", origin.get("lat"), origin.get("lon"))
print("  nodes ", kinds)
' "$DEST/scene.json"
