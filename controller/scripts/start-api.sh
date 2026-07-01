#!/usr/bin/env bash
set -euo pipefail

echo "Starting Stockfish Chess FastAPI server..."
echo "STOCKFISH_PATH=${STOCKFISH_PATH:-/usr/games/stockfish}"

if [ ! -x "${STOCKFISH_PATH:-/usr/games/stockfish}" ]; then
  echo "ERROR: Stockfish binary not found or not executable at: ${STOCKFISH_PATH:-/usr/games/stockfish}" >&2
  echo "Inside the container, try: which stockfish" >&2
  exit 1
fi

exec uvicorn api:app --host 0.0.0.0 --port 8000
