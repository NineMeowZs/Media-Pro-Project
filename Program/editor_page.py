"""editor_page.py

Layer order (top → bottom in timeline, matches CapCut):
  OVERLAY VIDEO  – picture-in-picture / sticker clips  (purple)
  TEXT           – title / subtitle text clips           (pink)
  ── MAIN VIDEO  – primary video track (largest)         (blue)  ← anchor
  AUDIO 1        – background music                      (teal)
  AUDIO 2        – SFX / voice-over                      (green)
"""

import os, sys
# Fix Windows DLL / OpenMP conflicts with PyTorch and OpenCV (WinError 1114)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
try:
    import site
    packages = site.getsitepackages() + [site.getusersitepackages()]
    for p in packages:
        torch_lib = os.path.join(p, "torch", "lib")
        if os.path.isdir(torch_lib) and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(torch_lib)
            except Exception:
                pass
except Exception:
    pass

# Safely pre-import torch on the main thread so c10.dll / OpenMP initialize cleanly
try:
    import torch
except Exception:
    pass

import customtkinter as ctk
from tkinter import messagebox, filedialog
import tkinter as tk
import threading
import queue
import math
import random
import cv2
import subprocess
from PIL import Image, ImageTk
import pygame
import tempfile
import json
import time
import copy
import numpy as np

import imageio_ffmpeg
from proxy_manager import ProxyManager
from video_display_engine import SmartVideoReader
import last_dirs as _ld

# ── Import Modular Components ────────────────────────────────────────────────
from editor_utils import *
from editor_utils import _ft, _bright, _dark, _nice_step, _TOOL_GROUPS
from editor_media import MediaPanel
from editor_preview import PreviewPanel
from editor_properties import PropertiesPanel
from transcript_panel import TranscriptPanel
from editor_timeline import TimelinePanel

from transcriber import transcribe_video, save_srt, detect_deadair_segments

# ── Subtitle & AI Transcription modules ───────────────────────────────────────
try:
    from subtitle_config import (SubtitleStyle, FONT_CHOICES,
                                  ANIMATION_CHOICES, POSITION_CHOICES,
                                  DECORATION_CHOICES, PRESETS)
    from subtitle_renderer import draw_subtitles_on_frame
    from video_exporter import export_video_with_subtitles
    HAS_SUBTITLES = True
except ImportError:
    HAS_SUBTITLES = False
    FONT_CHOICES = ANIMATION_CHOICES = POSITION_CHOICES = DECORATION_CHOICES = []
    PRESETS = []
    class SubtitleStyle:
        font_name="Arial"; font_size=32; font_color="#ffffff"
        decoration="outline"; animation="none"; position="bottom_center"
        margin_x=40; margin_y=40; custom_x=0.5; custom_y=0.85
        line_spacing=8; bg_opacity=0.5; max_chars_per_line=40; max_lines=2



def _build_atempo_filter(speed: float) -> str:
    """Chain FFmpeg atempo filters to support any speed multiplier between 0.1x and 10.0x."""
    spd = max(0.1, min(10.0, float(speed)))
    filters = []
    curr = spd
    while curr > 2.0:
        filters.append("atempo=2.0")
        curr /= 2.0
    while curr < 0.5:
        filters.append("atempo=0.5")
        curr /= 0.5
    filters.append(f"atempo={curr:.4f}")
    return ",".join(filters)

# ── Enable GPU / OpenCL acceleration ─────────────────────────────────────────
try:
    cv2.setUseOptimized(True)
    cv2.ocl.setUseOpenCL(True)
except Exception:
    pass

# ── PyTorch CUDA frame processing utilities ───────────────────────────────────
_TORCH_CUDA = False
_torch_device = None
try:
    import torch
    if torch.cuda.is_available():
        _TORCH_CUDA = True
        _torch_device = torch.device("cuda")
        # Allow TF32 for faster GPU matrix ops (Ampere+ GPUs)
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True   # optimise kernels for fixed input sizes
        print(f"[EditorPage] PyTorch CUDA enabled: {torch.cuda.get_device_name(0)}")
except Exception:
    pass


def _gpu_resize_bgr(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """
    Fast C++ OpenCV resize for preview frames during playback.
    Avoids host-device PyTorch memory roundtrips that cause PCIe latency stutter.
    """
    if frame is None:
        return frame
    return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)


def _gpu_bgr2rgb(frame: np.ndarray) -> np.ndarray:
    """
    Fast BGR to RGB channel view flip (zero-copy numpy slice).
    """
    if frame is None:
        return frame
    return frame[:, :, ::-1]


# ═════════════════════════════════════════════════════════════════════════════
class EditorPage(ctk.CTkFrame):

    # ── init ──────────────────────────────────────────────────────────────────
    def __init__(self, master, initial_video=None, initial_project=None, on_back=None):
        super().__init__(master, fg_color=BG_DEEP, corner_radius=0)
        self.master   = master
        self._on_back = on_back

        # Track data: {key: [clip_dict, ...]}  — layer_N keys created dynamically
        self.tracks  = {"main": [], "subtitle": [], "audio_0": []}
        self.assets  = []
        self.segments: list[dict] = []
        self.style   = SubtitleStyle()

        # Selection
        self.sel_track = "main"
        self.sel_idx   = -1

        # Drag state (managed by components but coordinates stored here if needed)
        self._dm   = None
        self._dtk  = None
        self._di   = -1
        self._dx0  = 0.0
        self._tl0  = 0.0
        self._st0  = 0.0
        self._en0  = 0.0

        # Playback
        self.cap        = None
        self._cap_path  = None
        self.fi         = 0       # frame index at TARGET_FPS
        self.playing    = False
        self._pt0       = -1.0   # perf_counter at play start (-1 = not set)
        self._pfi0      = 0      # fi at play start
        self._audio_tmp = None
        self._play_speed = 1.0   # effective playback speed (from active clip)

        # Frame buffer
        self._fbuf      = queue.Queue(maxsize=FRAME_BUF)
        self._dec_stop  = threading.Event()
        self._dec_th    = None
        self._dec_gen   = 0
        self._disp_img  = None
        self._last_raw_bgr = None  # cache raw frame for live preview refresh

        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)

        # Undo stacks
        self._undo: list = []
        self._redo: list = []

        # Tk vars
        self.v_ratio  = tk.StringVar(value="16:9")
        self.v_zoom   = tk.DoubleVar(value=1.0)
        self.v_vol    = tk.DoubleVar(value=1.0)
        self.v_speed  = tk.DoubleVar(value=1.0)
        self.v_text   = tk.StringVar(value="")

        self._thumbs:    dict = {}
        self._waveforms: dict = {}   # path → list[float] 0..1 amplitude bars
        self._cv_w: int       = 640   # cached preview canvas width
        self._cv_h: int       = 360   # cached preview canvas height
        self._canvas_img_id   = None  # canvas image item ID
        self._muted:     dict = {}
        self._solo_key:  str  = ""   # "" = none soloed
        self._multi_sel: list = []   # [(track_key, idx), ...]
        self._jkl_speed: float = 1.0 # J=rev/K=pause/L=fwd speed multiplier

        # ── Proxy manager (smooth preview) ────────────────────────────────────
        self._proxy_mgr = ProxyManager()
        threading.Thread(target=self._proxy_mgr.cleanup_old, daemon=True).start()

        # ── Waveform worker queue (sequential background processing) ──────────
        self._wf_queue = queue.Queue()
        self._wf_thread = threading.Thread(target=self._wf_worker, daemon=True)
        self._wf_thread.start()

        self._build_ui()

        if initial_project:
            self._load_project_file(initial_project)
            self._current_project_path = initial_project
        elif initial_video:
            self._load_video(initial_video)

        # Remove the loading overlay immediately and show first frame
        self.update_idletasks()
        if hasattr(self, "_overlay") and self._overlay.winfo_exists():
            self._overlay.destroy()
        self._render(0)
        self._tab("Media")
        # Defer a second render after layout settles so canvas has real size
        self.after(200, lambda: self._render(self.fi))

        # ── Audio: start AFTER clips are on the timeline ─────────────────────
        if initial_project:
            pass  # _setup_audio already called inside _load_project_file
        elif initial_video:
            self._setup_audio(initial_video)
            self._extract_waveforms_bg(initial_video)

        self._autosave_start()
        self._bind_keys()

    # ── load ──────────────────────────────────────────────────────────────────
    def _load_video(self, path):
        name = os.path.basename(path)
        self._proj_name = name
        self._current_project_path = None  # reset: new video → not yet saved
        if hasattr(self, "_proj_title_lbl"):
            self._proj_title_lbl.configure(text=self._proj_name)
        cap  = cv2.VideoCapture(path)
        fps  = cap.get(cv2.CAP_PROP_FPS) or 25
        cnt  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        dur  = cnt / fps
        cap.release()
        asset = {"path":path,"name":os.path.basename(path),"type":"video"}
        self.assets.append(asset)
        self.tracks["main"].append(self._clip(path,asset["name"],0,dur,fps=fps))
        self._push_undo()
        # ── Kick off proxy + waveform after UI is fully shown (defer 500ms) ──
        self.after(500, lambda p=path: self._start_proxy_build(p))
        self._extract_waveforms_bg(path)
        # Audio is set up in __init__ after _load_video returns (timeline already has clip)

    def _clip(self, path, name, start, end, tl=0.0, fps=25.0):
        return {"path":path,"name":name,"start":start,"end":end,
                "speed":1.0,"volume":1.0,"tl":tl,"fps":fps,
                "fade_in":0.0,"fade_out":0.0,
                "source_dur": end}

    # ── Proxy build helpers ───────────────────────────────────────────────────
    def _start_proxy_build(self, path):
        """Trigger async proxy build and report progress via status bar."""
        fname = os.path.basename(path)
        self._status(f"🔄 Building proxy for '{fname}'… 0%")
        def _on_r(px):
            try:
                if self.winfo_exists():
                    self.after(0, lambda: self._on_proxy_ready(path, px))
            except Exception:
                pass
        def _on_p(pct):
            try:
                if self.winfo_exists():
                    self.after(0, lambda: self._on_proxy_progress(fname, pct))
            except Exception:
                pass
        self._proxy_mgr.build_proxy_async(
            path,
            on_ready_cb=_on_r,
            on_progress_cb=_on_p,
        )

    def _on_proxy_progress(self, fname: str, pct: int):
        """Update status bar with proxy build progress."""
        self._status(f"🔄 Building proxy '{fname}'… {pct}%")

    def _on_proxy_ready(self, original_path: str, proxy_path: str):
        """Called when proxy is finished — switch cap to proxy."""
        # Force-release the current cap so next _render() picks up the proxy
        if self.cap is not None:
            self.cap.release()
            self.cap = None
            self._cap_path = None
        fname = os.path.basename(original_path)
        self._status(f"✅ Proxy ready — '{fname}' previewing at 480p")
        # Re-render current frame using the new proxy
        self._render(self.fi)
        # Restore normal status after 4 seconds
        self.after(4000, lambda: self._status("Ready"))

    def _show_proxy_bar(self, message: str, progress: str = ""):
        """Compat shim — route to status bar."""
        self._status(f"{message} {progress}".strip())

    def _hide_proxy_bar(self):
        """Compat shim — restore normal status."""
        self._status("Ready")

    def _setup_audio(self, path=None):
        """
        Build and load the timeline preview audio track into pygame mixer.
        Mixes all active main video clips and audio track clips on the timeline.
        """
        def run():
            try:
                self._status("🔊 Processing audio...")
                import imageio_ffmpeg
                ff = imageio_ffmpeg.get_ffmpeg_exe()

                main_audio = []
                for cl in self.tracks.get("main", []):
                    cp = cl.get("path", "")
                    if cp and os.path.exists(cp):
                        main_audio.append(cl)

                other_audio = []
                for ak in sorted(self._audio_keys()):
                    for cl in self.tracks.get(ak, []):
                        cp = cl.get("path", "")
                        if cp and os.path.exists(cp):
                            other_audio.append(cl)

                fd, tmp = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                self._audio_tmp = tmp

                if not main_audio and not other_audio:
                    # Create 5s silent WAV if no clips
                    cmd = [ff, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "5", tmp]
                    subprocess.run(cmd, capture_output=True, timeout=10)
                    try:
                        if not pygame.mixer.get_init():
                            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
                        pygame.mixer.music.load(tmp)
                    except Exception:
                        pass
                    return

                success = False

                # FAST PATH: Single Main Clip with no audio tracks
                if len(main_audio) == 1 and not other_audio:
                    cl0 = main_audio[0]
                    c_path = cl0["path"]
                    st0 = cl0.get("start", 0.0)
                    en0 = cl0.get("end", 0.0)
                    spd0 = max(cl0.get("speed", 1.0), 0.01)
                    vol0 = max(0.0, cl0.get("volume", 1.0))
                    dur0 = max(0.01, (en0 - st0) / spd0)

                    if st0 == 0.0 and abs(spd0 - 1.0) < 0.01 and abs(vol0 - 1.0) < 0.01:
                        cmd = [ff, "-y", "-i", c_path, "-vn", "-ar", "44100", "-ac", "2", tmp]
                    else:
                        atempo = _build_atempo_filter(spd0)
                        vol_f = f",volume={vol0:.3f}" if abs(vol0 - 1.0) > 0.01 else ""
                        cmd = [
                            ff, "-y", "-ss", str(st0), "-t", str(dur0),
                            "-i", c_path, "-vn",
                            "-filter_complex", f"[0:a]{atempo}{vol_f}[aout]",
                            "-map", "[aout]", "-ar", "44100", "-ac", "2", tmp
                        ]
                    proc = subprocess.run(cmd, capture_output=True, timeout=45)
                    success = (proc.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0)

                # MULTI-CLIP PATH: Concat Main clips + mix audio tracks
                if not success:
                    inputs_args = []
                    filter_chains = []
                    inp_idx = 0

                    main_tag = None
                    if main_audio:
                        main_chain_tags = []
                        for cl in main_audio:
                            c_path = cl["path"]
                            st   = cl.get("start", 0.0)
                            en   = cl.get("end", 0.0)
                            spd  = max(cl.get("speed", 1.0), 0.01)
                            dur  = max(0.01, (en - st) / spd)
                            vol  = max(0.0, cl.get("volume", 1.0))
                            inputs_args += ["-ss", str(st), "-t", str(dur), "-i", c_path]

                            chain_parts = []
                            if spd != 1.0:
                                chain_parts.append(_build_atempo_filter(spd))
                            if abs(vol - 1.0) > 0.01:
                                chain_parts.append(f"volume={vol:.3f}")
                            chain_str = ",".join(chain_parts) if chain_parts else "anull"
                            filter_chains.append(f"[{inp_idx}:a]{chain_str}[ma{inp_idx}]")
                            main_chain_tags.append(f"[ma{inp_idx}]")
                            inp_idx += 1

                        if len(main_chain_tags) == 1:
                            main_tag = main_chain_tags[0]
                        else:
                            cat_str = "".join(main_chain_tags)
                            filter_chains.append(f"{cat_str}concat=n={len(main_chain_tags)}:v=0:a=1[main_out]")
                            main_tag = "[main_out]"

                    other_tags = []
                    for cl in other_audio:
                        c_path   = cl["path"]
                        st       = cl.get("start", 0.0)
                        en       = cl.get("end", 0.0)
                        tl       = cl.get("tl", 0.0)
                        spd      = max(cl.get("speed", 1.0), 0.01)
                        vol      = max(0.0, cl.get("volume", 1.0))
                        dur      = max(0.01, (en - st) / spd)
                        delay_ms = max(0, int(tl * 1000))
                        inputs_args += ["-ss", str(st), "-t", str(dur), "-i", c_path]

                        chain_parts = []
                        if spd != 1.0:
                            chain_parts.append(_build_atempo_filter(spd))
                        if delay_ms > 0:
                            chain_parts.append(f"adelay={delay_ms}|{delay_ms}:all=1")
                        if abs(vol - 1.0) > 0.01:
                            chain_parts.append(f"volume={vol:.3f}")
                        chain_str = ",".join(chain_parts) if chain_parts else "anull"
                        filter_chains.append(f"[{inp_idx}:a]{chain_str}[oa{inp_idx}]")
                        other_tags.append(f"[oa{inp_idx}]")
                        inp_idx += 1

                    all_mix_tags = ([main_tag] if main_tag else []) + other_tags
                    if len(all_mix_tags) == 1:
                        filter_complex = ";".join(filter_chains) + f";{all_mix_tags[0]}anull[aout]"
                    else:
                        mix_str = "".join(all_mix_tags)
                        filter_complex = ";".join(filter_chains) + f";{mix_str}amix=inputs={len(all_mix_tags)}:normalize=0[aout]"

                    cmd = [ff, "-y"] + inputs_args + [
                        "-filter_complex", filter_complex,
                        "-map", "[aout]",
                        "-ar", "44100", "-ac", "2",
                        tmp
                    ]
                    proc = subprocess.run(cmd, capture_output=True, timeout=60)
                    success = (proc.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0)

                # FALLBACK: Directly decode first available audio clip
                if not success:
                    first_clip = (main_audio or other_audio)[0]
                    cmd_fb = [ff, "-y", "-i", first_clip["path"], "-vn", "-ar", "44100", "-ac", "2", tmp]
                    subprocess.run(cmd_fb, capture_output=True, timeout=30)

                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    try:
                        if not pygame.mixer.get_init():
                            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
                        pygame.mixer.music.load(tmp)
                        self.after(0, lambda: self._status("🔊 Audio ready"))
                    except Exception as mx_err:
                        print(f"[Mixer Load] {mx_err}")
                        try:
                            pygame.mixer.quit()
                            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
                            pygame.mixer.music.load(tmp)
                        except Exception as e2:
                            print(f"[Mixer Reinit] {e2}")
                else:
                    print("[Audio] output WAV missing/empty — audio will be silent")
            except Exception as e:
                print(f"[Audio Error] {e}")
            try:
                if self.winfo_exists():
                    self.after(0, self._finish_load)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _reload_audio(self):
        """Rebuild and reload mixed audio after track changes."""
        self._setup_audio()

    def _finish_load(self):
        """Called when audio is ready – just update status."""
        self._status("Ready")


    # ── keys ──────────────────────────────────────────────────────────────────
    def _is_typing(self):
        w = self.master.focus_get()
        if w is None:
            return False
        classname = w.winfo_class()
        if "Entry" in classname or "Text" in classname or isinstance(w, (tk.Entry, tk.Text, ctk.CTkEntry)):
            return True
        return False

    def _bind_keys(self):
        # 1. Control Key Combinations (Ctrl+Z, Ctrl+Y, Ctrl+S, Ctrl+O, Ctrl+I, Ctrl+B)
        def _on_ctrl_key(event):
            if self._is_typing():
                return  # let the widget handle it normally (copy/paste in entries)
            key = event.keysym.lower()
            code = event.keycode
            # US keycodes: Z=90, Y=89, S=83, O=79, I=73, B=66
            if key == 'z' or code == 90:
                self._undo_do()
                return "break"
            elif key == 'y' or code == 89:
                self._redo_do()
                return "break"
            elif key == 'b' or code == 66:
                self._split()
                return "break"
            elif key == 's' or code == 83:
                if event.state & 1:  # Ctrl+Shift+S = Save As
                    self._save_as()
                else:
                    self._save()
                return "break"
            elif key == 'o' or code == 79:
                self._load_project()
                return "break"
            elif key == 'i' or code == 73:
                self._import()
                return "break"
            # All other Ctrl combos (C, V, X, A, etc.) → fall through so OS/widgets handle them

        # 2. General Keyboard Shortcuts (S, G, M, J, K, L, Space, Delete, Backspace, Arrows)
        def _on_general_key(event):
            if self._is_typing():
                return
            # If Control modifier is active, ignore (let _on_ctrl_key or OS handle it)
            if event.state & 4:
                return

            key = event.keysym.lower()
            code = event.keycode

            # Arrow keys & Space & Delete
            if key == "space" or code == 32:
                self._toggle_play()
                return "break"
            elif key in ("delete", "backspace") or code in (46, 8):
                self._del_sel()
                return "break"
            elif key == "left" or code == 37:
                shift = (event.state & 1)  # Shift key active
                self._step(-TARGET_FPS if shift else -1)
                return "break"
            elif key == "right" or code == 39:
                shift = (event.state & 1)
                self._step(TARGET_FPS if shift else 1)
                return "break"
            # US layout single keys: S=83, G=71, M=77, J=74, K=75, L=76
            elif key == 's' or code == 83:
                self._split()
                return "break"
            elif key == 'g' or code == 71:
                self._ripple_delete()
                return "break"
            elif key == 'm' or code == 77:
                self._toggle_mute_sel()
                return "break"
            elif key == 'j' or code == 74:
                self._jkl("J")
                return "break"
            elif key == 'k' or code == 75:
                self._jkl("K")
                return "break"
            elif key == 'l' or code == 76:
                self._jkl("L")
                return "break"

        # Bind globally to the root window master
        self.master.bind("<Control-KeyPress>", _on_ctrl_key)
        self.master.bind("<KeyPress>", _on_general_key)

    # ── J/K/L playback ────────────────────────────────────────────────────────
    def _jkl(self, key):
        if key == "K":
            self._stop(); self._jkl_speed = 1.0; return
        if key == "L":
            if self.playing and self._jkl_speed > 0:
                self._jkl_speed = min(4.0, self._jkl_speed * 2)
                self._status(f"Speed ×{self._jkl_speed:.0f}")
            else:
                self._jkl_speed = 1.0; self._play()
        if key == "J":
            if self.playing and self._jkl_speed < 0:
                self._jkl_speed = max(-4.0, self._jkl_speed * 2)
                self._status(f"Reverse ×{abs(self._jkl_speed):.0f}")
            else:
                self._stop()
                self._jkl_speed = -1.0
                self._status("Reverse play (frame step)")

    # ── Real waveform extraction (queued in background) ───────────────────────
    def _wf_worker(self):
        while True:
            try:
                path = self._wf_queue.get()
                if path:
                    self._extract_waveform(path)
                self._wf_queue.task_done()
            except Exception as e:
                pass

    def _extract_waveforms_bg(self, path):
        if path and path not in self._waveforms:
            self._wf_queue.put(path)

    def _extract_waveform(self, path, n_bars=200):
        if path in self._waveforms: return
        try:
            import struct as _struct, math as _math
            ff  = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [ff,"-y","-i",path,"-vn","-ar","8000","-ac","1","-f","s16le","-"]
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            raw  = proc.stdout
            n    = len(raw) // 2
            if n < 2: raise RuntimeError("No audio")
            samps = _struct.unpack(f"<{n}h", raw[:n*2])
            chunk = max(1, n // n_bars)
            bars  = []
            for i in range(n_bars):
                sl = samps[i*chunk:(i+1)*chunk]
                if not sl: bars.append(0.05); continue
                rms = _math.sqrt(sum(x*x for x in sl) / len(sl))
                bars.append(min(1.0, rms / 6000.0))
            mx = max(bars) or 1.0
            self._waveforms[path] = [b/mx for b in bars]
            self.after(0, self._draw_tl)
        except Exception:
            random.seed(hash(path) % 9999)
            self._waveforms[path] = [0.15 + random.random()*0.85 for _ in range(n_bars)]

    # ── Project load ──────────────────────────────────────────────────────────
    def _load_project(self):
        path = filedialog.askopenfilename(
            title="Open Project",
            initialdir=_ld.get(_ld.OPEN_PROJECT),
            filetypes=[("VideoAI Project","*.json"),("All","*.*")])
        if not path: return
        _ld.remember(_ld.OPEN_PROJECT, path)
        try:
            with open(path) as f: data = json.load(f)
            saved = data.get("tracks", {})
            self.tracks = {"main": [], "subtitle": [], "audio_0": []}
            # Restore all tracks including dynamic layers
            for k, v in saved.items():
                self.tracks[k] = v
            # Compat: rename old key names
            for old, new in [("audio1","audio_0"),("audio2","audio_1"),("overlay","layer_0"),("text","layer_1")]:
                if old in self.tracks and new not in self.tracks:
                    self.tracks[new] = self.tracks.pop(old)
            if data.get("assets"): self.assets = data["assets"]
            self.segments = data.get("segments", [])
            
            # Fallback to recreate segments if project had subtitle clips but no segments
            if not self.segments and self.tracks.get("subtitle"):
                self.segments = []
                for clip in self.tracks["subtitle"]:
                    self.segments.append({
                        "start": clip.get("tl", 0.0),
                        "end": clip.get("tl", 0.0) + (clip.get("end", 5.0) - clip.get("start", 0.0)) / max(clip.get("speed", 1.0), 0.01),
                        "text": clip.get("sub_text", clip.get("name", ""))
                    })

            if hasattr(self, "transcript_panel"):
                self.transcript_panel.set_segments(self.segments)

            self._rebuild_label_column()
            self._push_undo(); self._draw_tl(); self._render(0)
            self._tab("Media"); self._status(f"Loaded: {os.path.basename(path)}")
            for k in self._audio_keys():
                for cl in self.tracks[k]:
                    if cl.get("path"): self._extract_waveforms_bg(cl["path"])
            # Also extract waveforms for main track video clips
            for cl in self.tracks.get("main", []):
                if cl.get("path"): self._extract_waveforms_bg(cl["path"])
            for lk in [k for k in self.tracks if k.startswith("layer_")]:
                for cl in self.tracks[lk]:
                    if cl.get("path"): self._extract_waveforms_bg(cl["path"])
            # Add to recents
            self._add_to_recent(path)
        except Exception as ex: messagebox.showerror("Load Error", str(ex))

    def _add_to_recent(self, project_path):
        try:
            recent_file = os.path.join(os.path.dirname(__file__), "recent_projects.json")
            recent_list = []
            if os.path.exists(recent_file):
                try:
                    with open(recent_file, "r") as f:
                        recent_list = json.load(f)
                except:
                    pass
            recent_list = [p for p in recent_list if p.get("path") != project_path]
            
            main_video = ""
            if self.tracks.get("main"):
                main_video = self.tracks["main"][0]["path"]
                
            import time
            recent_list.insert(0, {
                "path": project_path,
                "name": os.path.basename(project_path),
                "modified": time.time(),
                "main_video": main_video
            })
            recent_list = recent_list[:10]
            with open(recent_file, "w") as f:
                json.dump(recent_list, f, indent=2)
        except Exception as e:
            print(f"Error updating recents: {e}")

    def _relocate_path(self, old_path: str, project_dir: str) -> str:
        if not old_path or os.path.exists(old_path):
            return old_path
        filename = os.path.basename(old_path)
        c1 = os.path.join(project_dir, filename)
        if os.path.exists(c1):
            return c1
        c2 = os.path.join(project_dir, "media", filename)
        if os.path.exists(c2):
            return c2
        return old_path

    def _load_project_file(self, path):
        try:
            name = os.path.basename(path)
            self._proj_name = name
            if hasattr(self, "_proj_title_lbl"):
                self._proj_title_lbl.configure(text=self._proj_name)
            with open(path) as f: data = json.load(f)
            saved = data.get("tracks", {})
            self.tracks = {"main": [], "subtitle": [], "audio_0": []}
            for k, v in saved.items():
                self.tracks[k] = v
            for old, new in [("audio1","audio_0"),("audio2","audio_1"),("overlay","layer_0"),("text","layer_1")]:
                if old in self.tracks and new not in self.tracks:
                    self.tracks[new] = self.tracks.pop(old)

            # Auto-relocate paths if project folder was moved
            proj_dir = os.path.dirname(os.path.abspath(path))
            for tk, clips in self.tracks.items():
                for cl in clips:
                    if cl.get("path"):
                        cl["path"] = self._relocate_path(cl["path"], proj_dir)
            if data.get("assets"):
                self.assets = data["assets"]
                for ast in self.assets:
                    if ast.get("path"):
                        ast["path"] = self._relocate_path(ast["path"], proj_dir)
            self.segments = data.get("segments", [])

            if "ratio" in data and hasattr(self, "v_ratio"):
                self.v_ratio.set(data["ratio"])

            if "style" in data and hasattr(self, "style"):
                st = data["style"]
                if "font_name" in st: self.style.font_name = st["font_name"]
                if "font_size" in st: self.style.font_size = st["font_size"]
                if "font_color" in st: self.style.font_color = st["font_color"]
                if "decoration" in st: self.style.decoration = st["decoration"]
                if "animation" in st: self.style.animation = st["animation"]
                if "position" in st: self.style.position = st["position"]
            
            if not self.segments and self.tracks.get("subtitle"):
                self.segments = []
                for clip in self.tracks["subtitle"]:
                    self.segments.append({
                        "start": clip.get("tl", 0.0),
                        "end": clip.get("tl", 0.0) + (clip.get("end", 5.0) - clip.get("start", 0.0)) / max(clip.get("speed", 1.0), 0.01),
                        "text": clip.get("sub_text", clip.get("name", ""))
                    })

            if self.tracks.get("main"):
                main_video_path = self.tracks["main"][0]["path"]
                self._setup_audio(main_video_path)
                self._extract_waveforms_bg(main_video_path)
                # Also extract waveforms for all main track clips
                for cl in self.tracks.get("main", []):
                    if cl.get("path"): self._extract_waveforms_bg(cl["path"])
                # Extract waveforms for audio and layer tracks
                for k in self._audio_keys():
                    for cl in self.tracks.get(k, []):
                        if cl.get("path"): self._extract_waveforms_bg(cl["path"])
                for lk in [k for k in self.tracks if k.startswith("layer_")]:
                    for cl in self.tracks.get(lk, []):
                        if cl.get("path"): self._extract_waveforms_bg(cl["path"])
                # ── Build proxy after UI settles (defer 500ms) ───────────────────
                self.after(500, lambda p=main_video_path: self._start_proxy_build(p))

            if hasattr(self, "transcript_panel"):
                self.transcript_panel.set_segments(self.segments)
                
            self.after(50, lambda: self._rebuild_label_column())
            self._push_undo()
            
            self._add_to_recent(path)
        except Exception as ex:
            messagebox.showerror("Load Error", f"Failed to load project:\n{ex}")

    # ── Mute / Solo (real) ────────────────────────────────────────────────────
    def _toggle_mute_sel(self):
        k = self.sel_track
        self._muted[k] = not self._muted.get(k, False)
        lbl = TRACK_BY_KEY.get(k, {}).get("label", k)
        self._status(f"{'Muted' if self._muted[k] else 'Unmuted'}: {lbl}")
        self._rebuild_label_column(); self._draw_tl()
        self._build_track_controls()

    def _toggle_mute_track(self, key):
        self._muted[key] = not self._muted.get(key, False)
        lbl = TRACK_BY_KEY.get(key, {}).get("label", key)
        self._status(f"{'Muted' if self._muted[key] else 'Unmuted'}: {lbl}")
        self._rebuild_label_column(); self._draw_tl()
        self._build_track_controls()

    def _solo_track(self, key):
        self._solo_key = "" if self._solo_key == key else key
        lbl = TRACK_BY_KEY.get(key, {}).get("label", key)
        self._status(f"Solo: {lbl}" if self._solo_key else "Solo off")
        self._rebuild_label_column(); self._draw_tl()
        self._build_track_controls()

    def _is_active(self, key):
        if self._solo_key: return key == self._solo_key
        return not self._muted.get(key, False)

    # ── Dynamic layer helpers ─────────────────────────────────────────────────
    def _layer_keys(self) -> list[str]:
        """Return sorted list of layer_N keys (e.g. ['layer_0','layer_1'])"""
        keys = [k for k in self.tracks if k.startswith("layer_")]
        return sorted(keys, key=lambda k: int(k.split("_")[1]))

    def _audio_keys(self) -> list[str]:
        """Return sorted list of audio_N keys"""
        keys = [k for k in self.tracks if k.startswith("audio_")]
        return sorted(keys, key=lambda k: int(k.split("_")[1]))

    def _all_track_rows(self) -> list[tuple]:
        """
        Return (key, label, color, height, kind) for every row top→bottom:
          Layer N (highest = top), …, Layer 0, [empty slot], MAIN, SUBTITLE, AUDIO
        """
        rows = []
        layer_keys = self._layer_keys()

        # Layers — highest number draws at top (most overlay)
        for key in reversed(layer_keys):
            n = int(key.split("_")[1])
            rows.append((key, f"Layer {n+1}", C_PURPLE, 30, "layer"))

        # Always show one empty Layer slot at top so the user has somewhere to drop
        rows.append(("__empty_layer__", "+ Layer", "#2a1a3a", 28, "empty"))

        # Main video
        rows.append(("main", "VIDEO", C_BLUE, 56, "main"))
        # Subtitle
        rows.append(("subtitle", "SUBTITLE", C_AMBER, 28, "subtitle"))

        # Audio tracks: show those with clips, plus always at least one empty slot
        audio_keys = self._audio_keys()
        shown_any_empty = False
        for key in audio_keys:
            n = int(key.split("_")[1])
            label = f"AUDIO {n+1}"
            col = C_TEAL if n == 0 else C_GREEN
            rows.append((key, label, col, 32, "audio"))
            if not self.tracks.get(key):
                shown_any_empty = True

        # Always ensure at least one empty audio slot exists for dropping
        if not shown_any_empty:
            existing = audio_keys
            next_n = int(existing[-1].split("_")[1]) + 1 if existing else 0
            new_key = f"audio_{next_n}"
            if new_key not in self.tracks:
                self.tracks[new_key] = []
            label = f"AUDIO {next_n+1}"
            col = C_TEAL if next_n == 0 else C_GREEN
            rows.append((new_key, label, col, 32, "audio"))

        return rows


    def _find_free_layer(self, tl_start: float, tl_end: float) -> str:
        """
        Find the lowest layer_N that has no clip overlapping [tl_start, tl_end].
        Creates a new layer if all existing ones are occupied.
        """
        for key in self._layer_keys():
            occupied = False
            for item in self.tracks[key]:
                dur = (item["end"] - item["start"]) / max(item.get("speed", 1.0), 0.01)
                item_tl = item.get("tl", 0.0)
                # Check overlap
                if item_tl < tl_end and item_tl + dur > tl_start:
                    occupied = True
                    break
            if not occupied:
                return key
        # All occupied: spawn a new layer
        existing = self._layer_keys()
        n = int(existing[-1].split("_")[1]) + 1 if existing else 0
        new_key = f"layer_{n}"
        self.tracks[new_key] = []
        self._rebuild_label_column()  # refresh sidebar
        return new_key

    # ── Ripple delete (G key) ─────────────────────────────────────────────────
    def _ripple_delete(self):
        items = self.tracks.get(self.sel_track, [])
        if not (0 <= self.sel_idx < len(items)):
            self._status("Nothing selected for ripple delete (G)"); return
        clip  = items[self.sel_idx]
        dur   = (clip["end"] - clip["start"]) / max(clip["speed"], 0.01)
        tl_rm = clip.get("tl", 0.0)
        items.pop(self.sel_idx)
        for c in items:
            if c.get("tl", 0.0) >= tl_rm + dur - 0.01:
                c["tl"] = max(0.0, c["tl"] - dur)
        self.sel_idx = max(0, self.sel_idx - 1)
        self._push_undo(); self._draw_tl()
        self._status(f"Ripple delete — pulled {_ft(dur)}")

    # ── Magnetic snap ─────────────────────────────────────────────────────────
    def _snap(self, tl: float, excl_k: str, excl_i: int) -> float:
        sc = 30.0
        if hasattr(self, "timeline_panel"):
            sc = self.timeline_panel._scale()
        thresh = SNAP_PX / max(sc, 0.01)
        best = tl; best_d = thresh
        candidates = [0.0, self.fi / float(TARGET_FPS)]
        for k, clips in self.tracks.items():
            for i, c in enumerate(clips):
                if k == excl_k and i == excl_i: continue
                dur = (c["end"]-c["start"])/max(c.get("speed", 1.0), 0.01)
                candidates += [c.get("tl",0.0), c.get("tl",0.0)+dur]
        for sp in candidates:
            d = abs(sp - tl)
            if d < best_d: best_d = d; best = sp
        if best != tl: self._status(f"Snapped to {_ft(best)}")
        return best

    # ─────────────────────────────────────────────────────────────────────────
    # UI BUILD
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_header()

        # Bottom Timeline Panel (Full width across bottom "ไทม์ไลน์ยาวจนสุดมุม")
        self.timeline_panel = TimelinePanel(self, controller=self)
        self.timeline_panel.pack(side="bottom", fill="x", padx=8, pady=(4, 8))
        self._tlc = self.timeline_panel._tlc
        self._lcc = self.timeline_panel._lcc

        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        # Left Sidebar & Media lists (explicit 330px width)
        self.media_panel = MediaPanel(mid, controller=self)
        self.media_panel.configure(width=330)
        self.media_panel.pack_propagate(False)
        self.media_panel.pack(side="left", fill="y", padx=(0, 6))
        self._mpanel = self.media_panel._mpanel
        self._pscroll = self.media_panel._pscroll
        self._ptitle = self.media_panel._ptitle
        self._tbtn = self.media_panel._tbtn

        # Center Video Canvas Preview
        self.preview_panel = PreviewPanel(mid, controller=self)
        self.preview_panel.pack(side="left", fill="both", expand=True, padx=3)
        self.canvas = self.preview_panel.canvas
        self._scrub = self.preview_panel._scrub
        self._scrub_v = self.preview_panel._scrub_v
        self._tlbl = self.preview_panel._tlbl
        self._pbtn = self.preview_panel._pbtn

        # Right Properties Panel
        self.properties_panel = PropertiesPanel(mid, controller=self)
        self.properties_panel.pack(side="right", fill="y", padx=(6, 0))
        self._pp = self.properties_panel
        self._pp_dyn = self.properties_panel._pp_dyn
        self._track_ctrl_frame = self.properties_panel._track_ctrl_frame

        # Loading overlay
        self._overlay = ctk.CTkFrame(self, fg_color=BG_DEEP)
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        ctk.CTkLabel(self._overlay, text="Loading…",
                     font=ctk.CTkFont(size=16), text_color=TXT_L
                     ).place(relx=.5, rely=.5, anchor="center")

        self.transcript_panel = TranscriptPanel(
            parent=self.media_panel._pscroll,
            controller=self
        )

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        h = ctk.CTkFrame(self, height=54, fg_color=PANEL_DARK, corner_radius=0)
        h.pack(side="top", fill="x")
        h.pack_propagate(False)

        # Left: Home button (🏠 Home) + Logo + Project Name
        left = ctk.CTkFrame(h, fg_color="transparent")
        left.pack(side="left", padx=(10, 0), pady=4)

        ctk.CTkButton(left, text="🏠 Home", width=78, height=32, corner_radius=10,
                      fg_color=PANEL_MID, hover_color=PANEL_HOV,
                      text_color=TXT_W,
                      font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                      command=self._back
                      ).pack(side="left", padx=(0, 10))

        brand_box = ctk.CTkFrame(left, fg_color="transparent")
        brand_box.pack(side="left")

        ctk.CTkLabel(brand_box, text="MediaPro",
                     font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
                     text_color=TXT_W, anchor="w").pack(anchor="w")

        self._proj_name = "Untitled Project"
        self._proj_title_lbl = ctk.CTkLabel(brand_box, text=self._proj_name,
                                             font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                                             text_color="#60a5fa", anchor="w")
        self._proj_title_lbl.pack(anchor="w", pady=(0, 0))

        # Center: Status bar
        self._stat = ctk.CTkLabel(h, text="Ready · Space=play  S=split  G=ripple  M=mute",
                                   font=ctk.CTkFont(size=9), text_color=TXT_G)
        self._stat.pack(side="left", padx=20)

        # Right: Prominent Export Button (only export button shown)
        right = ctk.CTkFrame(h, fg_color="transparent")
        right.pack(side="right", padx=12)

        # Prominent rounded blue Export button
        ctk.CTkButton(right, text="Export", height=36, width=100, corner_radius=10,
                      fg_color="#3b82f6", hover_color="#2563eb",
                      font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                      text_color="#ffffff",
                      command=self._export).pack(side="right", padx=(6, 0))

        # Save As button
        ctk.CTkButton(right, text="Save As", height=32, width=72, corner_radius=8,
                      fg_color=PANEL_MID, hover_color=PANEL_HOV,
                      font=ctk.CTkFont(size=10, weight="bold"), command=self._save_as
                      ).pack(side="right", padx=3)

        # Save button — overwrites current file, shows Save As dialog if no file yet
        ctk.CTkButton(right, text="Save", height=32, width=58, corner_radius=8,
                      fg_color=PANEL_LIGHT, hover_color=PANEL_HOV,
                      font=ctk.CTkFont(size=10, weight="bold"), command=self._save
                      ).pack(side="right", padx=3)

    # ── Bridge Component Methods ──────────────────────────────────────────────
    def _rebuild_label_column(self):
        if hasattr(self, "timeline_panel"):
            self.timeline_panel._rebuild_label_column()

    def _draw_tl(self):
        if hasattr(self, "timeline_panel"):
            self.timeline_panel._draw_tl()

    def _scale(self):
        if hasattr(self, "timeline_panel"):
            return self.timeline_panel._scale()
        return 1.0

    def _show(self, frame):
        if hasattr(self, "preview_panel"):
            self.preview_panel._show(frame)

    def _refresh_preview(self):
        # Throttle to max 30fps to avoid CPU thrash from rapid property changes
        import time as _time
        now = _time.perf_counter()
        if hasattr(self, "_last_preview_t") and (now - self._last_preview_t) < 0.033:
            return
        self._last_preview_t = now
        if hasattr(self, "preview_panel"):
            self.preview_panel._refresh_preview()

    def _refresh_props(self):
        if hasattr(self, "properties_panel"):
            self.properties_panel._refresh_props()

    def _upd_time(self, t):
        if hasattr(self, "preview_panel"):
            self.preview_panel._upd_time(t)

    def _upd_scrub(self, t):
        if hasattr(self, "preview_panel"):
            self.preview_panel._upd_scrub(t)

    def _apply_overlay(self, frame, t):
        if hasattr(self, "preview_panel"):
            return self.preview_panel._apply_overlay(frame, t)
        return frame

    def _build_track_controls(self):
        if hasattr(self, "properties_panel"):
            self.properties_panel._build_track_controls()

    def _tab(self, name):
        if hasattr(self, "media_panel"):
            self.media_panel._tab(name)

    def _track_kind(self, track_key):
        if track_key in TRACK_BY_KEY:
            return TRACK_BY_KEY[track_key]["kind"]
        if track_key.startswith("layer_"):
            return "layer"
        if track_key.startswith("audio_"):
            return "audio"
        return ""

    # ── Smooth playback ───────────────────────────────────────────────────────
    def _toggle_play(self):
        if self.playing: self._stop()
        else:            self._play()

    def _play(self):
        self.playing = True
        self._dec_gen = getattr(self, "_dec_gen", 0) + 1
        gen = self._dec_gen
        self._dec_stop.set()  # signal any existing worker to exit immediately
        time.sleep(0.01)
        self._dec_stop.clear()

        if hasattr(self, "preview_panel"):
            self.preview_panel._pbtn.configure(text="⏸")

        # Determine effective play speed from the active clip at current time
        t = self.fi / float(TARGET_FPS)
        active_clip = self._at("main", t)
        self._play_speed = float(active_clip.get("speed", 1.0)) if active_clip else 1.0
        if self._play_speed <= 0:
            self._play_speed = 1.0

        # flush old buffer
        while not self._fbuf.empty():
            try: self._fbuf.get_nowait()
            except queue.Empty: break

        self._dec_th = threading.Thread(target=lambda g=gen: self._dec_worker(g), daemon=True)
        self._dec_th.start()

        start_sec = self.fi / float(TARGET_FPS)
        play_speed = self._play_speed
        def _start_audio_and_clock(g=gen):
            min_frames = min(12, FRAME_BUF - 1)
            deadline   = time.perf_counter() + 0.35
            while self._fbuf.qsize() < min_frames and time.perf_counter() < deadline:
                if not self.playing or g != getattr(self, "_dec_gen", 0):
                    return
                time.sleep(0.003)
            if not self.playing or g != getattr(self, "_dec_gen", 0):
                return
            try:
                # Set pygame volume from active clip
                _vol = 1.0
                if active_clip:
                    _vol = float(active_clip.get("volume", 1.0))
                pygame.mixer.music.set_volume(min(2.0, max(0.0, _vol)))
                pygame.mixer.music.play(start=start_sec)
            except Exception:
                pass
            self._pt0  = time.perf_counter()
            self._pfi0 = self.fi
        threading.Thread(target=_start_audio_and_clock, daemon=True).start()
        self.after(16, self._tick)

    def _stop(self):
        self.playing = False
        self._dec_gen = getattr(self, "_dec_gen", 0) + 1
        self._dec_stop.set()
        self._pt0 = -1.0  # reset clock sentinel
        if hasattr(self, "preview_panel"):
            self.preview_panel._pbtn.configure(text="▶")
            # Reset cached PhotoImage so pause path renders fresh high-quality frame
            self.preview_panel._disp_img = None
            self.preview_panel._canvas_img_id = None
        try: pygame.mixer.music.pause()
        except: pass
        # Flush queue on stop
        while not self._fbuf.empty():
            try: self._fbuf.get_nowait()
            except queue.Empty: break
        # Re-render the current frame so preview shows the paused image
        self.after(60, lambda: self._render(self.fi))
        self.after(80, self._draw_tl)

    def _dec_worker(self, gen=None):
        fi          = self.fi
        cap_path    = None
        cap         = None
        try:
            while self.playing and not self._dec_stop.is_set():
                if gen is not None and gen != getattr(self, "_dec_gen", 0):
                    break

                if self._fbuf.full():
                    time.sleep(0.005)
                    continue

                t    = fi / float(TARGET_FPS)
                clip = self._at("main", t)
                if not clip:
                    # ถ้าไม่มีคลิปหลัก ให้ขยับเฟรมไปข้างหน้าเรื่อยๆ
                    fi += 1
                    time.sleep(0.01)
                    continue

                src_fps = clip.get("fps", TARGET_FPS)
                src_t   = (t - clip.get("tl", 0.0)) * clip["speed"] + clip["start"]
                src_fi  = int(round(src_t * src_fps))

                play_path = self._proxy_mgr.get_proxy(clip["path"]) or clip["path"]

                if cap is None or cap_path != play_path:
                    if hasattr(cap, "release"): cap.release()
                    cap         = SmartVideoReader(play_path)
                    cap_path    = play_path

                # ดึงด้วย Exact Frame Index แทน Time Float
                ok, fr = cap.get_frame_at_index(src_fi)
                if not ok:
                    fi += 1
                    time.sleep(0.005)
                    continue

                sc = clip.get("scale", 1.0)
                rot = clip.get("rotate", 0.0)
                cx = clip.get("custom_x", 0.5)
                cy = clip.get("custom_y", 0.5)
                if sc != 1.0 or rot != 0.0 or cx != 0.5 or cy != 0.5:
                    fr = self._apply_clip_transform(fr, sc, rot, cx, cy)

                fr = self._apply_overlay(fr, t)

                if self.playing:
                    if hasattr(self, "preview_panel"):
                        fr_ready = self.preview_panel._crop_ratio(fr)
                        cw = max(getattr(self.preview_panel, "_cv_w", 640), 640)
                        ch = max(getattr(self.preview_panel, "_cv_h", 360), 360)
                    else:
                        fr_ready = fr
                        cw, ch = 640, 360
                    fh, fw = fr_ready.shape[:2]
                    sc_disp = min(cw / fw, ch / fh)
                    nw = max(1, int(fw * sc_disp))
                    nh = max(1, int(fh * sc_disp))
                    fr_ready = _gpu_resize_bgr(fr_ready, nw, nh)
                    fr_ready = _gpu_bgr2rgb(fr_ready)
                else:
                    fr_ready = fr

                try:
                    self._fbuf.put((fi, fr_ready), timeout=0.05)
                    fi += 1  # ขยับไปเฟรมถัดไปอย่างเคร่งครัด
                except queue.Full:
                    continue
        finally:
            if cap is not None and hasattr(cap, "release"):
                try: cap.release()
                except Exception: pass
            cap = None
            import gc; gc.collect()

    def _tick(self):
        if not self.playing: return
        if self._pt0 < 0:
            self.after(16, self._tick); return

        elapsed   = time.perf_counter() - self._pt0
        play_speed = getattr(self, "_play_speed", 1.0)
        
        # คำนวณว่า ณ เวลานี้ควรจะแสดงถึง frame index ไหน
        target_fi = self._pfi0 + int(elapsed * TARGET_FPS * play_speed)
        total_fi  = int(self._dur() * TARGET_FPS)

        if target_fi >= total_fi:
            self.fi = 0; self._stop(); self._render(0); return

        shown = None
        # ดึงเฟรมจากคิว และทิ้งเฟรมที่ตกรอบ (Frame Drop) เพื่อให้ทันเสียง
        while not self._fbuf.empty():
            try:
                fi, fr = self._fbuf.queue[0]
                if fi <= target_fi:
                    shown = self._fbuf.get_nowait()
                else:
                    break
            except (queue.Empty, IndexError):
                break

        if shown:
            self.fi = shown[0]
            self._show(shown[1])

            now = time.perf_counter()
            if not hasattr(self, "_last_ui_tick"):
                self._last_ui_tick = 0.0
            if now - self._last_ui_tick > 0.10:
                t = self.fi / float(TARGET_FPS)
                self._upd_time(t)
                self._upd_scrub(t)
                self._fast_ph_update()
                self._last_ui_tick = now

        self.after(16, self._tick)

    def _fast_ph_update(self):
        if not (hasattr(self.timeline_panel, '_tl_ph_line') and hasattr(self.timeline_panel, '_tlc')): return
        try:
            scale = self._scale()
            px    = (self.fi / float(TARGET_FPS)) * scale
            H     = self.timeline_panel._tlc.winfo_height()
            self.timeline_panel._tlc.coords(self.timeline_panel._tl_ph_line, px, 0, px, H)
            self.timeline_panel._tlc.coords(self.timeline_panel._tl_ph_cap,
                                            px-6, 0, px+6, 0, px+2, 10, px-2, 10)

            # Auto-scroll: throttle to 300ms — use cached scrollregion to avoid Tk IPC on every call
            now = time.perf_counter()
            if not hasattr(self, "_last_scroll_t"):
                self._last_scroll_t = 0.0
            if now - self._last_scroll_t < 0.3:
                return
            c = self.timeline_panel._tlc
            W = c.winfo_width()
            # Use cached scrollregion width (updated only when _draw_tl runs, not every frame)
            cw = getattr(self, "_cached_tl_cw", 0)
            if cw <= W:
                return
            left, right = c.xview()
            vis_left  = left * cw
            vis_right = right * cw
            margin = W * 0.15
            if px < vis_left or px > (vis_right - margin):
                target_left = px - W / 2
                c.xview_moveto(max(0.0, target_left / cw))
                self._last_scroll_t = now
        except Exception:
            pass

    def _go_start(self):  self._stop(); self.fi=0; self._render(0)
    def _go_end(self):
        self._stop()
        self.fi=max(0,int(self._dur()*TARGET_FPS)-1); self._render(self.fi)
    def _skip_b(self):
        self._stop(); self.fi=max(0,self.fi-TARGET_FPS*5); self._render(self.fi)
    def _skip_f(self):
        self._stop()
        self.fi=min(int(self._dur()*TARGET_FPS)-1,self.fi+TARGET_FPS*5)
        self._render(self.fi)
    def _step(self,d):
        self._stop()
        self.fi=max(0,min(int(self._dur()*TARGET_FPS)-1,self.fi+d))
        self._render(self.fi)
    def _scrub_seek(self,val):
        self._stop(); total=max(self._dur(),0.1)
        t=float(val)/1000*total; self.fi=int(t*TARGET_FPS); self._render(self.fi)

    # ── Rendering ─────────────────────────────────────────────────────────────
    def _apply_clip_transform(self, frame, scale=1.0, rotate=0.0, custom_x=0.5, custom_y=0.5):
        if frame is None or (scale == 1.0 and rotate == 0.0 and custom_x == 0.5 and custom_y == 0.5):
            return frame
        try:
            h, w = frame.shape[:2]
            if rotate != 0.0:
                angle = float(rotate)
                center = (w / 2.0, h / 2.0)
                M = cv2.getRotationMatrix2D(center, -angle, 1.0)
                border_val = (0, 0, 0, 0) if frame.shape[2] == 4 else (0, 0, 0)
                frame = cv2.warpAffine(frame, M, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=border_val)

            if scale != 1.0 and scale > 0.01:
                s = float(scale)
                nw = max(1, int(w * s))
                nh = max(1, int(h * s))
                resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

                canvas = np.zeros_like(frame)
                if s <= 1.0:
                    y_off = (h - nh) // 2
                    x_off = (w - nw) // 2
                    canvas[max(0, y_off):min(h, y_off+nh), max(0, x_off):min(w, x_off+nw)] = resized[:h, :w]
                    frame = canvas
                else:
                    frame = cv2.resize(resized, (w, h), interpolation=cv2.INTER_LINEAR)

            if custom_x != 0.5 or custom_y != 0.5:
                dx = int((float(custom_x) - 0.5) * w)
                dy = int((float(custom_y) - 0.5) * h)
                M_shift = np.float32([[1, 0, dx], [0, 1, dy]])
                border_val = (0, 0, 0, 0) if frame.shape[2] == 4 else (0, 0, 0)
                frame = cv2.warpAffine(frame, M_shift, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=border_val)
        except Exception as e:
            print(f"[Transform Error] {e}")
        return frame

    def _render(self, fi: int):
        t = fi / float(TARGET_FPS)
        self._upd_time(t); self._upd_scrub(t)
        self._fast_ph_update(); self._upd_info()

        clip = self._at("main", t)
        if not clip: return

        src_t = (t - clip["tl"]) * clip["speed"] + clip["start"]

        # ── Use proxy for scrub/pause preview if available ────────────────────
        render_path = self._proxy_mgr.get_proxy(clip["path"]) or clip["path"]

        if self.cap is None or self._cap_path != render_path:
            if hasattr(self.cap, "release"): self.cap.release()
            self.cap = SmartVideoReader(render_path)
            self._cap_path = render_path

        ok, frame = self.cap.get_frame_at_time(src_t)
        if ok:
            sc = clip.get("scale", 1.0)
            rot = clip.get("rotate", 0.0)
            cx = clip.get("custom_x", 0.5)
            cy = clip.get("custom_y", 0.5)
            if sc != 1.0 or rot != 0.0 or cx != 0.5 or cy != 0.5:
                frame = self._apply_clip_transform(frame, sc, rot, cx, cy)
            frame = self._apply_overlay(frame, t)
            self._show(frame)

    def _upd_info(self):
        if not self.playing:
            self._refresh_props()

    # ── Editing operations ────────────────────────────────────────────────────
    def _split(self):
        t=self.fi/float(TARGET_FPS)
        clip=self._at(self.sel_track,t)
        if not clip:
            clip=self._at("main",t)
        if not clip: self._status("No clip at playhead"); return

        track_key=self.sel_track if self._at(self.sel_track,t) else "main"
        items=self.tracks[track_key]; idx=items.index(clip)
        src_t=(t-clip["tl"])*clip["speed"]+clip["start"]
        if src_t<=clip["start"]+0.04 or src_t>=clip["end"]-0.04:
            self._status("Too close to edge"); return
        new=copy.deepcopy(clip)
        clip["end"]=src_t; new["start"]=src_t; new["tl"]=t
        items.insert(idx+1,new)
        self._push_undo(); self._status(f"Split at {_ft(t)}"); self._draw_tl()

    def _del_sel(self):
        """
        Delete all selected items across single selection AND box multi-selection (_multi_sel).
        Safely removes items per track in descending order to avoid index shifting.
        """
        targets = set()
        if getattr(self, "_multi_sel", None):
            for k, idx in self._multi_sel:
                targets.add((k, idx))
        if self.sel_track and 0 <= self.sel_idx < len(self.tracks.get(self.sel_track, [])):
            targets.add((self.sel_track, self.sel_idx))

        if not targets:
            return

        # Group targets by track
        by_track = {}
        for k, idx in targets:
            by_track.setdefault(k, []).append(idx)

        has_sub_deleted = False

        for k, idx_list in by_track.items():
            items = self.tracks.get(k, [])
            # Sort indices in descending order to prevent index corruption during pop
            for idx in sorted(idx_list, reverse=True):
                if 0 <= idx < len(items):
                    items.pop(idx)
                    if k == "subtitle":
                        has_sub_deleted = True

        if has_sub_deleted:
            self._sync_segments_from_tracks()
            if hasattr(self, "transcript_panel"):
                self.transcript_panel.set_segments(self.segments)

        self._multi_sel = []
        self.sel_track = ""
        self.sel_idx = -1
        if hasattr(self, "properties_panel"):
            self.properties_panel._refresh_props()

        self._push_undo()
        self._draw_tl()
        self._refresh_preview()
        self._status("Deleted selected items")

    def _del_subtitle(self, idx):
        """Unified subtitle delete: removes clip from timeline AND segment from transcript panel."""
        sub_clips = self.tracks.get("subtitle", [])
        if not (0 <= idx < len(sub_clips)):
            return
        sub_clips.pop(idx)
        # Rebuild segments from remaining subtitle clips to stay in sync
        self._sync_segments_from_tracks()
        # Refresh transcript panel
        if hasattr(self, "transcript_panel"):
            self.transcript_panel.set_segments(self.segments)
        # Update selection
        remaining = self.tracks.get("subtitle", [])
        self.sel_idx = min(idx, len(remaining) - 1) if remaining else -1
        if not remaining:
            self.sel_track = ""
            self.sel_idx = -1
        self._push_undo()
        self._draw_tl()
        self._status("Subtitle deleted")

    def _delete_all_subtitles(self):
        """Delete all subtitle clips from timeline tracks and transcript panel."""
        if not self.tracks.get("subtitle") and not self.segments:
            from tkinter import messagebox
            messagebox.showinfo("Subtitles", "ไม่มีซับไตเติลให้ลบ")
            return

        from tkinter import messagebox
        if messagebox.askyesno("ลบซับทั้งหมด", "คุณต้องการลบซับไตเติลทั้งหมดออกจากไทม์ไลน์ใช่หรือไม่?"):
            self._push_undo()
            self.tracks["subtitle"] = []
            self.segments = []
            if hasattr(self, "transcript_panel"):
                self.transcript_panel.set_segments([])
            if self.sel_track == "subtitle":
                self.sel_track = ""
                self.sel_idx = -1
            self._multi_sel = [item for item in getattr(self, "_multi_sel", []) if item[0] != "subtitle"]
            self._draw_tl()
            self._refresh_preview()
            self._status("ลบซับไตเติลทั้งหมดเรียบร้อยแล้ว")

    def _sync_segments_from_tracks(self):
        """Rebuild self.segments from subtitle clips in tracks to keep them perfectly in sync."""
        self.segments = []
        for clip in self.tracks.get("subtitle", []):
            dur = (clip["end"] - clip["start"]) / max(clip.get("speed", 1.0), 0.01)
            self.segments.append({
                "start": clip.get("tl", 0.0),
                "end": clip.get("tl", 0.0) + dur,
                "text": clip.get("sub_text", clip.get("name", ""))
            })

    def _cut_timeline_range(self, t0: float, t1: float):
        """
        Remove time range [t0, t1] from all tracks with ripple deletion.
        Splits clips spanning across the range, trims boundary overlaps,
        drops fully covered clips, shifts subsequent clips left by (t1 - t0),
        and updates subtitles/segments, audio mixer, and undo history.
        """
        dt = t1 - t0
        if dt <= 0.001:
            return

        for tk_key, clips in list(self.tracks.items()):
            new_clips = []
            for c in clips:
                c_tl = c.get("tl", 0.0)
                spd = max(c.get("speed", 1.0), 0.01)
                c_dur = max(0.01, (c["end"] - c["start"]) / spd)
                c_end = c_tl + c_dur

                # 1. Clip completely before cut range -> unchanged
                if c_end <= t0 + 0.001:
                    new_clips.append(c)
                # 2. Clip completely after cut range -> shift left by dt
                elif c_tl >= t1 - 0.001:
                    c_copy = copy.deepcopy(c)
                    c_copy["tl"] = max(0.0, c_tl - dt)
                    new_clips.append(c_copy)
                # 3. Clip completely inside cut range -> dropped
                elif c_tl >= t0 - 0.001 and c_end <= t1 + 0.001:
                    continue
                # 4. Cut range is strictly inside the clip -> split into 2 clips
                elif c_tl < t0 and c_end > t1:
                    part_a = copy.deepcopy(c)
                    part_a["end"] = c["start"] + (t0 - c_tl) * spd
                    new_clips.append(part_a)

                    part_b = copy.deepcopy(c)
                    part_b["start"] = c["start"] + (t1 - c_tl) * spd
                    part_b["tl"] = max(0.0, t0)
                    new_clips.append(part_b)
                # 5. Overlaps left boundary (starts before t0, ends inside [t0, t1])
                elif c_tl < t0 and c_end <= t1:
                    part_a = copy.deepcopy(c)
                    part_a["end"] = c["start"] + (t0 - c_tl) * spd
                    new_clips.append(part_a)
                # 6. Overlaps right boundary (starts inside [t0, t1], ends after t1)
                elif c_tl >= t0 and c_end > t1:
                    part_b = copy.deepcopy(c)
                    part_b["start"] = c["start"] + (t1 - c_tl) * spd
                    part_b["tl"] = max(0.0, t0)
                    new_clips.append(part_b)

            self.tracks[tk_key] = new_clips

        self._sync_segments_from_tracks()
        if hasattr(self, "transcript_panel"):
            self.transcript_panel.set_segments(self.segments)

        self._push_undo()
        self._draw_tl()
        self._reload_audio()
        self._refresh_preview()
        self._status(f"✂ ตัด Dead Air ช่วง {_ft(t0)} - {_ft(t1)} เรียบร้อย")

    def _cut_all_deadair(self, deadair_list: list[dict]):
        """
        Cut all dead air silence intervals from timeline tracks in reverse chronological order.
        """
        if not deadair_list:
            return
        sorted_deadair = sorted(deadair_list, key=lambda x: x["start"], reverse=True)
        for d in sorted_deadair:
            t0 = d["start"]
            t1 = d["end"]
            dt = t1 - t0
            if dt <= 0.001:
                continue

            for tk_key, clips in list(self.tracks.items()):
                new_clips = []
                for c in clips:
                    c_tl = c.get("tl", 0.0)
                    spd = max(c.get("speed", 1.0), 0.01)
                    c_dur = max(0.01, (c["end"] - c["start"]) / spd)
                    c_end = c_tl + c_dur

                    if c_end <= t0 + 0.001:
                        new_clips.append(c)
                    elif c_tl >= t1 - 0.001:
                        c_copy = copy.deepcopy(c)
                        c_copy["tl"] = max(0.0, c_tl - dt)
                        new_clips.append(c_copy)
                    elif c_tl >= t0 - 0.001 and c_end <= t1 + 0.001:
                        continue
                    elif c_tl < t0 and c_end > t1:
                        part_a = copy.deepcopy(c)
                        part_a["end"] = c["start"] + (t0 - c_tl) * spd
                        new_clips.append(part_a)

                        part_b = copy.deepcopy(c)
                        part_b["start"] = c["start"] + (t1 - c_tl) * spd
                        part_b["tl"] = max(0.0, t0)
                        new_clips.append(part_b)
                    elif c_tl < t0 and c_end <= t1:
                        part_a = copy.deepcopy(c)
                        part_a["end"] = c["start"] + (t0 - c_tl) * spd
                        new_clips.append(part_a)
                    elif c_tl >= t0 and c_end > t1:
                        part_b = copy.deepcopy(c)
                        part_b["start"] = c["start"] + (t1 - c_tl) * spd
                        part_b["tl"] = max(0.0, t0)
                        new_clips.append(part_b)

                self.tracks[tk_key] = new_clips

        self._sync_segments_from_tracks()
        if hasattr(self, "transcript_panel"):
            self.transcript_panel.set_segments(self.segments)

        self._push_undo()
        self._draw_tl()
        self._reload_audio()
        self._refresh_preview()
        self._status(f"✂ ลบ Dead Air ทั้งหมด {len(deadair_list)} ช่วงเรียบร้อย")

    def _scroll_tl_to_time(self, t: float):
        """Scroll timeline canvas so that timestamp t is centered in view."""
        if hasattr(self, "timeline_panel") and hasattr(self.timeline_panel, "_tlc"):
            try:
                scale = self._scale()
                px = t * scale
                c = self.timeline_panel._tlc
                W = c.winfo_width()
                cw = getattr(self, "_cached_tl_cw", 0)
                if cw > W:
                    target_left = max(0.0, px - W / 2)
                    c.xview_moveto(target_left / cw)
            except Exception:
                pass

    def _render_main_track_audio(self) -> str:
        """
        Extract or render combined audio of all clips on main track to a temp 16kHz WAV file.
        Applies exact start/end trimming, clip speed (atempo), and timeline position (adelay).
        """
        main_clips = self.tracks.get("main", [])
        if not main_clips:
            raise RuntimeError("ไม่พบวิดีโอหรือคลิปบน Main Track กรุณานำเข้าวิดีโอก่อน")

        # Use raw file directly ONLY if 1 clip with 1.0x speed, 0 start, 0 tl
        if (len(main_clips) == 1 
            and main_clips[0].get("tl", 0.0) == 0.0 
            and main_clips[0].get("start", 0.0) == 0.0 
            and main_clips[0].get("speed", 1.0) == 1.0):
            return main_clips[0]["path"]

        try:
            temp_wav = os.path.join(tempfile.gettempdir(), f"combined_main_audio_{os.getpid()}.wav")
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
            inputs = []
            filter_chains = []

            for idx, cl in enumerate(main_clips):
                path  = cl["path"]
                start = cl.get("start", 0.0)
                end   = cl.get("end", 0.0)
                speed = cl.get("speed", 1.0)
                dur   = max(0.01, (end - start) / max(speed, 0.01))

                inputs.extend(["-ss", str(start), "-t", str(dur), "-i", path])
                atempo_str = _build_atempo_filter(speed)
                filter_chains.append(f"[{idx}:a]{atempo_str}[a{idx}]")

            if len(main_clips) == 1:
                filter_complex = f"{filter_chains[0]};[a0]anull[aout]"
            else:
                cat_inputs = "".join([f"[a{i}]" for i in range(len(main_clips))])
                filter_complex = f"{';'.join(filter_chains)};{cat_inputs}concat=n={len(main_clips)}:v=0:a=1[aout]"

            cmd = [ff, "-y"] + inputs + ["-filter_complex", filter_complex, "-map", "[aout]", "-ac", "1", "-ar", "16000", temp_wav]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0 and os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 0:
                return temp_wav
        except Exception as e:
            print(f"[AudioRender Error] {e}")
        return main_clips[0]["path"]

    def _dup(self, tk_key, idx):
        items=self.tracks[tk_key]
        if 0<=idx<len(items):
            d=copy.deepcopy(items[idx]); dur=(d["end"]-d["start"])/max(d["speed"],0.01)
            d["tl"]=d.get("tl",0)+dur; items.insert(idx+1,d)
            self._push_undo(); self._draw_tl(); self._status("Duplicated")

    def _add_text(self):
        txt = self.v_text.get().strip() or "Text"
        tl_start = self.fi / float(TARGET_FPS)
        dur = 5.0
        tl_end = tl_start + dur
        tk = self._find_free_layer(tl_start, tl_end)

        # Inherit current default style from project style settings
        st = getattr(self, "style", None)
        f_name  = getattr(st, "font_name", "Tahoma") if st else "Tahoma"
        f_size  = getattr(st, "font_size", 36) if st else 36
        f_color = getattr(st, "font_color", "#ffffff") if st else "#ffffff"
        f_deco  = getattr(st, "decoration", "shadow") if st else "shadow"
        f_bold  = bool(getattr(st, "bold", False)) if st else False
        f_italic = bool(getattr(st, "italic", False)) if st else False

        new_clip = {
            "path": "", "name": txt,
            "start": 0, "end": dur,
            "speed": 1.0, "volume": 1.0,
            "tl": tl_start,
            "fps": TARGET_FPS,
            "custom_x": 0.5, "custom_y": 0.2,
            "font_name": f_name, "font_size": f_size,
            "font_color": f_color, "decoration": f_deco,
            "bold": f_bold, "italic": f_italic,
            "source_dur": 999999.0
        }
        self.tracks[tk].append(new_clip)
        self.sel_track = tk
        self.sel_idx = len(self.tracks[tk]) - 1
        self._push_undo()
        self._draw_tl()
        if hasattr(self, "properties_panel"):
            self.properties_panel._refresh_props()
        self._refresh_preview()
        self._status(f'Text: "{txt}"')


    def _move_track(self, idx, src_key, dst_key):
        items=self.tracks.get(src_key,[])
        if 0<=idx<len(items):
            clip=items.pop(idx)
            if dst_key not in self.tracks:
                self.tracks[dst_key] = []
            self.tracks[dst_key].append(clip)
            self.sel_track=dst_key; self.sel_idx=len(self.tracks[dst_key])-1
            self._push_undo(); self._rebuild_label_column(); self._draw_tl()

    def _set_speed(self, idx, tk_key, spd):
        items=self.tracks.get(tk_key,[])
        if 0<=idx<len(items):
            items[idx]["speed"]=spd; self.v_speed.set(spd)
            if hasattr(self.properties_panel, "_spd_lbl") and self.properties_panel._spd_lbl.winfo_exists():
                self.properties_panel._spd_lbl.configure(text=f"{spd:.2f}×")
            self._push_undo(); self._draw_tl()

    def _set_fade(self, idx, tk_key, which, val):
        items = self.tracks.get(tk_key, [])
        if 0 <= idx < len(items):
            if which in ("fade_in","both"):  items[idx]["fade_in"]  = val
            if which in ("fade_out","both"): items[idx]["fade_out"] = val
            self._push_undo(); self._draw_tl()
            self._status(f"Fade set: {which}={val}s")

    def _apply_speed(self, val):
        if hasattr(self.properties_panel, "_spd_lbl") and self.properties_panel._spd_lbl.winfo_exists():
            self.properties_panel._spd_lbl.configure(text=f"{float(val):.2f}×")
        items=self.tracks.get(self.sel_track,[])
        if 0<=self.sel_idx<len(items):
            items[self.sel_idx]["speed"]=float(val); self._draw_tl()
            # Reload audio with the new speed applied via atempo
            self.after(200, self._reload_audio)

    def _apply_vol(self, val):
        if hasattr(self.properties_panel, "_vol_lbl") and self.properties_panel._vol_lbl.winfo_exists():
            self.properties_panel._vol_lbl.configure(text=f"{int(float(val)*100)}%")
        items=self.tracks.get(self.sel_track,[])
        if 0<=self.sel_idx<len(items):
            items[self.sel_idx]["volume"]=float(val)
            # Apply volume to pygame immediately during playback
            try:
                pygame.mixer.music.set_volume(min(2.0, max(0.0, float(val))))
            except Exception:
                pass

    # ── Import / asset management ─────────────────────────────────────────────
    def _import(self):
        path=filedialog.askopenfilename(
            title="Import Media",
            initialdir=_ld.get(_ld.IMPORT_MEDIA),
            filetypes=[("Media","*.mp4 *.mov *.avi *.mkv *.webm *.wav *.mp3 *.aac *.jpg *.png"),
                       ("All","*.*")])
        if not path: return
        _ld.remember(_ld.IMPORT_MEDIA, path)
        ext=os.path.splitext(path)[1].lower()
        atype=("video" if ext in (".mp4",".mov",".avi",".mkv",".webm")
               else "audio" if ext in (".wav",".mp3",".aac",".ogg")
               else "image")
        self.assets.append({"path":path,"name":os.path.basename(path),"type":atype})
        self._tab("Media"); self._status(f"Imported: {os.path.basename(path)}")
        # ── Kick off proxy build immediately for video files ──────────────────
        if atype == "video":
            self._start_proxy_build(path)

    def _import_audio(self):
        path=filedialog.askopenfilename(
            title="Import Audio",
            initialdir=_ld.get(_ld.IMPORT_AUDIO),
            filetypes=[("Audio","*.wav *.mp3 *.aac *.ogg"),("All","*.*")])
        if path:
            _ld.remember(_ld.IMPORT_AUDIO, path)
            self.assets.append({"path":path,"name":os.path.basename(path),"type":"audio"})
            self._tab("Audio")

    def _get_media_duration(self, path):
        """Get accurate duration from video or audio file using ffprobe/ffmpeg."""
        try:
            ff = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [ff, "-i", path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            import re
            m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', res.stderr)
            if m:
                h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return h * 3600 + mi * 60 + s
        except Exception:
            pass
        return None

    def _add_to_tl(self, asset):
        ext = os.path.splitext(asset["path"])[1].lower()
        is_audio = ext in (".wav", ".mp3", ".aac", ".ogg")
        is_image = ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
        fps = TARGET_FPS
        dur = 5.0

        if is_image:
            dur = 5.0  # default 5s for images, user can trim
        elif is_audio:
            # Read real audio duration
            real_dur = self._get_media_duration(asset["path"])
            dur = real_dur if real_dur and real_dur > 0 else 5.0
        else:
            # Video
            cap = cv2.VideoCapture(asset["path"])
            fps = cap.get(cv2.CAP_PROP_FPS) or TARGET_FPS
            cnt = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            dur = cnt / fps if cnt > 0 else 5.0
            cap.release()

        # For the very first clip, always start at t=0 (no gap)
        all_clips = sum(len(v) for v in self.tracks.values())
        tl_start = 0.0 if all_clips == 0 else self._dur()
        tl_end = tl_start + dur

        if is_audio:
            # Find first empty audio track, or create one
            tk = None
            for ak in self._audio_keys():
                if not self.tracks.get(ak):
                    tk = ak
                    break
            if tk is None:
                existing = self._audio_keys()
                if existing:
                    n = int(existing[-1].split("_")[1]) + 1
                else:
                    n = 0
                tk = f"audio_{n}"
                self.tracks[tk] = []
        elif not self.tracks.get("main"):
            tk = "main"
            tl_start = 0.0  # first video clip always at position 0
            tl_end = tl_start + dur
        elif is_image:
            tk = self._find_free_layer(tl_start, tl_end)
        else:
            # Additional video: append after existing main clips
            tk = "main"
            # tl_start already = self._dur() from above

        clip_obj = self._clip(asset["path"], asset["name"], 0, dur,
                              tl=tl_start, fps=fps)
        if is_image:
            clip_obj["source_dur"] = 999999.0
            clip_obj["end"] = 999999.0
        if is_audio:
            clip_obj["source_dur"] = dur

        self.tracks[tk].append(clip_obj)
        self.sel_track = tk
        self.sel_idx = len(self.tracks[tk]) - 1

        if is_audio or ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            self._extract_waveforms_bg(asset["path"])
        # Kick off proxy build for video clips added to timeline
        if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            self._start_proxy_build(asset["path"])
        # Reload mixed audio whenever an audio/video clip is added
        if is_audio or ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            self.after(300, self._reload_audio)
        self._push_undo(); self._rebuild_label_column(); self._draw_tl()
        self._refresh_props()
        self._status(f"Added to [{tk}]: {asset['name']}")


    # ── Helpers ───────────────────────────────────────────────────────────────
    def _at(self, track, t):
        for item in self.tracks.get(track,[]):
            dur=(item["end"]-item["start"])/max(item["speed"],0.01)
            tl=item.get("tl",0.0)
            if tl<=t<tl+dur: return item
        return None

    def _dur(self):
        max_t = 0.1
        for track_key, clips in self.tracks.items():
            for c in clips:
                dur = (c["end"] - c["start"]) / max(c.get("speed", 1.0), 0.01)
                max_t = max(max_t, c.get("tl", 0.0) + dur)
        return max_t

    def _status(self, msg):
        try:
            if hasattr(self, "_stat") and self._stat.winfo_exists():
                self._stat.configure(text=msg)
        except Exception:
            pass

    # ── Undo / Redo ───────────────────────────────────────────────────────────
    def _push_undo(self):
        # Save both tracks AND segments together so undo is fully atomic
        snap = {"tracks": copy.deepcopy(self.tracks),
                "segments": copy.deepcopy(self.segments)}
        self._undo.append(snap)
        if len(self._undo) > MAX_UNDO: self._undo.pop(0)
        self._redo.clear()

    def _undo_do(self):
        if len(self._undo) < 2: self._status("Nothing to undo"); return
        curr = self._undo.pop()
        self._redo.append(curr)
        snap = self._undo[-1]
        self.tracks = copy.deepcopy(snap["tracks"] if isinstance(snap, dict) else snap)
        self.segments = copy.deepcopy(snap.get("segments", []) if isinstance(snap, dict) else [])
        if not self.segments:
            self._sync_segments_from_tracks()
        if hasattr(self, "transcript_panel"):
            self.transcript_panel.set_segments(self.segments)
        self.sel_track = ""
        self.sel_idx = -1
        self._multi_sel = []
        self._rebuild_label_column()
        self._draw_tl(); self._render(self.fi); self._status("Undo")

    def _redo_do(self):
        if not self._redo: self._status("Nothing to redo"); return
        snap = self._redo.pop()
        self._undo.append(snap)
        self.tracks = copy.deepcopy(snap["tracks"] if isinstance(snap, dict) else snap)
        self.segments = copy.deepcopy(snap.get("segments", []) if isinstance(snap, dict) else [])
        if not self.segments:
            self._sync_segments_from_tracks()
        if hasattr(self, "transcript_panel"):
            self.transcript_panel.set_segments(self.segments)
        self.sel_track = ""
        self.sel_idx = -1
        self._multi_sel = []
        self._rebuild_label_column()
        self._draw_tl(); self._render(self.fi); self._status("Redo")

    # ── Export ────────────────────────────────────────────────────────────────
    def get_export_segments(self):
        export_segs = []
        for clip in self.tracks.get("subtitle", []):
            text = clip.get("sub_text", clip.get("name", "")).strip()
            if not text:
                continue
            dur = (clip["end"] - clip["start"]) / max(clip.get("speed", 1.0), 0.01)
            export_segs.append({
                "start": clip.get("tl", 0.0),
                "end": clip.get("tl", 0.0) + dur,
                "text": text,
                "font_name": clip.get("font_name", getattr(self.style, "font_name", "Tahoma")),
                "font_size": clip.get("font_size", getattr(self.style, "font_size", 44)),
                "font_color": clip.get("font_color", getattr(self.style, "font_color", "#ffffff")),
                "bold": clip.get("bold", getattr(self.style, "bold", False)),
                "italic": clip.get("italic", getattr(self.style, "italic", False)),
                "decoration": clip.get("decoration", getattr(self.style, "decoration", "shadow")),
                "decoration_color": clip.get("decoration_color", getattr(self.style, "decoration_color", "#000000")),
                "letter_spacing": clip.get("letter_spacing", getattr(self.style, "letter_spacing", 0)),
                "custom_x": clip.get("custom_x", getattr(self.style, "custom_x", 0.5)),
                "custom_y": clip.get("custom_y", getattr(self.style, "custom_y", 0.85)),
            })
        export_segs.sort(key=lambda x: x["start"])
        return export_segs

    def _detach_audio(self, track_key, idx):
        """Extract audio from the clip's time range and add it as a separate audio track.
        After detach, mutes the source video clip so it has no audio."""
        items = self.tracks.get(track_key, [])
        if not (0 <= idx < len(items)):
            return
        clip = items[idx]
        path = clip.get("path", "")
        if not path or not os.path.exists(path):
            self._status("Cannot detach: invalid path"); return
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            self._status("Cannot detach: not a video file"); return

        # Capture the clip's actual time range (after any splitting)
        clip_start = clip.get("start", 0.0)           # start in source file (seconds)
        clip_dur   = (clip["end"] - clip["start"]) / max(clip.get("speed", 1.0), 0.01)
        clip_tl    = clip.get("tl", 0.0)               # position on timeline

        self._status("Detaching audio…")

        def _run_detach():
            try:
                ff = imageio_ffmpeg.get_ffmpeg_exe()
                base = os.path.splitext(os.path.basename(path))[0]
                out_dir = os.path.dirname(path)
                out_path = os.path.join(out_dir, f"{base}_audio.wav")
                counter = 1
                while os.path.exists(out_path):
                    out_path = os.path.join(out_dir, f"{base}_audio_{counter}.wav")
                    counter += 1
                # Extract ONLY the clip's portion from the source video
                cmd = [
                    ff, "-y",
                    "-ss", str(clip_start),      # seek to clip start in source
                    "-t",  str(clip_dur),         # extract only clip duration
                    "-i",  path,
                    "-vn", "-ar", "44100", "-ac", "2", out_path
                ]
                res = subprocess.run(cmd, capture_output=True, timeout=120)
                if res.returncode != 0:
                    raise RuntimeError("FFmpeg audio extraction failed")

                # Find free audio track
                tk = None
                for ak in self._audio_keys():
                    if not self.tracks.get(ak):
                        tk = ak; break
                if tk is None:
                    existing = self._audio_keys()
                    n = int(existing[-1].split("_")[1]) + 1 if existing else 0
                    tk = f"audio_{n}"
                    self.tracks[tk] = []

                # Audio clip starts at tl=clip_tl, source start=0 (already trimmed)
                audio_clip = self._clip(
                    out_path,
                    os.path.basename(out_path),
                    0,
                    clip_dur,
                    tl=clip_tl,
                    fps=TARGET_FPS
                )
                audio_clip["source_dur"] = clip_dur

                def _ui_update():
                    self.tracks[tk].append(audio_clip)
                    # Mute the source video clip so it no longer plays audio
                    clip["muted"] = True
                    asset = {"path": out_path, "name": os.path.basename(out_path), "type": "audio"}
                    self.assets.append(asset)
                    self._extract_waveforms_bg(out_path)
                    self._push_undo()
                    self._rebuild_label_column()
                    self._draw_tl()
                    self._status(f"Audio detached → {os.path.basename(out_path)} (video muted)")

                self.after(0, _ui_update)
            except Exception as ex:
                self.after(0, lambda e=ex: self._status(f"Detach error: {e}"))

        threading.Thread(target=_run_detach, daemon=True).start()

    def _export(self):
        if not self.tracks["main"]:
            messagebox.showwarning("Export", "No video on main track!"); return
        has_subs = bool(self.tracks.get("subtitle"))
        _ExportDialog(self, self._do_export, has_subs=has_subs, proj_name=self._proj_name)

    def _do_export(self, out, crf, resolution, burn_subs):
        if not out: return
        self._status("Exporting…")
        threading.Thread(
            target=self._export_worker,
            args=(out, crf, resolution, burn_subs), daemon=True
        ).start()

    def _export_worker(self, out, crf=20, resolution="Original", burn_subs=False):
        temp_out = None
        try:
            ff    = imageio_ffmpeg.get_ffmpeg_exe()
            clips = sorted(self.tracks["main"], key=lambda c: c.get("tl", 0))
            n     = len(clips)
            if n == 0:
                self.after(0, lambda: messagebox.showwarning("Export", "No clips on main track!"))
                return

            # Determine target resolution & aspect ratio
            target_w, target_h = 1920, 1080
            if clips:
                try:
                    cap_t = cv2.VideoCapture(clips[0]["path"])
                    ok, fr = cap_t.read()
                    if ok:
                        target_h, target_w = fr.shape[:2]
                    else:
                        w_opt = int(cap_t.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h_opt = int(cap_t.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        if w_opt > 0 and h_opt > 0:
                            target_w, target_h = w_opt, h_opt
                    cap_t.release()
                except:
                    pass

            ratio_name = getattr(self.v_ratio, "get", lambda: "16:9")()
            rm = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "2.35:1": 2.35}
            r = rm.get(ratio_name, 16 / 9)

            _RES_VALS = {"1080p": (1920, 1080), "720p": (1280, 720), "480p": (854, 480)}
            if resolution in _RES_VALS:
                bw, bh = _RES_VALS[resolution]
            else:
                bw, bh = target_w, target_h

            if r >= 1.0:
                target_h = bh
                target_w = int(round(bh * r))
            else:
                target_w = bh if bw >= bh else bw
                target_h = int(round(target_w / r))

            target_w = (max(2, target_w) // 2) * 2
            target_h = (max(2, target_h) // 2) * 2

            export_segs = self.get_export_segments()
            
            all_layer_clips = []
            for lk in self._layer_keys():
                all_layer_clips.extend(self.tracks.get(lk, []))
            overlays = sorted(all_layer_clips, key=lambda c: c.get("tl", 0))
            # Separate video/audio/image overlays from text overlays
            media_overlays = [ov for ov in overlays if ov.get("path", "") != ""]
            text_overlays = [ov for ov in overlays if ov.get("path", "") == ""]

            # Merge text overlays and subtitles into all_export_subs for flawless burning
            all_export_subs = []
            if burn_subs and export_segs:
                all_export_subs.extend(export_segs)

            for ov in text_overlays:
                txt = ov.get("name", "Text").strip()
                if not txt:
                    continue
                tl_start = ov.get("tl", 0.0)
                dur = (ov["end"] - ov["start"]) / max(ov.get("speed", 1.0), 0.01)
                all_export_subs.append({
                    "start": tl_start,
                    "end": tl_start + dur,
                    "text": txt,
                    "font_name": ov.get("font_name", "Tahoma"),
                    "font_size": ov.get("font_size", 44),
                    "font_color": ov.get("font_color", "#ffffff"),
                    "bold": bool(ov.get("bold", False)),
                    "italic": bool(ov.get("italic", False)),
                    "decoration": ov.get("decoration", "shadow"),
                    "decoration_color": ov.get("decoration_color", "#000000"),
                    "letter_spacing": ov.get("letter_spacing", 0),
                    "align": ov.get("align", "center"),
                    "custom_x": ov.get("custom_x", 0.5),
                    "custom_y": ov.get("custom_y", 0.2),
                })
            all_export_subs.sort(key=lambda x: x["start"])

            need_burn = bool(all_export_subs)
            if need_burn:
                temp_out = out + "_temp_merge.mp4"
                target_out = temp_out
            else:
                target_out = out

            def _has_audio(path):
                try:
                    import subprocess
                    r = subprocess.run([ff, "-i", path], capture_output=True, text=True,
                                       encoding="utf-8", errors="ignore", timeout=3)
                    info = (r.stderr or "") + (r.stdout or "")
                    return "Audio:" in info
                except Exception:
                    return False

            cmd = [ff, "-y"]
            for cl in clips:
                cmd += ["-ss", str(cl["start"]), "-to", str(cl["end"]),
                        "-i", cl["path"]]

            has_silent = False
            for cl in clips:
                if not _has_audio(cl["path"]):
                    has_silent = True
                    break

            if has_silent:
                cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]

            for ov in media_overlays:
                ext_ov = os.path.splitext(ov["path"])[1].lower()
                is_img_ov = ext_ov in (".jpg", ".jpeg", ".png")
                if is_img_ov:
                    cmd += ["-i", ov["path"]]
                else:
                    cmd += ["-ss", str(ov["start"]), "-to", str(ov["end"]),
                            "-i", ov["path"]]

            _EFF = {
                "blur_soft": ",boxblur=3:1",
                "vignette":  ",vignette",
                "warm":      ",colorchannelmixer=rr=1.1:gg=1.0:bb=0.85",
                "cold":      ",colorchannelmixer=rr=0.85:gg=1.0:bb=1.15",
                "bw":        ",hue=s=0",
            }

            fc = []; vp = []; ap = []
            for idx, cl in enumerate(clips):
                sp  = max(cl.get("speed", 1.0), 0.01)
                bri = cl.get("brightness", 0.0)
                con = cl.get("contrast",   1.0)
                sat = cl.get("saturation", 1.0)
                eff = cl.get("effect", "none")
                rot = cl.get("rotate", 0.0)
                sc  = cl.get("scale", 1.0)
                cx  = cl.get("custom_x", 0.5)
                cy  = cl.get("custom_y", 0.5)

                vf = f"[{idx}:v]setpts={1/sp}*PTS"
                if rot != 0.0:
                    rad = rot * 3.14159265 / 180.0
                    vf += f",rotate={rad:.4f}:c=black@0:ow=rotw({rad:.4f}):oh=roth({rad:.4f})"
                if sc != 1.0 and sc > 0.01:
                    vf += f",scale=iw*{sc:.3f}:ih*{sc:.3f}"

                crop_filter = f"crop='if(gt(iw/ih,{r:.4f}),ih*{r:.4f},iw)':'if(gt(iw/ih,{r:.4f}),ih,iw/{r:.4f})'"
                vf += f",{crop_filter},scale={target_w}:{target_h}"

                if bri != 0.0 or con != 1.0 or sat != 1.0:
                    vf += (f",eq=brightness={bri:.3f}"
                           f":contrast={con:.3f}"
                           f":saturation={sat:.3f}")
                vf += _EFF.get(eff, "")
                vf += f"[v{idx}]"
                fc.append(vf)

                at = min(max(sp, 0.5), 2.0)
                duration = cl["end"] - cl["start"]
                if _has_audio(cl["path"]):
                    fc.append(f"[{idx}:a]atempo={at}[a{idx}]")
                else:
                    fc.append(f"[{n}:a]trim=duration={duration},asetpts=PTS-STARTPTS,atempo={at}[a{idx}]")

                vp.append(f"[v{idx}]")
                ap.append(f"[a{idx}]")

            fc.append("".join(vp) + f"concat=n={n}:v=1:a=0[vcat]")
            fc.append("".join(ap) + f"concat=n={n}:v=0:a=1[aout]")

            curr_v = "[vcat]"
            ov_start_idx = n + 1 if has_silent else n
            for idx_ov, ov in enumerate(media_overlays):
                ov_idx = ov_start_idx + idx_ov
                tl_start = ov.get("tl", 0.0)
                dur = (ov["end"] - ov["start"]) / max(ov.get("speed", 1.0), 0.01)
                tl_end = tl_start + dur
                rot = ov.get("rotate", 0.0)
                sc  = ov.get("scale", 1.0)
                cx  = ov.get("custom_x", 0.5)
                cy  = ov.get("custom_y", 0.5)

                ov_in = f"[{ov_idx}:v]"
                if rot != 0.0:
                    rad = rot * 3.14159265 / 180.0
                    next_ov = f"[ov_rot_{idx_ov}]"
                    fc.append(f"{ov_in}rotate={rad:.4f}:c=black@0:ow=rotw({rad:.4f}):oh=roth({rad:.4f}){next_ov}")
                    ov_in = next_ov

                ov_scaled = f"[ovs{idx_ov}]"
                fc.append(f"{ov_in}scale=iw*0.5*{sc:.3f}:-1{ov_scaled}")

                next_v = f"[ov_out{idx_ov}]"
                fc.append(f"{curr_v}{ov_scaled}overlay=x=(W-w)*{cx:.3f}:y=(H-h)*{cy:.3f}:enable='between(t,{tl_start:.3f},{tl_end:.3f})'{next_v}")
                curr_v = next_v

            out_v = curr_v

            # ── Mix in separate audio tracks (audio_0, audio_1, …) ───────────
            extra_audio_labels: list[str] = []
            extra_idx_offset = n + 1 + len(media_overlays)
            if has_silent:
                extra_idx_offset += 1

            for ak in self._audio_keys():
                for ac in self.tracks.get(ak, []):
                    ap_path = ac.get("path", "")
                    if not ap_path or not os.path.exists(ap_path):
                        continue
                    ac_start = ac.get("start", 0.0)
                    ac_end   = ac.get("end", ac.get("source_dur", ac_start + 5.0))
                    ac_tl    = ac.get("tl", 0.0)
                    ac_speed = max(ac.get("speed", 1.0), 0.01)
                    ac_vol   = ac.get("volume", 1.0)
                    ext_idx  = extra_idx_offset + len(extra_audio_labels)
                    cmd.extend(["-ss", str(ac_start), "-to", str(ac_end), "-i", ap_path])
                    delay_ms = max(0, int(ac_tl * 1000))
                    atempo_f = _build_atempo_filter(ac_speed)
                    vol_f = f",volume={ac_vol:.3f}" if abs(ac_vol - 1.0) > 0.01 else ""
                    lbl = f"xa{len(extra_audio_labels)}"
                    fc.append(f"[{ext_idx}:a]{atempo_f}{vol_f},adelay={delay_ms}|{delay_ms}[{lbl}]")
                    extra_audio_labels.append(f"[{lbl}]")

            final_aout = "[aout]"
            if extra_audio_labels:
                mix_in = "[aout]" + "".join(extra_audio_labels)
                n_mix = 1 + len(extra_audio_labels)
                fc.append(f"{mix_in}amix=inputs={n_mix}:normalize=0[amixed]")
                final_aout = "[amixed]"

            cmd += ["-filter_complex", ";".join(fc),
                    "-map", out_v, "-map", final_aout,
                    "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k", target_out]

            self.after(0, lambda: self._status("Rendering… 0%"))

            total_dur = self._dur()
            import re as _re
            
            # บังคับ UTF-8 และ errors="replace" เพื่อตัดปัญหา cp874 decoding crash
            proc = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            stderr_lines = []
            while True:
                line = proc.stderr.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    stderr_lines.append(line)
                    m = _re.search(r'time=(\d+):(\d+):([\d.]+)', line)
                    if m and total_dur > 0:
                        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                        elapsed = h * 3600 + mi * 60 + s
                        pct = min(99, int(elapsed / total_dur * 100))
                        self.after(0, lambda p=pct: self._status(f"Rendering… {p}%"))
            ret = proc.wait()
            if ret != 0:
                err = "".join(stderr_lines)[-600:]
                raise RuntimeError(f"FFmpeg error: {err}")

            if need_burn and all_export_subs:
                self.after(0, lambda: self._status("Burning subtitles & text…"))
                from video_exporter import export_video_with_subtitles
                export_video_with_subtitles(
                    target_out, out, all_export_subs, self.style,
                    progress_cb=lambda m: self.after(0, lambda ms=m: self._status(ms))
                )
                if os.path.exists(target_out):
                    try: os.remove(target_out)
                    except: pass

            self.after(0, lambda: (
                self._status(f"Exported: {os.path.basename(out)}"),
                messagebox.showinfo("Done", f"Saved:\n{out}")))
        except Exception as ex:
            err_msg = str(ex)
            if temp_out and os.path.exists(temp_out):
                try: os.remove(temp_out)
                except: pass
            # Bind err_msg เข้ากับ Lambda เพื่อป้องกัน NameError
            self.after(0, lambda msg=err_msg: (
                self._status("Export failed"),
                messagebox.showerror("Export Error", msg)
            ))
    # ── Subtitles ─────────────────────────────────────────────────────────────
    def _sub_dialog(self):
        if not HAS_SUBTITLES:
            messagebox.showinfo("Subtitles",
                "subtitle_config.py not found.\nPlace it next to editor_page.py."); return
        if not self.tracks["main"]:
            messagebox.showwarning("Subtitles","No video on main track."); return
        _SubtitleDialog(self.master,self.style,self._on_sub)

    def _on_sub(self, style, model_size, words_per_line=8, srt_path="", range_mode="full", t_start=0.0, t_end=0.0):
        self.style = style
        if not self.tracks.get("main"):
            messagebox.showwarning("Subtitles", "No video on main track.")
            return

        vpath = self._render_main_track_audio()

        def run():
            self.after(0, lambda: self._status("Transcribing…"))
            try:
                audio_range = None
                if range_mode == "custom" and t_end > t_start:
                    audio_range = (t_start, t_end)

                segs = transcribe_video(
                    vpath,
                    model_size=model_size,
                    words_per_line=words_per_line,
                    audio_range=audio_range,
                    progress_cb=lambda m: self.after(0, lambda ms=m: self._status(ms)),
                )

                if audio_range:
                    for seg in segs:
                        seg["start"] += t_start
                        seg["end"] += t_start

                def _apply_results():
                    try:
                        self._push_undo()
                        self.segments = segs

                        if range_mode == "full":
                            self.tracks["subtitle"] = []

                        for seg in segs:
                            self.tracks["subtitle"].append({
                                "path": "",
                                "name": seg["text"][:24],
                                "start": 0,
                                "end": max(seg["end"] - seg["start"], 0.05),
                                "speed": 1.0,
                                "volume": 1.0,
                                "tl": seg["start"],
                                "fps": TARGET_FPS,
                                "sub_text": seg["text"],
                            })

                        if hasattr(self, "transcript_panel"):
                            self.transcript_panel.set_segments(self.segments)

                        if srt_path and segs:
                            try:
                                from transcriber import save_srt
                                save_srt(segs, style, srt_path)
                                self._status(f"Done: {len(segs)} segs – SRT saved: {os.path.basename(srt_path)}")
                            except Exception as srt_ex:
                                self._status(f"SRT save error: {srt_ex}")
                        else:
                            self._status(f"Done: {len(segs)} segments")

                        self._tab("Captions")
                        self._draw_tl()
                    except Exception as apply_ex:
                        print(f"[Subtitle Apply Error] {apply_ex}")

                self.after(0, _apply_results)
            except Exception as ex:
                self.after(0, lambda err=ex: (self._status(f"Error: {err}"),
                                              messagebox.showerror("Error", str(err))))
        threading.Thread(target=run, daemon=True).start()

    def _export_subs(self):
        export_segs = self.get_export_segments()
        if not export_segs: messagebox.showwarning("Export","No subtitles."); return
        out=filedialog.asksaveasfilename(
            title="Export Video with Subtitles",
            initialdir=_ld.get(_ld.EXPORT_VIDEO),
            defaultextension=".mp4",
            filetypes=[("MP4","*.mp4")])
        if not out: return
        _ld.remember(_ld.EXPORT_VIDEO, out)
        vpath=self.tracks["main"][0]["path"]
        self._status("Exporting with subtitles…")
        def run():
            try:
                export_video_with_subtitles(vpath,out,export_segs,self.style,
                    progress_cb=lambda m:self.after(0,lambda ms=m:self._status(ms)))
                self.after(0,lambda:messagebox.showinfo("Done",f"Saved:\n{out}"))
            except Exception as ex:
                self.after(0,lambda:messagebox.showerror("Error",str(ex)))
        threading.Thread(target=run,daemon=True).start()

    def _save_srt(self):
        export_segs = self.get_export_segments()
        if not export_segs:
            messagebox.showwarning("Save SRT","No subtitles to save."); return
        from transcriber import save_srt
        video_stem = ""
        if self.tracks.get("main"):
            video_stem = os.path.splitext(os.path.basename(self.tracks["main"][0]["path"]))[0]
        init = video_stem + ".srt" if video_stem else "subtitles.srt"
        out = filedialog.asksaveasfilename(
            title="Save SRT File",
            initialdir=_ld.get(_ld.SAVE_PROJECT),
            initialfile=init,
            defaultextension=".srt",
            filetypes=[("SRT Subtitle","*.srt"),("All files","*.*")])
        if not out: return
        _ld.remember(_ld.SAVE_PROJECT, out)
        try:
            save_srt(export_segs, self.style, out)
            self._status(f"SRT saved: {os.path.basename(out)}")
            messagebox.showinfo("SRT Saved", f"Saved:\n{out}")
        except Exception as ex:
            messagebox.showerror("Save SRT Error", str(ex))

    def _clear_subs(self):
        self.segments = []
        self.tracks["subtitle"] = []
        if hasattr(self, "transcript_panel"):
            self.transcript_panel.set_segments([])
        self._tab("Transcript")
        self._status("Subtitles cleared")
        self._draw_tl()
        self._refresh_preview()

    # ── Save / Autosave ───────────────────────────────────────────────────────
    def _write_project(self, path):
        """Write project JSON to the given path. Returns True on success."""
        try:
            name = os.path.basename(path)
            self._proj_name = name
            if hasattr(self, "_proj_title_lbl"):
                self._proj_title_lbl.configure(text=self._proj_name)
            payload = {
                "tracks":  self.tracks,
                "assets":  self.assets,
                "muted":   self._muted,
                "segments": self.segments,
                "ratio":   self.v_ratio.get() if hasattr(self, "v_ratio") else "16:9",
                "style":   {
                    "font_name": self.style.font_name,
                    "font_size": self.style.font_size,
                    "font_color": self.style.font_color,
                    "decoration": self.style.decoration,
                    "animation": self.style.animation,
                    "position": self.style.position,
                } if hasattr(self, "style") else {},
                "version": 5,
            }
            with open(path, "w") as f:
                json.dump(payload, f, indent=2, default=str)
            self._status(f"Saved: {os.path.basename(path)}")
            self._add_to_recent(path)
            return True
        except Exception as ex:
            messagebox.showerror("Save Error", str(ex))
            return False

    def _save(self):
        """Save project: overwrite current file if it exists, else ask for path (Save As)."""
        path = getattr(self, "_current_project_path", None)
        if not path:
            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                initialdir=_ld.get(_ld.SAVE_PROJECT),
                filetypes=[("Project","*.json")])
        if path:
            _ld.remember(_ld.SAVE_PROJECT, path)
            self._current_project_path = path
            self._write_project(path)

    def _save_as(self):
        """Always show Save As dialog regardless of current project path."""
        init_name = "project.json"
        if getattr(self, "_proj_name", "") and self._proj_name != "Untitled Project":
            stem = os.path.splitext(self._proj_name)[0]
            init_name = stem + ".json" if not stem.lower().endswith(".json") else stem
        path = filedialog.asksaveasfilename(
            title="Save Project As",
            defaultextension=".json",
            initialfile=init_name,
            initialdir=_ld.get(_ld.SAVE_PROJECT),
            filetypes=[("Project","*.json"),("All","*.*")])
        if path:
            _ld.remember(_ld.SAVE_PROJECT, path)
            self._current_project_path = path
            self._write_project(path)

    def _autosave_start(self):
        def loop():
            while True:
                time.sleep(60)
                try:
                    with open("autosave.json","w") as f:
                        json.dump({"tracks":self.tracks},f,default=str)
                except: pass
        threading.Thread(target=loop,daemon=True).start()

    # ── Back / cleanup ────────────────────────────────────────────────────────
    def _back(self):
        self._stop()
        if self.cap: self.cap.release()
        try: pygame.mixer.music.unload()
        except: pass
        self._on_back()

    def find_active_segment(self):
        t = self.fi / float(TARGET_FPS)
        for idx, seg in enumerate(self.segments):
            if seg["start"] <= t <= seg["end"]:
                return idx
        return -1

    def seek_to_segment(self, idx):
        if not hasattr(self, "segments") or not self.segments:
            return
        if not (0 <= idx < len(self.segments)):
            return
        seg = self.segments[idx]
        self.fi = int(seg["start"] * TARGET_FPS)
        self.sel_track = "subtitle"
        self.sel_idx = idx
        # Sync transcript panel selection
        if hasattr(self, "transcript_panel"):
            self.transcript_panel.select_segment(idx)
        if hasattr(self, "timeline_panel"):
            self.timeline_panel._draw_tl()
        self._render(self.fi)
        self._refresh_props()

    def _import_srt(self):
        path = filedialog.askopenfilename(
            title="Import SRT File",
            initialdir=_ld.get(_ld.IMPORT_MEDIA),
            filetypes=[("SRT Subtitle", "*.srt"), ("All files", "*.*")]
        )
        if not path:
            return
        _ld.remember(_ld.IMPORT_MEDIA, path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            import re
            pattern = re.compile(
                r'(\d+)\s+(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s+(.*?)(?=\n\n|\n*$|\n\d+\n)',
                re.DOTALL
            )
            matches = pattern.findall(content)
            
            def parse_time(t_str):
                h, m, s_ms = t_str.split(':')
                s, ms = s_ms.split(',')
                return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0
                
            segs = []
            for m in matches:
                idx, start_str, end_str, text = m
                segs.append({
                    "start": parse_time(start_str),
                    "end": parse_time(end_str),
                    "text": text.strip().replace('\n', ' ')
                })
            
            if not segs:
                messagebox.showwarning("Import SRT", "No valid subtitle segments found in the SRT file.")
                return
                
            self.segments = segs
            
            # Populate subtitle track
            self.tracks["subtitle"] = []
            for seg in segs:
                self.tracks["subtitle"].append({
                    "path": "",
                    "name": seg["text"][:24],
                    "start": 0,
                    "end": max(seg["end"] - seg["start"], 0.05),
                    "speed": 1.0,
                    "volume": 1.0,
                    "tl": seg["start"],
                    "fps": TARGET_FPS,
                    "sub_text": seg["text"],
                })
                
            if hasattr(self, "transcript_panel"):
                self.transcript_panel.set_segments(self.segments)
                
            self._tab("Transcript")
            self._push_undo()
            self._draw_tl()
            self._refresh_preview()
            self._status(f"Imported {len(segs)} segments from SRT")
            
        except Exception as e:
            messagebox.showerror("Import SRT Error", str(e))


# ═════════════════════════════════════════════════════════════════════════════
class _ExportDialog(ctk.CTkToplevel):
    """Export settings dialog – resolution, quality, subtitle burn."""

    _CRF_MAP = {
        "High   (CRF 18)": 18,
        "Medium (CRF 23)": 23,
        "Low    (CRF 28)": 28,
    }

    def __init__(self, master, on_done, has_subs=False, proj_name=""):
        super().__init__(master)
        self.title("Export Settings")
        self.geometry("430x550"); self.resizable(False, False)
        self.configure(fg_color=PANEL_DARK)
        self._on_done  = on_done
        self._has_subs = has_subs

        import last_dirs as _ld
        saved_export_dir = _ld.get(_ld.EXPORT_VIDEO, fallback="")
        self._export_dir = saved_export_dir if (saved_export_dir and os.path.isdir(saved_export_dir)) else ""

        pname = proj_name if proj_name else getattr(master, "_proj_name", "Untitled Project")
        stem = os.path.splitext(pname)[0]
        fname = f"{stem}.mp4" if not stem.lower().endswith(".mp4") else stem

        if self._export_dir:
            self._default_path = os.path.join(self._export_dir, fname)
        else:
            self._default_path = ""  # Clean / blank by default

        self._build()
        self.after(100, self._raise)

    def _raise(self):
        self.lift(); self.focus_force(); self.grab_set()

    def _build(self):
        ctk.CTkLabel(self, text="🎬  Export Settings",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TXT_W).pack(pady=(18, 2))
        ctk.CTkLabel(self, text="H.264 · AAC · MP4",
                     font=ctk.CTkFont(size=9), text_color=TXT_G).pack()

        sc = ctk.CTkFrame(self, fg_color="transparent")
        sc.pack(fill="both", expand=True, padx=22, pady=10)

        def sec(t):
            ctk.CTkLabel(sc, text=t,
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=TXT_G).pack(anchor="w", pady=(10, 3))

        # Resolution
        sec("RESOLUTION")
        self._res_v = tk.StringVar(value="Original")
        rf = ctk.CTkFrame(sc, fg_color="transparent")
        rf.pack(fill="x", pady=(0, 6))
        for r in ["Original", "1080p", "720p", "480p"]:
            ctk.CTkRadioButton(rf, text=r, value=r, variable=self._res_v,
                                font=ctk.CTkFont(size=10),
                                radiobutton_width=16, radiobutton_height=16
                                ).pack(side="left", padx=8)

        # Quality
        sec("QUALITY")
        self._q_v = tk.StringVar(value="High   (CRF 18)")
        for q in self._CRF_MAP:
            ctk.CTkRadioButton(sc, text=q, value=q, variable=self._q_v,
                                font=ctk.CTkFont(size=10),
                                radiobutton_width=16, radiobutton_height=16
                                ).pack(anchor="w", padx=4, pady=2)

        # Subtitle
        sec("SUBTITLE")
        self._sub_v = tk.BooleanVar(value=self._has_subs)
        self._sub_cb = ctk.CTkCheckBox(
            sc, text="Burn subtitles into video",
            variable=self._sub_v,
            font=ctk.CTkFont(size=10),
            state="normal" if self._has_subs else "disabled")
        self._sub_cb.pack(anchor="w", padx=4)
        if not self._has_subs:
            ctk.CTkLabel(sc, text="(Generate subtitles first via Transcript tab)",
                         font=ctk.CTkFont(size=8), text_color=TXT_G
                         ).pack(anchor="w", padx=22)

        # Output path
        sec("OUTPUT FILE")
        self._path_v = tk.StringVar(value=self._default_path)
        row = ctk.CTkFrame(sc, fg_color="transparent")
        row.pack(fill="x", pady=(0, 4))
        ctk.CTkEntry(row, textvariable=self._path_v, height=28,
                     corner_radius=6, fg_color=PANEL_MID,
                     placeholder_text="Choose output path…"
                     ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(row, text="Browse", width=70, height=28,
                      corner_radius=6, fg_color=PANEL_LIGHT,
                      hover_color=PANEL_HOV, font=ctk.CTkFont(size=9),
                      command=self._browse).pack(side="left")

        # Action buttons
        br = ctk.CTkFrame(self, fg_color="transparent")
        br.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkButton(br, text="Cancel", width=90, height=36,
                      corner_radius=8, fg_color=PANEL_MID,
                      hover_color=PANEL_LIGHT,
                      command=self.destroy).pack(side="left")
        ctk.CTkButton(br, text="🎬  Export", height=36, corner_radius=8,
                      fg_color=C_BLUE, hover_color=_dark(C_BLUE),
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._submit).pack(side="right")

    def _browse(self):
        import last_dirs as _ld
        stem = "Output_Video"
        if hasattr(self.master, "_proj_name") and self.master._proj_name:
            stem = os.path.splitext(self.master._proj_name)[0]
        init_file = f"{stem}.mp4" if not stem.lower().endswith(".mp4") else stem

        path = filedialog.asksaveasfilename(
            title="Save Export As",
            initialdir=self._export_dir if (self._export_dir and os.path.isdir(self._export_dir)) else None,
            initialfile=init_file,
            filetypes=[("MP4 Video", "*.mp4"), ("All Files", "*.*")],
            defaultextension=".mp4"
        )
        if path:
            self._path_v.set(path)
            self._export_dir = os.path.dirname(path)
            _ld.remember(_ld.EXPORT_VIDEO, self._export_dir)

    def _submit(self):
        out = self._path_v.get().strip()
        if not out:
            self._browse()
            out = self._path_v.get().strip()
            if not out:
                return
        import last_dirs as _ld
        _ld.remember(_ld.EXPORT_VIDEO, os.path.dirname(out))
        self.destroy()
        self._on_done(
            out,
            self._CRF_MAP.get(self._q_v.get(), 20),
            self._res_v.get(),
            self._sub_v.get()
        )


# ═════════════════════════════════════════════════════════════════════════════
class _SubtitleDialog(ctk.CTkToplevel):
    _LOCAL_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper-small-final")

    def __init__(self, master, style, on_done):
        super().__init__(master)
        self.title("Subtitle Settings")
        self.geometry("500x700"); self.resizable(False, False)
        self.configure(fg_color=PANEL_DARK)
        self._on_done  = on_done
        self._style    = copy.deepcopy(style)
        self._srt_path = ""
        self._build()
        self.after(100, self._raise)

    def _build(self):
        ctk.CTkLabel(self, text="Auto-Subtitle Settings",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TXT_W).pack(pady=(18, 2))
        ctk.CTkLabel(self, text="Whisper (Local Model) + PyThaiNLP",
                     font=ctk.CTkFont(size=10), text_color=TXT_G).pack()

        sc = ctk.CTkScrollableFrame(self, fg_color="transparent")
        sc.pack(fill="both", expand=True, padx=14, pady=10)

        def sec(t):
            ctk.CTkLabel(sc, text=t, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=TXT_G).pack(anchor="w", pady=(10, 3))

        sec("โมเดล (Model Path)")
        _default_model = self._LOCAL_MODEL if os.path.isdir(self._LOCAL_MODEL) else "base"
        # Row: entry + browse button
        _mrow = ctk.CTkFrame(sc, fg_color="transparent")
        _mrow.pack(fill="x", pady=(0, 2))
        self._cm = ctk.CTkEntry(_mrow, placeholder_text="Path to model folder…",
                                height=28, corner_radius=6, fg_color=PANEL_MID)
        self._cm.pack(side="left", fill="x", expand=True)
        self._cm.insert(0, _default_model)

        def _browse_model():
            from tkinter import filedialog as _fd
            folder = _fd.askdirectory(title="Select Whisper Model Folder")
            if folder:
                self._cm.delete(0, "end")
                self._cm.insert(0, folder)

        ctk.CTkButton(
            _mrow, text="…", width=28, height=28,
            fg_color=PANEL_MID, hover_color="#334155",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=_browse_model,
        ).pack(side="left", padx=(4, 0))

        ctk.CTkLabel(sc, text="Fallback (ถ้าไม่ระบุ path):",
                     font=ctk.CTkFont(size=8), text_color=TXT_G).pack(anchor="w")
        self._mv = tk.StringVar(value="base")
        mf = ctk.CTkFrame(sc, fg_color="transparent"); mf.pack(fill="x", pady=(0, 6))
        for m in ["tiny", "base", "small", "medium"]:
            ctk.CTkRadioButton(mf, text=m, value=m, variable=self._mv,
                                font=ctk.CTkFont(size=9)).pack(side="left", padx=6)

        sec("จำนวนคำต่อซับ (Words per subtitle)")
        wpl_row = ctk.CTkFrame(sc, fg_color="transparent")
        wpl_row.pack(fill="x", pady=(0, 6))
        self._wpl_v = tk.IntVar(value=8)
        ctk.CTkSlider(wpl_row, from_=3, to=20, variable=self._wpl_v,
                      width=200, progress_color=C_AMBER, button_color=C_AMBER,
                      command=lambda v: self._wpl_lbl.configure(
                          text=f"{int(float(v))} คำ")
                      ).pack(side="left", padx=(0, 8))
        self._wpl_lbl = ctk.CTkLabel(wpl_row, text="8 คำ",
                                      font=ctk.CTkFont(size=10), text_color=TXT_W)
        self._wpl_lbl.pack(side="left")

        if PRESETS:
            sec("Style Preset")
            pf=ctk.CTkFrame(sc,fg_color="transparent"); pf.pack(fill="x",pady=(0,6))
            for pi,p in enumerate(PRESETS):
                ctk.CTkButton(pf,text=p["name"],width=108,height=26,corner_radius=6,
                              fg_color=PANEL_MID,hover_color=PANEL_LIGHT,
                              font=ctk.CTkFont(size=9),
                              command=lambda pp=p:self._preset(pp)
                              ).grid(row=pi//4,column=pi%4,padx=2,pady=2)

        sec("Font")
        self._fv=tk.StringVar(value=self._style.font_name)
        fonts=FONT_CHOICES or ["Arial","Tahoma","Courier New"]
        ctk.CTkOptionMenu(sc,values=fonts,variable=self._fv,height=28,
                          corner_radius=6,fg_color=PANEL_MID).pack(fill="x",pady=(0,4))
        r=ctk.CTkFrame(sc,fg_color="transparent"); r.pack(fill="x",pady=(0,6))
        ctk.CTkLabel(r,text="Size:",font=ctk.CTkFont(size=9),text_color=TXT_G,width=38).pack(side="left")
        self._sv=tk.IntVar(value=self._style.font_size)
        ctk.CTkSlider(r,from_=14,to=60,variable=self._sv,width=180).pack(side="left",padx=6)
        ctk.CTkLabel(r,textvariable=self._sv,font=ctk.CTkFont(size=9),text_color=TXT_G).pack(side="left")

        cr=ctk.CTkFrame(sc,fg_color="transparent"); cr.pack(fill="x",pady=(0,6))
        ctk.CTkLabel(cr,text="Color:",font=ctk.CTkFont(size=9),text_color=TXT_G).pack(side="left")
        self._cv=tk.StringVar(value=self._style.font_color)
        ctk.CTkEntry(cr,textvariable=self._cv,width=80,height=26,
                     corner_radius=6,fg_color=PANEL_MID).pack(side="left",padx=6)

        sec("Decoration")
        self._dv=tk.StringVar(value=self._style.decoration)
        ctk.CTkOptionMenu(sc,values=DECORATION_CHOICES or["none","outline","shadow","box"],
                          variable=self._dv,height=28,corner_radius=6,
                          fg_color=PANEL_MID).pack(fill="x",pady=(0,6))

        sec("Animation")
        self._av=tk.StringVar(value=self._style.animation)
        ctk.CTkOptionMenu(sc,values=ANIMATION_CHOICES or["none","fade_in","slide_up"],
                          variable=self._av,height=28,corner_radius=6,
                          fg_color=PANEL_MID).pack(fill="x",pady=(0,6))

        sec("Position")
        self._pv=tk.StringVar(value=self._style.position)
        ctk.CTkOptionMenu(sc,values=POSITION_CHOICES or["bottom_center","top_center"],
                          variable=self._pv,height=28,corner_radius=6,
                          fg_color=PANEL_MID).pack(fill="x",pady=(0,6))

        sec("ขอบเขตเวลาสร้างซับไตเติล (Time Range)")
        self._range_mode = tk.StringVar(value="full")
        rf = ctk.CTkFrame(sc, fg_color="transparent")
        rf.pack(fill="x", pady=(0, 4))

        ctk.CTkRadioButton(rf, text="ทั้งหมด (Full)", value="full", variable=self._range_mode,
                            font=ctk.CTkFont(size=9)).pack(side="left", padx=4)
        ctk.CTkRadioButton(rf, text="กำหนดช่วงเวลา (Custom Range)", value="custom", variable=self._range_mode,
                            font=ctk.CTkFont(size=9)).pack(side="left", padx=4)

        self._t_range_row = ctk.CTkFrame(sc, fg_color="transparent")
        self._t_range_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(self._t_range_row, text="เริ่ม (วินาที):", font=ctk.CTkFont(size=9), text_color=TXT_G).pack(side="left", padx=(0, 2))
        self._t_start_ent = ctk.CTkEntry(self._t_range_row, width=64, height=26, corner_radius=6, fg_color=PANEL_MID)
        self._t_start_ent.insert(0, "0.0")
        self._t_start_ent.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(self._t_range_row, text="ถึง (วินาที):", font=ctk.CTkFont(size=9), text_color=TXT_G).pack(side="left", padx=(0, 2))
        self._t_end_ent = ctk.CTkEntry(self._t_range_row, width=64, height=26, corner_radius=6, fg_color=PANEL_MID)
        self._t_end_ent.insert(0, "60.0")
        self._t_end_ent.pack(side="left")

        sec("SRT Export")
        self._srt_var = tk.BooleanVar(value=False)
        srt_check = ctk.CTkCheckBox(sc, text="Auto-save SRT after transcription",
                                     variable=self._srt_var,
                                     font=ctk.CTkFont(size=10),
                                     command=self._toggle_srt_path)
        srt_check.pack(anchor="w", pady=(0,4))

        self._srt_row = ctk.CTkFrame(sc, fg_color="transparent")
        self._srt_row.pack(fill="x", pady=(0,6))
        self._srt_entry = ctk.CTkEntry(self._srt_row,
                                        placeholder_text="Output .srt path…",
                                        height=28, corner_radius=6,
                                        fg_color=PANEL_MID, state="disabled")
        self._srt_entry.pack(side="left", fill="x", expand=True, padx=(0,4))
        self._srt_browse = ctk.CTkButton(self._srt_row, text="Browse",
                                          width=62, height=28, corner_radius=6,
                                          fg_color=PANEL_LIGHT, hover_color=PANEL_HOV,
                                          font=ctk.CTkFont(size=9),
                                          state="disabled",
                                          command=self._browse_srt)
        self._srt_browse.pack(side="left")

        br=ctk.CTkFrame(self,fg_color="transparent")
        br.pack(fill="x",padx=14,pady=(0,14))
        ctk.CTkButton(br,text="Cancel",width=100,height=34,corner_radius=8,
                      fg_color=PANEL_MID,hover_color=PANEL_LIGHT,
                      command=self.destroy).pack(side="left")
        ctk.CTkButton(br,text="Generate Subtitles",height=34,corner_radius=8,
                      fg_color=C_BLUE,hover_color=_dark(C_BLUE),
                      font=ctk.CTkFont(size=11,weight="bold"),
                      command=self._submit).pack(side="right")

    def _raise(self):
        self.lift()
        self.focus_force()
        self.grab_set()

    def _toggle_srt_path(self):
        state = "normal" if self._srt_var.get() else "disabled"
        self._srt_entry.configure(state=state)
        self._srt_browse.configure(state=state)

    def _browse_srt(self):
        path = filedialog.asksaveasfilename(
            title="Save SRT File As",
            initialdir=_ld.get(_ld.SAVE_PROJECT),
            initialfile="subtitles.srt",
            defaultextension=".srt",
            filetypes=[("SRT Subtitle","*.srt"),("All files","*.*")])
        if path:
            _ld.remember(_ld.SAVE_PROJECT, path)
            self._srt_path = path
            self._srt_entry.configure(state="normal")
            self._srt_entry.delete(0, "end")
            self._srt_entry.insert(0, path)
            self._srt_entry.configure(state="readonly")

    def _preset(self,p):
        self._fv.set(p.get("font","Tahoma")); self._sv.set(p.get("size",32))
        self._cv.set(p.get("color","#ffffff")); self._dv.set(p.get("deco","outline"))
        self._av.set(p.get("anim","none"))

    def _submit(self):
        s = self._style
        s.font_name  = self._fv.get()
        s.font_size  = self._sv.get()
        s.font_color = self._cv.get()
        s.decoration = self._dv.get()
        s.animation  = self._av.get()
        s.position   = self._pv.get()
        mp    = self._cm.get().strip()
        model = mp if mp else self._mv.get()
        words_per_line = int(self._wpl_v.get())
        srt_path = ""
        if self._srt_var.get():
            srt_path = self._srt_path or self._srt_entry.get().strip()

        # ── Validate model path before submitting ────────────────────────────
        # If user typed a directory path, verify it actually exists and looks
        # like a HuggingFace model folder (has config.json or pytorch_model.bin)
        if mp and not self._mv.get() == mp:
            if not os.path.isdir(mp):
                from tkinter import messagebox as _mb
                _mb.showerror(
                    "Model Path Error",
                    f"ไม่พบ folder:\n{mp}\n\n"
                    "กรุณาเลือก folder ของ Whisper model ที่ถูกต้อง\n"
                    "(ควรมีไฟล์ config.json หรือ pytorch_model.bin)\n\n"
                    "หรือเลือก fallback model (tiny/base/small/medium) แทน"
                )
                return  # ไม่ปิด dialog ให้ user แก้ไขก่อน
            # Warn if folder looks incomplete
            has_model = any(
                os.path.exists(os.path.join(mp, f))
                for f in ["config.json", "pytorch_model.bin",
                          "model.safetensors", "best.pt", "model.pt"]
            )
            if not has_model:
                from tkinter import messagebox as _mb
                ok = _mb.askyesno(
                    "Model Warning",
                    f"ไม่พบไฟล์ model ใน folder:\n{mp}\n\n"
                    "อาจเกิดข้อผิดพลาดระหว่างโหลด\n"
                    "ต้องการดำเนินการต่อหรือไม่?"
                )
                if not ok:
                    return

        rmode = self._range_mode.get()
        t_start = 0.0
        t_end = 0.0
        if rmode == "custom":
            try:
                t_start = float(self._t_start_ent.get())
                t_end = float(self._t_end_ent.get())
            except Exception:
                t_start = 0.0
                t_end = 0.0

        self.destroy()
        self._on_done(s, model, words_per_line, srt_path, rmode, t_start, t_end)