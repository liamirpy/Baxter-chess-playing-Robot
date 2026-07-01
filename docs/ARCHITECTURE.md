# Architecture

## Components

### `ros/baxter_chess`

ROS package for Baxter motion. It contains:

- `calibrate_board.py` — stores board square calibration using a1, h1, and a8.
- `calibrate_home.py` — stores a safe home/rest pose after moves.
- `test_square.py` — moves above a square without picking.
- `move_piece.py` — executes pick/place and capture moves.
- `chess_board.py` — maps chess squares to calibrated robot poses.
- `baxter_motion.py` — Baxter IK, gripper, and motion helpers.

Calibration is stored under `~/.baxter_chess/board_<limb>.json` by default.

### `controller/api.py`

FastAPI chess service. It manages games, validates moves with `python-chess`, calls Stockfish, and exposes a browser viewer.

Main endpoints include:

- `GET /health`
- `GET /viewer`
- `POST /games`
- `GET /games/{game_id}`
- `POST /games/{game_id}/human-move`
- `POST /games/{game_id}/confirm-stockfish-move-physical`

### `controller/kinect_fastapi_physical_controller_with_signal.py`

Kinect/OpenCV physical-board controller. It captures board images, compares board states, infers legal human moves, sends them to the FastAPI chess service, and builds Baxter ROS command arguments.

Its local control API runs on port `8765` by default:

- `GET /health`
- `GET /status`
- `POST /capture`
- `POST /move-done`

### Bridge scripts

- `controller/baxter_status_bridge.py` reads `/status`, then runs `rosrun baxter_chess move_piece.py ...`.
- `controller/baxter_keyboard_bridge.py` is kept as a backward-compatible wrapper.
- `scripts/baxter_simple_terminal_loop.sh` is a shell-based bridge loop.

## Data flow

1. Human moves a physical chess piece.
2. Kinect controller captures the board after `/move-done` or Enter.
3. Controller detects the legal move and sends it to FastAPI.
4. FastAPI validates the move and asks Stockfish for the robot response.
5. Controller saves the generated Baxter ROS command while the board state is still correct.
6. Bridge script runs the saved ROS command.
7. Baxter moves the robot piece.
8. Optional verification checks the board again.
