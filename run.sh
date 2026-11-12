#!/usr/bin/env bash
# Start the TB-AMR Agent Team on a Mac or Linux machine.
#   ./run.sh            offline demo, replay agents
#   ./run.sh live       real ENA data (Claude agents if ANTHROPIC_API_KEY is set)
# The API key can live in ~/.config/tbamr/anthropic_key (chmod 600) instead of your shell profile,
# so it is only loaded for this app. An ANTHROPIC_API_KEY already in the environment wins.
set -euo pipefail
cd "$(dirname "$0")/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
KEY_FILE="${TBAMR_KEY_FILE:-$HOME/.config/tbamr/anthropic_key}"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -r "$KEY_FILE" ]; then
  ANTHROPIC_API_KEY="$(tr -d '[:space:]' < "$KEY_FILE")"; export ANTHROPIC_API_KEY
fi
export TBAMR_DATA="${1:-demo}"
echo "Data: $TBAMR_DATA · Brain: ${TBAMR_BRAIN:-$( [ -n "${ANTHROPIC_API_KEY:-}" ] && echo claude || echo replay )}"
echo "Open http://localhost:8000"
exec ./.venv/bin/uvicorn tbamr.api:app --port 8000
