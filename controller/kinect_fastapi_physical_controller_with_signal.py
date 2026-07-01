import sys
import os
import json
import webbrowser
import threading
from queue import Queue, Empty
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
import chess
import requests

from kinect_board_camera import KinectBoardCamera

from kinect_live_legal_move_compare import (
    compare_board_images,
    infer_legal_move_from_changed_squares,
    draw_result_image,
    resize_for_display,
)


# ============================================================
# Settings
# ============================================================

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
VIEWER_BASE_URL = os.getenv("VIEWER_BASE_URL", BASE_URL)

LIB_DIR = os.getenv("LIB_DIR", "/usr/lib/x86_64-linux-gnu")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "captures_fastapi_physical")

BOARD_SIZE = int(os.getenv("BOARD_SIZE", "800"))

USE_HIGH_QUALITY = os.getenv("USE_HIGH_QUALITY", "true").lower() in {"1", "true", "yes", "on"}

BOARD_IMAGE_ROTATION = os.getenv("BOARD_IMAGE_ROTATION", "cw")
VALID_BOARD_ROTATIONS = ["none", "cw", "180", "ccw"]

SHOW_HELP_TEXT_DEFAULT = os.getenv("SHOW_HELP_TEXT_DEFAULT", "true").lower() in {"1", "true", "yes", "on"}

# Choose who plays the physical human side.
#   HUMAN_COLOR="white" -> human moves first, robot/Stockfish is black.
#   HUMAN_COLOR="black" -> robot/Stockfish moves first as white, human is black.
HUMAN_COLOR = os.getenv("HUMAN_COLOR", "black").strip().lower()
if HUMAN_COLOR not in {"white", "black"}:
    raise ValueError('HUMAN_COLOR must be "white" or "black"')

ROBOT_COLOR = "black" if HUMAN_COLOR == "white" else "white"

# Baxter limb used when building robot ROS command fields in /status.
ROBOT_LIMB = os.getenv("ROBOT_LIMB", "left").strip().lower()
if ROBOT_LIMB not in {"left", "right"}:
    raise ValueError('ROBOT_LIMB must be "left" or "right"')

# Local control API.
# This is separate from your chess FastAPI server on port 8000.
# POST /capture or POST /move-done does the same thing as pressing ENTER.
CONTROL_API_HOST = os.getenv("CONTROL_API_HOST", "0.0.0.0")
CONTROL_API_PORT = int(os.getenv("CONTROL_API_PORT", "8765"))

# Optional safety token. Leave empty for no token.
# If you set this, every API call must include:
#   Header: X-Control-Token: your_token
# or:
#   Query: ?token=your_token
# or:
#   JSON: {"token": "your_token"}
CONTROL_API_TOKEN = os.getenv("CONTROL_API_TOKEN", "")

WINDOW_LIVE = "Kinect FastAPI Physical Chess Controller"
WINDOW_TOP_DOWN = "Top Down Board"
WINDOW_RESULT = "Move Detection Result"


# ============================================================
# API helpers for the chess FastAPI server
# ============================================================

def api_request(method: str, path: str, json_data: Optional[dict] = None) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json_data,
            timeout=30,
        )
    except requests.exceptions.ConnectionError:
        print()
        print("Could not connect to FastAPI.")
        print("Make sure your server is running:")
        print("  uvicorn main:app --reload")
        sys.exit(1)

    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}

    if not response.ok:
        print()
        print("API error:")
        print(data.get("detail", data))
        raise RuntimeError("API request failed")

    return data


def create_api_game(difficulty: str, think_time: float) -> dict[str, Any]:
    return api_request(
        method="POST",
        path="/games",
        json_data={
            "difficulty": difficulty,
            "human_color": HUMAN_COLOR,
            "think_time": think_time,
        },
    )


def send_human_move_to_api(game_id: str, move: str, think_time: float) -> dict[str, Any]:
    return api_request(
        method="POST",
        path=f"/games/{game_id}/human-move",
        json_data={
            "move": move,
            "think_time": think_time,
        },
    )


def confirm_stockfish_move_to_api(game_id: str, move: str) -> dict[str, Any]:
    return api_request(
        method="POST",
        path=f"/games/{game_id}/confirm-stockfish-move",
        json_data={
            "move": move,
        },
    )



# ============================================================
# Manual board-corner helpers
# ============================================================

MANUAL_CORNER_CLICK_ORDER = ["a1", "h1", "a8"]


def _point_to_list(point) -> list[float]:
    """Convert a point-like value to [x, y]."""
    if isinstance(point, dict):
        return [float(point["x"]), float(point["y"])]

    if isinstance(point, (list, tuple)) and len(point) == 2:
        return [float(point[0]), float(point[1])]

    raise ValueError("Point must be [x, y] or {'x': x, 'y': y}.")


def build_manual_corners(a1, h1, a8) -> dict[str, list[float]]:
    """
    Build all four board corners from manually selected a1, h1, and a8.

    The fourth corner is computed as:
        h8 = h1 + (a8 - a1)

    Coordinates are in the live camera image coordinate system.
    """
    a1_np = np.asarray(_point_to_list(a1), dtype=np.float32)
    h1_np = np.asarray(_point_to_list(h1), dtype=np.float32)
    a8_np = np.asarray(_point_to_list(a8), dtype=np.float32)
    h8_np = h1_np + (a8_np - a1_np)

    return {
        "a1": a1_np.tolist(),
        "h1": h1_np.tolist(),
        "a8": a8_np.tolist(),
        "h8": h8_np.tolist(),
    }


def parse_manual_corners_payload(body: dict[str, Any]) -> dict[str, list[float]]:
    """
    Parse JSON like:
        {"a1": [100, 700], "h1": [900, 700], "a8": [100, 100]}
    or:
        {"a1": {"x": 100, "y": 700}, ...}
    """
    try:
        return build_manual_corners(
            a1=body["a1"],
            h1=body["h1"],
            a8=body["a8"],
        )
    except Exception as error:
        raise ValueError(
            "Send JSON with a1, h1, and a8. Example: "
            '{"a1":[100,700],"h1":[900,700],"a8":[100,100]}'
        ) from error


def manual_corners_to_array(manual_corners: dict[str, list[float]]) -> np.ndarray:
    """
    Return corners in image/top-down order:
        top-left=a8, top-right=h8, bottom-right=h1, bottom-left=a1
    """
    return np.asarray(
        [
            manual_corners["a8"],
            manual_corners["h8"],
            manual_corners["h1"],
            manual_corners["a1"],
        ],
        dtype=np.float32,
    )


def draw_manual_chessboard_grid(image, manual_corners: dict[str, list[float]]):
    """
    Draw grid labels using the exact manual chess-corner orientation.

    a8 is the top-left chess corner, h8 top-right, h1 bottom-right, a1 bottom-left.
    This avoids re-ordering the corners by image position.
    """
    output = image.copy()
    dst = manual_corners_to_array(manual_corners)
    board = float(BOARD_SIZE)
    src = np.asarray(
        [
            [0.0, 0.0],
            [board, 0.0],
            [board, board],
            [0.0, board],
        ],
        dtype=np.float32,
    )

    homography = cv2.getPerspectiveTransform(src, dst)

    for i in range(9):
        t = board * i / 8.0
        p1 = board_point_to_frame_point(homography, t, 0.0)
        p2 = board_point_to_frame_point(homography, t, board)
        cv2.line(output, p1, p2, (0, 255, 0), 1)

        p3 = board_point_to_frame_point(homography, 0.0, t)
        p4 = board_point_to_frame_point(homography, board, t)
        cv2.line(output, p3, p4, (0, 255, 0), 1)

    for row in range(8):
        for col in range(8):
            square = chr(ord("a") + col) + str(8 - row)
            x = board * (col + 0.5) / 8.0
            y = board * (row + 0.5) / 8.0
            cx, cy = board_point_to_frame_point(homography, x, y)

            cv2.putText(
                output,
                square,
                (cx - 13, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 0),
                4,
                cv2.LINE_AA,
            )
            cv2.putText(
                output,
                square,
                (cx - 13, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

    return output


def capture_top_down_from_manual_corners(
    camera: KinectBoardCamera,
    manual_corners: dict[str, list[float]],
):
    """
    Capture a top-down board image using manually defined chess corners.

    The output image is canonical chess orientation:
        a8 top-left, h8 top-right, h1 bottom-right, a1 bottom-left.
    """
    captured_frame = camera.get_rgb_frame()
    src = manual_corners_to_array(manual_corners)
    dst = np.asarray(
        [
            [0.0, 0.0],
            [float(BOARD_SIZE), 0.0],
            [float(BOARD_SIZE), float(BOARD_SIZE)],
            [0.0, float(BOARD_SIZE)],
        ],
        dtype=np.float32,
    )

    homography = cv2.getPerspectiveTransform(src, dst)
    top_down = cv2.warpPerspective(captured_frame, homography, (BOARD_SIZE, BOARD_SIZE))

    overlay = draw_manual_chessboard_grid(captured_frame.copy(), manual_corners)

    return top_down, captured_frame, overlay


def draw_manual_corner_markers(image, manual_corners=None, click_points=None):
    """Draw manual corner points on the live image."""
    output = image.copy()

    if manual_corners:
        colors = {
            "a1": (0, 255, 255),
            "h1": (255, 255, 0),
            "a8": (255, 0, 255),
            "h8": (0, 255, 0),
        }

        for name, point in manual_corners.items():
            x, y = int(round(point[0])), int(round(point[1]))
            cv2.circle(output, (x, y), 9, colors.get(name, (0, 255, 0)), -1)
            cv2.putText(
                output,
                name,
                (x + 10, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                colors.get(name, (0, 255, 0)),
                2,
                cv2.LINE_AA,
            )

    if click_points:
        for index, point in enumerate(click_points):
            name = MANUAL_CORNER_CLICK_ORDER[index]
            x, y = int(round(point[0])), int(round(point[1]))
            cv2.circle(output, (x, y), 9, (0, 165, 255), -1)
            cv2.putText(
                output,
                name,
                (x + 10, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 165, 255),
                2,
                cv2.LINE_AA,
            )

    return output


def print_manual_corners(manual_corners: dict[str, list[float]]):
    print()
    print("Manual board corners enabled:")
    for name in ["a1", "h1", "a8", "h8"]:
        x, y = manual_corners[name]
        print(f"  {name}: x={x:.1f}, y={y:.1f}")
    print("Manual mode uses orientation: a8 top-left, h8 top-right, h1 bottom-right, a1 bottom-left.")

# ============================================================
# Local control API helpers
# ============================================================

def make_json_response(handler: BaseHTTPRequestHandler, status_code: int, data: dict):
    payload = json.dumps(data).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def make_control_handler(
    command_queue: Queue,
    status_lock: threading.Lock,
    status_data: dict[str, Any],
):
    class ControlAPIHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _read_json_body(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0:
                return {}

            raw_body = self.rfile.read(content_length)
            if not raw_body:
                return {}

            try:
                return json.loads(raw_body.decode("utf-8"))
            except Exception:
                return {}

        def _authorized(self, parsed_url, body: dict[str, Any]) -> bool:
            if not CONTROL_API_TOKEN:
                return True

            header_token = self.headers.get("X-Control-Token", "")
            query_token = parse_qs(parsed_url.query).get("token", [""])[0]
            body_token = str(body.get("token", ""))

            return CONTROL_API_TOKEN in {header_token, query_token, body_token}

        def _queue_action(self, action: str, source: str = "api"):
            command_queue.put(
                {
                    "action": action,
                    "source": source,
                    "time": datetime.now().isoformat(timespec="seconds"),
                }
            )

            with status_lock:
                status_data["last_api_command"] = action
                status_data["last_api_command_time"] = datetime.now().isoformat(timespec="seconds")

            make_json_response(
                self,
                200,
                {
                    "ok": True,
                    "queued": action,
                    "message": f"Queued action {action!r}.",
                },
            )

        def do_GET(self):
            parsed = urlparse(self.path)

            if parsed.path == "/health":
                make_json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "service": "kinect-chess-controller-control-api",
                    },
                )
                return

            if parsed.path == "/status":
                with status_lock:
                    snapshot = dict(status_data)

                make_json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "status": snapshot,
                    },
                )
                return

            make_json_response(
                self,
                404,
                {
                    "ok": False,
                    "error": "Not found. Use GET /health, GET /status, POST /capture, or POST /move-done.",
                },
            )

        def do_POST(self):
            parsed = urlparse(self.path)
            body = self._read_json_body()

            if not self._authorized(parsed, body):
                make_json_response(
                    self,
                    401,
                    {
                        "ok": False,
                        "error": "Unauthorized. Send X-Control-Token header, ?token=..., or JSON token.",
                    },
                )
                return

            # These endpoints do the same thing as pressing ENTER.
            if parsed.path in {"/capture", "/enter", "/move-done", "/moved-done"}:
                self._queue_action("capture")
                return

            # Manual corner endpoint.
            # Example JSON:
            #   {"a1":[100,700], "h1":[900,700], "a8":[100,100]}
            # h8 is computed automatically.
            if parsed.path == "/manual-corners":
                try:
                    manual_corners = parse_manual_corners_payload(body)
                except ValueError as error:
                    make_json_response(
                        self,
                        400,
                        {
                            "ok": False,
                            "error": str(error),
                        },
                    )
                    return

                command_queue.put(
                    {
                        "action": "set_manual_corners",
                        "source": "api",
                        "time": datetime.now().isoformat(timespec="seconds"),
                        "manual_corners": manual_corners,
                    }
                )

                with status_lock:
                    status_data["last_api_command"] = "set_manual_corners"
                    status_data["last_api_command_time"] = datetime.now().isoformat(timespec="seconds")

                make_json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "queued": "set_manual_corners",
                        "manual_corners": manual_corners,
                        "message": "Manual board corners queued. h8 was computed automatically.",
                    },
                )
                return

            # Generic command endpoint.
            # Example JSON: {"action": "capture"}
            if parsed.path == "/command":
                action = str(body.get("action", "")).strip().lower()

                allowed_actions = {
                    "capture",
                    "rotate",
                    "flip",
                    "help",
                    "force_detect",
                    "clear_manual_corners",
                    "reset",
                    "quit",
                }

                if action not in allowed_actions:
                    make_json_response(
                        self,
                        400,
                        {
                            "ok": False,
                            "error": f"Invalid action {action!r}.",
                            "allowed_actions": sorted(allowed_actions),
                        },
                    )
                    return

                self._queue_action(action)
                return

            make_json_response(
                self,
                404,
                {
                    "ok": False,
                    "error": "Not found. Use POST /capture, POST /move-done, POST /manual-corners, or POST /command.",
                },
            )

    return ControlAPIHandler


def start_control_api(
    command_queue: Queue,
    status_lock: threading.Lock,
    status_data: dict[str, Any],
) -> ThreadingHTTPServer:
    handler_class = make_control_handler(command_queue, status_lock, status_data)
    server = ThreadingHTTPServer((CONTROL_API_HOST, CONTROL_API_PORT), handler_class)

    thread = threading.Thread(
        target=server.serve_forever,
        name="KinectChessControlAPI",
        daemon=True,
    )
    thread.start()

    return server


# ============================================================
# User input helpers
# ============================================================

def ask_difficulty() -> str:
    env_value = os.getenv("DIFFICULTY", "").strip().upper()
    if env_value in {"B", "E", "M", "X"}:
        print(f"Difficulty from DIFFICULTY env: {env_value}")
        return env_value

    print("Choose Stockfish difficulty:")
    print("  B = Beginner")
    print("  E = Easy")
    print("  M = Medium")
    print("  X = Expert")

    while True:
        value = input("Difficulty [M]: ").strip().upper()

        if value == "":
            return "M"

        if value in {"B", "E", "M", "X"}:
            return value

        print("Invalid difficulty. Choose B, E, M, or X.")


def ask_think_time() -> float:
    env_value = os.getenv("THINK_TIME", "").strip()
    if env_value:
        try:
            think_time = float(env_value)
            if 0.05 <= think_time <= 10:
                print(f"Think time from THINK_TIME env: {think_time}")
                return think_time
        except ValueError:
            pass
        print(f"Ignoring invalid THINK_TIME env value: {env_value!r}")

    while True:
        value = input("Stockfish think time [0.5]: ").strip()

        if value == "":
            return 0.5

        try:
            think_time = float(value)
        except ValueError:
            print("Enter a number like 0.5 or 1.")
            continue

        if 0.05 <= think_time <= 10:
            return think_time

        print("Think time must be between 0.05 and 10.")


# ============================================================
# LED helpers
# ============================================================

def set_led_human_turn(camera: KinectBoardCamera):
    print("[LED] GREEN - human turn")
    camera.led_green()


def set_led_stockfish_turn(camera: KinectBoardCamera):
    print("[LED] RED - Stockfish / robot turn")
    camera.led_red()


def set_led_waiting(camera: KinectBoardCamera):
    print("[LED] YELLOW - scanning/checking")
    camera.led_yellow()


def set_led_error(camera: KinectBoardCamera):
    print("[LED] ERROR - detection or wrong move")
    camera.led_error()


# ============================================================
# Save helpers
# ============================================================

def save_image(prefix: str, image):
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{prefix}_{timestamp}.png"

    cv2.imwrite(str(path), image)

    return path


def save_capture_set(prefix: str, top_down, overlay=None, result_image=None):
    saved = {}

    saved["top_down"] = save_image(f"{prefix}_top_down", top_down)

    if overlay is not None:
        saved["overlay"] = save_image(f"{prefix}_overlay", overlay)

    if result_image is not None:
        saved["result"] = save_image(f"{prefix}_result", result_image)

    return saved


# ============================================================
# Board orientation helpers
# ============================================================

def rotate_board_image(image, rotation: str):
    if rotation == "none":
        return image

    if rotation == "cw":
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    if rotation == "ccw":
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

    if rotation == "180":
        return cv2.rotate(image, cv2.ROTATE_180)

    raise ValueError(
        f"Invalid BOARD_IMAGE_ROTATION={rotation!r}. "
        f"Use one of: {', '.join(VALID_BOARD_ROTATIONS)}"
    )


def next_board_rotation(rotation: str) -> str:
    try:
        index = VALID_BOARD_ROTATIONS.index(rotation)
    except ValueError:
        return VALID_BOARD_ROTATIONS[0]

    return VALID_BOARD_ROTATIONS[(index + 1) % len(VALID_BOARD_ROTATIONS)]


def transform_cell_after_rotation(row: int, col: int, rotation: str) -> tuple[int, int]:
    if rotation == "none":
        return row, col

    if rotation == "cw":
        return col, 7 - row

    if rotation == "ccw":
        return 7 - col, row

    if rotation == "180":
        return 7 - row, 7 - col

    raise ValueError(
        f"Invalid board rotation {rotation!r}. "
        f"Use one of: {', '.join(VALID_BOARD_ROTATIONS)}"
    )


def square_name_for_raw_cell(
    row: int,
    col: int,
    board_rotation: str,
    flip_labels: bool,
) -> str:
    rotated_row, rotated_col = transform_cell_after_rotation(row, col, board_rotation)

    if flip_labels:
        rotated_row = 7 - rotated_row
        rotated_col = 7 - rotated_col

    file_char = chr(ord("a") + rotated_col)
    rank_char = str(8 - rotated_row)
    return file_char + rank_char


def order_corners(corners) -> np.ndarray:
    pts = np.asarray(corners, dtype=np.float32).reshape(-1, 2)

    if len(pts) != 4:
        raise ValueError("Expected exactly 4 board corners.")

    rect = np.zeros((4, 2), dtype=np.float32)

    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    diff = np.diff(pts, axis=1).reshape(-1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    return rect


def board_point_to_frame_point(homography, x: float, y: float) -> tuple[int, int]:
    point = np.array([[[x, y]]], dtype=np.float32)
    transformed = cv2.perspectiveTransform(point, homography)[0][0]
    return int(round(transformed[0])), int(round(transformed[1]))


def draw_oriented_chessboard_grid(
    image,
    corners,
    board_rotation: str,
    flip_labels: bool,
):
    if corners is None:
        return image

    try:
        rect = order_corners(corners)
    except Exception:
        return image

    board = float(BOARD_SIZE)
    src = np.array(
        [
            [0.0, 0.0],
            [board, 0.0],
            [board, board],
            [0.0, board],
        ],
        dtype=np.float32,
    )

    homography = cv2.getPerspectiveTransform(src, rect)

    for i in range(9):
        t = board * i / 8.0

        p1 = board_point_to_frame_point(homography, t, 0.0)
        p2 = board_point_to_frame_point(homography, t, board)
        cv2.line(image, p1, p2, (0, 255, 0), 1)

        p3 = board_point_to_frame_point(homography, 0.0, t)
        p4 = board_point_to_frame_point(homography, board, t)
        cv2.line(image, p3, p4, (0, 255, 0), 1)

    for row in range(8):
        for col in range(8):
            square = square_name_for_raw_cell(
                row=row,
                col=col,
                board_rotation=board_rotation,
                flip_labels=flip_labels,
            )

            x = board * (col + 0.5) / 8.0
            y = board * (row + 0.5) / 8.0
            cx, cy = board_point_to_frame_point(homography, x, y)

            cv2.putText(
                image,
                square,
                (cx - 13, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 0),
                4,
                cv2.LINE_AA,
            )
            cv2.putText(
                image,
                square,
                (cx - 13, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

    return image


def draw_labels_on_top_down(top_down, flip_labels: bool):
    image = top_down.copy()
    height, width = image.shape[:2]
    cell_w = width / 8.0
    cell_h = height / 8.0

    for row in range(8):
        for col in range(8):
            label_row = 7 - row if flip_labels else row
            label_col = 7 - col if flip_labels else col

            square = chr(ord("a") + label_col) + str(8 - label_row)

            x = int(col * cell_w + 8)
            y = int(row * cell_h + 22)

            cv2.putText(
                image,
                square,
                (x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 0, 0),
                4,
                cv2.LINE_AA,
            )
            cv2.putText(
                image,
                square,
                (x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

    return image


# ============================================================
# Color / side helpers
# ============================================================

def color_to_chess(color: str):
    return chess.WHITE if color == "white" else chess.BLACK


def board_turn_color(board: chess.Board) -> str:
    return "white" if board.turn == chess.WHITE else "black"


def color_title(color: str) -> str:
    return color.capitalize()


# ============================================================
# Baxter / robot command fields for GET /status
# ============================================================

PIECE_TYPE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


def empty_robot_move_status() -> dict[str, Any]:
    return {
        "robot_move": None,
        "robot_from_square": None,
        "robot_to_square": None,
        "robot_piece": None,
        "robot_capture": False,
        "robot_captured_piece": None,
        "robot_is_castling": False,
        "robot_promotion": None,
        "robot_ros_args": None,
        "robot_ros_command": None,
        "robot_ros_commands": [],
        "robot_ros_commands_text": [],
        "robot_status_error": None,
    }


def build_single_robot_ros_args(board: chess.Board, move: chess.Move, limb: str):
    moving_piece = board.piece_at(move.from_square)

    if moving_piece is None:
        return None

    from_square = chess.square_name(move.from_square)
    to_square = chess.square_name(move.to_square)
    piece_name = PIECE_TYPE_NAMES[moving_piece.piece_type]

    ros_args = [
        "--limb", limb,
        "--from-square", from_square,
        "--to-square", to_square,
        "--piece", piece_name,
    ]

    if board.is_capture(move):
        if board.is_en_passant(move):
            captured_piece_name = "pawn"
        else:
            captured_piece = board.piece_at(move.to_square)
            captured_piece_name = (
                PIECE_TYPE_NAMES[captured_piece.piece_type]
                if captured_piece is not None
                else "piece"
            )

        ros_args.extend([
            "--capture",
            "--captured-piece", captured_piece_name,
        ])

    # If your Baxter move_piece.py supports promotion, uncomment this block.
    # if move.promotion:
    #     ros_args.extend(["--promotion", PIECE_TYPE_NAMES[move.promotion]])

    return ros_args


def build_castling_robot_ros_args(board: chess.Board, move: chess.Move, limb: str):
    rank = chess.square_rank(move.from_square)

    king_from = chess.square_name(move.from_square)
    king_to = chess.square_name(move.to_square)

    # Kingside castle: king goes to g-file, rook h-file to f-file.
    if chess.square_file(move.to_square) == 6:
        rook_from = chess.square_name(chess.square(7, rank))
        rook_to = chess.square_name(chess.square(5, rank))

    # Queenside castle: king goes to c-file, rook a-file to d-file.
    else:
        rook_from = chess.square_name(chess.square(0, rank))
        rook_to = chess.square_name(chess.square(3, rank))

    return [
        [
            "--limb", limb,
            "--from-square", king_from,
            "--to-square", king_to,
            "--piece", "king",
        ],
        [
            "--limb", limb,
            "--from-square", rook_from,
            "--to-square", rook_to,
            "--piece", "rook",
        ],
    ]


def ros_args_to_command(ros_args) -> Optional[str]:
    if not ros_args:
        return None

    return "rosrun baxter_chess move_piece.py " + " ".join(str(item) for item in ros_args)


def build_robot_move_status(board: chess.Board, move_uci: Optional[str], limb: str = "left") -> dict[str, Any]:
    """
    Build the Baxter/ROS command fields for a pending Stockfish move.

    Important design choice:
    This function is meant to be called immediately when Stockfish returns the
    robot move, while the local board is still in the position BEFORE the robot
    move is physically applied. The resulting dict is then saved and returned
    from /status. This avoids rebuilding later from a board state that may have
    changed.
    """
    data = empty_robot_move_status()

    if not move_uci:
        data["robot_status_error"] = "No expected Stockfish move."
        return data

    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        data["robot_status_error"] = f"Invalid UCI move: {move_uci}"
        return data

    from_square = chess.square_name(move.from_square)
    to_square = chess.square_name(move.to_square)

    moving_piece = board.piece_at(move.from_square)

    if moving_piece is None:
        data.update({
            "robot_move": move_uci,
            "robot_from_square": from_square,
            "robot_to_square": to_square,
            "robot_status_error": f"No piece found on {from_square}. FEN: {board.fen()}",
        })
        return data

    piece_name = PIECE_TYPE_NAMES[moving_piece.piece_type]
    is_capture = board.is_capture(move)
    captured_piece_name = None

    if is_capture:
        if board.is_en_passant(move):
            captured_piece_name = "pawn"
        else:
            captured_piece = board.piece_at(move.to_square)
            captured_piece_name = (
                PIECE_TYPE_NAMES[captured_piece.piece_type]
                if captured_piece is not None
                else "piece"
            )

    is_castling = board.is_castling(move)
    promotion_name = PIECE_TYPE_NAMES.get(move.promotion) if move.promotion else None

    # Build commands even if python-chess says the move is not legal, as long as
    # the from-square has a piece. This prevents /status from returning None when
    # a local/remote board legality mismatch occurs. The warning is returned in
    # robot_status_error for debugging.
    legality_warning = None
    if move not in board.legal_moves:
        legality_warning = f"Warning: {move_uci} is not in local board.legal_moves. FEN: {board.fen()}"

    if is_castling:
        ros_commands = build_castling_robot_ros_args(board, move, limb)
    else:
        one_command = build_single_robot_ros_args(board, move, limb)
        ros_commands = [one_command] if one_command is not None else []

    ros_commands_text = [ros_args_to_command(item) for item in ros_commands]

    data.update({
        "robot_move": move_uci,
        "robot_from_square": from_square,
        "robot_to_square": to_square,
        "robot_piece": piece_name,
        "robot_capture": is_capture,
        "robot_captured_piece": captured_piece_name,
        "robot_is_castling": is_castling,
        "robot_promotion": promotion_name,
        "robot_ros_args": ros_commands[0] if ros_commands else None,
        "robot_ros_command": ros_commands_text[0] if ros_commands_text else None,
        "robot_ros_commands": ros_commands,
        "robot_ros_commands_text": ros_commands_text,
        "robot_status_error": legality_warning,
    })

    return data

# ============================================================
# Display helpers
# ============================================================

def draw_live_instructions(
    display,
    state: str,
    board: chess.Board,
    game_id: str,
    expected_stockfish_move: Optional[str],
    board_rotation: str,
    show_help_text: bool,
    manual_corners_enabled: bool = False,
    manual_click_mode: bool = False,
):
    if not show_help_text:
        return display

    turn_color = board_turn_color(board)
    if turn_color == HUMAN_COLOR:
        turn_text = f"{color_title(turn_color)} / human to move"
    else:
        turn_text = f"{color_title(turn_color)} / robot pending"

    step_help = {
        "BORDER_CALIBRATION": "Step 1: EMPTY board -> ENTER locks border/corners",
        "SETUP_PIECES": "Step 2: Put pieces -> ENTER saves initial piece position",
        "HUMAN_TURN": f"Step 3: Human moves {HUMAN_COLOR.upper()} -> ENTER detects human move",
        "ROBOT_TURN": f"Step 4: Robot moves {ROBOT_COLOR.upper()} -> ENTER verifies robot move",
        "GAME_OVER": "Game finished",
    }.get(state, "ENTER = capture/check current step")

    lines = [
        f"State: {state}",
        step_help,
        f"Chess: {turn_text}",
        f"Game ID: {game_id}",
        "API POST /capture or /move-done = same as ENTER",
        "c = force empty-board border detection + lock",
        "m = manual corners: click a1, h1, a8",
        "u = clear manual corners",
        "r = reset to empty-board calibration",
        f"Manual corners: {'ON' if manual_corners_enabled else 'OFF'}",
        f"Manual click mode: {'ON' if manual_click_mode else 'OFF'}",
        f"Board rotation: {board_rotation}",
        "o = rotate board view 90 deg",
        "f = flip labels 180 deg",
        "h = hide/show this help text",
        "l = print legal moves",
        "q = quit",
    ]

    if expected_stockfish_move:
        lines.insert(3, f"Expected robot move: {expected_stockfish_move}")

    y = 28

    for index, line in enumerate(lines):
        if index == 0:
            bg = (0, 100, 0)

            if state == "BORDER_CALIBRATION":
                bg = (120, 90, 0)
            elif state == "SETUP_PIECES":
                bg = (100, 100, 0)
            elif state == "HUMAN_TURN":
                bg = (0, 130, 0)
            elif state == "ROBOT_TURN":
                bg = (0, 0, 180)
            elif state == "GAME_OVER":
                bg = (80, 80, 80)

            cv2.rectangle(display, (8, y - 22), (760, y + 8), bg, -1)

        cv2.putText(
            display,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (255, 255, 255),
            2,
        )

        y += 26

    return display


def print_board_state(board: chess.Board):
    print()
    print(board)
    print()
    print(f"FEN: {board.fen()}")

    if board.is_game_over():
        print(f"Game over: {board.result()}")
    else:
        turn = "White" if board.turn == chess.WHITE else "Black"
        print(f"Turn: {turn}")


def print_comparison_result(title: str, comparison: dict):
    print()
    print(title)
    print("=" * len(title))

    changed = comparison["changed"]

    if not changed:
        print("Changed squares: none")
    else:
        print("Changed squares:")
        for item in changed:
            print(
                f"  {item['square']}: "
                f"diff={item['diff_score']:.2f}, "
                f"occupancy_delta={item['occupancy_delta']:.2f}"
            )

    print(f"Image guess: {comparison.get('estimated_move')}")
    print(f"Legal move:  {comparison.get('legal_move')}")
    print(f"SAN:         {comparison.get('legal_san')}")

    candidates = comparison.get("legal_candidates") or []

    if candidates:
        print()
        print("Top legal candidates:")
        for candidate in candidates[:5]:
            print(
                f"  {candidate['uci']} "
                f"({candidate['san']}), "
                f"score={candidate['score']:.2f}, "
                f"expected={sorted(candidate['expected'])}"
            )


# ============================================================
# Camera capture helper
# ============================================================

def fresh_capture(
    camera: KinectBoardCamera,
    board_rotation: str,
    manual_corners: Optional[dict[str, list[float]]] = None,
):
    if manual_corners is not None:
        # Manual mode already returns canonical chess orientation:
        # a8 top-left, h8 top-right, h1 bottom-right, a1 bottom-left.
        return capture_top_down_from_manual_corners(camera, manual_corners)

    # Important: do NOT redetect the board border during the game.
    # Corners are detected once on the empty board, then locked in KinectBoardCamera.
    raw_top_down, captured_frame = camera.capture_top_down_board(
        force_redetect=False,
        stable_frames=2,
    )

    top_down = rotate_board_image(raw_top_down, board_rotation)

    overlay = draw_oriented_chessboard_grid(
        captured_frame.copy(),
        camera.current_corners,
        board_rotation,
        camera.flip_labels,
    )

    return top_down, captured_frame, overlay


# ============================================================
# Main physical controller
# ============================================================

def main():
    print("Kinect + FastAPI Physical Chess Controller")
    print("==========================================")
    print()

    difficulty = ask_difficulty()
    think_time = ask_think_time()

    print()
    print("Creating FastAPI game...")

    api_game = create_api_game(difficulty, think_time)
    game_id = api_game["game_id"]

    viewer_url = f"{VIEWER_BASE_URL}/viewer?game_id={game_id}"

    print()
    print("Game created.")
    print(f"Game ID: {game_id}")
    print(f"Difficulty: {api_game['difficulty_name']}")
    print(f"Human color: {HUMAN_COLOR.upper()}")
    print(f"Robot color: {ROBOT_COLOR.upper()}")
    print(f"Viewer: {viewer_url}")

    try:
        webbrowser.open(viewer_url)
    except Exception:
        pass

    board = chess.Board()

    camera = KinectBoardCamera(
        lib_dir=LIB_DIR,
        use_high_quality=USE_HIGH_QUALITY,
        board_size=BOARD_SIZE,
    )

    board_rotation = BOARD_IMAGE_ROTATION
    show_help_text = SHOW_HELP_TEXT_DEFAULT

    manual_board_corners: Optional[dict[str, list[float]]] = None
    manual_click_mode = False
    manual_click_points: list[list[float]] = []
    mouse_state = {
        "raw_shape": None,
        "display_shape": None,
    }

    state = "BORDER_CALIBRATION"

    previous_top_down = None
    human_top_down = None

    expected_stockfish_move = None
    pending_api_result = None

    # Saved Baxter/ROS command for the pending robot move.
    # This is built exactly when Stockfish returns a move, not rebuilt later.
    saved_robot_status = empty_robot_move_status()

    capture_count = 0
    should_quit = False

    control_queue: Queue = Queue()
    status_lock = threading.Lock()
    status_data: dict[str, Any] = {
        "running": True,
        "state": state,
        "game_id": game_id,
        "fen": board.fen(),
        "human_color": HUMAN_COLOR,
        "robot_color": ROBOT_COLOR,
        "board_rotation": board_rotation,
        "flip_labels": False,
        "show_help_text": show_help_text,
        "manual_corners_enabled": False,
        "manual_corners": None,
        "corners_locked": False,
        "expected_stockfish_move": expected_stockfish_move,
        "last_capture_source": None,
        "last_capture_time": None,
        "last_capture_ok": None,
        "last_capture_message": None,
    }
    status_data.update(empty_robot_move_status())

    control_server = start_control_api(control_queue, status_lock, status_data)

    print()
    print("Local control API started.")
    print(f"  Local machine:  http://127.0.0.1:{CONTROL_API_PORT}")
    print(f"  Network:        http://<this-computer-ip>:{CONTROL_API_PORT}")
    print("  Same as ENTER:  POST /capture")
    print("  Same as ENTER:  POST /move-done")
    print("  Manual corners: POST /manual-corners")
    print("  Status:         GET  /status")
    print()

    def update_status(
        last_capture_source: Optional[str] = None,
        last_capture_ok: Optional[bool] = None,
        last_capture_message: Optional[str] = None,
    ):
        with status_lock:
            status_data["running"] = True
            status_data["state"] = state
            status_data["game_id"] = game_id
            status_data["fen"] = board.fen()
            status_data["human_color"] = HUMAN_COLOR
            status_data["robot_color"] = ROBOT_COLOR
            status_data["board_rotation"] = board_rotation
            status_data["flip_labels"] = bool(camera.flip_labels)
            status_data["show_help_text"] = bool(show_help_text)
            status_data["manual_corners_enabled"] = manual_board_corners is not None
            status_data["manual_corners"] = manual_board_corners
            status_data["corners_locked"] = bool(getattr(camera, "corners_locked", False))
            status_data["expected_stockfish_move"] = expected_stockfish_move
            status_data["robot_limb"] = ROBOT_LIMB

            # Return the saved robot command. Do not rebuild it here, because
            # /status may be called after local state changes.
            status_data.update(saved_robot_status)

            if last_capture_source is not None:
                status_data["last_capture_source"] = last_capture_source
                status_data["last_capture_time"] = datetime.now().isoformat(timespec="seconds")
                status_data["last_capture_ok"] = last_capture_ok
                status_data["last_capture_message"] = last_capture_message

    def process_capture_step(source: str):
        nonlocal state
        nonlocal previous_top_down
        nonlocal human_top_down
        nonlocal expected_stockfish_move
        nonlocal pending_api_result
        nonlocal saved_robot_status
        nonlocal capture_count

        print()
        if state == "BORDER_CALIBRATION":
            print(f"{source.upper()} capture signal -> EMPTY board calibration. Detecting and locking border/corners...")
        elif state == "SETUP_PIECES":
            print(f"{source.upper()} capture signal -> saving initial piece position using locked corners...")
        elif manual_board_corners is not None:
            print(f"{source.upper()} capture signal -> using manual locked board corners...")
        else:
            print(f"{source.upper()} capture signal -> capturing with locked board corners...")

        capture_count += 1
        set_led_waiting(camera)

        try:
            top_down, captured_frame, overlay = fresh_capture(
                camera,
                board_rotation,
                manual_corners=manual_board_corners,
            )
        except Exception as error:
            set_led_error(camera)
            message = f"Could not capture board: {error}"
            print(message)
            print("Make sure the board is visible and try again.")
            update_status(source, False, message)
            return

        cv2.imshow(WINDOW_TOP_DOWN, draw_labels_on_top_down(top_down, camera.flip_labels))

        if state == "BORDER_CALIBRATION":
            # The image is from the EMPTY board. Save it only as a debug/reference image.
            # Do not use it as the move baseline. The baseline must be captured after pieces are placed.
            if hasattr(camera, "lock_corners"):
                camera.lock_corners()

            saved = save_capture_set(
                prefix=f"{capture_count:03d}_empty_board_corners_locked",
                top_down=top_down,
                overlay=overlay,
            )

            print("Empty board border/corners detected and LOCKED.")
            print(f"Top-down empty board: {saved['top_down']}")
            print(f"Overlay:              {saved['overlay']}")
            print()
            print("Now put all chess pieces on the board without moving the board or camera.")
            print("Then press ENTER or send POST /move-done again to save the initial piece position.")

            state = "SETUP_PIECES"
            set_led_waiting(camera)
            update_status(source, True, "Empty board corners locked. Put pieces, then capture initial position.")
            return

        if state == "SETUP_PIECES":
            previous_top_down = top_down.copy()

            saved = save_capture_set(
                prefix=f"{capture_count:03d}_initial_position_with_pieces",
                top_down=top_down,
                overlay=overlay,
            )

            print("Initial physical piece position saved using the locked board corners.")
            print(f"Top-down: {saved['top_down']}")
            print(f"Overlay:   {saved['overlay']}")

            if HUMAN_COLOR == "black":
                # Because the human is black, Stockfish/robot is white and starts the game.
                # The API calculated the first white move when the game was created.
                expected_stockfish_move = api_game.get("pending_stockfish_move")
                pending_api_result = api_game

                if expected_stockfish_move is None:
                    set_led_error(camera)
                    message = "Human is black, but the API did not return a first pending Stockfish move."
                    print(message)
                    saved_robot_status = empty_robot_move_status()
                    update_status(source, False, message)
                    return

                # Build and save the Baxter command immediately, while the
                # local board is still before the robot's first move.
                saved_robot_status = build_robot_move_status(
                    board=board,
                    move_uci=expected_stockfish_move,
                    limb=ROBOT_LIMB,
                )

                human_top_down = previous_top_down.copy()
                state = "ROBOT_TURN"
                set_led_stockfish_turn(camera)

                print()
                print("Robot starts because human is BLACK.")
                print(f"Make this {ROBOT_COLOR.upper()} move on the real board: {expected_stockfish_move}")
                if api_game.get("pending_stockfish_san"):
                    print(f"SAN: {api_game.get('pending_stockfish_san')}")
                print("Then send POST /capture or POST /move-done to verify the robot move.")

                update_status(source, True, "Initial position captured. Robot/Stockfish starts because human is black.")
                return

            state = "HUMAN_TURN"
            set_led_human_turn(camera)

            print()
            print("Human turn.")
            print(f"Move a {HUMAN_COLOR.upper()} piece on the real board, then send POST /capture or POST /move-done.")

            update_status(source, True, "Initial piece position captured. Human turn started.")
            return

        if state == "HUMAN_TURN":
            if board.turn != color_to_chess(HUMAN_COLOR):
                set_led_error(camera)
                message = f"Internal error: local board does not say {HUMAN_COLOR.upper()} / human to move."
                print(message)
                update_status(source, False, message)
                return

            comparison = compare_board_images(
                previous_top_down,
                top_down,
                flip_labels=camera.flip_labels,
            )

            legal_result = infer_legal_move_from_changed_squares(
                board=board,
                changed=comparison["changed"],
                image_guess=comparison["estimated_move"],
            )

            comparison["legal_move"] = legal_result["move"]
            comparison["legal_san"] = legal_result["san"]
            comparison["legal_candidates"] = legal_result["candidates"]

            result_image = draw_result_image(top_down, comparison)
            cv2.imshow(WINDOW_RESULT, result_image)

            saved = save_capture_set(
                prefix=f"{capture_count:03d}_human",
                top_down=top_down,
                overlay=overlay,
                result_image=result_image,
            )

            print_comparison_result("Human move detection", comparison)

            human_move = comparison["legal_move"]

            if human_move is None:
                set_led_error(camera)
                message = "No legal human move confirmed. Fix the board/detection and try again."
                print()
                print(message)
                update_status(source, False, message)
                return

            print()
            print(f"Sending human move to FastAPI physical endpoint: {human_move}")

            try:
                api_result = send_human_move_to_api(
                    game_id=game_id,
                    move=human_move,
                    think_time=think_time,
                )
            except RuntimeError:
                set_led_error(camera)
                message = "FastAPI rejected the detected human move."
                print(message)
                print("Fix the physical board or detection and try again.")
                update_status(source, False, message)
                return

            human_move_obj = chess.Move.from_uci(human_move)
            human_san = board.san(human_move_obj)
            board.push(human_move_obj)

            human_top_down = top_down.copy()
            expected_stockfish_move = api_result["stockfish_move"]
            pending_api_result = api_result

            print()
            print(f"Human move accepted: {human_move} ({human_san})")

            if api_result["game_over"]:
                print("Game over after human move.")
                print(f"Result: {api_result['result']}")
                state = "GAME_OVER"
                previous_top_down = top_down.copy()
                saved_robot_status = empty_robot_move_status()
                set_led_waiting(camera)
                update_status(source, True, f"Human move accepted: {human_move}. Game over.")
                return

            if expected_stockfish_move is None:
                set_led_error(camera)
                message = "FastAPI did not return a Stockfish move."
                print(message)
                print("Fix the API/game state and try again.")
                saved_robot_status = empty_robot_move_status()
                update_status(source, False, message)
                return

            # Build and save the Baxter command immediately, while the local
            # board is in the position after the human move and before the
            # robot move is applied. This is the safest time to identify the
            # robot piece and capture information.
            saved_robot_status = build_robot_move_status(
                board=board,
                move_uci=expected_stockfish_move,
                limb=ROBOT_LIMB,
            )

            print()
            print("Stockfish pending response:")
            print(f"  Move: {expected_stockfish_move}")
            print(f"  SAN:  {api_result['stockfish_san']}")
            print()
            print("FastAPI has NOT applied this Stockfish move yet.")
            print("The robot/operator must move it physically first.")

            state = "ROBOT_TURN"
            set_led_stockfish_turn(camera)

            print()
            print("Robot/operator turn.")
            print(f"Make this {ROBOT_COLOR.upper()} move on the real board: {expected_stockfish_move}")
            print("Then send POST /capture or press ENTER to verify it.")

            update_status(source, True, f"Human move accepted: {human_move}. Waiting for robot move.")
            return

        if state == "ROBOT_TURN":
            if board.turn != color_to_chess(ROBOT_COLOR):
                set_led_error(camera)
                message = f"Internal error: local board does not say {ROBOT_COLOR.upper()} / robot to move."
                print(message)
                update_status(source, False, message)
                return

            if human_top_down is None:
                set_led_error(camera)
                message = "Internal error: missing human_top_down image."
                print(message)
                update_status(source, False, message)
                return

            if expected_stockfish_move is None:
                set_led_error(camera)
                message = "Internal error: missing expected Stockfish move."
                print(message)
                update_status(source, False, message)
                return

            comparison = compare_board_images(
                human_top_down,
                top_down,
                flip_labels=camera.flip_labels,
            )

            legal_result = infer_legal_move_from_changed_squares(
                board=board,
                changed=comparison["changed"],
                image_guess=comparison["estimated_move"],
            )

            comparison["legal_move"] = legal_result["move"]
            comparison["legal_san"] = legal_result["san"]
            comparison["legal_candidates"] = legal_result["candidates"]

            result_image = draw_result_image(top_down, comparison)
            cv2.imshow(WINDOW_RESULT, result_image)

            saved = save_capture_set(
                prefix=f"{capture_count:03d}_robot",
                top_down=top_down,
                overlay=overlay,
                result_image=result_image,
            )

            print_comparison_result("Robot move verification", comparison)

            robot_move = comparison["legal_move"]

            if robot_move is None:
                set_led_error(camera)
                message = f"No legal robot move confirmed. Expected Stockfish move: {expected_stockfish_move}"
                print()
                print(message)
                print("Fix the board/detection and try again.")
                update_status(source, False, message)
                return

            if robot_move != expected_stockfish_move:
                set_led_error(camera)
                message = f"Wrong robot move detected. Expected {expected_stockfish_move}, detected {robot_move}."
                print()
                print("Wrong robot move detected.")
                print(f"Expected: {expected_stockfish_move}")
                print(f"Detected: {robot_move}")
                print("Fix the physical board, then try again.")
                update_status(source, False, message)
                return

            print()
            print(f"Robot move matches pending Stockfish move: {robot_move}")
            print("Confirming Stockfish move to FastAPI...")

            try:
                confirm_result = confirm_stockfish_move_to_api(
                    game_id=game_id,
                    move=robot_move,
                )
            except RuntimeError:
                set_led_error(camera)
                message = "FastAPI rejected the confirmed robot move."
                print()
                print(message)
                print("Fix the board/API state and try again.")
                update_status(source, False, message)
                return

            robot_move_obj = chess.Move.from_uci(robot_move)
            robot_san = board.san(robot_move_obj)
            board.push(robot_move_obj)

            previous_top_down = top_down.copy()

            print()
            print(f"Robot move verified and confirmed: {robot_move} ({robot_san})")

            if board.fen() != confirm_result["fen"]:
                print()
                print("Warning: local physical board FEN does not match API FEN.")
                print(f"Local: {board.fen()}")
                print(f"API:   {confirm_result['fen']}")

            if board.is_game_over():
                print()
                print("Game over.")
                print(f"Result: {board.result()}")
                state = "GAME_OVER"
                expected_stockfish_move = None
                pending_api_result = None
                saved_robot_status = empty_robot_move_status()
                set_led_waiting(camera)
                update_status(source, True, f"Robot move confirmed: {robot_move}. Game over.")
                return

            expected_stockfish_move = None
            pending_api_result = None
            saved_robot_status = empty_robot_move_status()
            human_top_down = None

            state = "HUMAN_TURN"
            set_led_human_turn(camera)

            print()
            print_board_state(board)
            print("Human turn again.")
            print(f"Move a {HUMAN_COLOR.upper()} piece, then send POST /capture or press ENTER.")

            update_status(source, True, f"Robot move confirmed: {robot_move}. Human turn again.")
            return

        if state == "GAME_OVER":
            print()
            print("Game is over.")
            print(f"Result: {board.result()}")
            set_led_waiting(camera)
            update_status(source, True, f"Game is over: {board.result()}")
            return

    def live_mouse_callback(event, x, y, flags, param):
        nonlocal manual_board_corners
        nonlocal manual_click_mode
        nonlocal manual_click_points
        nonlocal board_rotation

        if event != cv2.EVENT_LBUTTONDOWN or not manual_click_mode:
            return

        raw_shape = mouse_state.get("raw_shape")
        display_shape = mouse_state.get("display_shape")

        if raw_shape is None or display_shape is None:
            print("Manual click ignored: no frame size is available yet.")
            return

        raw_h, raw_w = raw_shape[:2]
        display_h, display_w = display_shape[:2]

        raw_x = float(x) * float(raw_w) / max(float(display_w), 1.0)
        raw_y = float(y) * float(raw_h) / max(float(display_h), 1.0)

        manual_click_points.append([raw_x, raw_y])
        clicked_name = MANUAL_CORNER_CLICK_ORDER[len(manual_click_points) - 1]
        print(f"Manual corner {clicked_name} set at x={raw_x:.1f}, y={raw_y:.1f}")

        if len(manual_click_points) == 3:
            manual_board_corners = build_manual_corners(
                a1=manual_click_points[0],
                h1=manual_click_points[1],
                a8=manual_click_points[2],
            )
            manual_click_points = []
            manual_click_mode = False

            # Manual corners define the chess orientation directly, so reset rotation/label flips.
            board_rotation = "none"
            camera.flip_labels = False
            camera.current_corners = manual_corners_to_array(manual_board_corners)

            print_manual_corners(manual_board_corners)
            if state == "BORDER_CALIBRATION":
                state = "SETUP_PIECES"
                print("Manual corners locked. Now put pieces, then press ENTER or POST /move-done to save the initial position.")
            else:
                print("Now press ENTER or POST /move-done to capture using these manual corners.")
            update_status(last_capture_message="Manual board corners set from mouse clicks.")

    try:
        camera.start()

        cv2.namedWindow(WINDOW_LIVE, cv2.WINDOW_NORMAL)
        cv2.namedWindow(WINDOW_TOP_DOWN, cv2.WINDOW_NORMAL)
        cv2.namedWindow(WINDOW_RESULT, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW_LIVE, live_mouse_callback)

        print()
        print("Live controller started.")
        print()
        print("Controls:")
        print("  ENTER = current step: 1) lock empty-board corners, 2) save pieces, 3) detect moves")
        print("  API   = POST /capture or POST /move-done does the same as ENTER")
        print("  c     = force empty-board border detection and lock corners")
        print("  m     = manual corners: click a1, h1, a8")
        print("  u     = clear manual corners")
        print("  r     = reset to empty-board calibration")
        print("  o     = rotate board view 90 deg")
        print("  f     = flip labels 180 deg")
        print("  h     = hide/show help text on live image")
        print("  l     = print legal moves")
        print("  q     = quit")
        print()
        print("Step 1:")
        print("  Remove all chess pieces. Keep only the EMPTY board under the Kinect.")
        print("  Press ENTER or send POST /move-done to detect and LOCK the border/corners.")
        print("Step 2:")
        print("  Put all chess pieces in the starting position without moving the board/camera.")
        print("  Press ENTER or send POST /move-done again to save the initial piece baseline.")
        print("Step 3:")
        print("  Play normally. The border/corners stay locked for the whole game.")
        print(f"  Human color: {HUMAN_COLOR.upper()}")
        print(f"  Robot color: {ROBOT_COLOR.upper()}")
        if HUMAN_COLOR == "black":
            print("  Robot/Stockfish will make the first WHITE move after the initial pieces are saved.")
        print()

        set_led_waiting(camera)
        print_board_state(board)
        update_status()

        while True:
            frame = camera.get_rgb_frame()
            mouse_state["raw_shape"] = frame.shape

            if manual_board_corners is None:
                camera.update(frame, force_detect=False)

            display = frame.copy()

            if manual_board_corners is not None:
                display = draw_manual_chessboard_grid(display, manual_board_corners)
            elif camera.current_corners is not None:
                display = draw_oriented_chessboard_grid(
                    display,
                    camera.current_corners,
                    board_rotation,
                    camera.flip_labels,
                )

            display = draw_manual_corner_markers(
                display,
                manual_corners=manual_board_corners,
                click_points=manual_click_points,
            )

            display = resize_for_display(display)
            mouse_state["display_shape"] = display.shape

            draw_live_instructions(
                display=display,
                state=state,
                board=board,
                game_id=game_id,
                expected_stockfish_move=expected_stockfish_move,
                board_rotation=board_rotation,
                show_help_text=show_help_text,
                manual_corners_enabled=manual_board_corners is not None,
                manual_click_mode=manual_click_mode,
            )

            cv2.imshow(WINDOW_LIVE, display)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

            elif key == ord("c"):
                print("Forcing chessboard detection...")
                ok = camera.update(frame, force_detect=True)
                if ok and state == "BORDER_CALIBRATION":
                    state = "SETUP_PIECES"
                    print("Board detected and corners locked. Now put pieces, then press ENTER or POST /move-done.")
                else:
                    print("Board detected." if ok else "Board detection failed.")

            elif key == ord("m"):
                manual_click_mode = True
                manual_click_points = []
                print()
                print("Manual corner mode ON.")
                print("Click these three corners in the live window, in this exact order:")
                print("  1) a1")
                print("  2) h1")
                print("  3) a8")
                print("The code will compute h8 automatically.")

            elif key == ord("u"):
                manual_board_corners = None
                manual_click_mode = False
                manual_click_points = []
                camera.reset_detection()
                state = "BORDER_CALIBRATION"
                previous_top_down = None
                human_top_down = None
                expected_stockfish_move = None
                pending_api_result = None
                print("Manual/locked corners cleared. Back to empty-board calibration.")

            elif key == ord("r"):
                manual_board_corners = None
                manual_click_mode = False
                manual_click_points = []
                camera.reset_detection()
                state = "BORDER_CALIBRATION"
                previous_top_down = None
                human_top_down = None
                expected_stockfish_move = None
                pending_api_result = None
                print("Board detection reset. Back to Step 1: empty-board calibration.")

            elif key == ord("o"):
                board_rotation = next_board_rotation(board_rotation)
                print(f"Board image rotation: {board_rotation}")
                print("The live square labels and move-detection orientation now use this rotation.")
                print("Use the setting where a1 is bottom-left and h8 is top-right in the top-down board.")

            elif key == ord("f"):
                camera.flip_labels = not camera.flip_labels
                print(f"Flip labels 180 deg: {camera.flip_labels}")

            elif key == ord("h"):
                show_help_text = not show_help_text
                print(f"Help text on live image: {show_help_text}")
                print("Square names stay visible. Only the large help/status text is toggled.")

            elif key == ord("l"):
                print()
                print("Legal moves:")
                print(", ".join(move.uci() for move in board.legal_moves))

            elif key in (13, 10):
                process_capture_step(source="keyboard")

            # Process commands received from the local control API.
            while True:
                try:
                    command = control_queue.get_nowait()
                except Empty:
                    break

                action = command.get("action")
                source = command.get("source", "api")

                if action == "capture":
                    process_capture_step(source=source)

                elif action == "set_manual_corners":
                    manual_board_corners = command.get("manual_corners")
                    manual_click_mode = False
                    manual_click_points = []
                    board_rotation = "none"
                    camera.flip_labels = False
                    if manual_board_corners is not None:
                        camera.current_corners = manual_corners_to_array(manual_board_corners)
                        if hasattr(camera, "lock_corners"):
                            camera.lock_corners()
                        print_manual_corners(manual_board_corners)
                        if state == "BORDER_CALIBRATION":
                            state = "SETUP_PIECES"
                            print("[API] Manual corners set and locked. Put pieces, then POST /move-done to save baseline.")
                        else:
                            print("[API] Manual corners set. Captures will use these locked corners.")

                elif action == "clear_manual_corners":
                    manual_board_corners = None
                    manual_click_mode = False
                    manual_click_points = []
                    camera.reset_detection()
                    state = "BORDER_CALIBRATION"
                    previous_top_down = None
                    human_top_down = None
                    expected_stockfish_move = None
                    pending_api_result = None
                    print("[API] Manual/locked corners cleared. Back to empty-board calibration.")

                elif action == "rotate":
                    board_rotation = next_board_rotation(board_rotation)
                    print(f"[API] Board image rotation: {board_rotation}")

                elif action == "flip":
                    camera.flip_labels = not camera.flip_labels
                    print(f"[API] Flip labels 180 deg: {camera.flip_labels}")

                elif action == "help":
                    show_help_text = not show_help_text
                    print(f"[API] Help text on live image: {show_help_text}")

                elif action == "force_detect":
                    print("[API] Forcing chessboard detection...")
                    ok = camera.update(frame, force_detect=True)
                    if ok and state == "BORDER_CALIBRATION":
                        state = "SETUP_PIECES"
                        print("[API] Board detected and corners locked. Put pieces, then POST /move-done.")
                    else:
                        print("[API] Board detected." if ok else "[API] Board detection failed.")

                elif action == "reset":
                    manual_board_corners = None
                    manual_click_mode = False
                    manual_click_points = []
                    camera.reset_detection()
                    state = "BORDER_CALIBRATION"
                    previous_top_down = None
                    human_top_down = None
                    expected_stockfish_move = None
                    pending_api_result = None
                    print("[API] Board detection reset. Back to Step 1: empty-board calibration.")

                elif action == "quit":
                    print("[API] Quit requested.")
                    should_quit = True

            update_status()

            if should_quit:
                break

    finally:
        with status_lock:
            status_data["running"] = False
            status_data["state"] = "STOPPED"

        try:
            control_server.shutdown()
            control_server.server_close()
        except Exception:
            pass

        try:
            camera.led_off()
        except Exception:
            pass

        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()