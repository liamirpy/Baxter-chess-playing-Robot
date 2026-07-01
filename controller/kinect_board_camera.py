import ctypes
import os
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


class KinectBoardCamera:
    # Kinect / libfreenect constants
    FREENECT_RESOLUTION_LOW = 0
    FREENECT_RESOLUTION_MEDIUM = 1
    FREENECT_RESOLUTION_HIGH = 2
    FREENECT_VIDEO_RGB = 0
    # Kinect LED values
    LED_OFF = 0
    LED_GREEN = 1
    LED_RED = 2
    LED_YELLOW = 3
    LED_BLINK_GREEN = 4
    LED_BLINK_RED_YELLOW = 6

    def __init__(
        self,
        lib_dir: str,
        use_high_quality: bool = False,
        board_size: int = 800,
    ):
        self.lib_dir = lib_dir
        self.use_high_quality = use_high_quality

        self.board_size = board_size
        self.square_size = self.board_size / 8.0

        self.inner_pattern_size = (7, 7)
        self.min_board_area = 2500

        self.sync = None

        self.frame_width = 640
        self.frame_height = 480
        self.video_resolution = self.FREENECT_RESOLUTION_MEDIUM
        self.video_mode_name = "MEDIUM 640x480"

        self.current_corners = None
        self.current_inner_points = None

        # When True, current_corners are frozen.
        # This prevents hands, shadows, or pieces from moving the detected board corners.
        self.corners_locked = False
        self.manual_corners_enabled = False

        self.prev_gray = None
        self.track_points = None
        self.tracking_active = False

        self.frame_counter = 0
        self.last_detection_frame = -9999

        self.auto_detect_every_n_frames = 15
        self.auto_redetect_when_tracking_weak = True

        self.tilt_angle = 0
        self.min_tilt = -30
        self.max_tilt = 30
        self.tilt_step = 5

        self.flip_labels = False
        self.led_supported = False

        self._set_video_mode()

    # ============================================================
    # Start / stop
    # ============================================================

    def start(self):
        self.sync = self._load_freenect_sync()
        self._setup_functions(self.sync)
        print("KinectBoardCamera started.")
        print(f"Video mode: {self.video_mode_name}")

   
    def stop(self):
        if self.sync is not None:
            try:
                self.led_off()
            except Exception:
                pass

            self.sync.freenect_sync_stop()
            self.sync = None
            print("KinectBoardCamera stopped.")

    def _load_freenect_sync(self):
        libfreenect = os.path.join(self.lib_dir, "libfreenect.so")
        libsync = os.path.join(self.lib_dir, "libfreenect_sync.so")

        if not os.path.exists(libfreenect):
            raise FileNotFoundError(f"Missing: {libfreenect}")

        if not os.path.exists(libsync):
            raise FileNotFoundError(f"Missing: {libsync}")

        ctypes.CDLL(libfreenect, mode=ctypes.RTLD_GLOBAL)
        sync = ctypes.CDLL(libsync, mode=ctypes.RTLD_GLOBAL)

        return sync

    def _setup_functions(self, sync):
        sync.freenect_sync_get_video_with_res.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        sync.freenect_sync_get_video_with_res.restype = ctypes.c_int

        sync.freenect_sync_set_tilt_degs.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
        ]
        sync.freenect_sync_set_tilt_degs.restype = ctypes.c_int

        sync.freenect_sync_stop.argtypes = []
        sync.freenect_sync_stop.restype = None

        try:
            sync.freenect_sync_set_led.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
            ]
            sync.freenect_sync_set_led.restype = ctypes.c_int
            self.led_supported = True
            print("Kinect LED control is available through freenect_sync.")
        except AttributeError:
            self.led_supported = False
            print("Warning: freenect_sync_set_led is not available.")

    def _set_video_mode(self):
        if self.use_high_quality:
            self.frame_width = 1280
            self.frame_height = 1024
            self.video_resolution = self.FREENECT_RESOLUTION_HIGH
            self.video_mode_name = "HIGH 1280x1024"
        else:
            self.frame_width = 640
            self.frame_height = 480
            self.video_resolution = self.FREENECT_RESOLUTION_MEDIUM
            self.video_mode_name = "MEDIUM 640x480"

    # ============================================================
    # Kinect frame
    # ============================================================

    def get_rgb_frame(self):
        if self.sync is None:
            raise RuntimeError("Kinect is not started. Call camera.start() first.")

        data_ptr = ctypes.c_void_p()
        timestamp = ctypes.c_uint32()

        result = self.sync.freenect_sync_get_video_with_res(
            ctypes.byref(data_ptr),
            ctypes.byref(timestamp),
            0,
            self.video_resolution,
            self.FREENECT_VIDEO_RGB,
        )

        if result != 0 or not data_ptr.value:
            raise RuntimeError(
                f"Could not get RGB frame in {self.video_mode_name}. "
                "If high quality fails, set use_high_quality=False."
            )

        buffer_type = ctypes.c_uint8 * (
            self.frame_width * self.frame_height * 3
        )
        buffer = buffer_type.from_address(data_ptr.value)

        rgb = np.ctypeslib.as_array(buffer)
        rgb = rgb.reshape((self.frame_height, self.frame_width, 3)).copy()

        # Kinect gives RGB, OpenCV uses BGR
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        return bgr

    # ============================================================
    # Kinect tilt
    # ============================================================

    def set_tilt(self, angle: int):
        if self.sync is None:
            raise RuntimeError("Kinect is not started.")

        angle = int(np.clip(angle, self.min_tilt, self.max_tilt))

        result = self.sync.freenect_sync_set_tilt_degs(angle, 0)

        if result != 0:
            print(f"Warning: could not set Kinect tilt to {angle} degrees")
            return

        self.tilt_angle = angle
        print(f"Kinect tilt angle: {self.tilt_angle} degrees")

    def tilt_up(self):
        self.set_tilt(self.tilt_angle + self.tilt_step)

    def tilt_down(self):
        self.set_tilt(self.tilt_angle - self.tilt_step)

    def tilt_center(self):
        self.set_tilt(0)



        # ============================================================
    # Kinect LED
    # ============================================================

    def set_led(self, led_value: int, name: str = ""):
        if self.sync is None:
            print("Kinect is not started. Cannot set LED.")
            return

        if not self.led_supported:
            print(f"LED not supported through freenect_sync. Requested: {name}")
            return

        result = self.sync.freenect_sync_set_led(led_value, 0)

        if result != 0:
            print(f"Warning: could not set Kinect LED to {name}. Error code: {result}")
        else:
            if name:
                print(f"Kinect LED: {name}")

    def led_off(self):
        self.set_led(self.LED_OFF, "OFF")

    def led_green(self):
        self.set_led(self.LED_GREEN, "GREEN - human turn")

    def led_red(self):
        self.set_led(self.LED_RED, "RED - Stockfish / robot turn")

    def led_yellow(self):
        self.set_led(self.LED_YELLOW, "YELLOW - waiting / scanning")

    def led_blink_green(self):
        self.set_led(self.LED_BLINK_GREEN, "BLINK GREEN")

    def led_error(self):
        self.set_led(self.LED_BLINK_RED_YELLOW, "BLINK RED/YELLOW - error")

    # ============================================================
    # Geometry helpers
    # ============================================================

    def order_corners(self, points):
        pts = np.array(points, dtype=np.float32)

        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1).reshape(-1)

        top_left = pts[np.argmin(s)]
        bottom_right = pts[np.argmax(s)]
        top_right = pts[np.argmin(diff)]
        bottom_left = pts[np.argmax(diff)]

        return np.array(
            [top_left, top_right, bottom_right, bottom_left],
            dtype=np.float32,
        )

    def is_valid_corners(self, corners):
        if corners is None:
            return False

        corners = np.asarray(corners, dtype=np.float32)

        if corners.shape != (4, 2):
            return False

        if not np.all(np.isfinite(corners)):
            return False

        area = abs(cv2.contourArea(corners.astype(np.float32)))

        if area < self.min_board_area:
            return False

        x_min, y_min = corners.min(axis=0)
        x_max, y_max = corners.max(axis=0)

        if x_max < 0 or y_max < 0:
            return False

        if x_min >= self.frame_width or y_min >= self.frame_height:
            return False

        return True

    def chess_label(self, row, col):
        files = "abcdefgh"

        if not self.flip_labels:
            file_char = files[col]
            rank = 8 - row
        else:
            file_char = files[7 - col]
            rank = row + 1

        return f"{file_char}{rank}"

    def get_board_to_image_homography(self, corners):
        board_corners = np.array(
            [
                [0, 0],
                [self.board_size, 0],
                [self.board_size, self.board_size],
                [0, self.board_size],
            ],
            dtype=np.float32,
        )

        H = cv2.getPerspectiveTransform(
            board_corners,
            corners.astype(np.float32),
        )

        return H

    def warp_board_top_down(self, frame, corners=None):
        if corners is None:
            corners = self.current_corners

        if corners is None:
            raise RuntimeError("No chessboard corners available.")

        dst = np.array(
            [
                [0, 0],
                [self.board_size, 0],
                [self.board_size, self.board_size],
                [0, self.board_size],
            ],
            dtype=np.float32,
        )

        H = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)

        warped = cv2.warpPerspective(
            frame,
            H,
            (self.board_size, self.board_size),
        )

        return warped

    # ============================================================
    # Automatic chessboard detection
    # ============================================================

    def build_ideal_inner_points(self):
        ideal_inner = []

        for row in range(self.inner_pattern_size[1]):
            for col in range(self.inner_pattern_size[0]):
                ideal_inner.append(
                    [
                        (col + 1) * self.square_size,
                        (row + 1) * self.square_size,
                    ]
                )

        return np.array(ideal_inner, dtype=np.float32)

    def build_ideal_outer_points(self):
        return np.array(
            [
                [0, 0],
                [self.board_size, 0],
                [self.board_size, self.board_size],
                [0, self.board_size],
            ],
            dtype=np.float32,
        )

    def preprocess_gray_variants(self, gray):
        variants = []

        variants.append(gray)

        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        variants.append(blur)

        equalized = cv2.equalizeHist(blur)
        variants.append(equalized)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        variants.append(clahe.apply(blur))

        return variants

    def detect_inner_chessboard_corners(self, gray):
        variants = self.preprocess_gray_variants(gray)

        if hasattr(cv2, "findChessboardCornersSB"):
            sb_flags = cv2.CALIB_CB_NORMALIZE_IMAGE

            if hasattr(cv2, "CALIB_CB_EXHAUSTIVE"):
                sb_flags |= cv2.CALIB_CB_EXHAUSTIVE

            if hasattr(cv2, "CALIB_CB_ACCURACY"):
                sb_flags |= cv2.CALIB_CB_ACCURACY

            for gray_variant in variants:
                found, corners = cv2.findChessboardCornersSB(
                    gray_variant,
                    self.inner_pattern_size,
                    flags=sb_flags,
                )

                if found and corners is not None:
                    return True, corners.reshape(-1, 2).astype(np.float32)

        classic_flags = (
            cv2.CALIB_CB_ADAPTIVE_THRESH
            | cv2.CALIB_CB_NORMALIZE_IMAGE
            | cv2.CALIB_CB_FILTER_QUADS
        )

        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER,
            50,
            0.001,
        )

        for gray_variant in variants:
            found, corners = cv2.findChessboardCorners(
                gray_variant,
                self.inner_pattern_size,
                classic_flags,
            )

            if not found or corners is None:
                continue

            corners = cv2.cornerSubPix(
                gray,
                corners,
                winSize=(7, 7),
                zeroZone=(-1, -1),
                criteria=criteria,
            )

            return True, corners.reshape(-1, 2).astype(np.float32)

        return False, None

    def estimate_outer_board_from_inner_points(self, inner_points):
        detected_inner = inner_points.reshape(-1, 2).astype(np.float32)
        ideal_inner = self.build_ideal_inner_points()
        ideal_outer = self.build_ideal_outer_points()

        H_ideal_to_image, inliers = cv2.findHomography(
            ideal_inner,
            detected_inner,
            cv2.RANSAC,
            3.0,
        )

        if H_ideal_to_image is None or inliers is None:
            return None

        inlier_count = int(inliers.sum())

        if inlier_count < 35:
            return None

        outer_image = cv2.perspectiveTransform(
            ideal_outer.reshape(-1, 1, 2),
            H_ideal_to_image,
        ).reshape(4, 2)

        outer_image = self.order_corners(outer_image)

        if not self.is_valid_corners(outer_image):
            return None

        return outer_image.astype(np.float32)

    def auto_detect_chessboard(self, frame, verbose=False):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        found, inner_points = self.detect_inner_chessboard_corners(gray)

        if not found:
            if verbose:
                print("Auto-detect: 7x7 inner chessboard corners not found.")
            return None, None

        outer_corners = self.estimate_outer_board_from_inner_points(
            inner_points
        )

        if outer_corners is None:
            if verbose:
                print("Auto-detect: could not estimate valid outer board corners.")
            return None, None

        if verbose:
            area = abs(cv2.contourArea(outer_corners))
            print(f"Auto-detect succeeded. Board area: {area:.1f} px^2")

        return outer_corners, inner_points.astype(np.float32)

    def try_auto_detect_and_start_tracking(self, frame, force=False):
        if not force:
            if (
                self.frame_counter - self.last_detection_frame
                < self.auto_detect_every_n_frames
            ):
                return False

        self.last_detection_frame = self.frame_counter

        corners, inner_points = self.auto_detect_chessboard(
            frame,
            verbose=force,
        )

        if corners is None:
            return False

        self.current_corners = corners
        self.current_inner_points = inner_points
        self.redetect_tracking_points(frame)

        return True

    # ============================================================
    # Tracking
    # ============================================================

    def create_board_mask(self, gray_shape, corners):
        mask = np.zeros(gray_shape, dtype=np.uint8)
        polygon = corners.astype(np.int32)
        cv2.fillConvexPoly(mask, polygon, 255)
        return mask

    def redetect_tracking_points(self, frame):
        if self.current_corners is None:
            self.tracking_active = False
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = self.create_board_mask(gray.shape, self.current_corners)

        points = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=300,
            qualityLevel=0.01,
            minDistance=6,
            blockSize=7,
            mask=mask,
        )

        if points is None or len(points) < 12:
            print("Warning: not enough feature points to track.")
            self.tracking_active = False
            self.track_points = None
            self.prev_gray = gray
            return

        self.track_points = points.astype(np.float32)
        self.prev_gray = gray
        self.tracking_active = True

        print(f"Tracking initialized with {len(self.track_points)} points.")

    def update_board_tracking(self, frame):
        if (
            not self.tracking_active
            or self.prev_gray is None
            or self.track_points is None
        ):
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        next_points, status, error = cv2.calcOpticalFlowPyrLK(
            self.prev_gray,
            gray,
            self.track_points,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(
                cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                30,
                0.01,
            ),
        )

        if next_points is None or status is None:
            self.tracking_active = False
            return

        status = status.reshape(-1)

        old_good = self.track_points[status == 1].reshape(-1, 2)
        new_good = next_points[status == 1].reshape(-1, 2)

        if len(old_good) < 12:
            print("Tracking weak. Re-detecting tracking points.")
            self.redetect_tracking_points(frame)
            return

        H_delta, inliers = cv2.findHomography(
            old_good,
            new_good,
            cv2.RANSAC,
            5.0,
        )

        if H_delta is None or inliers is None:
            print("Could not estimate board movement.")
            self.redetect_tracking_points(frame)
            return

        inlier_count = int(inliers.sum())

        if inlier_count < 10:
            print("Too few good tracking points. Re-detecting.")
            self.redetect_tracking_points(frame)
            return

        new_corners = cv2.perspectiveTransform(
            self.current_corners.reshape(-1, 1, 2),
            H_delta,
        ).reshape(4, 2)

        if self.is_valid_corners(new_corners):
            self.current_corners = new_corners.astype(np.float32)
        else:
            print("Invalid tracked corners. Trying automatic re-detection.")
            self.tracking_active = False

            if self.auto_redetect_when_tracking_weak:
                self.try_auto_detect_and_start_tracking(frame, force=True)

            return

        self.prev_gray = gray
        self.track_points = new_good.reshape(-1, 1, 2).astype(np.float32)

        if self.frame_counter % 20 == 0 or len(self.track_points) < 80:
            self.redetect_tracking_points(frame)

    # ============================================================
    # Public capture methods
    # ============================================================

    def lock_corners(self):
        """Freeze the current board corners so hands/pieces cannot move them."""
        if self.current_corners is None:
            print("Cannot lock corners: no board corners are available yet.")
            return False

        self.corners_locked = True
        self.tracking_active = False
        self.track_points = None
        self.prev_gray = None
        print("Board corners locked.")
        return True

    def unlock_corners(self):
        """Allow automatic detection/tracking again."""
        self.corners_locked = False
        self.manual_corners_enabled = False
        print("Board corners unlocked.")
        return True

    def set_manual_corners_from_a1_h1_a8(self, a1, h1, a8):
        """
        Manually define the chessboard using three image points.

        Args:
            a1: bottom-left chess square corner in image pixels, e.g. (120, 720)
            h1: bottom-right chess square corner in image pixels
            a8: top-left chess square corner in image pixels

        h8 is calculated automatically as: h8 = h1 + (a8 - a1)

        Internally current_corners must be ordered as:
            [top_left(a8), top_right(h8), bottom_right(h1), bottom_left(a1)]
        """
        a1 = np.asarray(a1, dtype=np.float32)
        h1 = np.asarray(h1, dtype=np.float32)
        a8 = np.asarray(a8, dtype=np.float32)

        h8 = h1 + (a8 - a1)

        corners = np.array(
            [a8, h8, h1, a1],
            dtype=np.float32,
        )

        if not self.is_valid_corners(corners):
            raise ValueError(
                f"Manual corners are invalid: a1={a1}, h1={h1}, a8={a8}, h8={h8}"
            )

        self.current_corners = corners
        self.current_inner_points = None
        self.manual_corners_enabled = True

        # Important: disable tracking and lock the corners.
        # Otherwise optical flow may drag the corners when a hand/piece enters the image.
        self.lock_corners()

        print("Manual board corners set and locked:")
        print(f"  a8/top-left:     {a8}")
        print(f"  h8/top-right:    {h8}")
        print(f"  h1/bottom-right: {h1}")
        print(f"  a1/bottom-left:  {a1}")

        return corners

    def reset_detection(self):
        self.current_corners = None
        self.current_inner_points = None

        # When True, current_corners are frozen.
        # This prevents hands, shadows, or pieces from moving the detected board corners.
        self.corners_locked = False
        self.manual_corners_enabled = False

        self.prev_gray = None
        self.track_points = None
        self.tracking_active = False

        self.frame_counter = 0
        self.last_detection_frame = -9999

        print("Board detection reset.")

    def update(self, frame, force_detect=False):
        self.frame_counter += 1

        # If corners are locked, do not track or redetect them while hands/pieces move.
        # Press/use force_detect=True only when you intentionally want a new calibration.
        if self.corners_locked and self.current_corners is not None and not force_detect:
            return True

        if force_detect or self.current_corners is None:
            ok = self.try_auto_detect_and_start_tracking(
                frame,
                force=force_detect,
            )

            # When the user explicitly forces detection, lock the detected corners.
            # This is the recommended workflow: empty board -> press c -> lock -> place pieces.
            if ok and force_detect:
                self.lock_corners()

            return ok

        self.update_board_tracking(frame)
        return self.current_corners is not None

    def wait_until_board_detected(self, timeout_seconds=10):
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            frame = self.get_rgb_frame()
            ok = self.update(frame, force_detect=False)

            if ok and self.current_corners is not None:
                return True

        return False

    def capture_top_down_board(
        self,
        force_redetect=False,
        stable_frames=3,
    ):
        """
        Returns:
            top_down_board_image, original_frame
        """
        if force_redetect:
            self.reset_detection()

        frame = None

        for _ in range(max(1, stable_frames)):
            frame = self.get_rgb_frame()
            ok = self.update(frame, force_detect=False)

            if not ok and self.current_corners is None:
                self.update(frame, force_detect=True)

            time.sleep(0.05)

        if frame is None:
            raise RuntimeError("No frame captured.")

        if self.current_corners is None:
            raise RuntimeError("Chessboard was not detected.")

        top_down = self.warp_board_top_down(frame, self.current_corners)

        return top_down, frame

    def capture_and_save_top_down(
        self,
        output_dir="captures",
        prefix="board",
        force_redetect=False,
    ):
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        top_down, frame = self.capture_top_down_board(
            force_redetect=force_redetect,
        )

        overlay = self.draw_chessboard_grid(frame.copy())

        top_down_path = output_path / f"{prefix}_{timestamp}_top_down.png"
        overlay_path = output_path / f"{prefix}_{timestamp}_overlay.png"

        cv2.imwrite(str(top_down_path), top_down)
        cv2.imwrite(str(overlay_path), overlay)

        return {
            "top_down_path": str(top_down_path),
            "overlay_path": str(overlay_path),
            "top_down_image": top_down,
            "overlay_image": overlay,
        }

    # ============================================================
    # Drawing / debugging
    # ============================================================

    def draw_chessboard_grid(self, frame):
        if self.current_corners is None:
            return frame

        corners = self.current_corners
        square_size = self.board_size // 8

        H = self.get_board_to_image_homography(corners)

        cv2.polylines(
            frame,
            [corners.astype(np.int32)],
            isClosed=True,
            color=(0, 255, 255),
            thickness=2,
        )

        for i, p in enumerate(corners):
            x, y = int(p[0]), int(p[1])
            cv2.circle(frame, (x, y), 6, (0, 255, 255), -1)
            cv2.putText(
                frame,
                str(i + 1),
                (x + 8, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )

        for i in range(9):
            value = i * square_size

            p1 = np.array([[[value, 0]]], dtype=np.float32)
            p2 = np.array([[[value, self.board_size]]], dtype=np.float32)

            img_p1 = cv2.perspectiveTransform(p1, H)[0][0]
            img_p2 = cv2.perspectiveTransform(p2, H)[0][0]

            cv2.line(
                frame,
                tuple(img_p1.astype(int)),
                tuple(img_p2.astype(int)),
                (0, 255, 0),
                2,
            )

            p1 = np.array([[[0, value]]], dtype=np.float32)
            p2 = np.array([[[self.board_size, value]]], dtype=np.float32)

            img_p1 = cv2.perspectiveTransform(p1, H)[0][0]
            img_p2 = cv2.perspectiveTransform(p2, H)[0][0]

            cv2.line(
                frame,
                tuple(img_p1.astype(int)),
                tuple(img_p2.astype(int)),
                (0, 255, 0),
                2,
            )

        for row in range(8):
            for col in range(8):
                cx = col * square_size + square_size / 2
                cy = row * square_size + square_size / 2

                center_board = np.array([[[cx, cy]]], dtype=np.float32)
                center_img = cv2.perspectiveTransform(center_board, H)[0][0]

                x, y = int(center_img[0]), int(center_img[1])
                label = self.chess_label(row, col)

                cv2.putText(
                    frame,
                    label,
                    (x - 16, y + 6),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 0, 255),
                    2,
                )

        return frame