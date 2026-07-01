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


def main():
    parser = argparse.ArgumentParser(description="Add or update a Baxter chess rest/home pose in the board calibration JSON.")
    parser.add_argument("--limb", choices=["left", "right"], default="left")
    parser.add_argument("--config", default=None, help="Config JSON path. Default: ~/.baxter_chess/board_<limb>.json")
    parser.add_argument("--name", default="home", help="Name of saved pose. Default: home")
    args = parser.parse_args()

    rospy.init_node("baxter_chess_calibrate_home")
    config_path = os.path.expanduser(args.config or default_config_path(args.limb))

    if not os.path.exists(config_path):
        raise RuntimeError("Config file not found: {}. Run calibrate_board.py first.".format(config_path))

    with open(config_path, "r") as f:
        config = json.load(f)

    limb = baxter_interface.Limb(args.limb)
    print("\n=== Calibrate {} pose ===".format(args.name))
    print("Move Baxter's {} gripper to a safe rest position after chess moves.".format(args.limb))
    print("Recommended: above and outside the board, not blocking the camera/player, with a comfortable elbow/wrist.")
    input_fn("Press Enter to record {} pose...".format(args.name))

    pose = pose_to_dict(limb.endpoint_pose())
    pose["saved_at_unix"] = time.time()
    config[args.name] = pose

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2, sort_keys=True)

    print("Saved {} pose to: {}".format(args.name, config_path))
    print("Position: {:.4f}, {:.4f}, {:.4f}".format(
        pose["position"][0], pose["position"][1], pose["position"][2]))
    print("Test it with:")
    print("  rosrun baxter_chess go_home.py --limb {} --name {}".format(args.limb, args.name))


if __name__ == "__main__":
    main()
