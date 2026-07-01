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

from chess_board import ChessBoard
from baxter_motion import BaxterChessArm


def default_config_path(limb):
    return os.path.expanduser("~/.baxter_chess/board_{}.json".format(limb))


def main():
    parser = argparse.ArgumentParser(description="Move Baxter to a saved chess rest/home pose.")
    parser.add_argument("--limb", choices=["left", "right"], default="left")
    parser.add_argument("--config", default=None)
    parser.add_argument("--name", default="home")
    parser.add_argument("--speed", type=float, default=0.20)
    args = parser.parse_args()

    rospy.init_node("baxter_chess_go_home")
    board = ChessBoard.from_file(args.config or default_config_path(args.limb))
    robot = BaxterChessArm(args.limb, speed=args.speed)
    robot.enable_robot()

    if not board.has_named_pose(args.name):
        raise RuntimeError("No '{}' pose saved. Run calibrate_home.py first.".format(args.name))

    print("Moving to {} pose".format(args.name))
    if not robot.move_to_calibrated_pose(board, args.name):
        raise RuntimeError("Could not move to {} pose. Recalibrate it in a reachable position.".format(args.name))
    print("Done")


if __name__ == "__main__":
    main()
