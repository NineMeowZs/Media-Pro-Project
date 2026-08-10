"""editor_utils.py – Design tokens, configuration variables, and helper functions for MediaPro editor"""

import customtkinter as ctk

# ── Optional subtitle modules imports to verify if HAS_SUBTITLES is active ─────
HAS_SUBTITLES = True
try:
    from subtitle_config import SubtitleStyle
except ImportError:
    HAS_SUBTITLES = False
    class SubtitleStyle:
        font_name="Arial"; font_size=32; font_color="#ffffff"
        decoration="outline"; animation="none"; position="bottom_center"
        margin_x=40; margin_y=40; custom_x=0.5; custom_y=0.85
        line_spacing=8; bg_opacity=0.5; max_chars_per_line=40; max_lines=2

# ── Design tokens (CapCut-inspired dark palette) ────────────────────────────
BG_DEEP     = "#0a0a0d"
BG_DARK     = "#0f0f14"
PANEL_DARK  = "#141418"
PANEL_MID   = "#1a1a20"
PANEL_LIGHT = "#22222a"
PANEL_HOV   = "#2c2c38"

C_BLUE      = "#2d7cf6"    # main video / primary accent
C_PURPLE    = "#9b5de5"    # overlay
C_PINK      = "#f72585"    # text clips
C_TEAL      = "#00b4d8"    # audio 1
C_GREEN     = "#06d6a0"    # audio 2
C_RED       = "#ef233c"    # playhead / delete
C_AMBER     = "#f9a826"    # warning / speed

TXT_W  = "#f0f0f5"
TXT_G  = "#5a5a6e"
TXT_L  = "#9090aa"
BORD   = "#20202a"

TL_BG      = "#0b0b0f"
TL_ROW_BG  = "#101014"
TL_RULER   = "#080810"

# ── Toolbar button groups (label, icon, command-name, color) ─────────────────
_TOOL_GROUPS = [
    [
        ("Split",     "✂",  "_split",          C_BLUE),
        ("Delete",    "🗑",  "_del_sel",         C_RED),
        ("Ripple",    "⊖",  "_ripple_delete",   C_AMBER),
    ],
    [
        ("Undo",      "↩",  "_undo_do",         TXT_L),
        ("Redo",      "↪",  "_redo_do",         TXT_L),
    ],
    [
        ("Import",    "+",  "_import",          C_GREEN),
    ],
]

BASE_TRACK_KEYS = ["main", "subtitle", "audio_0", "audio_1"]

KIND_STYLE = {
    "layer":    (C_PURPLE, 30),
    "main":     (C_BLUE,   56),
    "subtitle": (C_AMBER,  28),
    "audio":    (C_TEAL,   32),
}

RATIO_OPT  = ["16:9", "9:16", "1:1", "4:3", "2.35:1"]
TARGET_FPS = 30
RULER_H    = 22
TGAP       = 3     # gap between track rows (px)
LABEL_W    = 90
EDGE_PX    = 9
MAX_UNDO   = 60
FRAME_BUF  = 90
SNAP_PX    = 8     # pixel distance for magnetic snap
FADE_ZONE  = 8     # px from corner → fade handle

TRACK_KEYS   = BASE_TRACK_KEYS
TRACK_BY_KEY = {
    "main":     {"label": "VIDEO",    "color": C_BLUE,   "height": 56, "kind": "main"},
    "subtitle": {"label": "SUBTITLE", "color": C_AMBER,  "height": 28, "kind": "subtitle"},
    "audio_0":  {"label": "AUDIO 1",  "color": C_TEAL,   "height": 32, "kind": "audio"},
    "audio_1":  {"label": "AUDIO 2",  "color": C_GREEN,  "height": 28, "kind": "audio"},
}


def _ft(t: float) -> str:
    m = int(t // 60)
    s = int(t % 60)
    cs = int((t % 1) * 100)
    return f"{m:02}:{s:02}.{cs:02}"


def _bright(hx: str, d=40) -> str:
    try:
        r = min(255, int(hx[1:3], 16) + d)
        g = min(255, int(hx[3:5], 16) + d)
        b = min(255, int(hx[5:7], 16) + d)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hx


def _dark(hx: str, d=30) -> str:
    try:
        r = max(0, int(hx[1:3], 16) - d)
        g = max(0, int(hx[3:5], 16) - d)
        b = max(0, int(hx[5:7], 16) - d)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hx


def _nice_step(span: float) -> float:
    for s in [0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]:
        if span / s < 18:
            return s
    return 600.0
