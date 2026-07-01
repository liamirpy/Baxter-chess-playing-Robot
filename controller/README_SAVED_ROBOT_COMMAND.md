# Chess Kinect + Baxter Saved Robot Command Package

This package uses the simpler and safer design:

1. Human finishes a move.
2. The bridge sends `POST /move-done` to the Kinect controller.
3. The Kinect controller detects the human move.
4. FastAPI/Stockfish returns the pending robot move.
5. The controller immediately builds and saves the Baxter command while the board state is correct.
6. `GET /status` returns the saved robot command fields.
7. The Baxter bridge runs the saved command.

This avoids rebuilding the robot command later from a changed board state.

## Run the Docker controller

```bash
cd chess_kinect_baxter_saved_command_project

docker compose up -d api

xhost +local:docker
docker compose --profile kinect run --rm --service-ports controller
```

If you use sudo Docker:

```bash
xhost +local:root
sudo DISPLAY=$DISPLAY docker compose --profile kinect run --rm --service-ports controller
```

## Check status

```bash
curl -s http://127.0.0.1:8765/status | python3 -m json.tool
```

After a human move is accepted, status should include fields like:

```json
"expected_stockfish_move": "g8f6",
"robot_move": "g8f6",
"robot_from_square": "g8",
"robot_to_square": "f6",
"robot_piece": "knight",
"robot_capture": false,
"robot_ros_command": "rosrun baxter_chess move_piece.py --limb left --from-square g8 --to-square f6 --piece knight"
```

If something is wrong, check:

```json
"robot_status_error"
```

## Run bridge in dry-run mode

```bash
python3 baxter_status_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP> \
  --dry-run
```

## Run bridge for real

```bash
python3 baxter_status_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP>
```

## Run with automatic robot verification

This runs Baxter, waits until the `rosrun` command finishes, then immediately sends another `/move-done` to verify the robot move.

```bash
python3 baxter_status_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP> \
  --auto-verify
```

There is no `--verify-delay`; Python waits until the Baxter command finishes.
