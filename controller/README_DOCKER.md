# Docker setup for the Stockfish FastAPI chess API + Kinect controller

This folder contains a Docker setup for:

- `api.py` — FastAPI chess server using Stockfish.
- `kinect_fastapi_physical_controller_with_signal.py` — optional Kinect physical controller.

The API server is the easy part. The Kinect controller needs real USB hardware, X11 display access, and the local helper modules used by your controller code.

## 1. Put all required Python files in this folder

At minimum you need:

```text
api.py
kinect_fastapi_physical_controller_with_signal.py
Dockerfile
docker-compose.yml
requirements.txt
scripts/start-api.sh
scripts/start-controller.sh
```

Your controller also imports these local files, so they must be in the same folder before building/running:

```text
kinect_board_camera.py
kinect_live_legal_move_compare.py
```

If those files are missing, the API container will still work, but the Kinect controller will fail with `ModuleNotFoundError`.

## 2. Run only the FastAPI + Stockfish API

```bash
docker compose up --build api
```

Open:

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/viewer
```

Test health:

```bash
curl http://127.0.0.1:8000/health
```

## 3. Run the Kinect controller too

On Linux/X11, allow Docker to open GUI windows:

```bash
xhost +local:docker
```

Then run:

```bash
docker compose --profile kinect up --build
```

The controller exposes its local control API on:

```text
http://127.0.0.1:8765/health
http://127.0.0.1:8765/status
```

Trigger a capture from another terminal:

```bash
curl -X POST http://127.0.0.1:8765/capture
```

## 4. Run controller interactively only

If you want to run the API first and then attach the controller interactively:

```bash
docker compose up --build -d api
xhost +local:docker
docker compose --profile kinect run --rm controller
```

## 5. Environment variables

The Docker version patches your original hard-coded paths into environment variables:

```text
STOCKFISH_PATH=/usr/games/stockfish
BASE_URL=http://api:8000
VIEWER_BASE_URL=http://127.0.0.1:8000
LIB_DIR=/usr/lib/x86_64-linux-gnu
OUTPUT_DIR=/app/captures_fastapi_physical
BOARD_SIZE=800
BOARD_IMAGE_ROTATION=cw
USE_HIGH_QUALITY=true
SHOW_HELP_TEXT_DEFAULT=true
CONTROL_API_HOST=0.0.0.0
CONTROL_API_PORT=8765
CONTROL_API_TOKEN=
DIFFICULTY=M
THINK_TIME=0.5
```

`DIFFICULTY` and `THINK_TIME` are optional. If you do not set them, the controller asks you interactively.

## 6. Important Kinect notes

Kinect inside Docker usually requires:

- Linux host, not macOS/Windows Docker Desktop.
- USB device mapping: `/dev/bus/usb:/dev/bus/usb`.
- `privileged: true` or specific USB permissions.
- X11 display mount: `/tmp/.X11-unix:/tmp/.X11-unix`.
- Your helper files `kinect_board_camera.py` and `kinect_live_legal_move_compare.py`.

If the camera is not detected, first test it on the host outside Docker, then check USB permissions.


---

See `README_EMPTY_BOARD_LOCKED.md` for the new empty-board calibration workflow.
