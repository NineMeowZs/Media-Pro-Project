"""last_dirs.py — Persistent memory for last-used directories per function key."""

import os
import json

_LAST_DIRS_FILE = os.path.join(os.path.dirname(__file__), "last_dirs.json")
_cache: dict = {}
_loaded = False


def _load():
    global _cache, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if os.path.exists(_LAST_DIRS_FILE):
            with open(_LAST_DIRS_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
    except Exception:
        _cache = {}


def _save():
    try:
        with open(_LAST_DIRS_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[last_dirs] save error: {e}")


def get(key: str, fallback: str = "") -> str:
    """Return the last-used directory for this key, or fallback if not set."""
    _load()
    d = _cache.get(key, fallback)
    # Verify still exists, otherwise return fallback
    if d and os.path.isdir(d):
        return d
    return fallback


def remember(key: str, path: str):
    """Store the directory of 'path' (file) or 'path' itself (dir) for this key."""
    _load()
    if os.path.isfile(path):
        d = os.path.dirname(path)
    elif os.path.isdir(path):
        d = path
    else:
        return
    _cache[key] = d
    _save()


# Convenience constants for key names
IMPORT_MEDIA   = "import_media"
IMPORT_AUDIO   = "import_audio"
SAVE_PROJECT   = "save_project"
OPEN_PROJECT   = "open_project"
EXPORT_VIDEO   = "export_video"
WHISPER_MODEL  = "whisper_model"
BROWSE_PROJECT = "browse_project"
