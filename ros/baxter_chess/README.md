# baxter_chess

ROS/Python scripts for calibrating a physical chessboard and moving Baxter chess pieces.

## Typical use

```bash
cd ~/ros_ws
./baxter.sh
catkin_make
source devel/setup.bash
rosrun baxter_tools enable_robot.py -e
```

Calibrate the board. By default, the reference piece is a pawn:

```bash
rosrun baxter_chess calibrate_board.py --limb left --captured-area
```

During calibration, put the gripper at the height where it should close around a pawn for a1, h1, and a8.
The code then raises/lowers Z for other pieces using the piece-height table.

## Piece heights

Default example heights are in meters:

```json
{
  "pawn": 0.045,
  "rook": 0.050,
  "knight": 0.055,
  "bishop": 0.065,
  "queen": 0.075,
  "king": 0.085
}
```

Measure your real pieces and override them during calibration:

```bash
rosrun baxter_chess calibrate_board.py --limb left --captured-area \
  --piece-height pawn=0.043 \
  --piece-height rook=0.050 \
  --piece-height knight=0.056 \
  --piece-height bishop=0.064 \
  --piece-height queen=0.078 \
  --piece-height king=0.086
```

The key parameter is `grasp_fraction`:

```text
piece_grasp_z_offset = (piece_height - reference_piece_height) * grasp_fraction + piece_z_bias
```

For example, if the pawn is 45 mm, king is 85 mm, and `grasp_fraction=0.45`, Baxter grips the king about 18 mm higher than the pawn:

```text
(0.085 - 0.045) * 0.45 = 0.018 m
```

You can tune this in `~/.baxter_chess/board_left.json`:

```json
"grasp_fraction": 0.45,
"piece_z_bias": {
  "pawn": 0.000,
  "rook": 0.000,
  "knight": 0.000,
  "bishop": 0.000,
  "queen": 0.000,
  "king": 0.000
}
```

Use `piece_z_bias` for small corrections. Example: if Baxter grips the queen too low, set:

```json
"queen": 0.004
```

That raises the queen grasp target by 4 mm.

## Test a square and piece height

```bash
rosrun baxter_chess test_square.py --limb left --square e4 --piece pawn
rosrun baxter_chess test_square.py --limb left --square e4 --piece king
```

## Move a piece

```bash
rosrun baxter_chess move_piece.py --limb left --from-square e2 --to-square e4 --piece pawn
```

Move a taller piece:

```bash
rosrun baxter_chess move_piece.py --limb left --from-square d1 --to-square h5 --piece queen
```

Capture, including the type of the captured piece:

```bash
rosrun baxter_chess move_piece.py --limb left --from-square e4 --to-square d5 --piece pawn --capture --captured-piece knight
```

## Safety

Start with `test_square.py` and a high hover. Do not pick pieces until Baxter is centered above a1, h1, a8, h8, and e4. Keep the board fixed after calibration.

## Python executable note

The scripts use `#!/usr/bin/env python3`. If your Baxter/ROS installation expects Python 2, change the shebang in `scripts/*.py` back to `#!/usr/bin/env python` and make sure `/usr/bin/python` exists.

## Optional: saved home/rest pose after each move

If you want Baxter to move its hand away from the destination square after each chess move, save a named `home` pose:

```bash
rosrun baxter_chess calibrate_home.py --limb left
```

Move the gripper to a safe position above/outside the board, then press Enter. The pose is saved inside:

```bash
~/.baxter_chess/board_left.json
```

Test the saved home pose:

```bash
rosrun baxter_chess go_home.py --limb left
```

After that, normal moves will automatically go to `home` after finishing:

```bash
rosrun baxter_chess move_piece.py --limb left --from-square e2 --to-square e4 --piece pawn
```

To disable the final home move for one command:

```bash
rosrun baxter_chess move_piece.py --limb left --from-square e2 --to-square e4 --piece pawn --no-home
```

To use a different saved pose name:

```bash
rosrun baxter_chess calibrate_home.py --limb left --name standby
rosrun baxter_chess move_piece.py --limb left --from-square e2 --to-square e4 --piece pawn --home standby
```

## Partial gripper opening before picking

Baxter electric gripper positions use this scale:

```text
0   = closed
100 = fully open
```

For chess, full open can hit neighboring pieces. This package can pre-open the gripper only part way before picking. The values are saved in `~/.baxter_chess/board_left.json`:

```json
"gripper_pre_open_position": 45.0,
"gripper_release_open_position": 65.0,
"piece_gripper_pre_open": {
  "pawn": 35.0,
  "rook": 40.0,
  "knight": 45.0,
  "bishop": 45.0,
  "queen": 50.0,
  "king": 50.0
}
```

Tune these numbers for your actual chess pieces. Example: make pawn picking open only to 30%:

```json
"piece_gripper_pre_open": {
  "pawn": 30.0,
  "rook": 40.0,
  "knight": 45.0,
  "bishop": 45.0,
  "queen": 50.0,
  "king": 50.0
}
```

You can also override it for one command without editing the JSON:

```bash
rosrun baxter_chess move_piece.py --limb left --from-square e2 --to-square e4 --piece pawn --pre-open 30
```

For captures, you can tune the captured piece opening separately:

```bash
rosrun baxter_chess move_piece.py --limb left --from-square e4 --to-square f5 --piece pawn --capture --captured-piece pawn --pre-open 30 --captured-pre-open 30
```

If the gripper hits neighboring pieces, lower the pre-open value. If the gripper hits the target piece while descending or misses it, raise the pre-open value slightly.
