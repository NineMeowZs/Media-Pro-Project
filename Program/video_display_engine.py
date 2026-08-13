"""video_display_engine.py – High-Performance GPU-Accelerated Video Reader Engine.

Priority order:
  1. Decord GPU  – NVIDIA NVDEC hardware decode directly on VRAM (fastest)
  2. Decord CPU  – C++ accelerated decode, still much faster than OpenCV
  3. OpenCV      – pure CPU fallback

GPU initialization is LAZY (happens on first SmartVideoReader instantiation)
so that PyTorch DLLs (loaded by transcriber.py) are ready before we try GPU.
"""

import os
import cv2
import numpy as np
import ctypes

# ── Pre-load PyTorch DLLs (same pattern as transcriber.py) ───────────────────
# This ensures c10.dll / torch.dll are in memory before Decord tries GPU context.
_torch_lib = r"C:\Users\User\AppData\Roaming\Python\Python314\site-packages\torch\lib"
if os.path.exists(_torch_lib):
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(_torch_lib)
        except Exception:
            pass
    for _dll in ["libiomp5md.dll", "c10.dll", "torch_cpu.dll", "torch.dll", "c10_cuda.dll", "torch_cuda.dll"]:
        _dpath = os.path.join(_torch_lib, _dll)
        if os.path.exists(_dpath):
            try:
                ctypes.WinDLL(_dpath)
            except Exception:
                pass


# ── Lazy GPU state — populated on first use ───────────────────────────────────
_GPU_CHECKED   = False
_HAS_CUDA      = False
_DECORD_CTX    = None          # decord.gpu(0) or decord.cpu(0)
_HAS_DECORD    = False


def _ensure_gpu_ready():
    """
    One-time GPU capability detection.
    Called lazily so PyTorch DLLs are guaranteed to be loaded first.
    """
    global _GPU_CHECKED, _HAS_CUDA, _DECORD_CTX, _HAS_DECORD

    if _GPU_CHECKED:
        return
    _GPU_CHECKED = True

    try:
        import decord
        _HAS_DECORD = True

        # Try PyTorch CUDA detection
        _cuda_ok = False
        try:
            import torch
            if torch.cuda.is_available():
                _cuda_ok = True
        except Exception:
            pass

        if _cuda_ok:
            try:
                # Verify Decord can actually open GPU context
                _DECORD_CTX = decord.gpu(0)
                _HAS_CUDA   = True
                print(f"[VideoEngine] NVDEC GPU decode ENABLED ✓ (RTX 3060)")
            except Exception as e:
                _DECORD_CTX = decord.cpu(0)
                print(f"[VideoEngine] Decord GPU unavailable, using CPU: {e}")
        else:
            _DECORD_CTX = decord.cpu(0)
            print("[VideoEngine] Decord CPU decode (CUDA not available)")

    except ImportError:
        _HAS_DECORD = False
        print("[VideoEngine] Decord not installed — using OpenCV fallback")


class SmartVideoReader:
    """
    High-performance video reader:
      GPU path  → Decord NVDEC (VRAM decode, minimal CPU usage)
      CPU path  → Decord C++ FFmpeg (fast sequential decode)
      Fallback  → OpenCV sequential stream reader (zero-seek during playback)

    GPU/CPU detection is lazy — happens on first instantiation, not at import.
    """

    def __init__(self, path: str, force_cpu: bool = False):
        self.path                = path
        self._vr                 = None
        self._cap                = None
        self._use_decord         = False
        self._use_gpu            = False
        self._num_frames         = 0
        self._fps                = 30.0
        self._w                  = 0
        self._h                  = 0
        self._last_frame         = None
        self._current_frame_idx  = -1

        _ensure_gpu_ready()      # one-time DLL check (no-op on subsequent calls)
        self._open(force_cpu)

    def _open(self, force_cpu: bool = False):
        if not self.path or not os.path.exists(self.path):
            return

        # ── Decord (GPU → CPU) ────────────────────────────────────────────────
        if _HAS_DECORD:
            try:
                import decord
                decord.bridge.set_bridge("native")

                use_gpu = _HAS_CUDA and not force_cpu and _DECORD_CTX is not None
                ctx = _DECORD_CTX if use_gpu else None

                try:
                    if use_gpu:
                        self._vr = decord.VideoReader(self.path, ctx=ctx)
                        self._use_gpu = True
                    else:
                        self._vr = decord.VideoReader(self.path, ctx=decord.cpu(0))
                except Exception:
                    # GPU codec unsupported for this file — fallback to CPU decode
                    self._vr = decord.VideoReader(self.path, ctx=decord.cpu(0))
                    self._use_gpu = False

                self._num_frames = len(self._vr)
                self._fps        = float(self._vr.get_avg_fps() or 30.0)

                if self._num_frames > 0:
                    sample       = self._vr[0].asnumpy()
                    self._h, self._w = sample.shape[:2]
                    self._use_decord = True
                    self._current_frame_idx = 0
                    return

            except Exception as e:
                self._vr         = None
                self._use_decord = False
                self._use_gpu    = False

        # ── OpenCV fallback ───────────────────────────────────────────────────
        try:
            self._cap        = cv2.VideoCapture(self.path)
            self._fps        = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
            self._num_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._w          = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or 0)
            self._h          = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            self._current_frame_idx = -1
        except Exception as e:
            print(f"[SmartVideoReader OpenCV Error] {e}")

    def read_next_frame(self) -> tuple[bool, np.ndarray | None]:
        """
        Ultra-fast sequential frame read without seeking.
        Maintains 30-60 FPS smooth video streaming during playback.
        """
        next_idx = self._current_frame_idx + 1

        # Decord path
        if self._use_decord and self._vr is not None:
            if 0 <= next_idx < self._num_frames:
                try:
                    rgb = self._vr[next_idx].asnumpy()
                    bgr = rgb[:, :, ::-1].copy()
                    self._current_frame_idx = next_idx
                    self._last_frame = bgr
                    return True, bgr
                except Exception:
                    pass

        # OpenCV path
        if self._cap is None and self.path and os.path.exists(self.path):
            try:
                self._cap = cv2.VideoCapture(self.path)
            except Exception:
                pass

        if self._cap is not None:
            try:
                ok, fr = self._cap.read()
                if ok and fr is not None:
                    self._current_frame_idx += 1
                    self._last_frame = fr
                    return True, fr
            except Exception:
                pass

        if self._last_frame is not None:
            return True, self._last_frame

        return False, None

    def get_frame_at_time(self, sec: float) -> tuple[bool, np.ndarray | None]:
        """
        Extract frame BGR numpy array at timestamp sec.
        If sec corresponds to the next sequential frame, uses fast read without seek.
        Otherwise performs random access seek.
        """
        if sec < 0:
            sec = 0.0

        target_idx = (
            max(0, min(int(sec * self._fps), self._num_frames - 1))
            if self._num_frames > 0
            else max(0, int(sec * self._fps))
        )

        # Fast sequential path: no seek required
        if target_idx == self._current_frame_idx + 1:
            return self.read_next_frame()

        if target_idx == self._current_frame_idx and self._last_frame is not None:
            return True, self._last_frame

        # ── Decord (GPU or CPU) Random Access ────────────────────────────────
        if self._use_decord and self._vr is not None:
            try:
                rgb  = self._vr[target_idx].asnumpy()
                bgr  = rgb[:, :, ::-1].copy()
                self._current_frame_idx = target_idx
                self._last_frame = bgr
                return True, bgr
            except Exception:
                pass

        # ── OpenCV fallback Random Access Seek ───────────────────────────────
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
                    self._current_frame_idx = target_idx
                    self._last_frame = fr
                    return True, fr
            except Exception:
                pass

        if self._last_frame is not None:
            return True, self._last_frame

        return False, None

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
        self._vr = None
        self._current_frame_idx = -1

