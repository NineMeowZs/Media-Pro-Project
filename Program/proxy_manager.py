"""proxy_manager.py – Auto Proxy System for MediaPro
Builds lightweight 480p H.264 proxy files in the background so that
Preview / Playback is smooth even on high-bitrate source files.
Export always uses the original full-quality path.
"""

import os
import hashlib
import tempfile
import threading
import subprocess
import time

try:
    import imageio_ffmpeg
    _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    _FFMPEG = "ffmpeg"

# Proxy cache directory — inside system temp, shared across sessions
_PROXY_DIR = os.path.join(tempfile.gettempdir(), "mediapro_proxies")
os.makedirs(_PROXY_DIR, exist_ok=True)

# Max age (seconds) before a proxy is considered stale and deleted on cleanup
_MAX_AGE_DAYS = 7


def _proxy_key(original_path: str) -> str:
    """Deterministic filename for a given source path (MD5 hex of the path)."""
    return hashlib.md5(original_path.encode("utf-8")).hexdigest() + ".mp4"


def _proxy_path_for(original_path: str) -> str:
    return os.path.join(_PROXY_DIR, _proxy_key(original_path))


class ProxyManager:
    """
    Manages proxy video files for smooth preview playback.

    Usage:
        pm = ProxyManager()
        pm.build_proxy_async(path, on_ready_cb=..., on_progress_cb=...)
        preview_path = pm.get_proxy(path) or path  # fallback to original
    """

    def __init__(self):
        # Maps original_path → proxy_path (once ready)
        self._ready: dict[str, str] = {}
        # Paths currently being built (avoid duplicate builds)
        self._building: set[str] = set()
        self._lock = threading.Lock()

        # Pre-populate from existing cache files
        self._scan_cache()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def get_proxy(self, original_path: str) -> str | None:
        """
        Return the proxy path if it is ready; otherwise return None.
        Safe to call from any thread.
        """
        with self._lock:
            return self._ready.get(original_path)

    def is_building(self, original_path: str) -> bool:
        with self._lock:
            return original_path in self._building

    def build_proxy_async(
        self,
        original_path: str,
        on_ready_cb=None,
        on_progress_cb=None,
    ):
        """
        Start building a proxy for *original_path* in a daemon thread.
        Skips silently if proxy already exists or is being built.

        on_ready_cb(proxy_path)      – called when done (from worker thread)
        on_progress_cb(pct: int)     – called periodically with 0-100
        """
        with self._lock:
            if original_path in self._ready:
                if on_ready_cb:
                    on_ready_cb(self._ready[original_path])
                return
            if original_path in self._building:
                return  # already in progress
            self._building.add(original_path)

        t = threading.Thread(
            target=self._build_worker,
            args=(original_path, on_ready_cb, on_progress_cb),
            daemon=True,
        )
        t.start()

    def original_path(self, proxy_path: str) -> str | None:
        """Reverse-lookup: given a proxy path, return the original (if known)."""
        with self._lock:
            for orig, prx in self._ready.items():
                if prx == proxy_path:
                    return orig
        return None

    def cleanup_old(self):
        """Delete proxy files older than _MAX_AGE_DAYS. Call at startup."""
        cutoff = time.time() - _MAX_AGE_DAYS * 86400
        for fn in os.listdir(_PROXY_DIR):
            fp = os.path.join(_PROXY_DIR, fn)
            try:
                if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────────

    def _scan_cache(self):
        """On startup, register any existing proxy files (skip re-building)."""
        # We can only register the key→path mapping; we don't know the original
        # paths until a clip is actually loaded, so this is a no-op for now.
        # The per-path hash check in build_proxy_async handles re-use correctly.
        pass

    def _build_worker(self, original_path, on_ready_cb, on_progress_cb):
        proxy = _proxy_path_for(original_path)
        success = False
        try:
            # If a completed proxy already exists on disk, reuse it
            if os.path.isfile(proxy) and os.path.getsize(proxy) > 10_000:
                success = True
            else:
                success = self._run_ffmpeg(original_path, proxy, on_progress_cb)
        except Exception as e:
            print(f"[Proxy] build error for {original_path}: {e}")
        finally:
            with self._lock:
                self._building.discard(original_path)
                if success:
                    self._ready[original_path] = proxy

        if success and on_ready_cb:
            on_ready_cb(proxy)

    def _run_ffmpeg(self, src: str, dst: str, on_progress_cb) -> bool:
        """
        Encode a 480p proxy using ffmpeg with GPU hardware acceleration when available.
        Returns True on success, False on failure.
        """
        # Get source duration for progress reporting
        dur = self._probe_duration(src)

        tmp_dst = dst + ".tmp.mp4"

        # Check for GPU encoders
        v_codec_args = ["-c:v", "libx264", "-crf", "23", "-preset", "ultrafast", "-tune", "fastdecode"]
        try:
            from video_exporter import _detect_gpu_encoder
            enc_name, _ = _detect_gpu_encoder()
            if enc_name == "h264_nvenc":
                v_codec_args = ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "24"]
            elif enc_name == "h264_qsv":
                v_codec_args = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "24"]
            elif enc_name == "h264_amf":
                v_codec_args = ["-c:v", "h264_amf", "-quality", "speed"]
        except Exception:
            pass

        cmd = [
            _FFMPEG, "-y",
            "-i", src,
            # Video: scale to max 480 height, keep aspect
            "-vf", "scale=-2:min(480\\,ih)",
            *v_codec_args,
            # Audio: copy stream as-is (fast, no re-encode)
            "-c:a", "copy",
            "-movflags", "+faststart",
            tmp_dst,
        ]

        try:
            extra_kwargs = {}
            if os.name == "nt":
                extra_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            proc = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore",
                **extra_kwargs,
            )

            # Parse ffmpeg stderr for time= progress
            for line in proc.stderr:
                if "time=" in line and dur and dur > 0 and on_progress_cb:
                    try:
                        t_str = line.split("time=")[1].split()[0]
                        h, m, s = t_str.split(":")
                        elapsed = int(h) * 3600 + int(m) * 60 + float(s)
                        pct = int(min(99, elapsed / dur * 100))
                        on_progress_cb(pct)
                    except Exception:
                        pass

            proc.wait()

            if proc.returncode == 0 and os.path.isfile(tmp_dst):
                os.replace(tmp_dst, dst)
                if on_progress_cb:
                    on_progress_cb(100)
                return True
            else:
                if os.path.isfile(tmp_dst):
                    os.remove(tmp_dst)
                return False
        except Exception as e:
            print(f"[Proxy] ffmpeg error: {e}")
            if os.path.isfile(tmp_dst):
                try:
                    os.remove(tmp_dst)
                except Exception:
                    pass
            return False

    def _probe_duration(self, path: str) -> float | None:
        """Return video duration in seconds using ffprobe/ffmpeg."""
        try:
            cmd = [
                _FFMPEG, "-i", path,
                "-f", "null", "-"
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="ignore", timeout=10
            )
            for line in result.stderr.splitlines():
                if "Duration:" in line:
                    t = line.split("Duration:")[1].split(",")[0].strip()
                    h, m, s = t.split(":")
                    return int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            pass
        return None
