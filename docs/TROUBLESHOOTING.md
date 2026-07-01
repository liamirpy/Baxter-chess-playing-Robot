# Troubleshooting

## `rosrun baxter_chess ...` cannot find the package

Rebuild and source your workspace:

```bash
cd ~/ros_ws
catkin_make
source devel/setup.bash
rospack find baxter_chess
```

## Baxter IK fails

- Confirm Baxter is enabled.
- Confirm the target square is reachable.
- Re-run board calibration.
- Start with `test_square.py` and a larger hover height.

## Gripper hits nearby pieces

Tune `gripper_pre_open_position` and `piece_gripper_pre_open` inside:

```text
~/.baxter_chess/board_left.json
```

Lower values open the gripper less before descending.

## Kinect controller cannot see the camera in Docker

- Confirm the Kinect works on the host outside Docker.
- Confirm `/dev/bus/usb` is mapped into the container.
- Confirm the container runs with USB permissions or `privileged: true`.
- On Linux/X11, run `xhost +local:docker` before starting the controller.

## Controller API is not reachable

Check the URLs:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/status | python3 -m json.tool
```

If the Kinect controller is on another computer, replace `127.0.0.1` with that computer's IP address.

## The detected move is wrong

- Improve lighting.
- Lock the empty-board calibration.
- Re-check manual corners.
- Make sure the board does not move after calibration.
- Use the saved captures in `controller/captures/` to inspect what the detector saw.
