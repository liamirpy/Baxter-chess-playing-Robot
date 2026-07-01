#!/usr/bin/env bash
set -euo pipefail

# If the user mounted extra Python helper files in ./project_mount, make them importable.
export PYTHONPATH="/app:/app/project_mount:${PYTHONPATH:-}"

echo "Waiting for chess API at ${BASE_URL:-http://127.0.0.1:8000}..."
python3 - <<'PY'
import os
import sys
import time
import requests

base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
for attempt in range(60):
    try:
        response = requests.get(f"{base_url}/health", timeout=2)
        if response.ok:
            print("Chess API is ready.")
            sys.exit(0)
    except Exception:
        pass
    time.sleep(1)

print(f"ERROR: API did not become ready at {base_url}", file=sys.stderr)
sys.exit(1)
PY

exec python3 kinect_fastapi_physical_controller_with_signal.py
