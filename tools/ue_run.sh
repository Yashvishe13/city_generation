#!/usr/bin/env bash
# Run a UE editor Python script headlessly against the CityGen project.
#   tools/ue_run.sh UnrealProject/Scripts/bootstrap_city_level.py
set -euo pipefail

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.7}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${PROJECT:-$REPO_ROOT/UnrealProject/CityGen.uproject}"
EDITOR="$UE_ROOT/Engine/Binaries/Mac/UnrealEditor-Cmd"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <script.py> [extra UE args...]" >&2
  exit 2
fi

SCRIPT="$1"; shift
[[ "$SCRIPT" = /* ]] || SCRIPT="$REPO_ROOT/$SCRIPT"

exec "$EDITOR" "$PROJECT" \
  -run=pythonscript -script="$SCRIPT" \
  -unattended -nosplash -nosound -NullRHI -stdout -FullStdOutLogOutput "$@"
