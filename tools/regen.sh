#!/usr/bin/env bash
# Full reproducible run: translate OSM -> rebuild the UE level.
#   tools/regen.sh [area]        e.g. tools/regen.sh midtown
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AREA="${1:-midtown}"

"$REPO_ROOT/pipeline/.venv/bin/osm2pcg" --area "$AREA"
# The PCG graph / builder reads Content/Data/city.json.
cp "$REPO_ROOT/data/out/$AREA/city.json" "$REPO_ROOT/UnrealProject/Content/Data/city.json"
"$REPO_ROOT/tools/build_ue.sh"
"$REPO_ROOT/tools/ue_run.sh" UnrealProject/Scripts/build_pcg_graph.py
"$REPO_ROOT/tools/ue_run.sh" UnrealProject/Scripts/bootstrap_city_level.py
