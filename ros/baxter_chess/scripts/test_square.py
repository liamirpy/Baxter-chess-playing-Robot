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
    parser = argparse.ArgumentParser(description="Move Baxter above a chess square without picking anything.")
    parser.add_argument("--limb", choices=["left", "right"], default="left")
    parser.add_argument("--square", default="e4")
    parser.add_argument("--piece", choices=PIECE_TYPES, default="pawn", help="Piece type used to calculate grasp Z height.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--speed", type=float, default=0.20)
    parser.add_argument("--extra-hover", type=float, default=0.05, help="Extra meters above normal hover for first tests.")
    args = parser.parse_args()

    rospy.init_node("baxter_chess_test_square")
    board = ChessBoard.from_file(args.config or default_config_path(args.limb))
    robot = BaxterChessArm(args.limb, speed=args.speed)
    robot.enable_robot()

    piece = normalize_piece(args.piece)
    base_pos = board.square_to_position(args.square)
    pos = board.square_to_grasp_position(args.square, piece)
    hover = board.hover_position(pos, extra=args.extra_hover)
    print("{} reference target: {:.4f}, {:.4f}, {:.4f}".format(args.square, base_pos[0], base_pos[1], base_pos[2]))
    print("{} {} grasp target: {:.4f}, {:.4f}, {:.4f}".format(args.square, piece, pos[0], pos[1], pos[2]))
    print("Piece height={:.1f} mm, z_offset={:.1f} mm".format(
        board.piece_height(piece) * 1000.0, board.piece_z_offset(piece) * 1000.0))
    print("Moving to safe hover: {:.4f}, {:.4f}, {:.4f}".format(hover[0], hover[1], hover[2]))
    ok = robot.move_to_board_position(board, hover)
    if not ok:
        raise RuntimeError("Could not move to square hover. Check calibration/orientation/reachability.")
    print("Done. If it is centered, rerun with --extra-hover 0.0, then test move_piece.py.")


if __name__ == "__main__":
    main()
