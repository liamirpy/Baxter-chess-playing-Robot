#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import print_function
import argparse
import os

import sys
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import rospy

from chess_board import ChessBoard, PIECE_TYPES, normalize_piece
from baxter_motion import BaxterChessArm


def default_config_path(limb):
    return os.path.expanduser("~/.baxter_chess/board_{}.json".format(limb))


def main():
    parser = argparse.ArgumentParser(description="Move one chess piece from one square to another using Baxter.")
    parser.add_argument("--limb", choices=["left", "right"], default="left")
    parser.add_argument("--from-square", required=True, help="Example: e2")
    parser.add_argument("--to-square", required=True, help="Example: e4")
    parser.add_argument("--piece", choices=PIECE_TYPES, default="pawn", help="Piece being moved; controls Z grasp height.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--speed", type=float, default=0.20)
    parser.add_argument("--capture", action="store_true", help="First remove the piece currently on --to-square to captured_area.")
    parser.add_argument("--captured-piece", choices=PIECE_TYPES, default=None,
                        help="Piece currently on --to-square. If omitted, uses --piece.")
    parser.add_argument("--home", default="home",
                        help="Named calibrated pose to move to after the move. Default: home.")
    parser.add_argument("--no-home", action="store_true",
                        help="Do not move to a rest/home pose after finishing the move.")
    parser.add_argument("--pre-open", type=float, default=None,
                        help="Override pre-open gripper position for this moving piece only, 0=closed, 100=fully open.")
    parser.add_argument("--captured-pre-open", type=float, default=None,
                        help="Override pre-open gripper position for the captured piece only.")
    parser.add_argument("--release-open", type=float, default=None,
                        help="Override release-open gripper position after placing/dropping.")
    args = parser.parse_args()

    rospy.init_node("baxter_chess_move_piece")
    board = ChessBoard.from_file(args.config or default_config_path(args.limb))
    if args.release_open is not None:
        board.gripper_release_open_position = float(args.release_open)
    robot = BaxterChessArm(args.limb, speed=args.speed)
    robot.enable_robot()

    piece = normalize_piece(args.piece)
    captured_piece = normalize_piece(args.captured_piece or args.piece)
    if args.pre_open is not None:
        board.piece_gripper_pre_open[piece] = float(args.pre_open)
    if args.captured_pre_open is not None:
        board.piece_gripper_pre_open[captured_piece] = float(args.captured_pre_open)

    print("Piece: {} height={:.1f} mm, z_offset={:.1f} mm, pre_open={:.1f}".format(
        piece, board.piece_height(piece) * 1000.0, board.piece_z_offset(piece) * 1000.0,
        board.gripper_pre_open_for_piece(piece)))

    if args.capture:
        print("Capture enabled: removing {} from {} first.".format(captured_piece, args.to_square))
        print("Captured piece height={:.1f} mm, z_offset={:.1f} mm, pre_open={:.1f}".format(
            board.piece_height(captured_piece) * 1000.0, board.piece_z_offset(captured_piece) * 1000.0,
            board.gripper_pre_open_for_piece(captured_piece)))
        if not robot.remove_piece_to_captured_area(board, args.to_square, piece=captured_piece):
            raise RuntimeError("Failed while removing captured piece from {}.".format(args.to_square))

    print("Moving {} {} -> {}".format(piece, args.from_square, args.to_square))
    ok = robot.move_piece(board, args.from_square, args.to_square, piece=piece)
    if not ok:
        raise RuntimeError("Move failed. Check IK, board calibration, piece height, and gripper.")

    if not args.no_home:
        if board.has_named_pose(args.home):
            print("Moving to {} pose after move".format(args.home))
            if not robot.move_to_calibrated_pose(board, args.home):
                raise RuntimeError("Move succeeded, but could not move to {} pose. Recalibrate home or use --no-home.".format(args.home))
        else:
            print("Move complete, but no '{}' pose is saved. Run calibrate_home.py or use --no-home.".format(args.home))
    print("Move complete")


if __name__ == "__main__":
    main()
