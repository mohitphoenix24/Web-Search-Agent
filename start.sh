#!/usr/bin/env bash
# Starts the agent backend (port 8000) and the React UI (port 5180).
# Open http://localhost:5180   ·   Ctrl+C stops both.
# First time? Run ./setup.sh
cd "$(dirname "$0")"

# Keep the .venv isolated: a PYTHONPATH set by ROS, conda etc. would leak
# other packages into it and can cause version clashes.
unset PYTHONPATH

if [ ! -x .venv/bin/uvicorn ] || [ ! -d frontend/node_modules ]; then
  echo "Looks like setup hasn't run yet. Run ./setup.sh first."
  exit 1
fi

.venv/bin/uvicorn server:app --port 8000 &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null' EXIT

cd frontend && npm run dev
