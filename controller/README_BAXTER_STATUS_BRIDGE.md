# Chess Kinect + Baxter Status Bridge

This package includes the full Docker project and a simple Baxter bridge.

## Main idea

The Kinect controller detects the human move. After Stockfish chooses the robot move, `GET /status` now returns ready-to-run Baxter command information:

```json
{
  "robot_move": "d8e7",
  "robot_from_square": "d8",
  "robot_to_square": "e7",
  "robot_piece": "queen",
  "robot_capture": true,
  "robot_captured_piece": "pawn",
  "robot_ros_args": [
    "--limb", "left",
    "--from-square", "d8",
    "--to-square", "e7",
    "--piece", "queen",
    "--capture",
    "--captured-piece", "pawn"
  ],
  "robot_ros_command": "rosrun baxter_chess move_piece.py --limb left --from-square d8 --to-square e7 --piece queen --capture --captured-piece pawn"
}
```

The Baxter bridge only reads those fields and runs the command. It does not use the camera or calculate chess logic.

## Run the API

```bash
cd chess_kinect_baxter_status_project
docker compose up -d api
```

Open:

```text
http://127.0.0.1:8000/viewer
```

## Run the Kinect controller

Without sudo:

```bash
xhost +local:docker
docker compose --profile kinect run --rm --service-ports controller
```

With sudo:

```bash
xhost +local:root
sudo DISPLAY=$DISPLAY docker compose --profile kinect run --rm --service-ports controller
```

## Human color

Default is:

```bash
HUMAN_COLOR=black
```

That means Baxter/Stockfish plays white first.

To make human white:

```bash
HUMAN_COLOR=white docker compose --profile kinect run --rm --service-ports controller
```

## Locked empty-board workflow

1. Put empty board under Kinect.
2. Press Enter or call `POST /move-done`.
3. Corners are detected and locked.
4. Put the chess pieces on the board.
5. Press Enter or call `POST /move-done` again.
6. Initial board + pieces baseline is saved.
7. Play normally.

## Check controller status

```bash
curl -s http://127.0.0.1:8765/status | python3 -m json.tool
```

After the human move is detected, look for:

```json
"robot_ros_commands"
```

## Run Baxter bridge in dry-run mode

Run this on the ROS/Baxter PC:

```bash
python3 baxter_status_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP> \
  --dry-run
```

If the Kinect controller is on another PC, replace `127.0.0.1` with that PC's IP:

```bash
--control-url http://KINECT_PC_IP:8765
```

## Run Baxter bridge for real

```bash
python3 baxter_status_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP>
```

## Auto verify robot move

The script waits until `rosrun baxter_chess move_piece.py` finishes. Then, if you pass `--auto-verify`, it immediately sends another `/move-done` to verify the robot move.

```bash
python3 baxter_status_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP> \
  --auto-verify
```

No `--verify-delay` is used. Python already waits for the Baxter command to finish.

## Baxter setup mode

Default command setup line is:

```bash
source ./baxter.sh
```

If your setup needs the exact executed form:

```bash
./baxter.sh
```

run:

```bash
python3 baxter_status_bridge.py --execute-baxter-sh
```

## Install bridge dependency

On the ROS/Baxter PC:

```bash
pip3 install requests
```
