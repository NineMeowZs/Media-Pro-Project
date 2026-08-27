# """video_display_engine.py – High-Performance GPU-Accelerated Video Reader Engine."""

# import os
# import cv2
# import numpy as np
# import ctypes

# _GPU_CHECKED   = False
# _HAS_CUDA      = False
# _DECORD_CTX    = None
# _HAS_DECORD    = False


# def _ensure_gpu_ready():
#     global _GPU_CHECKED, _HAS_CUDA, _DECORD_CTX, _HAS_DECORD
#     if _GPU_CHECKED:
#         return
#     _GPU_CHECKED = True

#     try:
#         import decord
#         _HAS_DECORD = True
#         try:
#             import torch
#             if torch.cuda.is_available():
#                 _DECORD_CTX = decord.gpu(0)
#                 _HAS_CUDA = True
#                 print("[VideoEngine] NVDEC GPU decode ENABLED ✓")
#             else:
#                 _DECORD_CTX = decord.cpu(0)
#                 print("[VideoEngine] Decord CPU decode (CUDA not available)")
#         except Exception:
#             _DECORD_CTX = decord.cpu(0)
#     except ImportError:
#         _HAS_DECORD = False
#         print("[VideoEngine] Decord not installed — using OpenCV fallback")


# class SmartVideoReader:
#     def __init__(self, path: str, force_cpu: bool = False):
#         self.path               = path
#         self._vr                = None
#         self._cap               = None
#         self._use_decord        = False
#         self._use_gpu           = False
#         self._num_frames        = 0
#         self._fps               = 30.0
#         self._w                 = 0
#         self._h                 = 0
#         self._last_frame        = None
#         self._current_frame_idx = -1

#         _ensure_gpu_ready()
#         self._open(force_cpu)

#     def _open(self, force_cpu: bool = False):
#         if not self.path or not os.path.exists(self.path):
#             return

#         if _HAS_DECORD:
#             try:
#                 import decord
#                 decord.bridge.set_bridge("native")
#                 use_gpu = _HAS_CUDA and not force_cpu and _DECORD_CTX is not None
#                 ctx = _DECORD_CTX if use_gpu else decord.cpu(0)
#                 try:
#                     self._vr = decord.VideoReader(self.path, ctx=ctx)
#                     self._use_gpu = use_gpu
#                 except Exception:
#                     self._vr = decord.VideoReader(self.path, ctx=decord.cpu(0))
#                     self._use_gpu = False

#                 self._num_frames = len(self._vr)
#                 self._fps        = float(self._vr.get_avg_fps() or 30.0)

#                 if self._num_frames > 0:
#                     sample = self._vr[0].asnumpy()
#                     self._h, self._w = sample.shape[:2]
#                     self._use_decord = True
#                     self._current_frame_idx = -1
#                     return
#             except Exception:
#                 self._vr = None
#                 self._use_decord = False

#         try:
#             self._cap        = cv2.VideoCapture(self.path)
#             self._fps        = float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0)
#             self._num_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
#             self._w          = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
#             self._h          = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
#             self._current_frame_idx = -1
#         except Exception as e:
#             print(f"[SmartVideoReader OpenCV Error] {e}")

#     def get_frame_at_index(self, frame_idx: int) -> tuple[bool, np.ndarray | None]:
#         """ดึงเฟรมโดยตรงจาก Frame Index ช่วยตัดปัญหา float rounding time drift"""
#         if self._num_frames <= 0:
#             return False, None

#         target_idx = max(0, min(int(frame_idx), self._num_frames - 1))

#         if target_idx == self._current_frame_idx and self._last_frame is not None:
#             return True, self._last_frame

#         if self._use_decord and self._vr is not None:
#             try:
#                 frame_data = self._vr[target_idx]
#                 bgr = frame_data.asnumpy()[:, :, ::-1].copy()
#                 self._current_frame_idx = target_idx
#                 self._last_frame = bgr
#                 return True, bgr
#             except Exception:
#                 pass

#         if self._cap is not None:
#             try:
#                 diff = target_idx - self._current_frame_idx
#                 if 0 < diff <= 3:
#                     for _ in range(diff - 1):
#                         self._cap.grab()
#                     ok, fr = self._cap.read()
#                 else:
#                     self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(target_idx))
#                     ok, fr = self._cap.read()

#                 if ok and fr is not None:
#                     self._current_frame_idx = target_idx
#                     self._last_frame = fr
#                     return True, fr
#             except Exception:
#                 pass

#         if self._last_frame is not None:
#             return True, self._last_frame

#         return False, None

#     def get_frame_at_time(self, sec: float) -> tuple[bool, np.ndarray | None]:
#         if sec < 0:
#             sec = 0.0
#         frame_idx = int(round(sec * self._fps))
#         return self.get_frame_at_index(frame_idx)

#     @property
#     def fps(self) -> float:
#         return self._fps

#     @property
#     def num_frames(self) -> int:
#         return self._num_frames

#     @property
#     def width(self) -> int:
#         return self._w

#     @property
#     def height(self) -> int:
#         return self._h

#     def release(self):
#         if self._cap is not None:
#             try:
#                 self._cap.release()
#             except Exception:
#                 pass
#             self._cap = None
#         self._vr = None
#         self._last_frame = None
#         self._current_frame_idx = -1

#ตัวบนคือ gpu version comment ล่างแล้วเปิดบนถ้า preview กระตุก

"""video_display_engine.py – High-Performance Video Reader Engine (CPU Accelerated)."""

import os
import cv2
import numpy as np

_HAS_DECORD = False
try:
    import decord
    decord.bridge.set_bridge("native")
    _HAS_DECORD = True
    print("[VideoEngine] Decord C++ CPU decode ENABLED ✓ (Stable Mode)")
except ImportError:
    _HAS_DECORD = False
    print("[VideoEngine] Decord not installed — using OpenCV fallback")


class SmartVideoReader:
    def __init__(self, path: str, force_cpu: bool = True):
        self.path               = path
        self._vr                = None
        self._cap               = None
        self._use_decord        = False
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

        # ── 1. Decord CPU Path (เสถียรและไม่ทำให้เครื่องค้าง) ────────────────
        if _HAS_DECORD:
            try:
                import decord
                # ใช้ CPU Context เสมอเพื่อตัดปัญหา buffersink failed
                self._vr = decord.VideoReader(self.path, ctx=decord.cpu(0), num_threads=2)
                self._num_frames = len(self._vr)
                self._fps        = float(self._vr.get_avg_fps() or 30.0)

                if self._num_frames > 0:
                    sample = self._vr[0].asnumpy()
                    self._h, self._w = sample.shape[:2]
                    self._use_decord = True
                    self._current_frame_idx = -1
                    return
            except Exception as e:
                self._vr = None
                self._use_decord = False

        # ── 2. OpenCV Fallback ──────────────────────────────────────────────
        try:
            self._cap        = cv2.VideoCapture(self.path)
            self._fps        = float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0)
            self._num_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._w          = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self._h          = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            self._current_frame_idx = -1
        except Exception as e:
            print(f"[SmartVideoReader Error] {e}")

    def get_frame_at_index(self, frame_idx: int) -> tuple[bool, np.ndarray | None]:
        if self._num_frames <= 0:
            return False, None

        # ป้องกันไม่ให้ index เกินขนาดวิดีโอ (ตัดปัญหา buffersink EOF error)
        target_idx = max(0, min(int(frame_idx), self._num_frames - 1))

        if target_idx == self._current_frame_idx and self._last_frame is not None:
            return True, self._last_frame

        # Decord CPU Fetch
        if self._use_decord and self._vr is not None:
            try:
                frame_data = self._vr[target_idx]
                bgr = frame_data.asnumpy()[:, :, ::-1].copy()
                self._current_frame_idx = target_idx
                self._last_frame = bgr
                return True, bgr
            except Exception:
                # ถ้า Decord สะดุด ให้สลับไปลอง OpenCV อัตโนมัติ
                pass

        # OpenCV Fetch
        if self._cap is None and self.path and os.path.exists(self.path):
            try: self._cap = cv2.VideoCapture(self.path)
            except Exception: pass

        if self._cap is not None:
            try:
                diff = target_idx - self._current_frame_idx
                if 0 < diff <= 3:
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
            try: self._cap.release()
            except Exception: pass
            self._cap = None
        self._vr = None
        self._last_frame = None
        self._current_frame_idx = -1