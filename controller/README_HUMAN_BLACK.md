# Human Black / Robot White mode

This version supports choosing the physical human side with `HUMAN_COLOR`.

Default:

```bash
HUMAN_COLOR=black
```

That means:

```text
Robot / Stockfish = White
Human = Black
```

## Workflow when human is Black

1. Start API and controller.
2. Put the EMPTY board under the Kinect.
3. Press ENTER or call `POST /move-done`.
   - The controller detects and locks board corners.
4. Put all pieces on the board.
5. Press ENTER or call `POST /move-done`.
   - The controller saves the initial board-with-pieces baseline.
   - Because human is Black, the API already has a pending first White robot move.
6. Move the robot's suggested White move physically.
7. Press ENTER or call `POST /move-done` to verify the robot move.
8. Human moves a Black piece.
9. Press ENTER or call `POST /move-done` to detect the human move and get the next robot move.

## Run

```bash
docker compose up -d api
xhost +local:docker
docker compose --profile kinect run --rm --service-ports controller
```

If using `sudo docker`:

```bash
xhost +local:root
sudo DISPLAY=$DISPLAY docker compose --profile kinect run --rm --service-ports controller
```

## Change back to human White

```bash
HUMAN_COLOR=white docker compose --profile kinect run --rm --service-ports controller
```

or edit `.env` / `docker-compose.yml` and set:

```bash
HUMAN_COLOR=white
```

## Check current mode

```bash
curl -s http://127.0.0.1:8765/status | python3 -m json.tool
```

Look for:

```json
"human_color": "black",
"robot_color": "white"
```

## Baxter bridge

This package includes:

```bash
baxter_keyboard_bridge.py
```

Test without moving Baxter:

```bash
python3 baxter_keyboard_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP> \
  --limb left \
  --dry-run
```

Run for real:

```bash
python3 baxter_keyboard_bridge.py \
  --control-url http://127.0.0.1:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP> \
  --limb left
```

## Baxter status bridge update

This package also adds robot command fields to `GET /status`, including:

- `robot_move`
- `robot_from_square`
- `robot_to_square`
- `robot_piece`
- `robot_capture`
- `robot_captured_piece`
- `robot_ros_args`
- `robot_ros_command`
- `robot_ros_commands`

Use `baxter_status_bridge.py` on the ROS/Baxter PC to press Enter, trigger `/move-done`, read those status fields, and run Baxter.
