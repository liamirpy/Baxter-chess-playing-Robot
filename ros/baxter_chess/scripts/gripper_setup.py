#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import print_function
import argparse
import rospy
import baxter_interface


def main():
    parser = argparse.ArgumentParser(description="Calibrate and test a Baxter electric gripper.")
    parser.add_argument("--limb", choices=["left", "right"], default="left")
    args = parser.parse_args()

    rospy.init_node("baxter_chess_gripper_setup")
    rs = baxter_interface.RobotEnable(baxter_interface.CHECK_VERSION)
    if not rs.state().enabled:
        rs.enable()

    gripper = baxter_interface.Gripper(args.limb)
    print("Gripper type: {}".format(gripper.type()))
    if gripper.type() == "electric":
        print("Calibrating electric gripper...")
        ok = gripper.calibrate(block=True, timeout=10.0)
        print("Calibration result: {}".format(ok))
    print("Opening...")
    gripper.open(block=True, timeout=5.0)
    rospy.sleep(1.0)
    print("Closing...")
    gripper.close(block=True, timeout=5.0)
    rospy.sleep(1.0)
    print("Opening again...")
    gripper.open(block=True, timeout=5.0)
    print("Done")


if __name__ == "__main__":
    main()
