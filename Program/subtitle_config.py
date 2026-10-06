"""subtitle_config.py – Subtitle style configuration + persistent custom font management"""

import os
import json
from dataclasses import dataclass, field

# ── Persistent custom font storage ────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CUSTOM_FONTS_JSON = os.path.join(_THIS_DIR, "custom_fonts.json")

def load_custom_fonts() -> list[str]:
    """Load list of user-imported font names from custom_fonts.json."""
    try:
        if os.path.exists(_CUSTOM_FONTS_JSON):
            with open(_CUSTOM_FONTS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [str(x) for x in data if x]
    except Exception:
        pass
    return []

def save_custom_fonts(font_list: list[str]):
    """Persist custom font names to custom_fonts.json."""
    try:
        with open(_CUSTOM_FONTS_JSON, "w", encoding="utf-8") as f:
            json.dump(font_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[FontSave] {e}")

def add_custom_font(font_name_or_path: str) -> str:
    """
    Register a custom font.
    - If a .ttf/.otf path is given, copy it to a local 'fonts/' subfolder
      and register the family name via tkinter's font mechanism.
    - Returns the font family name that can be used in CTkFont / canvas.
    """
    import shutil

    ext = os.path.splitext(font_name_or_path)[1].lower()
    if ext in (".ttf", ".otf", ".woff", ".woff2"):
        # Copy font file into local fonts/ directory
        fonts_dir = os.path.join(_THIS_DIR, "fonts")
        os.makedirs(fonts_dir, exist_ok=True)
        dest = os.path.join(fonts_dir, os.path.basename(font_name_or_path))
        if not os.path.exists(dest):
            shutil.copy2(font_name_or_path, dest)

        # Try to load via tkinter font (pyglet/fonttools not needed for canvas rendering)
        family = os.path.splitext(os.path.basename(font_name_or_path))[0]
        try:
            import tkinter.font as tkfont
            tkfont.Font(family=family, size=12)
        except Exception:
            pass

        # Try to load via PIL/ImageFont for OpenCV subtitle rendering
        try:
            from PIL import ImageFont
            ImageFont.truetype(dest, 12)
        except Exception:
            pass

        font_name = family
    else:
        # Plain family name string (system font)
        font_name = font_name_or_path.strip()

    if not font_name:
        return ""

    current = load_custom_fonts()
    if font_name not in current:
        current.append(font_name)
        save_custom_fonts(current)
    return font_name

def get_all_fonts() -> list[str]:
    """Return merged list: default FONT_CHOICES + user-imported custom fonts."""
    custom = load_custom_fonts()
    merged = list(FONT_CHOICES)
    for f in custom:
        if f not in merged:
            merged.append(f)
    return merged

def get_custom_font_path(font_name: str) -> str:
    """Return absolute path to .ttf/.otf file for font_name if it exists in fonts/ folder."""
    fonts_dir = os.path.join(_THIS_DIR, "fonts")
    for ext in (".ttf", ".otf", ".TTF", ".OTF"):
        p = os.path.join(fonts_dir, font_name + ext)
        if os.path.exists(p):
            return p
        # Also try with spaces replaced by underscores or original name
        for base in os.listdir(fonts_dir) if os.path.isdir(fonts_dir) else []:
            stem = os.path.splitext(base)[0]
            if stem.lower() == font_name.lower():
                return os.path.join(fonts_dir, base)
    return ""


FONT_CHOICES = [
    "Tahoma",           # รองรับ Thai ✓
    "TH Sarabun New",   # ฟอนต์ไทยราชการ ✓
    "Cordia New",       # ฟอนต์ไทย ✓
    "Angsana New",      # ฟอนต์ไทย ✓
    "Leelawadee",       # รองรับ Thai ✓
    "Arial",
    "Courier New",
    "Times New Roman",
    "Verdana",
    "Impact",
]

ANIMATION_CHOICES = [
    "none",
    "fade_in",
    "slide_up",
    "slide_down",
    "typewriter",
    "pop",
]

POSITION_CHOICES = [
    "bottom_center",
    "bottom_left",
    "bottom_right",
    "top_center",
    "top_left",
    "top_right",
    "center",
    "custom",
]

DECORATION_CHOICES = [
    "none",
    "shadow",
    "outline",
    "box",
    "highlight",
]


PRESETS = [
    {"name": "มาตรฐาน",    "font": "Tahoma", "size": 32, "color": "#ffffff", "deco": "outline", "anim": "none"},
    {"name": "ริบบอน",     "font": "Tahoma", "size": 28, "color": "#ffffff", "deco": "box",     "anim": "fade_in"},
    {"name": "หัวมอล",     "font": "Tahoma", "size": 34, "color": "#facc15", "deco": "shadow",  "anim": "none"},
    {"name": "ซีออนเขียว", "font": "Tahoma", "size": 30, "color": "#22c55e", "deco": "outline", "anim": "fade_in"},
    {"name": "ดาร์กโมด",   "font": "Tahoma", "size": 28, "color": "#f0f0f0", "deco": "box",     "anim": "slide_up"},
    {"name": "ป๊อปโซน",    "font": "Tahoma", "size": 34, "color": "#ff4444", "deco": "shadow",  "anim": "pop"},
    {"name": "พาสเทล",     "font": "Tahoma", "size": 30, "color": "#c084fc", "deco": "outline", "anim": "fade_in"},
    {"name": "คลาสสิก",    "font": "Tahoma", "size": 32, "color": "#ffd700", "deco": "outline", "anim": "none"},
]


ALIGN_CHOICES = ["left", "center", "right"]


@dataclass
class SubtitleStyle:
    font_name: str = "Tahoma"
    font_size: int = 44
    font_color: str = "#FFFFFF"
    bold: bool = False
    italic: bool = False
    decoration: str = "outline"          # none / shadow / outline / box / highlight
    decoration_color: str = "#000000"
    animation: str = "fade_in"           # see ANIMATION_CHOICES
    position: str = "bottom_center"      # see POSITION_CHOICES
    align: str = "center"                # left / center / right
    max_chars_per_line: int = 40         # max chars before word-wrap
    max_lines: int = 2                   # max lines shown at once
    margin_x: int = 40                   # horizontal margin (px)
    margin_y: int = 40                   # vertical margin from edge (px)
    custom_x: float = 0.5                # normalized x (0-1) for custom position
    custom_y: float = 0.85               # normalized y (0-1) for custom position
    line_spacing: int = 8               # extra px between lines
    letter_spacing: int = 0             # extra px between characters
    bg_opacity: float = 0.5             # used only for box / highlight decoration

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SubtitleStyle":
        if not isinstance(data, dict):
            return cls()
        inst = cls()
        for k, v in data.items():
            if hasattr(inst, k):
                # Type coerce if needed
                cur_val = getattr(inst, k)
                if isinstance(cur_val, bool):
                    setattr(inst, k, bool(v))
                elif isinstance(cur_val, int):
                    try: setattr(inst, k, int(v))
                    except (ValueError, TypeError): pass
                elif isinstance(cur_val, float):
                    try: setattr(inst, k, float(v))
                    except (ValueError, TypeError): pass
                else:
                    setattr(inst, k, str(v))
        return inst


def verify_font_for_render(font_name: str) -> tuple[bool, str]:
    """Check if font_name exists in Windows Fonts or local fonts/ folder.
    Returns (is_available: bool, effective_font_name: str).
    If missing, returns (False, 'Tahoma').
    """
    if not font_name:
        return False, "Tahoma"

    # 1. Check local fonts directory
    local_path = get_custom_font_path(font_name)
    if local_path and os.path.exists(local_path):
        return True, font_name

    # 2. Check Windows Fonts directory
    windows_fonts = "C:/Windows/Fonts"
    if os.path.isdir(windows_fonts):
        candidates = [
            font_name + ".ttf",
            font_name + ".otf",
            font_name.lower() + ".ttf",
            font_name.lower() + ".otf",
        ]
        # Common mappings
        font_map = {
            "Arial": "arial.ttf",
            "Tahoma": "tahoma.ttf",
            "TH Sarabun New": "THSarabunNew.ttf",
            "Angsana New": "angsau32.ttf",
            "Cordia New": "cordia.ttf",
            "Leelawadee": "leelawad.ttf",
            "Courier New": "cour.ttf",
            "Times New Roman": "times.ttf",
            "Verdana": "verdana.ttf",
            "Impact": "impact.ttf",
        }
        if font_name in font_map:
            candidates.insert(0, font_map[font_name])

        for c in candidates:
            if os.path.exists(os.path.join(windows_fonts, c)):
                return True, font_name

    # Fallback to Tahoma
    return False, "Tahoma"

