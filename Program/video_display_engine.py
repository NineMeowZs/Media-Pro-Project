# video_display_engine.py – Optimized Low-I/O Video Reader Engine for Long Videos.

import os
import cv2
import numpy as np

class SmartVideoReader:
    def __init__(self, path: str, force_cpu: bool = True):
        self.path               = path
        self._cap               = None
        self._num_frames        = 0
        self._fps               = 30.0
        self._w                 = 0
        self._h                 = 0
        self._last_frame        = None
        self._current_frame_idx = -1

        self._open()

    def _open(self):
        if not self.path or not os.path.exists(self.path):
            return

        # ใช้ OpenCV VideoCapture โดยตรงสำหรับไฟล์ยาว เพื่อตัดปัญหา Decord Indexing Thrashing
        try:
            self._cap = cv2.VideoCapture(self.path)
            self._fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0)
            self._num_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self._h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            self._current_frame_idx = -1
        except Exception as e:
            print(f"[SmartVideoReader Error] {e}")

    def get_frame_at_index(self, frame_idx: int) -> tuple[bool, np.ndarray | None]:
        if self._num_frames <= 0:
            return False, None

        target_idx = max(0, min(int(frame_idx), self._num_frames - 1))

        if target_idx == self._current_frame_idx and self._last_frame is not None:
            return True, self._last_frame

        if self._cap is None and self.path and os.path.exists(self.path):
            try:
                self._cap = cv2.VideoCapture(self.path)
            except Exception:
                pass

        if self._cap is not None:
            try:
                diff = target_idx - self._current_frame_idx
                # หากเป็นการเล่นต่อเนื่องไปข้างหน้า (Sequential Read 1-5 เฟรม) ให้ใช้ .read() หรือ .grab()
                # จะทำให้ Disk อ่านเป็น Stream เส้นตรง ไม่เกิด Random Seek Head Thrashes
                if 0 < diff <= 5:
                    for _ in range(diff - 1):
                        self._cap.grab()
                    ok, fr = self._cap.read()
                else:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(target_idx))
                    ok, fr = self._cap.read()

                if ok and fr is not None:
                    self._current_frame_idx = target_idx
                    self._last_frame = fr
                    return True, fr
            except Exception:
                pass

        if self._last_frame is not None:
            return True, self._last_frame

        return False, None

    def get_frame_at_time(self, sec: float) -> tuple[bool, np.ndarray | None]:
        if sec < 0:
            sec = 0.0
        frame_idx = int(round(sec * self._fps))
        return self.get_frame_at_index(frame_idx)

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def num_frames(self) -> int:
        return self._num_frames

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    def release(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._last_frame = None
        self._current_frame_idx = -1