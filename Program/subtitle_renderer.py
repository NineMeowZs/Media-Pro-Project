"""subtitle_renderer.py – Draws subtitles onto an OpenCV frame

Performance optimizations:
- LRU cache on rendered RGBA overlays (avoids re-rendering identical text every frame)
- Fast numpy alpha composite instead of PIL round-trip for each frame
- Bold / Italic font loading via _load_pil_font
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from subtitle_config import SubtitleStyle
import os, platform
from functools import lru_cache


# --------------------------------------------------------------------------- #
#  Font helpers
# --------------------------------------------------------------------------- #

# ── Map ชื่อฟอนต์ → ไฟล์ .ttf จริงบน Windows ──────────────────────────────
_FONT_MAP: dict[str, list[str]] = {
    "Arial":           ["arialbd.ttf", "ariali.ttf", "arialbdi.ttf", "arial.ttf", "Arial.ttf"],
    "Tahoma":          ["tahomabd.ttf", "tahoma.ttf", "Tahoma.ttf"],
    "TH Sarabun New":  ["THSarabunNew Bold.ttf", "THSarabunNew.ttf", "THSarabun New.ttf"],
    "Angsana New":     ["AngsanaNew Bold.ttf", "angsau32.ttf", "ANGSAU32.TTF", "AngsanaNew.ttf"],
    "Cordia New":      ["CordiaNew Bold.ttf", "cordia.ttf", "CORDIA32.TTF", "CordiaNEW.ttf"],
    "Leelawadee":      ["leelawadbd.ttf", "leelawad.ttf", "Leelawadee.ttf"],
    "Courier New":     ["courbd.ttf", "couri.ttf", "courbi.ttf", "cour.ttf", "Courier New.ttf"],
    "Times New Roman": ["timesbd.ttf", "timesi.ttf", "timesbi.ttf", "times.ttf", "Times New Roman.ttf"],
    "Verdana":         ["verdanab.ttf", "verdanai.ttf", "verdanaz.ttf", "verdana.ttf", "Verdana.ttf"],
    "Impact":          ["impact.ttf", "Impact.ttf"],
}

# ── Bold/Italic variant suffixes ────────────────────────────────────────────
_BOLD_SUFFIX   = ["bd", "b", " Bold", "Bold", "-Bold"]
_ITALIC_SUFFIX = ["i", " Italic", "Italic", "-Italic"]
_BOLDITALIC_SUFFIX = ["bi", "z", " Bold Italic", "BoldItalic", "-BoldItalic"]

# ฟอนต์ที่รองรับ Thai — เรียงลำดับความสำคัญ
_THAI_FALLBACK = [
    "THSarabunNew.ttf",
    "tahoma.ttf",
    "leelawad.ttf",
    "cordia.ttf",
    "angsau32.ttf",
    "CORDIA32.TTF",
    "ANGSAU32.TTF",
]
_FONTS_DIR = "C:/Windows/Fonts"


@lru_cache(maxsize=32)
def _load_pil_font_cached(font_name: str, size: int, bold: bool, italic: bool) -> ImageFont.FreeTypeFont:
    """Load font with bold/italic variant support. Results are cached by (name, size, bold, italic)."""
    candidates: list[str] = []
    name = font_name

    base_files = _FONT_MAP.get(name, [])

    # 1) Try bold+italic specific variants first
    if bold and italic:
        for fn in base_files:
            base, ext = os.path.splitext(fn)
            for s in _BOLDITALIC_SUFFIX:
                candidates.append(os.path.join(_FONTS_DIR, base + s + ext))
    if bold:
        for fn in base_files:
            base, ext = os.path.splitext(fn)
            for s in _BOLD_SUFFIX:
                candidates.append(os.path.join(_FONTS_DIR, base + s + ext))
    if italic:
        for fn in base_files:
            base, ext = os.path.splitext(fn)
            for s in _ITALIC_SUFFIX:
                candidates.append(os.path.join(_FONTS_DIR, base + s + ext))

    # 2) Fallback to known base file list
    for fn in base_files:
        candidates.append(os.path.join(_FONTS_DIR, fn))

    # 3) Try direct path
    candidates += [
        name,
        os.path.join(_FONTS_DIR, name + ".ttf"),
        os.path.join(_FONTS_DIR, name.lower() + ".ttf"),
    ]

    # 4) Thai fallback fonts
    for fn in _THAI_FALLBACK:
        candidates.append(os.path.join(_FONTS_DIR, fn))

    for c in candidates:
        try:
            font = ImageFont.truetype(c, size)
            return font
        except Exception:
            pass

    return ImageFont.load_default()


def _load_pil_font(style: SubtitleStyle) -> ImageFont.FreeTypeFont:
    """Public wrapper — reads bold/italic from style and delegates to cached loader."""
    return _load_pil_font_cached(
        style.font_name,
        style.font_size,
        getattr(style, "bold", False),
        getattr(style, "italic", False)
    )


def _hex_to_rgb(hex_color: str) -> tuple:
    """Safely convert any hex color string (#RRGGBB, 0xRRGGBB, RRGGBB, #RGB) to (R, G, B) tuple."""
    try:
        h = str(hex_color).strip().lstrip("#")
        if h.startswith("0x") or h.startswith("0X"):
            h = h[2:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        pass
    return (255, 255, 255)



# --------------------------------------------------------------------------- #
#  Animation helpers
# --------------------------------------------------------------------------- #

def _compute_alpha(animation: str, progress: float) -> float:
    if animation == "fade_in":
        return min(1.0, progress * 5)
    if animation == "pop":
        return 1.0 if progress > 0.0 else 0.0
    return 1.0


def _compute_offset(animation: str, progress: float, frame_h: int) -> tuple[int, int]:
    if animation == "slide_up":
        dy = int((1 - min(1.0, progress * 5)) * 40)
        return 0, dy
    if animation == "slide_down":
        dy = -int((1 - min(1.0, progress * 5)) * 40)
        return 0, dy
    return 0, 0


def _typewriter_text(text: str, progress: float) -> str:
    n = max(1, int(len(text) * min(1.0, progress * 3)))
    return text[:n]


# --------------------------------------------------------------------------- #
#  Position helpers
# --------------------------------------------------------------------------- #

def _compute_xy(position: str, block_w: int, block_h: int,
                frame_w: int, frame_h: int,
                margin_x: int, margin_y: int,
                custom_x: float = 0.5, custom_y: float = 0.85) -> tuple[int, int]:
    pos = position.lower()
    if pos == "custom":
        x = int(custom_x * frame_w) - block_w // 2
        y = int(custom_y * frame_h) - block_h // 2
        x = max(0, min(x, frame_w - block_w))
        y = max(0, min(y, frame_h - block_h))
        return x, y

    if "left" in pos:
        x = margin_x
    elif "right" in pos:
        x = frame_w - block_w - margin_x
    else:
        x = (frame_w - block_w) // 2

    if "top" in pos:
        y = margin_y
    elif "bottom" in pos:
        y = frame_h - block_h - margin_y
    else:
        y = (frame_h - block_h) // 2
    return x, y


def _split_grapheme_clusters(text: str) -> list[str]:
    """Split string into grapheme clusters keeping Thai combining marks attached to base consonant."""
    clusters = []
    for char in text:
        code = ord(char)
        if clusters and (0x0E31 <= code <= 0x0E3A or 0x0E47 <= code <= 0x0E4E):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


# --------------------------------------------------------------------------- #
#  Cached RGBA overlay renderer
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=128)
def _render_subtitle_rgba(
    text: str,
    font_name: str,
    font_size: int,
    font_color: str,
    bold: bool,
    italic: bool,
    decoration: str,
    decoration_color: str,
    animation: str,
    animation_step: int,   # quantized to 20 buckets (0..19)
    frame_w: int,
    frame_h: int,
    position: str,
    margin_x: int,
    margin_y: int,
    custom_x_int: int,     # stored as int (x1000)
    custom_y_int: int,
    line_spacing: int,
    letter_spacing: int,
    bg_opacity_int: int,   # stored as int (x100)
) -> np.ndarray:
    """
    Render subtitle text to an RGBA numpy array.
    Supports Thai characters, bold stroke fallback, italic slant, and custom letter spacing.
    """
    progress = animation_step / 19.0
    custom_x = custom_x_int / 1000.0
    custom_y = custom_y_int / 1000.0
    bg_opacity = bg_opacity_int / 100.0

    font = _load_pil_font_cached(font_name, font_size, bold, italic)
    text_color_rgb = _hex_to_rgb(font_color)
    deco_color_rgb = _hex_to_rgb(decoration_color)

    display_text = _typewriter_text(text, progress) if animation == "typewriter" else text
    alpha_mul = _compute_alpha(animation, progress)
    dx, dy = _compute_offset(animation, progress, frame_h)

    # Measure lines with letter spacing
    scratch = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    dummy_draw = ImageDraw.Draw(scratch)
    lines = display_text.split("\n")

    line_widths = []
    line_heights = []
    line_clusters_list = []

    for line in lines:
        clusters = _split_grapheme_clusters(line)
        line_clusters_list.append(clusters)
        if letter_spacing > 0 and len(clusters) > 1:
            w_total = 0
            max_h = 10
            for c in clusters:
                bb = dummy_draw.textbbox((0, 0), c, font=font)
                w_total += (bb[2] - bb[0]) + letter_spacing
                max_h = max(max_h, bb[3] - bb[1])
            w_total -= letter_spacing
            line_widths.append(w_total)
            line_heights.append(max_h)
        else:
            bb = dummy_draw.textbbox((0, 0), line, font=font)
            line_widths.append(bb[2] - bb[0])
            line_heights.append(max(10, bb[3] - bb[1]))

    block_w = max(line_widths) if line_widths else 1
    block_h = sum(line_heights) + line_spacing * (len(lines) - 1)

    base_x, base_y = _compute_xy(
        position, block_w, block_h, frame_w, frame_h,
        margin_x, margin_y, custom_x, custom_y
    )
    base_x += dx
    base_y += dy

    # Draw onto RGBA layer
    layer = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    pad = 12
    if decoration in ("box", "highlight"):
        box_alpha = int(bg_opacity * 255 * alpha_mul)
        box_color = (*deco_color_rgb, box_alpha)
        draw.rectangle(
            [base_x - pad, base_y - pad,
             base_x + block_w + pad, base_y + block_h + pad],
            fill=box_color,
        )

    stroke_w = max(1, int(font_size * 0.04)) if bold else 0
    cur_y = base_y

    def _draw_cluster_line(lx, y_pos, clusters, fill_col, deco_col=None, is_shadow=False, is_outline=False):
        cx_pos = lx
        for c in clusters:
            bb = dummy_draw.textbbox((0, 0), c, font=font)
            cw = bb[2] - bb[0]
            if is_shadow:
                draw.text((cx_pos + 2, y_pos + 2), c, font=font, fill=deco_col,
                          stroke_width=stroke_w if bold else 0, stroke_fill=deco_col)
            elif is_outline:
                for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
                    draw.text((cx_pos + ox, y_pos + oy), c, font=font, fill=deco_col,
                              stroke_width=stroke_w + 1 if bold else 2, stroke_fill=deco_col)
            else:
                draw.text((cx_pos, y_pos), c, font=font, fill=fill_col,
                          stroke_width=stroke_w if bold else 0, stroke_fill=fill_col)
            cx_pos += cw + letter_spacing

    for line_idx, clusters in enumerate(line_clusters_list):
        lw = line_widths[line_idx]
        lx = base_x + (block_w - lw) // 2
        line_str = lines[line_idx]

        if letter_spacing > 0:
            if decoration == "shadow":
                _draw_cluster_line(lx, cur_y, clusters, None, (*deco_color_rgb, int(200 * alpha_mul)), is_shadow=True)
            elif decoration == "outline":
                _draw_cluster_line(lx, cur_y, clusters, None, (*deco_color_rgb, int(255 * alpha_mul)), is_outline=True)

            _draw_cluster_line(lx, cur_y, clusters, (*text_color_rgb, int(255 * alpha_mul)))
        else:
            if decoration == "shadow":
                draw.text((lx + 2, cur_y + 2), line_str, font=font,
                          fill=(*deco_color_rgb, int(200 * alpha_mul)),
                          stroke_width=stroke_w if bold else 0, stroke_fill=(*deco_color_rgb, int(200 * alpha_mul)))
            elif decoration == "outline":
                for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
                    draw.text((lx + ox, cur_y + oy), line_str, font=font,
                              fill=(*deco_color_rgb, int(255 * alpha_mul)),
                              stroke_width=stroke_w + 1 if bold else 2, stroke_fill=(*deco_color_rgb, int(255 * alpha_mul)))

            draw.text((lx, cur_y), line_str, font=font,
                      fill=(*text_color_rgb, int(255 * alpha_mul)),
                      stroke_width=stroke_w if bold else 0, stroke_fill=(*text_color_rgb, int(255 * alpha_mul)))

        cur_y += line_heights[line_idx] + line_spacing

    # Synthesize Italic if requested
    if italic:
        try:
            layer = layer.transform(
                (frame_w, frame_h),
                Image.AFFINE,
                (1, 0.22, -int(frame_h * 0.05), 0, 1, 0),
                resample=Image.BICUBIC
            )
        except Exception:
            pass

    return np.array(layer, dtype=np.uint8)


def _composite_rgba_onto_bgr(bgr: np.ndarray, rgba: np.ndarray) -> np.ndarray:
    """Fast numpy alpha composite — avoids PIL round-trip overhead."""
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    overlay_rgb = rgba[:, :, :3][:, :, ::-1]   # RGBA → BGR
    bgr_f = bgr.astype(np.float32)
    result = (overlay_rgb.astype(np.float32) * a + bgr_f * (1.0 - a))
    return np.clip(result, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
#  Main draw function
# --------------------------------------------------------------------------- #

def draw_subtitles_on_frame(
    frame: np.ndarray,
    text: str,
    style: SubtitleStyle,
    progress: float = 0.5,
) -> np.ndarray:
    """
    Draw *text* onto *frame* (H×W×3 BGR numpy array) according to *style*.
    Proportionally scales font size to frame resolution relative to 1080p baseline.
    """
    if not text.strip():
        return frame

    h, w = frame.shape[:2]

    # Quantize progress to 20 steps to maximise cache hits
    anim_step = min(19, int(progress * 20))

    # Scale font size and letter spacing proportionally to frame height (1080p baseline)
    scale_factor = h / 1080.0
    scaled_font_size = max(10, int(getattr(style, "font_size", 44) * scale_factor))
    scaled_letter_spacing = max(0, int(getattr(style, "letter_spacing", 0) * scale_factor))
    scaled_margin_x = max(10, int(getattr(style, "margin_x", 40) * scale_factor))
    scaled_margin_y = max(10, int(getattr(style, "margin_y", 40) * scale_factor))
    scaled_line_spacing = max(2, int(getattr(style, "line_spacing", 8) * scale_factor))

    rgba = _render_subtitle_rgba(
        text=text,
        font_name=getattr(style, "font_name", "Tahoma"),
        font_size=scaled_font_size,
        font_color=getattr(style, "font_color", "#ffffff"),
        bold=bool(getattr(style, "bold", False)),
        italic=bool(getattr(style, "italic", False)),
        decoration=getattr(style, "decoration", "outline"),
        decoration_color=getattr(style, "decoration_color", "#000000"),
        animation=getattr(style, "animation", "none"),
        animation_step=anim_step,
        frame_w=w,
        frame_h=h,
        position=getattr(style, "position", "bottom_center"),
        margin_x=scaled_margin_x,
        margin_y=scaled_margin_y,
        custom_x_int=int(getattr(style, "custom_x", 0.5) * 1000),
        custom_y_int=int(getattr(style, "custom_y", 0.85) * 1000),
        line_spacing=scaled_line_spacing,
        letter_spacing=scaled_letter_spacing,
        bg_opacity_int=int(getattr(style, "bg_opacity", 0.5) * 100),
    )

    return _composite_rgba_onto_bgr(frame, rgba)
