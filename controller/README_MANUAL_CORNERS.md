# Manual chessboard corners

This version adds manual board corners for cases where piece shadows hide the board border.

## GUI method

1. Start the controller.
2. In the live OpenCV window, press `m`.
3. Click the board corners in this exact order:
   1. `a1`
   2. `h1`
   3. `a8`
4. The code computes `h8` automatically.
5. Press ENTER or call `POST /move-done` as usual.

When manual corners are enabled, the capture no longer uses automatic border detection. It uses the manually defined corners to create the top-down board image.

Press `u` to clear manual corners. Press `r` to reset detection and clear manual corners.

## API method

You can also set corners through the local controller API:

```bash
curl -X POST http://127.0.0.1:8765/manual-corners \
  -H "Content-Type: application/json" \
  -d '{"a1":[120,720],"h1":[920,720],"a8":[120,120]}'
```

Then capture as usual:

```bash
curl -X POST http://127.0.0.1:8765/move-done
```

Check current status:

```bash
curl http://127.0.0.1:8765/status
```

Look for:

```json
"manual_corners_enabled": true
```

## Corner orientation

Manual mode assumes:

- `a8` = top-left of the chess board in the generated top-down image
- `h8` = top-right
- `h1` = bottom-right
- `a1` = bottom-left

You only provide `a1`, `h1`, and `a8`; `h8` is calculated as:

```text
h8 = h1 + (a8 - a1)
```
