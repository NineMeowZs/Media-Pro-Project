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
    try:
        h = str(hex_color).strip().lstrip("#")
        if h.startswith("0x") or h.startswith("0X"):
            h = h[2:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"
    except Exception:
        pass
    return f"&H{alpha:02X}FFFFFF"



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
    """Write an ASS subtitle file from segments and SubtitleStyle with exact positioning, letter spacing, and font styling."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_name},{int(style.font_size)},{_hex_to_ass_colour(style.font_color)},&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    pos_map = {
        "bottom_center": (960, 950),
        "bottom_left":   (360, 950),
        "bottom_right":  (1560, 950),
        "top_center":    (960, 130),
        "top_left":      (360, 130),
        "top_right":     (1560, 130),
        "center":        (960, 540),
        "custom":        (int(getattr(style, "custom_x", 0.5) * 1920), int(getattr(style, "custom_y", 0.85) * 1080)),
    }

    lines = [header]
    for seg in segments:
        start = _secs_to_ass_time(seg["start"])
        end   = _secs_to_ass_time(seg["end"])
        text  = seg.get("text", "").replace("\n", "\\N")
        if not text.strip():
            continue

        # Extract per-segment overrides
        fn   = seg.get("font_name", style.font_name)
        fs   = int(seg.get("font_size", style.font_size))
        fc   = seg.get("font_color", style.font_color)
        bl   = seg.get("bold", style.bold)
        it   = seg.get("italic", style.italic)
        dc   = seg.get("decoration", style.decoration)
        lsp  = int(seg.get("letter_spacing", getattr(style, "letter_spacing", 0)))
        dcol = seg.get("decoration_color", getattr(style, "decoration_color", "#000000"))
        bg_op = getattr(style, "bg_opacity", 0.5)

        # Determine exact position coordinates
        if "custom_x" in seg and "custom_y" in seg:
            px = int(seg["custom_x"] * 1920)
            py = int(seg["custom_y"] * 1080)
        elif style.position == "custom":
            px = int(getattr(style, "custom_x", 0.5) * 1920)
            py = int(getattr(style, "custom_y", 0.85) * 1080)
        else:
            px, py = pos_map.get(style.position, (960, 950))

        # Build inline ASS override tags
        tags = [
            f"\\an5\\pos({px},{py})",
            f"\\fn{fn}",
            f"\\fs{fs}",
            f"\\1c{_hex_to_ass_colour(fc)}",
            f"\\b{1 if bl else 0}",
            f"\\i{1 if it else 0}",
        ]

        if lsp > 0:
            tags.append(f"\\fsp{lsp}")

        if dc == "outline":
            tags.append(f"\\bord3\\shad0\\3c{_hex_to_ass_colour(dcol)}")
        elif dc == "shadow":
            tags.append(f"\\bord0\\shad3\\4c{_hex_to_ass_colour(dcol)}")
        elif dc in ("box", "highlight"):
            bg_alpha = int((1.0 - bg_op) * 255)
            tags.append(f"\\bord4\\shad0\\3c{_hex_to_ass_colour(dcol, alpha=bg_alpha)}")
        else:
            tags.append("\\bord0\\shad0")

        anim = getattr(style, "animation", "none")
        if anim == "fade_in":
            tags.append(r"\fad(200,0)")
        elif anim == "slide_up":
            tags.append(f"\\move({px},{py + 40},{px},{py},0,250)")

        tag_str = "{" + "".join(tags) + "}"
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{tag_str}{text}")

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

def _find_active_segment_and_style(t: float, segments: list[dict], default_style: SubtitleStyle):
    import copy
    for seg in segments:
        if seg["start"] <= t <= seg["end"]:
            dur = max(seg["end"] - seg["start"], 0.001)
            prog = (t - seg["start"]) / dur
            st = copy.copy(default_style)
            if "font_name" in seg: st.font_name = seg["font_name"]
            if "font_size" in seg: st.font_size = seg["font_size"]
            if "font_color" in seg: st.font_color = seg["font_color"]
            if "bold" in seg: st.bold = seg["bold"]
            if "italic" in seg: st.italic = seg["italic"]
            if "decoration" in seg: st.decoration = seg["decoration"]
            if "decoration_color" in seg: st.decoration_color = seg["decoration_color"]
            if "letter_spacing" in seg: st.letter_spacing = seg["letter_spacing"]
            if "custom_x" in seg: st.custom_x = seg["custom_x"]; st.position = "custom"
            if "custom_y" in seg: st.custom_y = seg["custom_y"]; st.position = "custom"
            return seg.get("text", ""), st, prog
    return "", default_style, 0.5


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
        text, seg_style, progress = _find_active_segment_and_style(t, segments, style)
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if text.strip():
            bgr = draw_subtitles_on_frame(bgr, text, seg_style, progress)
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

