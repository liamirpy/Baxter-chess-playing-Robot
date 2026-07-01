# Empty-board calibration + locked border workflow

This package is for the Kinect + FastAPI + Stockfish chess setup.

The important change is that the board border/corners are detected only once on an EMPTY board, then frozen for the whole game. Hands, shadows, and pieces will not move the detected border anymore.

## Workflow

1. Start the API and controller.
2. Put an EMPTY chessboard under the Kinect. No pieces.
3. Press ENTER in the OpenCV window, or call:

```bash
curl -X POST http://127.0.0.1:8765/move-done
```

This detects the empty-board border/corners and locks them.

4. Put all pieces in the starting position. Do not move the board or camera.
5. Press ENTER again, or call `/move-done` again. This saves the initial piece-position baseline.
6. Play normally. By default this package uses `HUMAN_COLOR=black`, so:
   - robot/Stockfish makes the first White move
   - call `/move-done` to verify the robot move
   - human moves a Black piece
   - call `/move-done`
   - controller detects the human move and gets the next Stockfish robot move

To make the human White instead, set `HUMAN_COLOR=white` in `.env` or in `docker-compose.yml`.

## Run

```bash
docker compose up -d api
xhost +local:docker
# If using sudo docker, use: xhost +local:root
docker compose --profile kinect run --rm --service-ports controller
```

If you must use sudo:

```bash
xhost +local:root
sudo DISPLAY=$DISPLAY docker compose --profile kinect run --rm --service-ports controller
```


## Choose human color

Default in this package:

```bash
HUMAN_COLOR=black
```

That means:

```text
Robot / Stockfish = White
Human = Black
```

So after the initial pieces baseline is saved, the controller immediately gives a first White robot move.

To use the old behavior instead:

```bash
HUMAN_COLOR=white docker compose --profile kinect run --rm --service-ports controller
```

## Useful endpoints

```bash
curl http://127.0.0.1:8765/status
curl -X POST http://127.0.0.1:8765/move-done
curl -X POST http://127.0.0.1:8765/capture
```

## Manual corners option

If automatic empty-board detection is unreliable, press `m` in the live window and click these three points:

1. a1
2. h1
3. a8

The code computes h8 automatically and locks the corners.

You can also set them by API:

```bash
curl -X POST http://127.0.0.1:8765/manual-corners \
  -H "Content-Type: application/json" \
  -d '{"a1":[120,720],"h1":[920,720],"a8":[120,120]}'
```

After that, put the pieces and call `/move-done` to save the initial piece baseline.

## Reset

To start over from empty-board calibration:

```bash
curl -X POST http://127.0.0.1:8765/command \
  -H "Content-Type: application/json" \
  -d '{"action":"reset"}'
```

or press `r` in the OpenCV window.
