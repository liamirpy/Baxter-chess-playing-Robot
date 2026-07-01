# Setup Guide

## ROS/Baxter setup

```bash
mkdir -p ~/ros_ws/src
cd ~/ros_ws/src
git clone https://github.com/<your-username>/baxter-chess-robot.git
cd ~/ros_ws
catkin_make
source devel/setup.bash
source ./baxter.sh
rosrun baxter_tools enable_robot.py -e
```

## Board calibration

```bash
rosrun baxter_chess gripper_setup.py --limb left
rosrun baxter_chess calibrate_board.py --limb left --captured-area
rosrun baxter_chess calibrate_home.py --limb left
```

Recommended validation sequence:

```bash
rosrun baxter_chess test_square.py --limb left --square a1 --piece pawn
rosrun baxter_chess test_square.py --limb left --square h1 --piece pawn
rosrun baxter_chess test_square.py --limb left --square a8 --piece pawn
rosrun baxter_chess test_square.py --limb left --square e4 --piece pawn
```

Only run real pick/place once the gripper is centered above the target squares.

## Controller setup with Docker

```bash
cd controller
docker compose up --build api
```

In another terminal:

```bash
cd controller
xhost +local:docker
docker compose --profile kinect up --build
```

## Controller setup without Docker

```bash
cd controller
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

In another terminal, run the Kinect controller:

```bash
cd controller
source .venv/bin/activate
python3 kinect_fastapi_physical_controller_with_signal.py
```

This path requires Stockfish, OpenCV, Kinect/libfreenect, and USB permissions to be configured on the host.

## Bridge dry run

```bash
cd controller
python3 baxter_status_bridge.py \
  --control-url http://<KINECT_PC_IP>:8765 \
  --ros-ws ~/ros_ws \
  --ros-ip <BAXTER_PC_ROS_IP> \
  --dry-run
```

Remove `--dry-run` after calibration and after the generated command looks correct.
