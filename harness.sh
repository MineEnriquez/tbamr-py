#!/usr/bin/env bash
# UI harness: seed a demo pipeline through every stage and boot uvicorn against it, so UI changes
# can be iterated on without running Docker + TB-Profiler every time.
#
#   ./harness.sh                 seed if missing, then serve
#   ./harness.sh seed            just (re)seed the DB
#   ./harness.sh serve           seed if missing, then serve
#   ./harness.sh --reseed        wipe tbamr-harness.db and reseed before serving
#
# Pass any trailing args through to `python -m tbamr.harness`, e.g.:
#   ./harness.sh serve --reseed --port 8001
set -euo pipefail
cd "$(dirname "$0")/backend"

cmd="serve"
extra=()
for a in "$@"; do
  case "$a" in
    seed|serve) cmd="$a" ;;
    *) extra+=("$a") ;;
  esac
done

exec ./.venv/bin/python -m tbamr.harness "$cmd" ${extra[@]+"${extra[@]}"}
