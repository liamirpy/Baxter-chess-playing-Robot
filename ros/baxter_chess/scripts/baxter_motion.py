#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baxter arm motion helpers for chess pick/place.

Uses Baxter's PositionKinematicsNode IK service. Cartesian pose -> joint angles ->
Limb.move_to_joint_positions().
"""

from __future__ import print_function
import struct

import rospy
import baxter_interface
from geometry_msgs.msg import Pose, Point, Quaternion, PoseStamped
from std_msgs.msg import Header
from baxter_core_msgs.srv import SolvePositionIK, SolvePositionIKRequest


class BaxterChessArm(object):
    def __init__(self, limb_name, speed=0.25, hover_pause=0.2, grip_pause=0.6):
        self.limb_name = limb_name
        self.limb = baxter_interface.Limb(limb_name)
        self.gripper = baxter_interface.Gripper(limb_name)
        self.hover_pause = hover_pause
        self.grip_pause = grip_pause
        self.limb.set_joint_position_speed(speed)

        ns = "ExternalTools/{}/PositionKinematicsNode/IKService".format(limb_name)
        self.iksvc = rospy.ServiceProxy(ns, SolvePositionIK)
        rospy.loginfo("Waiting for IK service: %s", ns)
        rospy.wait_for_service(ns, 10.0)
        rospy.loginfo("IK service ready")

    def enable_robot(self):
        rs = baxter_interface.RobotEnable(baxter_interface.CHECK_VERSION)
        if not rs.state().enabled:
            rospy.loginfo("Enabling Baxter")
            rs.enable()

    def _ik_request(self, pose, frame_id="base"):
        hdr = Header(stamp=rospy.Time.now(), frame_id=frame_id)
        ikreq = SolvePositionIKRequest()
        ikreq.pose_stamp.append(PoseStamped(header=hdr, pose=pose))
        try:
            resp = self.iksvc(ikreq)
        except (rospy.ServiceException, rospy.ROSException) as e:
            rospy.logerr("IK service call failed: %s", e)
            return None

        # Baxter SDK returns result_type as a byte string/array.
        try:
            resp_seeds = struct.unpack('<%dB' % len(resp.result_type), resp.result_type)
        except TypeError:
            # Python 3 compatibility fallback if result_type is already a sequence of ints.
            resp_seeds = list(resp.result_type)

        if not resp_seeds or resp_seeds[0] == resp.RESULT_INVALID:
            rospy.logerr("INVALID IK: no solution for pose x=%.3f y=%.3f z=%.3f",
                         pose.position.x, pose.position.y, pose.position.z)
            return None

        return dict(zip(resp.joints[0].name, resp.joints[0].position))

    def move_to_xyz_quat(self, xyz, quat, frame_id="base", timeout=20.0):
        pose = Pose()
        pose.position = Point(x=xyz[0], y=xyz[1], z=xyz[2])
        pose.orientation = Quaternion(x=quat[0], y=quat[1], z=quat[2], w=quat[3])
        joints = self._ik_request(pose, frame_id=frame_id)
        if joints is None:
            return False
        self.limb.move_to_joint_positions(joints, timeout=timeout, threshold=0.008)
        return True

    def move_to_board_position(self, board, position, timeout=20.0):
        return self.move_to_xyz_quat(position, board.orientation, board.frame_id, timeout)

    def move_above(self, board, position, extra=0.0):
        return self.move_to_board_position(board, board.hover_position(position, extra=extra))

    def move_to_calibrated_pose(self, board, name, timeout=20.0):
        """Move to a full pose saved in the calibration JSON.

        This is useful for a rest/home pose after a chess move. Unlike board
        square moves, it uses the saved pose orientation for that named pose.
        """
        pose = board.named_pose(name)
        xyz = pose["position"]
        quat = pose.get("orientation", board.orientation)
        rospy.loginfo("Move to calibrated pose %s at x=%.3f y=%.3f z=%.3f",
                      name, xyz[0], xyz[1], xyz[2])
        return self.move_to_xyz_quat(xyz, quat, board.frame_id, timeout=timeout)

    def command_gripper_position(self, position, label="gripper"):
        """Command Baxter electric gripper position. 0=closed, 100=fully open."""
        position = float(position)
        rospy.loginfo("Command %s to %.1f (0=closed, 100=fully open)", label, position)
        try:
            result = self.gripper.command_position(position, block=True, timeout=5.0)
            if result is False:
                rospy.logwarn("Gripper command to %.1f did not report success", position)
        except Exception as e:
            rospy.logwarn("Gripper command warning: %s", e)
        rospy.sleep(self.grip_pause)

    def open_gripper(self, position=100.0):
        # Use command_position for both full and partial opening so the opening is configurable.
        self.command_gripper_position(position, label="open gripper")

    def close_gripper(self, position=0.0):
        self.command_gripper_position(position, label="close gripper")

    def pick(self, board, position, label="piece", piece=None):
        rospy.loginfo("Pick %s at x=%.3f y=%.3f z=%.3f", label, position[0], position[1], position[2])
        pre_open = board.gripper_pre_open_for_piece(piece)
        self.open_gripper(pre_open)
        if not self.move_above(board, position):
            return False
        rospy.sleep(self.hover_pause)
        if not self.move_to_board_position(board, position):
            return False
        rospy.sleep(self.hover_pause)
        self.close_gripper(board.gripper_closed_position)
        if not self.move_above(board, position):
            return False
        rospy.sleep(self.hover_pause)
        return True

    def place(self, board, position, label="piece", piece=None):
        rospy.loginfo("Place %s at x=%.3f y=%.3f z=%.3f", label, position[0], position[1], position[2])
        if not self.move_above(board, position):
            return False
        rospy.sleep(self.hover_pause)
        if not self.move_to_board_position(board, position):
            return False
        rospy.sleep(self.hover_pause)
        release_open = board.gripper_release_open_for_piece(piece)
        self.open_gripper(release_open)
        if not self.move_above(board, position):
            return False
        rospy.sleep(self.hover_pause)
        return True

    def move_piece(self, board, from_square, to_square, piece="pawn"):
        from_pos = board.square_to_grasp_position(from_square, piece)
        to_pos = board.square_to_grasp_position(to_square, piece)
        label = "{} {}->{}".format(piece, from_square, to_square)
        return self.pick(board, from_pos, label=label, piece=piece) and self.place(board, to_pos, label=label, piece=piece)

    def remove_piece_to_captured_area(self, board, square, piece="pawn"):
        target = board.square_to_grasp_position(square, piece)
        captured = board.named_grasp_position("captured_area", piece)
        label = "captured {} from {}".format(piece, square)
        return self.pick(board, target, label=label, piece=piece) and self.place(board, captured, label=label, piece=piece)
