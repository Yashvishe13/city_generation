#!/usr/bin/env bash
# Run a coding task on the Hermes agent, retrying the failures that are the provider's
# fault rather than the task's.
#
#   tools/agent_task.sh <prompt-file> [--reasoning LEVEL] [--attempts N] [--area NAME]
#
# grok-4.6 behind xAI's gateway drops the connection when its thinking phase outlasts the
# proxy's idle timeout, before a single content token arrives:
#
#   API call failed after 3 retries: [Errno 32] Broken pipe
#   The model's thinking phase exceeded the upstream proxy's idle timeout
#
# Hermes already retries inside the call; those retries fail the same way, because the
# whole thinking phase re-runs and re-exceeds the same cap. Raising
# providers.xai.models.grok-4.6.stale_timeout_seconds to 900 did not help either — the
# upstream cap is shorter than that. What does work is starting the call over and, if it
# keeps happening, asking for less thinking. So: retry here, and step the reasoning effort
# down on each attempt.
#
# The task itself is unchanged between attempts, so a retry is not a different request —
# only a fresh connection.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES="$REPO_ROOT/hermes-agent/.venv/bin/hermes"
PROFILE="${HERMES_PROFILE:-citygen}"

PROMPT_FILE=""
REASONING="medium"
ATTEMPTS=3
SESSION=""            # --session NAME keeps context across steps of one build
EXPECT=()             # --expect PATH: artifacts that must exist AND be freshly written
VERIFY_CMD=""         # --verify-cmd CMD: must exit 0, or the run is rejected
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reasoning) REASONING="$2"; shift 2 ;;
    --attempts)  ATTEMPTS="$2"; shift 2 ;;
    --session)   SESSION="$2"; shift 2 ;;
    --expect)    EXPECT+=("$2"); shift 2 ;;
    --verify-cmd) VERIFY_CMD="$2"; shift 2 ;;
    --) shift; EXTRA+=("$@"); break ;;
    *) if [[ -z "$PROMPT_FILE" ]]; then PROMPT_FILE="$1"; else EXTRA+=("$1"); fi; shift ;;
  esac
done

[[ -f "$PROMPT_FILE" ]] || { echo "usage: $0 <prompt-file> [--reasoning LEVEL] [--attempts N]" >&2; exit 2; }
[[ -x "$HERMES" ]] || { echo "hermes not found at $HERMES (run uv sync in hermes-agent/)" >&2; exit 2; }

# A long build has to be split into steps, because one call that fetches, analyses,
# fits and writes an entire pipeline reliably outlasts the upstream cap. --session keeps
# the steps in one conversation, so step 2 still knows what step 1 measured, and a retry
# resumes rather than restarting the analysis from nothing.
SESSION_ARGS=()
[[ -n "$SESSION" ]] && SESSION_ARGS=(--continue "$SESSION")   # creates it on first use

# An agent has claimed completed work twice in this project without touching a file, once
# quoting a verifier result it never obtained. So nothing here trusts the report: artifacts
# must be NEWER than the run that supposedly wrote them, and the verification command is
# executed here rather than believed.
START_MARKER="$(mktemp)"

# Effort ladder: each retry thinks less, which is what actually gets under the cap.
ladder=("$REASONING" "medium" "low")
timeout_signature='Broken pipe|thinking phase exceeded|upstream proxy|stale_timeout'

for attempt in $(seq 1 "$ATTEMPTS"); do
  effort="${ladder[$((attempt - 1))]:-low}"
  echo "[agent] attempt $attempt/$ATTEMPTS (reasoning=$effort): $(basename "$PROMPT_FILE")" >&2

  output="$("$HERMES" -p "$PROFILE" --in "$REPO_ROOT" --yolo --reasoning "$effort" \
            "${SESSION_ARGS[@]+"${SESSION_ARGS[@]}"}" \
            -z "$(cat "$PROMPT_FILE")" "${EXTRA[@]+"${EXTRA[@]}"}" 2>&1)"
  status=$?

  if [[ $status -eq 0 ]] && ! grep -qE "$timeout_signature" <<<"$output"; then
    # An agent can report work it did not do. Reports are cheap; artifacts are not, so
    # trust the filesystem instead of the summary.
    missing=()
    for path in ${EXPECT[@]+"${EXPECT[@]}"}; do
      full="$REPO_ROOT/$path"; [[ -e "$full" ]] || full="$path"
      if [[ ! -s "$full" ]]; then
        missing+=("$path (does not exist)")
      elif [[ ! "$full" -nt "$START_MARKER" ]]; then
        missing+=("$path (not modified by this run)")
      fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
      echo "[agent] REPORT REJECTED - claimed completion but these do not exist:" >&2
      printf '[agent]   %s\n' "${missing[@]}" >&2
      if [[ $attempt -lt $ATTEMPTS ]]; then
        echo "[agent] retrying with an explicit demand for the missing artifacts" >&2
        PROMPT_FILE_ORIG="${PROMPT_FILE_ORIG:-$PROMPT_FILE}"
        RETRY_PROMPT="$(mktemp)"
        {
          cat "$PROMPT_FILE_ORIG"
          echo
          echo "PREVIOUS ATTEMPT PRODUCED NO FILES. These paths do not exist:"
          printf '  %s\n' "${missing[@]}"
          echo "Write them to disk. Do not describe work you have not done."
        } > "$RETRY_PROMPT"
        PROMPT_FILE="$RETRY_PROMPT"
        continue
      fi
      printf '%s\n' "$output"
      exit 1
    fi
    if [[ -n "$VERIFY_CMD" ]]; then
      echo "[agent] running verification: $VERIFY_CMD" >&2
      if ! verify_output="$(cd "$REPO_ROOT" && eval "$VERIFY_CMD" 2>&1)"; then
        echo "[agent] VERIFICATION FAILED - the report is not accepted" >&2
        if [[ $attempt -lt $ATTEMPTS ]]; then
          PROMPT_FILE_ORIG="${PROMPT_FILE_ORIG:-$PROMPT_FILE}"
          RETRY_PROMPT="$(mktemp)"
          {
            cat "$PROMPT_FILE_ORIG"
            echo
            echo "YOUR PREVIOUS ATTEMPT DID NOT PASS VERIFICATION. Output:"
            echo "$verify_output"
            echo
            echo "Fix the code and run it again. Do not report success you have not achieved."
          } > "$RETRY_PROMPT"
          PROMPT_FILE="$RETRY_PROMPT"
          touch "$START_MARKER"
          continue
        fi
        printf '%s\n' "$output"
        printf '\n[verification output]\n%s\n' "$verify_output"
        exit 1
      fi
      echo "[agent] verification passed" >&2
    fi
    printf '%s\n' "$output"
    exit 0
  fi

  if grep -qE "$timeout_signature" <<<"$output"; then
    echo "[agent] upstream timeout — provider dropped the call, not a task failure" >&2
    backoff=$((attempt * 15))
    if [[ $attempt -lt $ATTEMPTS ]]; then
      echo "[agent] retrying in ${backoff}s with lower reasoning effort" >&2
      sleep "$backoff"
      continue
    fi
  else
    # A real task failure: report it and stop, since retrying will not fix the task.
    printf '%s\n' "$output"
    exit "$status"
  fi
done

echo "[agent] gave up after $ATTEMPTS attempts; last output follows" >&2
printf '%s\n' "$output"
exit 1
