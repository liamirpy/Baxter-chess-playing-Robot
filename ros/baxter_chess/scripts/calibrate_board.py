#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import print_function
import argparse
import json
import os
import time


import sys
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import rospy
import baxter_interface

from chess_board import (
    DEFAULT_PIECE_HEIGHTS_M, PIECE_TYPES, normalize_piece,
    DEFAULT_GRIPPER_PRE_OPEN_POSITION, DEFAULT_GRIPPER_RELEASE_OPEN_POSITION,
    DEFAULT_GRIPPER_CLOSED_POSITION, DEFAULT_PIECE_GRIPPER_PRE_OPEN
)

try:
    input_fn = raw_input
except NameError:
    input_fn = input


def default_config_path(limb):
    return os.path.expanduser("~/.baxter_chess/board_{}.json".format(limb))


def pose_to_dict(pose):
    p = pose["position"]
    q = pose["orientation"]
    return {
        "position": [p.x, p.y, p.z],
        "orientation": [q.x, q.y, q.z, q.w]
    }


def capture_pose(limb, name, instructions):
    print("\n=== Calibrate {} ===".format(name))
    print(instructions)
    print("Move Baxter's gripper to the target pose, then press Enter here.")
    input_fn("Press Enter to record {}...".format(name))
    pose = pose_to_dict(limb.endpoint_pose())
    print("Recorded {} position: {:.4f}, {:.4f}, {:.4f}".format(
        name, pose["position"][0], pose["position"][1], pose["position"][2]))
    return pose


def parse_piece_height_overrides(values):
    heights = dict(DEFAULT_PIECE_HEIGHTS_M)
    for value in values:
        if "=" not in value:
            raise ValueError("Bad --piece-height '{}'. Use format piece=meters, e.g. king=0.085".format(value))
        piece, height = value.split("=", 1)
        piece = normalize_piece(piece)
        heights[piece] = float(height)
    return heights




def parse_piece_gripper_pre_open_overrides(values):
    positions = dict(DEFAULT_PIECE_GRIPPER_PRE_OPEN)
    for value in values:
        if "=" not in value:
            raise ValueError("Bad --piece-gripper-pre-open '{}'. Use format piece=value, e.g. pawn=35".format(value))
        piece, pos = value.split("=", 1)
        piece = normalize_piece(piece)
        positions[piece] = float(pos)
    return positions

def main():
    parser = argparse.ArgumentParser(description="Calibrate Baxter chessboard a1/h1/a8 points.")
    parser.add_argument("--limb", choices=["left", "right"], default="left")
    parser.add_argument("--output", default=None, help="Config JSON path. Default: ~/.baxter_chess/board_<limb>.json")
    parser.add_argument("--hover-height", type=float, default=0.12, help="Meters above pickup/place pose for safe travel.")
    parser.add_argument("--captured-area", action="store_true", help="Also record one off-board captured-piece drop pose.")
    parser.add_argument("--reference-piece", choices=PIECE_TYPES, default="pawn",
                        help="Piece used when recording a1/h1/a8 grasp height. Default: pawn.")
    parser.add_argument("--grasp-fraction", type=float, default=0.45,
                        help="Fraction of piece height where the gripper closes. Example: 0.45 means slightly below middle.")
    parser.add_argument("--piece-height", action="append", default=[],
                        help="Override one measured piece height in meters, e.g. --piece-height king=0.087. Can be repeated.")
    parser.add_argument("--gripper-pre-open", type=float, default=DEFAULT_GRIPPER_PRE_OPEN_POSITION,
                        help="Default electric gripper opening before picking, 0=closed, 100=fully open. Default: %(default)s")
    parser.add_argument("--gripper-release-open", type=float, default=DEFAULT_GRIPPER_RELEASE_OPEN_POSITION,
                        help="Electric gripper opening after placing/releasing, 0=closed, 100=fully open. Default: %(default)s")
    parser.add_argument("--piece-gripper-pre-open", action="append", default=[],
                        help="Override pre-open amount for one piece, e.g. pawn=32 or queen=52. Can be repeated.")
    args = parser.parse_args()

    rospy.init_node("baxter_chess_calibrate_board")
    limb = baxter_interface.Limb(args.limb)
    reference_piece = normalize_piece(args.reference_piece)
    piece_heights = parse_piece_height_overrides(args.piece_height)
    piece_gripper_pre_open = parse_piece_gripper_pre_open_overrides(args.piece_gripper_pre_open)

    print("\nIMPORTANT:")
    print("1) Tape/fix the chessboard so it cannot move after calibration.")
    print("2) Put the gripper in the SAME orientation for a1, h1, and a8.")
    print("3) Record a1/h1/a8 at the height where the fingers should close around a {}.".format(reference_piece))
    print("4) The code will raise/lower Z for other pieces using their heights.")
    print("5) Do NOT record too low if that would make the gripper hit the board.")
    print("\nPiece heights currently configured:")
    for p in PIECE_TYPES:
        print("  {:>6s}: {:5.1f} mm".format(p, piece_heights[p] * 1000.0))
    print("Grasp fraction: {:.2f}".format(args.grasp_fraction))
    print("Gripper pre-open before picking: {:.1f} (0=closed, 100=fully open)".format(args.gripper_pre_open))
    print("Gripper release-open after placing: {:.1f}".format(args.gripper_release_open))
    print("Piece-specific pre-open positions:")
    for p in PIECE_TYPES:
        print("  {:>6s}: {:5.1f}".format(p, piece_gripper_pre_open[p]))

    a1 = capture_pose(limb, "a1", "Center of square a1 at {} grasp height.".format(reference_piece))
    h1 = capture_pose(limb, "h1", "Center of square h1 at the same {} grasp height.".format(reference_piece))
    a8 = capture_pose(limb, "a8", "Center of square a8 at the same {} grasp height.".format(reference_piece))

    config = {
        "limb": args.limb,
        "frame_id": "base",
        "created_at_unix": time.time(),
        "hover_height": args.hover_height,
        "reference_piece": reference_piece,
        "grasp_fraction": args.grasp_fraction,
        "piece_heights": piece_heights,
        "piece_z_bias": {
            "pawn": 0.0,
            "rook": 0.0,
            "knight": 0.0,
            "bishop": 0.0,
            "queen": 0.0,
            "king": 0.0
        },
        "gripper_pre_open_position": args.gripper_pre_open,
        "gripper_release_open_position": args.gripper_release_open,
        "gripper_closed_position": DEFAULT_GRIPPER_CLOSED_POSITION,
        "piece_gripper_pre_open": piece_gripper_pre_open,
        "a1": a1,
        "h1": h1,
        "a8": a8,
        "orientation": a1["orientation"],
        "notes": "a1/h1/a8 positions are square centers at reference-piece grasp height. Piece-specific heights are applied as Z offsets. Electric gripper positions use 0=closed and 100=fully open."
    }

    if args.captured_area:
        captured = capture_pose(limb, "captured_area",
                                "Off-board place where captured pieces should be dropped, at {} grasp height.".format(reference_piece))
        config["captured_area"] = captured

    output = args.output or default_config_path(args.limb)
    output = os.path.expanduser(output)
    parent = os.path.dirname(output)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(output, "w") as f:
        json.dump(config, f, indent=2, sort_keys=True)
    print("\nSaved calibration to: {}".format(output))
    print("Next test: rosrun baxter_chess test_square.py --limb {} --square e4 --piece pawn --config {}".format(args.limb, output))
    print("Try a taller piece hover: rosrun baxter_chess test_square.py --limb {} --square e4 --piece king --config {}".format(args.limb, output))


if __name__ == "__main__":
    main()
