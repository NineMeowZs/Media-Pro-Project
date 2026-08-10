"""video_display_engine.py – High-Performance Video Reader Engine for Smooth Preview Display.
Uses Decord (C++ accelerated video loader) with automatic fallback to OpenCV.
"""

import os
import cv2

class SmartVideoReader:
    """High-performance video reader using Decord (with OpenCV fallback) for ultra-fast preview display."""

    def __init__(self, path: str):
        self.path = path
        self._vr = None
        self._cap = None
        self._use_decord = False
        self._num_frames = 0
        self._fps = 30.0
        self._w = 0
        self._h = 0
        self._open()

    def _open(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            import decord
            decord.bridge.set_bridge("native")
            self._vr = decord.VideoReader(self.path, ctx=decord.cpu(0))
            self._num_frames = len(self._vr)
            self._fps = float(self._vr.get_avg_fps() or 30.0)
            if self._num_frames > 0:
                sample = self._vr[0].asnumpy()
                self._h, self._w = sample.shape[:2]
                self._use_decord = True
                return
        except Exception as e:
            pass

        # OpenCV Fallback
        try:
            self._cap = cv2.VideoCapture(self.path)
            self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
            self._num_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self._h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        except Exception as e:
            print(f"[SmartVideoReader Fallback Error] {e}")

    def get_frame_at_time(self, sec: float):
        """Extract frame BGR array at timestamp sec."""
        if sec < 0:
            sec = 0.0
        frame_idx = max(0, min(int(sec * self._fps), self._num_frames - 1)) if self._num_frames > 0 else max(0, int(sec * self._fps))

        if self._use_decord and self._vr is not None:
            try:
                rgb = self._vr[frame_idx].asnumpy()
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                self._last_frame = bgr
                return True, bgr
            except Exception:
                pass

        if self._cap is None and self.path and os.path.exists(self.path):
            try:
                self._cap = cv2.VideoCapture(self.path)
            except Exception:
                pass

        if self._cap is not None:
            try:
                self._cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000.0)
                ok, fr = self._cap.read()
                if ok and fr is not None:
                    self._last_frame = fr
                    return True, fr
            except Exception:
                pass

        if hasattr(self, "_last_frame") and self._last_frame is not None:
            return True, self._last_frame

        return False, None

    def release(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._vr = None
