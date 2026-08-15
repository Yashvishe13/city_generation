#!/usr/bin/env bash
# Print a Python interpreter new enough to run this project's code (3.10+).
#
#   PYTHON="$("$(dirname "${BASH_SOURCE[0]}")/find_python.sh")" || exit 2
#
# Bare `python3` is not safe to assume: on the machine this was written on it resolves to
# a Python 3.5 framework build that dies with SIGKILL, while the working interpreter is
# /opt/homebrew/bin/python3. Hardcoding the Homebrew path is the other half of the same
# mistake - it is a machine path, and the whole point of this pass was to stop shipping
# those. So: honour $PYTHON, otherwise take the first candidate that reports 3.10+.
set -uo pipefail

usable() {
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    >/dev/null 2>&1
}

if [[ -n "${PYTHON:-}" ]]; then
  if usable "$PYTHON"; then echo "$PYTHON"; exit 0; fi
  echo "PYTHON=$PYTHON is not a working Python 3.10+" >&2
  exit 2
fi

for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if usable "$candidate"; then command -v "$candidate"; exit 0; fi
done

echo "no Python 3.10+ found on PATH; set PYTHON=/path/to/python3" >&2
exit 2
