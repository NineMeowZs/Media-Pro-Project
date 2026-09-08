"""settings_manager.py – Persistent application settings and model directory management.
Implements PDF Sections 11, 12, 13, 14:
- Persistent Model Path storage in settings.json
- Root model folder locking & auto-discovery of contained models
- Missing directory detection with PathWarningDialog trigger
- Clean Path UI helpers (compact human-friendly representation with full path tooltip)
"""

import os
import json

_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
_DEFAULT_SETTINGS = {
    "model_folder": "",
    "default_preset": "Standard",
    "theme": "Dark",
    "auto_separate_audio": True,
}

_cache: dict = {}
_loaded = False


def _load_settings():
    global _cache, _loaded
    if _loaded:
        return
    _loaded = True
    _cache = dict(_DEFAULT_SETTINGS)

    # If default whisper directory exists locally, set it as initial fallback
    local_model = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper-small-final")
    if os.path.isdir(local_model):
        _cache["model_folder"] = local_model

    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _cache.update(data)
        except Exception as e:
            print(f"[SettingsManager] Load error: {e}")


def _save_settings():
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[SettingsManager] Save error: {e}")


def get_setting(key: str, default=None):
    _load_settings()
    return _cache.get(key, default)


def set_setting(key: str, val):
    _load_settings()
    _cache[key] = val
    _save_settings()


# ── Model Path Management (Sections 11, 12, 13, 14) ───────────────────────────

def get_model_folder() -> str:
    """Return active model root directory."""
    _load_settings()
    folder = _cache.get("model_folder", "")
    return folder


def set_model_folder(path: str) -> bool:
    """Lock and persist current model folder as active root directory."""
    if not path:
        return False
    norm = os.path.abspath(path)
    if os.path.isdir(norm):
        set_setting("model_folder", norm)
        # Also sync to last_dirs.json
        try:
            import last_dirs as _ld
            _ld.remember(_ld.WHISPER_MODEL, norm)
        except Exception:
            pass
        return True
    return False


def validate_model_folder() -> tuple[bool, str]:
    """Check if the currently stored model directory exists on filesystem.
    Returns: (is_valid: bool, current_path: str)
    """
    _load_settings()
    folder = _cache.get("model_folder", "")
    if not folder:
        return False, ""
    if os.path.isdir(folder):
        return True, folder
    return False, folder


def format_clean_path(path: str, max_chars: int = 24) -> str:
    """Format path into a clean, compact UI representation (Section 14).
    e.g. 'C:\\...\\models\\whisper-small-final' -> 'Whisper Models' or 'whisper-small-final'
    """
    if not path:
        return "Not configured"
    norm = os.path.normpath(path)
    base = os.path.basename(norm)
    if not base:
        base = norm

    # Clean name mapping
    clean_names = {
        "whisper-small-final": "Whisper Small (Local)",
        "whisper-base": "Whisper Base",
        "models": "Model Directory",
    }
    if base.lower() in clean_names:
        return clean_names[base.lower()]

    if len(base) > max_chars:
        return base[:max_chars - 1] + "…"
    return base


def discover_available_models(root_folder: str = "") -> list[dict]:
    """Scan the locked model folder and discover all valid model subdirectories (Section 13).
    Returns list of dict: [{'name': '...', 'path': '...', 'type': 'huggingface'/'pt'}, ...]
    """
    if not root_folder:
        root_folder = get_model_folder()
    if not root_folder or not os.path.isdir(root_folder):
        return []

    results = []

    # Check if root folder itself is a model
    def _is_model_dir(d):
        files = ["config.json", "pytorch_model.bin", "model.safetensors", "model.pt", "best.pt"]
        return any(os.path.exists(os.path.join(d, f)) for f in files)

    if _is_model_dir(root_folder):
        results.append({
            "name": format_clean_path(root_folder),
            "folder_name": os.path.basename(root_folder),
            "path": root_folder,
            "is_root": True
        })

    try:
        for entry in os.scandir(root_folder):
            if entry.is_dir():
                if _is_model_dir(entry.path):
                    results.append({
                        "name": format_clean_path(entry.path),
                        "folder_name": entry.name,
                        "path": entry.path,
                        "is_root": False
                    })
    except Exception as e:
        print(f"[SettingsManager] Scan models error: {e}")

    return results


class SettingsManager:
    """SettingsManager interface supporting both OOP and functional settings access."""
    def get_model_path(self) -> str:
        return get_model_folder()

    def set_model_path(self, path: str) -> bool:
        if not path:
            return False
        set_setting("model_folder", path)
        try:
            import last_dirs as _ld
            _ld.remember(_ld.WHISPER_MODEL, path)
        except Exception:
            pass
        return True

    def validate_model_folder(self, path: str = None) -> tuple[bool, str]:
        if path is not None:
            return (os.path.isdir(path), path) if path else (False, "")
        return validate_model_folder()

    def format_path_display(self, path: str, max_len: int = 24) -> str:
        return format_clean_path(path, max_chars=max_len)

    def discover_models(self, root_folder: str = "") -> list[dict]:
        return discover_available_models(root_folder)


_mgr_singleton = None

def get_settings_manager() -> SettingsManager:
    global _mgr_singleton
    if _mgr_singleton is None:
        _mgr_singleton = SettingsManager()
    return _mgr_singleton
