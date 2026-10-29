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
        align="center"
        margin_x=40; margin_y=40; custom_x=0.5; custom_y=0.85
        line_spacing=8; bg_opacity=0.5; max_chars_per_line=40; max_lines=2

# ── Design tokens (60-30-10 Rule & WCAG AA Accessible Palette) ───────────────
# 60% Dominant (Canvas / Panels)
BG_DEEP     = "#0d1117"     # Deep canvas background
BG_DARK     = "#12161f"     # Editor frame background
PANEL_DARK  = "#161b22"     # Base panels & header
PANEL_MID   = "#1c2128"     # Cards, list rows, inactive tabs
PANEL_LIGHT = "#252d38"     # Elevated cards, secondary buttons
PANEL_HOV   = "#303a48"     # Interactive hover states

# 30% Structural (Borders & Readability Text)
TXT_W  = "#f8fafc"          # Primary text (high contrast, crisp readability)
TXT_L  = "#94a3b8"          # Secondary body text
TXT_G  = "#64748b"          # Muted helper labels, shortcuts
BORD   = "#30363d"          # Clean structural border

TL_BG      = "#0a0e14"      # Timeline canvas deep
TL_ROW_BG  = "#111620"      # Track lanes background
TL_RULER   = "#0d1117"      # Ruler background

# 10% High-Contrast Semantic Accents
C_BLUE      = "#3b82f6"     # Main video clip & primary action
C_PURPLE    = "#8b5cf6"     # AI Auto-edit & overlay layers
C_PINK      = "#f43f5e"     # Text & graphic clips
C_TEAL      = "#06b6d4"     # Audio 1 track
C_GREEN     = "#10b981"     # Audio 2 track & import
C_RED       = "#ef4444"     # Delete & playhead
C_AMBER     = "#f59e0b"     # Subtitles & ripple cut

# ── Toolbar button groups with Recognition-over-Recall Hotkey Badges ──────────
_TOOL_GROUPS = [
    [
        ("Split (S)",     "✂",  "_split",          C_BLUE),
        ("Delete (Del)",  "🗑",  "_del_sel",         C_RED),
        ("Ripple (G)",    "⊖",  "_ripple_delete",   C_AMBER),
    ],
    [
        ("Undo (Ctrl+Z)", "↩",  "_undo_do",         TXT_L),
        ("Redo (Ctrl+Y)", "↪",  "_redo_do",         TXT_L),
    ],
    [
        ("Import (+)",    "+",  "_import",          C_GREEN),
    ],
]

BASE_TRACK_KEYS = ["main", "subtitle", "audio_0", "audio_1"]

KIND_STYLE = {
    "layer":    (C_PURPLE, 30),
    "main":     (C_BLUE,   56),
    "subtitle": (C_AMBER,  28),
    "audio":    (C_TEAL,   32),
}

RATIO_OPT  = ["16:9", "9:16", "1:1", "4:3", "3:4", "2.35:1"]
TARGET_FPS = 30
RULER_H    = 22
TGAP       = 3     # gap between track rows (px)
LABEL_W    = 125
EDGE_PX    = 9
MAX_UNDO   = 60
FRAME_BUF  = 45
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


def _ft_ms(t: float) -> str:
    """Format seconds into mm:ss.mmm with millisecond precision."""
    if t < 0: t = 0.0
    m = int(t // 60)
    s = int(t % 60)
    ms = int(round((t % 1) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
        if s >= 60:
            m += 1
            s = 0
    return f"{m:02d}:{s:02d}.{ms:03d}"


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
