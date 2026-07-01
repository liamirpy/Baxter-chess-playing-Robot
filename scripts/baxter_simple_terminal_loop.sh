#!/usr/bin/env bash

set -u

CONTROL_URL="${CONTROL_URL:-http://127.0.0.1:8765}"
BAXTER_LIMB="${BAXTER_LIMB:-left}"
DRY_RUN="${DRY_RUN:-0}"
AUTO_VERIFY="${AUTO_VERIFY:-1}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-45}"

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ERROR: missing command: $1"
        exit 1
    fi
}

get_status_json() {
    curl -fsS "$CONTROL_URL/status"
}

post_move_done() {
    curl -fsS -X POST "$CONTROL_URL/move-done"
}

json_field() {
    local field="$1"
    python3 -c '
import json, sys
field = sys.argv[1]
raw = sys.stdin.read().strip()
if not raw:
    print(""); sys.exit(0)
try:
    data = json.loads(raw)
except Exception:
    print(""); sys.exit(0)
status = data.get("status", data)
value = status.get(field)
if value is None:
    print("")
elif isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
' "$field"
}

get_field_from_json() {
    local json_text="$1"
    local field="$2"
    printf '%s' "$json_text" | json_field "$field"
}

print_status_summary() {
    local status_json="$1"
    echo "Controller result:"
    echo "  state:                $(get_field_from_json "$status_json" state)"
    echo "  last_capture_ok:      $(get_field_from_json "$status_json" last_capture_ok)"
    echo "  last_capture_message: $(get_field_from_json "$status_json" last_capture_message)"
    echo "  expected move:        $(get_field_from_json "$status_json" expected_stockfish_move)"
}

has_robot_move() {
    local status_json="$1"
    local expected_move robot_move
    expected_move="$(get_field_from_json "$status_json" expected_stockfish_move)"
    robot_move="$(get_field_from_json "$status_json" robot_move)"
    [ -n "$expected_move" ] || [ -n "$robot_move" ]
}

wait_for_capture_to_finish() {
    local old_capture_time="$1"
    local start_time
    start_time="$(date +%s)"

    while true; do
        local status_json new_capture_time now elapsed
        if ! status_json="$(get_status_json 2>/tmp/kinect_status_error.txt)"; then
            echo "ERROR: could not read $CONTROL_URL/status" >&2
            cat /tmp/kinect_status_error.txt >&2
            return 1
        fi
        new_capture_time="$(get_field_from_json "$status_json" last_capture_time)"
        if [ -n "$new_capture_time" ] && [ "$new_capture_time" != "$old_capture_time" ]; then
            printf '%s' "$status_json"
            return 0
        fi
        now="$(date +%s)"
        elapsed=$((now - start_time))
        if [ "$elapsed" -ge "$WAIT_TIMEOUT_SECONDS" ]; then
            echo "ERROR: Timeout waiting for Kinect controller to finish /move-done." >&2
            echo "Last status received:" >&2
            printf '%s\n' "$status_json" >&2
            return 1
        fi
        sleep 0.2
    done
}

send_human_move_done_and_wait() {
    local current_json="$1"
    local old_capture_time
    old_capture_time="$(get_field_from_json "$current_json" last_capture_time)"
    echo >&2
    echo "No robot move pending." >&2
    echo "Sending POST /move-done to detect human/setup step..." >&2
    post_move_done >/dev/null
    wait_for_capture_to_finish "$old_capture_time"
}

check_controller_api() {
    echo "Checking Kinect controller API..."
    local status_json
    if ! status_json="$(get_status_json 2>/tmp/kinect_status_error.txt)"; then
        echo
        echo "ERROR: cannot reach Kinect controller at:"
        echo "  $CONTROL_URL"
        echo
        cat /tmp/kinect_status_error.txt
        echo
        echo "If Kinect controller is on another PC, use:"
        echo "  CONTROL_URL=http://KINECT_PC_IP:8765 ./baxter_simple_terminal_loop_fixed_full.sh"
        exit 1
    fi
    echo "Controller API is reachable."
    echo "Current state: $(get_field_from_json "$status_json" state)"
}

build_baxter_commands_json() {
    local limb="$1"
    python3 -c '
import json, sys
limb = sys.argv[1]
raw = sys.stdin.read().strip()
PIECE_NAMES = {"P":"pawn","N":"knight","B":"bishop","R":"rook","Q":"queen","K":"king","p":"pawn","n":"knight","b":"bishop","r":"rook","q":"queen","k":"king"}
def parse_status(raw_text):
    data = json.loads(raw_text)
    return data.get("status", data)
def expand_fen_board(board_part):
    rows = board_part.split("/")
    board = {}
    for row_index, row_text in enumerate(rows):
        rank = 8 - row_index
        file_index = 0
        for ch in row_text:
            if ch.isdigit():
                file_index += int(ch); continue
            file_char = chr(ord("a") + file_index)
            board[f"{file_char}{rank}"] = ch
            file_index += 1
    return board
def build_commands(status):
    existing = status.get("robot_ros_commands")
    if existing:
        return existing
    move = status.get("robot_move") or status.get("expected_stockfish_move")
    fen = status.get("fen")
    if not move:
        return []
    if not fen:
        raise RuntimeError("Status has robot move but no FEN.")
    fen_parts = fen.split()
    board = expand_fen_board(fen_parts[0])
    en_passant_square = fen_parts[3] if len(fen_parts) >= 4 else "-"
    from_sq, to_sq = move[0:2], move[2:4]
    moving_piece = board.get(from_sq)
    if moving_piece is None:
        raise RuntimeError(f"No piece found on {from_sq}. FEN: {fen}")
    piece_name = PIECE_NAMES.get(moving_piece, "piece")
    if piece_name == "king" and abs(ord(to_sq[0]) - ord(from_sq[0])) == 2:
        rank = from_sq[1]
        king_args = ["--limb", limb, "--from-square", from_sq, "--to-square", to_sq, "--piece", "king"]
        if to_sq[0] == "g":
            rook_from, rook_to = "h" + rank, "f" + rank
        else:
            rook_from, rook_to = "a" + rank, "d" + rank
        rook_args = ["--limb", limb, "--from-square", rook_from, "--to-square", rook_to, "--piece", "rook"]
        return [king_args, rook_args]
    args = ["--limb", limb, "--from-square", from_sq, "--to-square", to_sq, "--piece", piece_name]
    captured_piece = board.get(to_sq)
    if captured_piece is None and piece_name == "pawn" and to_sq == en_passant_square and from_sq[0] != to_sq[0]:
        args.extend(["--capture", "--captured-piece", "pawn"])
    elif captured_piece is not None:
        args.extend(["--capture", "--captured-piece", PIECE_NAMES.get(captured_piece, "piece")])
    return [args]
status = parse_status(raw)
print(json.dumps(build_commands(status)))
' "$limb"
}

commands_json_to_lines() {
    python3 -c '
import json, shlex, sys
commands = json.loads(sys.stdin.read().strip())
for args in commands:
    print("rosrun baxter_chess move_piece.py " + " ".join(shlex.quote(str(x)) for x in args))
'
}

run_one_baxter_command() {
    local args_json="$1"
    python3 -c '
import json, shlex, subprocess, sys
dry_run = sys.argv[1] == "1"
args = json.loads(sys.argv[2])
command = ["rosrun", "baxter_chess", "move_piece.py"] + [str(x) for x in args]
print()
print("Running Baxter command:")
print(" ".join(shlex.quote(x) for x in command))
if dry_run:
    print("DRY RUN: command not executed.")
    sys.exit(0)
subprocess.check_call(command)
' "$DRY_RUN" "$args_json"
}

run_baxter_commands() {
    local commands_json="$1"
    local count index one_args_json
    count="$(printf '%s' "$commands_json" | python3 -c 'import json,sys; print(len(json.loads(sys.stdin.read())))')"
    if [ "$count" -eq 0 ]; then
        echo "No Baxter command available."
        return 1
    fi
    echo
    echo "Baxter command(s):"
    printf '%s' "$commands_json" | commands_json_to_lines | sed 's/^/  /'
    index=0
    while [ "$index" -lt "$count" ]; do
        one_args_json="$(printf '%s' "$commands_json" | python3 -c 'import json,sys; idx=int(sys.argv[1]); print(json.dumps(json.loads(sys.stdin.read())[idx]))' "$index")"
        if ! run_one_baxter_command "$one_args_json"; then
            echo
            echo "Baxter command failed. NOT verifying robot move."
            return 1
        fi
        index=$((index + 1))
    done
    return 0
}

verify_robot_move() {
    echo
    echo "Baxter command succeeded. Automatically verifying robot move with POST /move-done..."
    local before_json old_capture_time verify_json ok
    before_json="$(get_status_json)"
    old_capture_time="$(get_field_from_json "$before_json" last_capture_time)"
    post_move_done >/dev/null
    if ! verify_json="$(wait_for_capture_to_finish "$old_capture_time")"; then
        echo "Verification failed: controller did not finish."
        return 1
    fi
    echo
    echo "Robot verification result:"
    print_status_summary "$verify_json"
    ok="$(get_field_from_json "$verify_json" last_capture_ok)"
    if [ "$ok" != "true" ]; then
        echo
        echo "Robot verification failed."
        echo "The physical board probably does not match the expected robot move."
        echo "Fix the board, then manually call:"
        echo "  curl -X POST $CONTROL_URL/move-done"
        return 1
    fi
    return 0
}

check_requirements() {
    require_command curl
    require_command python3
    require_command rosrun
}

check_requirements
check_controller_api

echo
echo "Simple Baxter Terminal Loop - Fixed Full Version"
echo "================================================"
echo "CONTROL_URL: $CONTROL_URL"
echo "BAXTER_LIMB: $BAXTER_LIMB"
echo "DRY_RUN:     $DRY_RUN"
echo "AUTO_VERIFY: $AUTO_VERIFY"
echo
echo "This script assumes your terminal is already prepared:"
echo "  cd ~/ros_ws"
echo "  source ./baxter.sh"
echo "  source devel/setup.bash"
echo "  export ROS_IP=<BAXTER_PC_ROS_IP>"
echo "  unset ROS_HOSTNAME"
echo
echo "Press ENTER only after the HUMAN move/setup step."

while true; do
    echo
    read -r -p "Press ENTER after HUMAN move/setup step, or Ctrl+C to quit... " _
    if ! local_status_json="$(get_status_json 2>/tmp/kinect_status_error.txt)"; then
        echo "ERROR: cannot read status from $CONTROL_URL"
        cat /tmp/kinect_status_error.txt
        continue
    fi
    echo
    echo "Current controller state: $(get_field_from_json "$local_status_json" state)"
    echo "Current expected move:    $(get_field_from_json "$local_status_json" expected_stockfish_move)"
    if has_robot_move "$local_status_json"; then
        echo
        echo "Robot move already pending. Sending Baxter command now."
        status_for_robot="$local_status_json"
    else
        if ! status_for_robot="$(send_human_move_done_and_wait "$local_status_json")"; then
            echo "Could not process /move-done."
            continue
        fi
        echo
        print_status_summary "$status_for_robot"
        ok="$(get_field_from_json "$status_for_robot" last_capture_ok)"
        if [ "$ok" != "true" ] && ! has_robot_move "$status_for_robot"; then
            echo
            echo "Kinect capture failed or no robot move was produced."
            echo "Fix board/camera and press ENTER again."
            continue
        fi
    fi
    if ! has_robot_move "$status_for_robot"; then
        echo
        echo "No robot move yet. This is normal for calibration/setup steps."
        continue
    fi
    if ! commands_json="$(printf '%s' "$status_for_robot" | build_baxter_commands_json "$BAXTER_LIMB")"; then
        echo
        echo "Could not build Baxter command from status."
        continue
    fi
    if ! run_baxter_commands "$commands_json"; then
        continue
    fi
    if [ "$DRY_RUN" = "1" ]; then
        echo
        echo "DRY_RUN is enabled, so robot did not move. Skipping auto verification."
        continue
    fi
    if [ "$AUTO_VERIFY" = "1" ]; then
        verify_robot_move || true
    fi
done
