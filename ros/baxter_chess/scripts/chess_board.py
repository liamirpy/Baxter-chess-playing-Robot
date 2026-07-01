#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chessboard coordinate mapping for Baxter.

The calibration file stores the end-effector target pose for the centers of a1,
h1, and a8. Any square is computed by interpolation on that board frame:
    square = a1 + file/7*(h1-a1) + rank/7*(a8-a1)
This works even if the board is rotated relative to Baxter's /base frame.

Piece-height support:
The a1/h1/a8 calibration is recorded at the desired grasp height for one
reference piece, by default a pawn. For another piece, Baxter raises/lowers the
Z target by:
    (height(piece) - height(reference_piece)) * grasp_fraction + piece_z_bias
This avoids recalibrating the whole board for every chess piece.
"""

from __future__ import print_function
import json
import os

FILES = "abcdefgh"
PIECE_TYPES = ["pawn", "rook", "knight", "bishop", "queen", "king"]
PIECE_ALIASES = {
    "p": "pawn", "pawn": "pawn",
    "r": "rook", "rook": "rook",
    "n": "knight", "knight": "knight",  # N is standard chess notation for knight.
    "b": "bishop", "bishop": "bishop",
    "q": "queen", "queen": "queen",
    "k": "king", "king": "king",
}

# Safe example values in meters. Replace these with your measured chess set.
# Do not assume these are exact for your pieces.
DEFAULT_PIECE_HEIGHTS_M = {
    "pawn": 0.045,
    "rook": 0.050,
    "knight": 0.055,
    "bishop": 0.065,
    "queen": 0.075,
    "king": 0.085,
}

# Baxter electric gripper position scale: 0=closed, 100=fully open.
# The pre-grasp opening should be just wide enough to clear the target piece,
# so the fingers do not hit neighboring chess pieces.
DEFAULT_GRIPPER_PRE_OPEN_POSITION = 45.0
DEFAULT_GRIPPER_RELEASE_OPEN_POSITION = 65.0
DEFAULT_GRIPPER_CLOSED_POSITION = 0.0
DEFAULT_PIECE_GRIPPER_PRE_OPEN = {
    "pawn": 35.0,
    "rook": 40.0,
    "knight": 45.0,
    "bishop": 45.0,
    "queen": 50.0,
    "king": 50.0,
}


def normalize_piece(piece):
    if piece is None:
        return None
    key = str(piece).strip().lower()
    if key not in PIECE_ALIASES:
        raise ValueError("Bad piece '{}'. Use one of: {}".format(piece, ", ".join(PIECE_TYPES)))
    return PIECE_ALIASES[key]


def _vec_add(a, b):
    return [a[i] + b[i] for i in range(3)]


def _vec_sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _vec_scale(s, v):
    return [s * v[i] for i in range(3)]


class ChessBoard(object):
    def __init__(self, config):
        self.config = config
        self.frame_id = config.get("frame_id", "base")
        self.limb = config.get("limb", "left")
        self.hover_height = float(config.get("hover_height", 0.12))
        self.approach_steps = int(config.get("approach_steps", 1))
        self.a1 = config["a1"]["position"]
        self.h1 = config["h1"]["position"]
        self.a8 = config["a8"]["position"]
        self.orientation = config.get("orientation", config["a1"]["orientation"])
        self.captured_area = config.get("captured_area")

        self.reference_piece = normalize_piece(config.get("reference_piece", "pawn"))
        self.grasp_fraction = float(config.get("grasp_fraction", 0.45))

        self.piece_heights = dict(DEFAULT_PIECE_HEIGHTS_M)
        for piece, height in config.get("piece_heights", {}).items():
            self.piece_heights[normalize_piece(piece)] = float(height)

        self.piece_z_bias = {}
        for piece, bias in config.get("piece_z_bias", {}).items():
            self.piece_z_bias[normalize_piece(piece)] = float(bias)

        # Gripper opening settings. Baxter electric gripper uses 0=closed, 100=fully open.
        self.gripper_pre_open_position = float(config.get(
            "gripper_pre_open_position", DEFAULT_GRIPPER_PRE_OPEN_POSITION))
        self.gripper_release_open_position = float(config.get(
            "gripper_release_open_position", DEFAULT_GRIPPER_RELEASE_OPEN_POSITION))
        self.gripper_closed_position = float(config.get(
            "gripper_closed_position", DEFAULT_GRIPPER_CLOSED_POSITION))

        self.piece_gripper_pre_open = dict(DEFAULT_PIECE_GRIPPER_PRE_OPEN)
        for piece, pos in config.get("piece_gripper_pre_open", {}).items():
            self.piece_gripper_pre_open[normalize_piece(piece)] = float(pos)

    @classmethod
    def from_file(cls, path):
        with open(os.path.expanduser(path), "r") as f:
            return cls(json.load(f))

    def save(self, path):
        path = os.path.expanduser(path)
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        with open(path, "w") as f:
            json.dump(self.config, f, indent=2, sort_keys=True)

    def square_to_position(self, square):
        """Return [x, y, z] in Baxter /base frame for a square center.

        This is the calibrated reference-grasp height, usually pawn grasp height.
        Use square_to_grasp_position(square, piece) for a piece-specific height.
        """
        square = square.strip().lower()
        if len(square) != 2 or square[0] not in FILES or square[1] not in "12345678":
            raise ValueError("Bad square '{}'. Use notation like e2 or h8.".format(square))

        file_index = FILES.index(square[0])
        rank_index = int(square[1]) - 1
        x_part = _vec_scale(file_index / 7.0, _vec_sub(self.h1, self.a1))
        y_part = _vec_scale(rank_index / 7.0, _vec_sub(self.a8, self.a1))
        return _vec_add(self.a1, _vec_add(x_part, y_part))

    def piece_height(self, piece):
        piece = normalize_piece(piece)
        return float(self.piece_heights[piece])

    def piece_z_offset(self, piece):
        """Return Z offset in meters relative to the reference-piece grasp height."""
        piece = normalize_piece(piece)
        if piece is None:
            return 0.0
        ref_height = self.piece_height(self.reference_piece)
        this_height = self.piece_height(piece)
        bias = float(self.piece_z_bias.get(piece, 0.0))
        return (this_height - ref_height) * self.grasp_fraction + bias

    def apply_piece_height(self, position, piece):
        p = list(position)
        p[2] += self.piece_z_offset(piece)
        return p

    def square_to_grasp_position(self, square, piece=None):
        """Return [x, y, z] for grasping a specific piece on a square."""
        pos = self.square_to_position(square)
        if piece is not None:
            pos = self.apply_piece_height(pos, piece)
        return pos

    def gripper_pre_open_for_piece(self, piece=None):
        """Return electric gripper pre-open position, 0=closed and 100=fully open."""
        if piece is None:
            return self.gripper_pre_open_position
        piece = normalize_piece(piece)
        return float(self.piece_gripper_pre_open.get(piece, self.gripper_pre_open_position))

    def gripper_release_open_for_piece(self, piece=None):
        """Return electric gripper release-open position after placing a piece."""
        return self.gripper_release_open_position

    def hover_position(self, position, extra=0.0):
        p = list(position)
        p[2] += self.hover_height + extra
        return p

    def named_pose(self, name):
        """Return a full calibrated pose dict, e.g. home or captured_area."""
        value = self.config.get(name)
        if not value:
            raise ValueError("No calibrated named pose '{}' in config.".format(name))
        return value

    def has_named_pose(self, name):
        return bool(self.config.get(name))

    def named_position(self, name):
        """Return a special calibrated position, e.g. captured_area."""
        value = self.config.get(name)
        if not value:
            raise ValueError("No calibrated named position '{}' in config.".format(name))
        return value["position"]

    def named_grasp_position(self, name, piece=None):
        pos = self.named_position(name)
        if piece is not None:
            pos = self.apply_piece_height(pos, piece)
        return pos
