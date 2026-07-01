import os

import cv2
import numpy as np
from pathlib import Path
from datetime import datetime

import chess

from kinect_board_camera import KinectBoardCamera


LIB_DIR = os.getenv("LIB_DIR", "/usr/lib/x86_64-linux-gnu")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "captures_legal_compare")

BOARD_SIZE = 800
SQUARE_SIZE = BOARD_SIZE // 8

WINDOW_LIVE = "Live Kinect Chessboard"
WINDOW_TOP_DOWN = "Top Down Board"
WINDOW_RESULT = "Detected Legal Move Result"

USE_HIGH_QUALITY = True

# Tune this if detection is too sensitive or not sensitive enough.
MIN_CHANGE_THRESHOLD = 12.0


def square_label(row: int, col: int, flip_labels: bool = False) -> str:
    files = "abcdefgh"

    if not flip_labels:
        file_char = files[col]
        rank = 8 - row
    else:
        file_char = files[7 - col]
        rank = row + 1

    return f"{file_char}{rank}"


def square_rect(row: int, col: int, margin_ratio: float = 0.18):
    x1 = col * SQUARE_SIZE
    y1 = row * SQUARE_SIZE
    x2 = x1 + SQUARE_SIZE
    y2 = y1 + SQUARE_SIZE

    margin = int(SQUARE_SIZE * margin_ratio)

    return (
        x1 + margin,
        y1 + margin,
        x2 - margin,
        y2 - margin,
    )


def get_square_crop(board_image, row: int, col: int, margin_ratio: float = 0.18):
    x1, y1, x2, y2 = square_rect(row, col, margin_ratio)
    return board_image[y1:y2, x1:x2]


def square_difference_score(previous_square, current_square) -> float:
    prev_gray = cv2.cvtColor(previous_square, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(current_square, cv2.COLOR_BGR2GRAY)

    prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 0)
    curr_gray = cv2.GaussianBlur(curr_gray, (5, 5), 0)

    diff = cv2.absdiff(prev_gray, curr_gray)

    return float(np.mean(diff))


def occupancy_score(square_image) -> float:
    """
    Rough estimate of whether a square contains a piece.

    Higher score usually means:
        more edges / more texture / likely piece
    """
    gray = cv2.cvtColor(square_image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    edges = cv2.Canny(gray, 50, 120)

    texture_score = float(np.std(gray))
    edge_score = float(np.mean(edges > 0)) * 80.0

    return texture_score + edge_score


def compare_board_images(previous_board, current_board, flip_labels: bool = False):
    scores = []

    for row in range(8):
        for col in range(8):
            previous_square = get_square_crop(previous_board, row, col)
            current_square = get_square_crop(current_board, row, col)

            diff_score = square_difference_score(previous_square, current_square)

            previous_occupancy = occupancy_score(previous_square)
            current_occupancy = occupancy_score(current_square)
            occupancy_delta = current_occupancy - previous_occupancy

            label = square_label(row, col, flip_labels)

            scores.append(
                {
                    "square": label,
                    "row": row,
                    "col": col,
                    "diff_score": diff_score,
                    "previous_occupancy": previous_occupancy,
                    "current_occupancy": current_occupancy,
                    "occupancy_delta": occupancy_delta,
                }
            )

    diff_values = np.array([item["diff_score"] for item in scores], dtype=np.float32)

    median = float(np.median(diff_values))
    mad = float(np.median(np.abs(diff_values - median)))
    auto_threshold = median + 5.0 * mad

    threshold = max(MIN_CHANGE_THRESHOLD, auto_threshold)

    changed = [
        item for item in scores
        if item["diff_score"] >= threshold
    ]

    changed.sort(key=lambda item: item["diff_score"], reverse=True)

    # Normal move/capture usually changes 2 squares.
    # Castling changes 4 squares.
    # En passant can change 3 squares.
    if len(changed) > 6:
        changed = changed[:6]

    image_guess = estimate_move_from_changed_squares(changed)

    return {
        "threshold": threshold,
        "changed": changed,
        "estimated_move": image_guess,
        "legal_move": None,
        "legal_san": None,
        "legal_candidates": [],
        "all_scores": sorted(scores, key=lambda item: item["diff_score"], reverse=True),
    }


def estimate_move_from_changed_squares(changed):
    """
    Image-only guess.

    This is useful for debugging, but the legal move detector below
    is more important.
    """
    if len(changed) < 2:
        return None

    from_candidate = min(changed, key=lambda item: item["occupancy_delta"])
    to_candidate = max(changed, key=lambda item: item["occupancy_delta"])

    from_square = from_candidate["square"]
    to_square = to_candidate["square"]

    if from_square == to_square:
        from_square = changed[0]["square"]
        to_square = changed[1]["square"]

    return f"{from_square}{to_square}"


def expected_changed_squares_for_move(board: chess.Board, move: chess.Move) -> set[str]:
    """
    Returns the squares expected to visually change for a legal move.

    Normal move:
        from, to

    Castling:
        king from, king to, rook from, rook to

    En passant:
        from, to, captured pawn square
    """
    changed = {
        chess.square_name(move.from_square),
        chess.square_name(move.to_square),
    }

    if board.is_castling(move):
        rank = chess.square_rank(move.from_square)

        # Kingside castling: king goes to g-file.
        if chess.square_file(move.to_square) == 6:
            rook_from = chess.square(7, rank)
            rook_to = chess.square(5, rank)

        # Queenside castling: king goes to c-file.
        else:
            rook_from = chess.square(0, rank)
            rook_to = chess.square(3, rank)

        changed.add(chess.square_name(rook_from))
        changed.add(chess.square_name(rook_to))

    if board.is_en_passant(move):
        if board.turn == chess.WHITE:
            captured_square = move.to_square - 8
        else:
            captured_square = move.to_square + 8

        changed.add(chess.square_name(captured_square))

    return changed


def infer_legal_move_from_changed_squares(
    board: chess.Board,
    changed,
    image_guess: str | None = None,
):
    changed_by_square = {
        item["square"]: item
        for item in changed
    }

    changed_squares = set(changed_by_square.keys())

    if len(changed_squares) < 2:
        return {
            "move": None,
            "san": None,
            "candidates": [],
            "reason": "Not enough changed squares.",
        }

    candidates = []

    for move in board.legal_moves:
        expected = expected_changed_squares_for_move(board, move)

        matched = expected & changed_squares
        missing = expected - changed_squares
        extra = changed_squares - expected

        # Normal move needs 2 squares.
        # Castling/en passant should match at least 3 if possible.
        if len(expected) <= 2:
            min_required = 2
        else:
            min_required = min(3, len(expected))

        if len(matched) < min_required:
            continue

        score = 0.0

        score += len(matched) * 10.0
        score -= len(missing) * 6.0
        score -= len(extra) * 1.0

        if expected.issubset(changed_squares):
            score += 5.0

        from_square = chess.square_name(move.from_square)
        to_square = chess.square_name(move.to_square)

        from_item = changed_by_square.get(from_square)
        to_item = changed_by_square.get(to_square)

        # Usually the source square becomes less occupied.
        if from_item is not None and from_item["occupancy_delta"] < 0:
            score += 3.0

        # Usually the destination square changes strongly.
        if to_item is not None:
            score += 2.0

            # If destination was empty before, occupancy often increases.
            if to_item["occupancy_delta"] > 0:
                score += 2.0

        # If the image-only guess agrees, give a small boost.
        if image_guess:
            if move.uci()[:4] == image_guess[:4]:
                score += 2.5

        candidates.append(
            {
                "score": score,
                "move": move,
                "uci": move.uci(),
                "san": board.san(move),
                "expected": expected,
                "matched": matched,
                "missing": missing,
                "extra": extra,
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)

    if not candidates:
        return {
            "move": None,
            "san": None,
            "candidates": [],
            "reason": "No legal move matched the changed squares.",
        }

    best_score = candidates[0]["score"]
    best_candidates = [
        item for item in candidates
        if abs(item["score"] - best_score) < 0.001
    ]

    # Promotion moves may have same changed squares:
    # e7e8q, e7e8r, e7e8b, e7e8n.
    # For now, prefer queen if promotion is ambiguous.
    queen_candidates = [
        item for item in best_candidates
        if item["move"].promotion == chess.QUEEN
    ]

    if queen_candidates:
        chosen = queen_candidates[0]
    else:
        chosen = best_candidates[0]

    return {
        "move": chosen["uci"],
        "san": chosen["san"],
        "candidates": candidates[:5],
        "reason": "Matched legal move.",
    }


def draw_result_image(current_board, comparison_result):
    output = current_board.copy()

    changed = comparison_result["changed"]
    image_guess = comparison_result.get("estimated_move")
    legal_move = comparison_result.get("legal_move")
    legal_san = comparison_result.get("legal_san")

    for item in changed:
        row = item["row"]
        col = item["col"]
        square = item["square"]

        x1 = col * SQUARE_SIZE
        y1 = row * SQUARE_SIZE
        x2 = x1 + SQUARE_SIZE
        y2 = y1 + SQUARE_SIZE

        cv2.rectangle(
            output,
            (x1, y1),
            (x2, y2),
            (0, 255, 255),
            5,
        )

        cv2.putText(
            output,
            square,
            (x1 + 10, y1 + 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 0, 255),
            2,
        )

    cv2.rectangle(output, (0, 0), (BOARD_SIZE, 90), (0, 0, 0), -1)

    line1 = f"Legal move: {legal_move or 'None'}"
    if legal_san:
        line1 += f"  ({legal_san})"

    line2 = f"Image guess: {image_guess or 'None'}"

    cv2.putText(
        output,
        line1,
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 255),
        2,
    )

    cv2.putText(
        output,
        line2,
        (20, 72),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
    )

    return output


def save_capture(prefix: str, top_down_image, overlay_image=None):
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    top_down_path = output_dir / f"{prefix}_{timestamp}_top_down.png"
    cv2.imwrite(str(top_down_path), top_down_image)

    overlay_path = None

    if overlay_image is not None:
        overlay_path = output_dir / f"{prefix}_{timestamp}_overlay.png"
        cv2.imwrite(str(overlay_path), overlay_image)

    return top_down_path, overlay_path


def save_result_image(result_image):
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = output_dir / f"move_result_{timestamp}.png"

    cv2.imwrite(str(result_path), result_image)

    return result_path


def resize_for_display(image, max_width=960):
    height, width = image.shape[:2]

    if width <= max_width:
        return image

    scale = max_width / width
    new_width = int(width * scale)
    new_height = int(height * scale)

    return cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)


def draw_live_instructions(display, board: chess.Board):
    turn_text = "White to move" if board.turn == chess.WHITE else "Black to move"

    lines = [
        f"Chess state: {turn_text}",
        "ENTER = reset detection, capture board, save / compare",
        "c = force board detection",
        "r = reset board detection",
        "f = flip labels",
        "l = print legal moves",
        "n = reset chess game state",
        "q = quit",
    ]

    y = 28

    for index, line in enumerate(lines):
        if index == 0:
            color = (255, 255, 255) if board.turn == chess.WHITE else (80, 80, 80)
            bg = (0, 0, 0) if board.turn == chess.WHITE else (255, 255, 255)

            cv2.rectangle(display, (8, y - 22), (330, y + 8), bg, -1)
        else:
            color = (255, 255, 255)

        cv2.putText(
            display,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
        )

        y += 26

    return display


def print_comparison_result(result):
    changed = result["changed"]
    image_guess = result["estimated_move"]
    legal_move = result["legal_move"]
    legal_san = result["legal_san"]
    candidates = result["legal_candidates"]

    print()
    print("Changed squares:")

    if not changed:
        print("  No clear changed squares detected.")
    else:
        for item in changed:
            print(
                f"  {item['square']}: "
                f"diff={item['diff_score']:.2f}, "
                f"occupancy_delta={item['occupancy_delta']:.2f}"
            )

    print(f"Threshold: {result['threshold']:.2f}")
    print(f"Image-only guess: {image_guess}")
    print(f"Confirmed legal move: {legal_move}")
    print(f"SAN: {legal_san}")

    if candidates:
        print()
        print("Top legal candidates:")
        for candidate in candidates:
            print(
                f"  {candidate['uci']} "
                f"({candidate['san']}), "
                f"score={candidate['score']:.2f}, "
                f"expected={sorted(candidate['expected'])}"
            )


def ask_starting_board() -> chess.Board:
    print()
    print("Chess board state setup")
    print("=======================")
    print("Press Enter for normal starting position.")
    print("Or paste a FEN if your physical board is not in the starting position.")
    print()

    fen = input("Starting FEN [standard]: ").strip()

    if not fen:
        return chess.Board()

    try:
        return chess.Board(fen)
    except ValueError:
        print("Invalid FEN. Using standard starting position.")
        return chess.Board()


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


def main():
    camera = KinectBoardCamera(
        lib_dir=LIB_DIR,
        use_high_quality=USE_HIGH_QUALITY,
        board_size=BOARD_SIZE,
    )

    board = ask_starting_board()

    previous_top_down = None
    capture_count = 0

    try:
        camera.start()

        cv2.namedWindow(WINDOW_LIVE, cv2.WINDOW_NORMAL)
        cv2.namedWindow(WINDOW_TOP_DOWN, cv2.WINDOW_NORMAL)
        cv2.namedWindow(WINDOW_RESULT, cv2.WINDOW_NORMAL)

        print()
        print("Live Kinect legal move comparison started.")
        print()
        print("Controls:")
        print("  ENTER = reset board detection, capture, compare, confirm legal move")
        print("  c     = force chessboard detection")
        print("  r     = reset chessboard detection")
        print("  f     = flip board labels")
        print("  l     = print legal moves")
        print("  n     = reset chess game state")
        print("  q     = quit")
        print()
        print("Important: click/focus the OpenCV live window before pressing keys.")
        print()

        print_board_state(board)

        while True:
            frame = camera.get_rgb_frame()

            camera.update(frame, force_detect=False)

            display = frame.copy()

            if camera.current_corners is not None:
                display = camera.draw_chessboard_grid(display)

            display = resize_for_display(display)
            draw_live_instructions(display, board)

            cv2.imshow(WINDOW_LIVE, display)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

            elif key == ord("c"):
                print("Forcing chessboard detection...")
                ok = camera.update(frame, force_detect=True)

                if ok:
                    print("Board detected.")
                else:
                    print("Board detection failed.")

            elif key == ord("r"):
                camera.reset_detection()
                print("Detection reset.")

            elif key == ord("f"):
                camera.flip_labels = not camera.flip_labels
                print(f"Flip labels: {camera.flip_labels}")

            elif key == ord("l"):
                print()
                print("Legal moves:")
                print(", ".join(move.uci() for move in board.legal_moves))

            elif key == ord("n"):
                board = chess.Board()
                previous_top_down = None
                capture_count = 0
                print()
                print("Chess game state reset.")
                print("Press ENTER to capture a new initial board image.")
                print_board_state(board)

            elif key in (13, 10):  # Enter key
                print()
                print("ENTER pressed -> resetting board detection and capturing fresh board...")

                if board.is_game_over():
                    print(f"Game is already over: {board.result()}")
                    continue

                capture_count += 1

                try:
                    top_down, captured_frame = camera.capture_top_down_board(
                        force_redetect=True,
                        stable_frames=5,
                    )

                    overlay = camera.draw_chessboard_grid(captured_frame.copy())

                except Exception as e:
                    print(f"Could not capture board after reset: {e}")
                    print("Make sure the board is clearly visible, then try again.")
                    continue

                cv2.imshow(WINDOW_TOP_DOWN, top_down)

                if previous_top_down is None:
                    top_path, overlay_path = save_capture(
                        prefix=f"capture_{capture_count:03d}_initial",
                        top_down_image=top_down,
                        overlay_image=overlay,
                    )

                    previous_top_down = top_down.copy()

                    print("Initial board saved after fresh re-detection.")
                    print(f"Top-down: {top_path}")
                    print(f"Overlay:   {overlay_path}")
                    print("Now move the side whose turn it is, then press ENTER again.")
                    print_board_state(board)

                else:
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

                    top_path, overlay_path = save_capture(
                        prefix=f"capture_{capture_count:03d}_new",
                        top_down_image=top_down,
                        overlay_image=overlay,
                    )

                    result_path = save_result_image(result_image)

                    cv2.imshow(WINDOW_RESULT, result_image)

                    print("New board saved and compared after fresh re-detection.")
                    print(f"Top-down: {top_path}")
                    print(f"Overlay:   {overlay_path}")
                    print(f"Result:    {result_path}")

                    print_comparison_result(comparison)

                    legal_move = comparison["legal_move"]

                    if legal_move is None:
                        print()
                        print("No legal move confirmed.")
                        print("The chess state was NOT updated.")
                        print("The previous image was NOT updated.")
                        print("Fix the board/detection and press ENTER again.")
                        continue

                    try:
                        move = chess.Move.from_uci(legal_move)
                        board.push(move)

                    except ValueError:
                        print()
                        print(f"Internal error: could not push move {legal_move}")
                        continue

                    # Only update reference image after a legal move is confirmed.
                    previous_top_down = top_down.copy()

                    print()
                    print(f"Move accepted: {legal_move} ({comparison['legal_san']})")
                    print_board_state(board)

    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()