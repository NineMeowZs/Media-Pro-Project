"""video_exporter.py – Burn subtitles into video via ffmpeg ASS filter (fast path)
or frame-by-frame OpenCV fallback (slow path).
"""

import cv2
import subprocess
import tempfile
import os
import shutil
import imageio_ffmpeg
import numpy as np

from subtitle_config import SubtitleStyle


# ─────────────────────────────────────────────────────────────────────────────
# Helper: convert SubtitleStyle to ASS colour string (&HAABBGGRR)
# ─────────────────────────────────────────────────────────────────────────────

def _hex_to_ass_colour(hex_color: str, alpha: int = 0) -> str:
    """Convert #RRGGBB → ASS &HAABBGGRR (alpha 0 = fully opaque)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _position_to_ass_alignment(position: str) -> int:
    """Map subtitle position name → ASS \an alignment (numpad layout)."""
    mapping = {
        "bottom_left":   1, "bottom_center": 2, "bottom_right":  3,
        "center_left":   4, "center":         5, "center_right":  6,
        "top_left":      7, "top_center":     8, "top_right":     9,
        "custom":        2,  # default to bottom-centre for custom
    }
    return mapping.get(position.lower(), 2)


def _style_to_ass_decoration(style: SubtitleStyle):
    """Return (BorderStyle, Outline, Shadow, BackColour) for ASS."""
    deco = style.decoration
    deco_col = _hex_to_ass_colour(style.decoration_color)

    if deco == "outline":
        return 1, 2, 0, deco_col
    elif deco == "shadow":
        return 1, 0, 2, deco_col
    elif deco in ("box", "highlight"):
        # BorderStyle 3 = opaque box background
        bg_alpha = int((1 - style.bg_opacity) * 255)
        box_col  = _hex_to_ass_colour(style.decoration_color, alpha=bg_alpha)
        return 3, 0, 0, box_col
    else:  # none
        return 1, 0, 0, "&H00000000"


def _find_font_file(font_name: str) -> str:
    """Return a .ttf path for the given font name, or empty string."""
    font_map = {
        "Arial":           "arial.ttf",
        "Tahoma":          "tahoma.ttf",
        "TH Sarabun New":  "THSarabunNew.ttf",
        "Angsana New":     "angsau32.ttf",
        "Cordia New":      "cordia.ttf",
        "Leelawadee":      "leelawad.ttf",
        "Courier New":     "cour.ttf",
        "Times New Roman": "times.ttf",
        "Verdana":         "verdana.ttf",
        "Impact":          "impact.ttf",
    }
    fonts_dir = "C:/Windows/Fonts"
    fn = font_map.get(font_name, font_name + ".ttf")
    path = os.path.join(fonts_dir, fn)
    return path if os.path.exists(path) else ""


# ─────────────────────────────────────────────────────────────────────────────
# Generate .ass file from segments + style
# ─────────────────────────────────────────────────────────────────────────────

def _secs_to_ass_time(t: float) -> str:
    """Convert seconds → ASS timestamp h:mm:ss.cc"""
    h  = int(t // 3600)
    m  = int((t % 3600) // 60)
    s  = int(t % 60)
    cs = int((t - int(t)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_file(segments: list[dict], style: SubtitleStyle, out_path: str) -> None:
    """Write an ASS subtitle file from segments and SubtitleStyle."""
    alignment  = _position_to_ass_alignment(style.position)
    border, outline, shadow, back_col = _style_to_ass_decoration(style)
    pri_col    = _hex_to_ass_colour(style.font_color)
    font_name  = style.font_name
    font_size  = style.font_size
    margin_v   = style.margin_y
    margin_h   = style.margin_x
    bold_flag  = -1 if style.bold else 0
    italic_flag = -1 if style.italic else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{pri_col},&H00FFFFFF,{_hex_to_ass_colour(style.decoration_color)},{back_col},{bold_flag},{italic_flag},0,0,100,100,0,0,{border},{outline},{shadow},{alignment},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in segments:
        start = _secs_to_ass_time(seg["start"])
        end   = _secs_to_ass_time(seg["end"])
        text  = seg.get("text", "").replace("\n", "\\N")

        # Apply animation via ASS tags
        anim = style.animation
        if anim == "fade_in":
            text = r"{\fad(200,0)}" + text
        elif anim == "slide_up":
            # Move from below → position
            text = r"{\move(960,1040,960,1000,0,300)}" + text
        elif anim == "fade_in":
            text = r"{\fad(200,0)}" + text

        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# GPU Hardware Encoder Detection
# ─────────────────────────────────────────────────────────────────────────────

_GPU_ENCODER_CACHE = None

def _detect_gpu_encoder() -> tuple[str, list[str]]:
    """
    Auto-detect available GPU hardware encoder in FFmpeg.
    Returns (encoder_name, encoder_args).
    Priority: NVENC (NVIDIA) > QSV (Intel) > AMF (AMD) > libx264 (CPU)
    """
    global _GPU_ENCODER_CACHE
    if _GPU_ENCODER_CACHE is not None:
        return _GPU_ENCODER_CACHE

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        res = subprocess.run([ff, "-encoders"], capture_output=True, text=True, timeout=5)
        encoders_output = res.stdout if res.returncode == 0 else ""
    except Exception:
        encoders_output = ""

    if "h264_nvenc" in encoders_output:
        _GPU_ENCODER_CACHE = (
            "h264_nvenc",
            [
                "-c:v", "h264_nvenc",
                "-preset", "p6",
                "-rc", "vbr",
                "-cq", "17",
                "-b:v", "16M",
                "-maxrate", "30M",
                "-bufsize", "30M",
                "-spatial-aq", "1",
                "-temporal-aq", "1",
                "-pix_fmt", "yuv420p",
            ]
        )
    elif "h264_qsv" in encoders_output:
        _GPU_ENCODER_CACHE = (
            "h264_qsv",
            ["-c:v", "h264_qsv", "-preset", "slow", "-global_quality", "18", "-pix_fmt", "yuv420p"]
        )
    elif "h264_amf" in encoders_output:
        _GPU_ENCODER_CACHE = (
            "h264_amf",
            ["-c:v", "h264_amf", "-quality", "quality", "-pix_fmt", "yuv420p"]
        )
    else:
        _GPU_ENCODER_CACHE = (
            "libx264",
            ["-c:v", "libx264", "-crf", "17", "-preset", "slow", "-pix_fmt", "yuv420p"]
        )

    return _GPU_ENCODER_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# Fast export: ffmpeg ASS filter  (≈ 10–20× faster than frame-by-frame)
# ─────────────────────────────────────────────────────────────────────────────

def export_video_with_subtitles(
    input_path: str,
    output_path: str,
    segments: list[dict],
    style: SubtitleStyle,
    progress_cb=None,
):
    """
    Burn subtitles using ffmpeg's ASS subtitle filter.
    Uses GPU hardware acceleration (NVENC / QSV / AMF) when available.
    Falls back to slow frame-by-frame rendering if ffmpeg fails.
    """
    enc_name, enc_args = _detect_gpu_encoder()
    gpu_msg = f"GPU ({enc_name})" if enc_name != "libx264" else "CPU (libx264)"

    if progress_cb:
        progress_cb(f"กำลัง Export ด้วย {gpu_msg} …")

    ff = imageio_ffmpeg.get_ffmpeg_exe()

    # Write temp .ass file
    tmp_ass = output_path + "_tmp_subs.ass"
    try:
        generate_ass_file(segments, style, tmp_ass)
    except Exception as e:
        if progress_cb:
            progress_cb(f"สร้าง ASS ล้มเหลว: {e} – ใช้ frame-by-frame แทน")
        _export_frame_by_frame(input_path, output_path, segments, style, progress_cb)
        return

    # Escape path for ffmpeg on Windows (backslash → forward-slash, escape colons)
    ass_path_escaped = tmp_ass.replace("\\", "/").replace(":", "\\:")

    # Build command line with optional GPU hardware decoding
    hw_args = ["-hwaccel", "auto"] if enc_name != "libx264" else []

    cmd = [
        ff, "-y",
        *hw_args,
        "-i", input_path,
        "-vf", f"ass='{ass_path_escaped}'",
        *enc_args,
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]

    if progress_cb:
        progress_cb(f"กำลัง Render ด้วย ffmpeg ({gpu_msg}) …")

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up temp ASS
    if os.path.exists(tmp_ass):
        os.remove(tmp_ass)

    if result.returncode == 0:
        if progress_cb:
            progress_cb(f"บันทึกไฟล์สำเร็จ: {os.path.basename(output_path)}")
    else:
        # If GPU command failed, retry once with CPU libx264 before falling back to frame-by-frame
        if enc_name != "libx264":
            if progress_cb:
                progress_cb("GPU export ไม่ผ่าน – ลองสลับใช้ CPU libx264 …")
            cpu_cmd = [
                ff, "-y",
                "-i", input_path,
                "-vf", f"ass='{ass_path_escaped}'",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                output_path,
            ]
            res_cpu = subprocess.run(cpu_cmd, capture_output=True, text=True)
            if res_cpu.returncode == 0:
                if progress_cb:
                    progress_cb(f"บันทึกไฟล์สำเร็จ: {os.path.basename(output_path)}")
                return

        if progress_cb:
            progress_cb("ffmpeg ASS ล้มเหลว – สลับไปใช้ frame-by-frame …")
        _export_frame_by_frame(input_path, output_path, segments, style, progress_cb)


# ─────────────────────────────────────────────────────────────────────────────
# Slow fallback: render frame-by-frame via OpenCV + PIL
# ─────────────────────────────────────────────────────────────────────────────

def _find_active_segment(t: float, segments: list[dict]) -> tuple[str, float]:
    for seg in segments:
        if seg["start"] <= t <= seg["end"]:
            dur = max(seg["end"] - seg["start"], 0.001)
            return seg["text"], (t - seg["start"]) / dur
    return "", 0.5


def _export_frame_by_frame(
    input_path: str,
    output_path: str,
    segments: list[dict],
    style: SubtitleStyle,
    progress_cb=None,
):
    """Fallback export: render frame-by-frame with GPU-accelerated video writer when available."""
    from moviepy import VideoFileClip
    from moviepy.video.io.ffmpeg_writer import FFMPEG_VideoWriter
    from subtitle_renderer import draw_subtitles_on_frame

    clip  = VideoFileClip(input_path)
    fps   = clip.fps
    total = max(1, int(clip.duration * fps))

    enc_name, _ = _detect_gpu_encoder()
    codec = enc_name if enc_name != "libx264" else "libx264"

    tmp_video = output_path + "_tmp_noaudio.mp4"
    writer = FFMPEG_VideoWriter(
        tmp_video, clip.size, fps,
        codec=codec, preset="fast", bitrate="5000k",
        audiofile=None,
    )

    if progress_cb:
        progress_cb(f"Render ทีละ Frame ({codec}) … 0%")

    for i, frame in enumerate(clip.iter_frames(fps=fps, dtype="uint8")):
        t = i / fps
        text, progress = _find_active_segment(t, segments)
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        bgr = draw_subtitles_on_frame(bgr, text, style, progress)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        writer.write_frame(rgb)
        if progress_cb and i % max(1, total // 20) == 0:
            progress_cb(f"Render ทีละ Frame … {int(i / total * 100)}%")

    writer.close()
    clip.close()

    if progress_cb:
        progress_cb("กำลังรวมเสียง …")

    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, "-y",
        "-i", tmp_video,
        "-i", input_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        shutil.copy2(tmp_video, output_path)

    if os.path.exists(tmp_video):
        os.remove(tmp_video)

    if progress_cb:
        progress_cb(f"บันทึกไฟล์สำเร็จ: {os.path.basename(output_path)}")

