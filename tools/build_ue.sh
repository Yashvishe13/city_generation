#!/usr/bin/env bash
# Compile the CityGen editor module.
set -euo pipefail
UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.7}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$UE_ROOT/Engine/Build/BatchFiles/Mac/Build.sh" \
  "${1:-CityGenEditor}" Mac "${2:-Development}" \
  -project="$REPO_ROOT/UnrealProject/CityGen.uproject"
