#!/usr/bin/env python3
"""
Baxter Status Bridge

Press ENTER after the human finishes a move.
This script sends POST /move-done to the Kinect controller, waits until the
controller finishes processing, reads robot_ros_commands from GET /status,
and runs rosrun baxter_chess move_piece.py with those arguments.

This script does not calculate chess moves. The Kinect controller status must
already include robot_ros_commands / robot_ros_commands_text.
"""

import argparse
import os
import shlex
import subprocess
import sys
import time

import requests


def get_status(control_url):
    response = requests.get(control_url + "/status", timeout=5)
    response.raise_for_status()
    data = response.json()
    return data.get("status", data)


def send_move_done(control_url):
    response = requests.post(control_url + "/move-done", timeout=5)
    response.raise_for_status()
    return response.json()


def wait_for_controller(control_url, old_capture_time, timeout_seconds=45.0):
    start = time.time()

    while time.time() - start < timeout_seconds:
        status = get_status(control_url)
        new_capture_time = status.get("last_capture_time")

        if new_capture_time and new_capture_time != old_capture_time:
            return status

        time.sleep(0.2)

    raise RuntimeError("Timeout waiting for Kinect controller to finish /move-done.")


def run_baxter_ros_command(ros_ws, ros_ip, ros_args, dry_run=False, source_baxter=True):
    ros_args_text = " ".join(shlex.quote(str(x)) for x in ros_args)

    if source_baxter:
        baxter_line = "source ./baxter.sh"
    else:
        baxter_line = "./baxter.sh"

    command = """
set -e

cd {ros_ws}

{baxter_line}

export ROS_IP={ros_ip}
unset ROS_HOSTNAME

rosrun baxter_chess move_piece.py {ros_args}
""".format(
        ros_ws=shlex.quote(ros_ws),
        baxter_line=baxter_line,
        ros_ip=shlex.quote(ros_ip),
        ros_args=ros_args_text,
    )

    print()
    print("Running Baxter command:")
    print(command)

    if dry_run:
        print("DRY RUN: command not executed.")
        return

    # This waits until move_piece.py finishes. No verify delay is needed.
    subprocess.check_call(["bash", "-lc", command])


def run_robot_commands_from_status(status, args):
    robot_move = status.get("robot_move")
    robot_ros_commands = status.get("robot_ros_commands")

    if not robot_move or not robot_ros_commands:
        print()
        print("No robot command available yet.")
        print("This is normal during calibration/setup steps, or if the human move was not detected.")
        print("Controller state:", status.get("state"))
        return False

    print()
    print("Robot move from controller status:")
    print("  move:           {}".format(status.get("robot_move")))
    print("  from:           {}".format(status.get("robot_from_square")))
    print("  to:             {}".format(status.get("robot_to_square")))
    print("  piece:          {}".format(status.get("robot_piece")))
    print("  capture:        {}".format(status.get("robot_capture")))
    print("  captured piece: {}".format(status.get("robot_captured_piece")))
    print("  castling:       {}".format(status.get("robot_is_castling")))

    print()
    print("Command text from status:")
    for item in status.get("robot_ros_commands_text", []):
        print("  " + str(item))

    for ros_args in robot_ros_commands:
        run_baxter_ros_command(
            ros_ws=args.ros_ws,
            ros_ip=args.ros_ip,
            ros_args=ros_args,
            dry_run=args.dry_run,
            source_baxter=not args.execute_baxter_sh,
        )

    return True


def verify_robot_move(control_url):
    before_verify = get_status(control_url)
    old_verify_time = before_verify.get("last_capture_time")

    print()
    print("Sending POST /move-done to verify robot move...")
    send_move_done(control_url)

    verify_status = wait_for_controller(
        control_url=control_url,
        old_capture_time=old_verify_time,
    )

    print()
    print("Robot verification result:")
    print("  state:                {}".format(verify_status.get("state")))
    print("  last_capture_ok:      {}".format(verify_status.get("last_capture_ok")))
    print("  last_capture_message: {}".format(verify_status.get("last_capture_message")))

    return verify_status


def main():
    parser = argparse.ArgumentParser(
        description="Press ENTER -> /move-done -> read robot command from /status -> run Baxter"
    )

    parser.add_argument(
        "--control-url",
        default="http://127.0.0.1:8765",
        help="Kinect controller URL. If controller is on another PC, use http://KINECT_PC_IP:8765",
    )

    parser.add_argument(
        "--ros-ws",
        default=os.path.expanduser(os.getenv("BAXTER_ROS_WS", "~/ros_ws")),
        help="Path to ros_ws folder containing baxter.sh. Can also be set with BAXTER_ROS_WS.",
    )

    parser.add_argument(
        "--ros-ip",
        default=os.getenv("ROS_IP"),
        help="ROS_IP for Baxter. Can also be set with ROS_IP.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Baxter command but do not execute it.",
    )

    parser.add_argument(
        "--auto-verify",
        action="store_true",
        help="After Baxter command finishes, immediately send /move-done again to verify robot move.",
    )

    parser.add_argument(
        "--execute-baxter-sh",
        action="store_true",
        help="Use ./baxter.sh instead of source ./baxter.sh. Default is source ./baxter.sh.",
    )

    args = parser.parse_args()

    if not args.ros_ip:
        parser.error("--ros-ip is required unless ROS_IP is set in the environment.")

    print("Baxter Status Bridge")
    print("====================")
    print("Kinect controller:", args.control_url)
    print("ROS workspace:    ", args.ros_ws)
    print("ROS_IP:           ", args.ros_ip)
    print("Dry run:          ", args.dry_run)
    print("Baxter setup:     ", "./baxter.sh" if args.execute_baxter_sh else "source ./baxter.sh")
    print()
    print("Workflow:")
    print("  1. Human finishes move.")
    print("  2. Press ENTER here.")
    print("  3. This sends POST /move-done to Kinect.")
    print("  4. Kinect detects human move and updates /status.")
    print("  5. This script reads robot_ros_commands from /status.")
    print("  6. This script runs Baxter command and waits until it finishes.")
    print("  7. With --auto-verify, it immediately sends /move-done again after Baxter finishes.")
    print()

    while True:
        try:
            input("Press ENTER after human move / setup step, or Ctrl+C to quit... ")

            before = get_status(args.control_url)
            old_capture_time = before.get("last_capture_time")

            print()
            print("Sending POST /move-done to Kinect controller...")
            send_move_done(args.control_url)

            status = wait_for_controller(
                control_url=args.control_url,
                old_capture_time=old_capture_time,
            )

            print()
            print("Controller result:")
            print("  state:                {}".format(status.get("state")))
            print("  last_capture_ok:      {}".format(status.get("last_capture_ok")))
            print("  last_capture_message: {}".format(status.get("last_capture_message")))
            print("  expected move:        {}".format(status.get("expected_stockfish_move")))
            print("  robot command:        {}".format(status.get("robot_ros_command")))

            if not status.get("last_capture_ok", False):
                print()
                print("Kinect capture failed or move was not accepted.")
                print("Fix board/camera and press ENTER again.")
                continue

            robot_was_sent = run_robot_commands_from_status(status, args)

            if robot_was_sent and args.auto_verify:
                verify_robot_move(args.control_url)

        except KeyboardInterrupt:
            print()
            print("Exiting.")
            sys.exit(0)

        except subprocess.CalledProcessError as error:
            print()
            print("Baxter command failed:")
            print(error)

        except Exception as error:
            print()
            print("ERROR:")
            print(error)


if __name__ == "__main__":
    main()
