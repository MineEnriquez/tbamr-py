#!/usr/bin/env bash
# Start the TB-AMR Agent Team on a Mac or Linux machine.
#   ./run.sh            offline demo, replay agents
#   ./run.sh live       real ENA data (Claude agents if ANTHROPIC_API_KEY is set)
set -euo pipefail
cd "$(dirname "$0")/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
export TBAMR_DATA="${1:-demo}"
echo "Data: $TBAMR_DATA · Brain: ${TBAMR_BRAIN:-$( [ -n "${ANTHROPIC_API_KEY:-}" ] && echo claude || echo replay )}"
echo "Open http://localhost:8000"
exec ./.venv/bin/uvicorn tbamr.api:app --port 8000
