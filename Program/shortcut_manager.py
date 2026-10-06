"""shortcut_manager.py – Shortcut preset system, custom shortcut editor, and conflict detection.
Implements PDF Sections 3, 4, 5:
- 4 Presets: Standard Video Editor, Premiere-style, CapCut-style, Custom
- Conflict Detection: alerts when key is assigned elsewhere with Replace / Cancel
- Clean Table UI with Preset dropdown and Reset to Default
- Persistent shortcut configuration in shortcuts.json
- Event matching dispatcher for Tkinter global keypresses
"""

import os
import json
import tkinter as tk
import customtkinter as ctk

from modal_system import BaseModal, ConflictDialog, ConfirmDialog

_SHORTCUTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shortcuts.json")

# Standard actions registry: (action_key, display_name, description, category)
ACTIONS_REGISTRY = [
    # Playback
    ("play_pause",       "Play / Pause",       "Toggle timeline video and audio playback", "Playback"),
    ("step_back",        "Step 1 Frame Back",  "Move playhead back by one frame (Shift=1s)", "Playback"),
    ("step_forward",     "Step 1 Frame Fwd",   "Move playhead forward by one frame (Shift=1s)", "Playback"),

    # Timeline navigation
    ("selection_tool",   "Selection Tool",     "Activate normal clip selection and move tool", "Timeline navigation"),
    ("split_tool",       "Split Tool",         "Quick split tool shortcut", "Timeline navigation"),

    # Clip editing
    ("split",            "Split Clip",         "Cut selected clip at playhead position", "Clip editing"),
    ("delete",           "Delete Clip",        "Delete selected clip(s) from timeline", "Clip editing"),
    ("ripple_delete",    "Ripple Delete",      "Delete selected clip and pull following clips left", "Clip editing"),
    ("mute",             "Mute Track / Clip",  "Toggle mute status on active track or clip", "Clip editing"),

    # Selection
    ("select_all",       "Select All",         "Select all clips on the active timeline", "Selection"),

    # Undo and redo
    ("undo",             "Undo",               "Revert previous timeline or property action", "Undo and redo"),
    ("redo",             "Redo",               "Reapply previously undone action", "Undo and redo"),

    # Media management
    ("import_media",     "Import Media",       "Import video, audio, or image asset", "Media management"),
    ("export_video",     "Export Video",       "Open video export render dialog", "Media management"),
    ("open_project",     "Open Project",       "Open existing project JSON file", "Media management"),
    ("save",             "Save Project",       "Save current project to file", "Media management"),
    ("save_as",          "Save Project As",    "Save project with new filename", "Media management"),

    # Application settings
    ("open_settings",    "Open Settings",      "Open application settings and shortcuts", "Application settings"),
]

# Presets according to PDF Sections 3 & 4
PRESET_STANDARD = {
    "play_pause":     "Space",
    "split":          "Ctrl+B",
    "delete":         "Delete",
    "ripple_delete":  "G",
    "undo":           "Ctrl+Z",
    "redo":           "Ctrl+Shift+Z",
    "mute":           "M",
    "selection_tool": "V",
    "split_tool":     "S",
    "step_back":      "Left",
    "step_forward":   "Right",
    "select_all":     "Ctrl+A",
    "save":           "Ctrl+S",
    "save_as":        "Ctrl+Shift+S",
    "open_project":   "Ctrl+O",
    "import_media":   "Ctrl+I",
    "export_video":   "Ctrl+E",
    "open_settings":  "Ctrl+,",
}

PRESET_PREMIERE = {
    "play_pause":     "Space",
    "split":          "Ctrl+K",
    "delete":         "Delete",
    "ripple_delete":  "Shift+Delete",
    "undo":           "Ctrl+Z",
    "redo":           "Ctrl+Shift+Z",
    "mute":           "Shift+M",
    "selection_tool": "V",
    "split_tool":     "C",
    "step_back":      "Left",
    "step_forward":   "Right",
    "select_all":     "Ctrl+A",
    "save":           "Ctrl+S",
    "save_as":        "Ctrl+Shift+S",
    "open_project":   "Ctrl+O",
    "import_media":   "Ctrl+I",
    "export_video":   "Ctrl+M",
    "open_settings":  "Ctrl+Alt+K",
}

PRESET_CAPCUT = {
    "play_pause":     "Space",
    "split":          "Ctrl+B",
    "delete":         "Delete",
    "ripple_delete":  "Shift+Backspace",
    "undo":           "Ctrl+Z",
    "redo":           "Ctrl+Shift+Z",
    "mute":           "M",
    "selection_tool": "V",
    "split_tool":     "B",
    "step_back":      "Left",
    "step_forward":   "Right",
    "select_all":     "Ctrl+A",
    "save":           "Ctrl+S",
    "save_as":        "Ctrl+Shift+S",
    "open_project":   "Ctrl+O",
    "import_media":   "Ctrl+I",
    "export_video":   "Ctrl+E",
    "open_settings":  "Ctrl+,",
}

PRESET_DICT = {
    "Standard": PRESET_STANDARD,
    "Premiere": PRESET_PREMIERE,
    "CapCut":   PRESET_CAPCUT,
}



class ShortcutManager:
    """Manages active shortcut mappings, presets, conflict detection, and key dispatch."""

    def __init__(self):
        self.active_preset = "Standard"
        self.custom_shortcuts = dict(PRESET_STANDARD)
        self.shortcuts = dict(PRESET_STANDARD)
        self._load()

    def _load(self):
        if os.path.exists(_SHORTCUTS_FILE):
            try:
                with open(_SHORTCUTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.active_preset = data.get("active_preset", "Standard")
                    self.custom_shortcuts = data.get("custom_shortcuts", dict(PRESET_STANDARD))
                    if self.active_preset == "Custom":
                        self.shortcuts = dict(self.custom_shortcuts)
                    elif self.active_preset in PRESET_DICT:
                        self.shortcuts = dict(PRESET_DICT[self.active_preset])
                    return
            except Exception as e:
                print(f"[ShortcutManager] Load error: {e}")
        self.apply_preset("Standard")

    def _save(self):
        try:
            with open(_SHORTCUTS_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "active_preset": self.active_preset,
                    "custom_shortcuts": self.custom_shortcuts,
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ShortcutManager] Save error: {e}")

    def apply_preset(self, preset_name: str):
        if preset_name in PRESET_DICT:
            self.active_preset = preset_name
            self.shortcuts = dict(PRESET_DICT[preset_name])
        elif preset_name == "Custom":
            self.active_preset = "Custom"
            self.shortcuts = dict(self.custom_shortcuts)
        self._save()

    def get_shortcut(self, action_key: str) -> str:
        return self.shortcuts.get(action_key, "")

    def check_conflict(self, action_key: str, new_shortcut: str) -> tuple[bool, str]:
        """Check if new_shortcut is already used by another action.
        Returns: (has_conflict, existing_action_key)
        """
        norm_new = self._normalize_shortcut_str(new_shortcut)
        for act, sc in self.shortcuts.items():
            if act != action_key and self._normalize_shortcut_str(sc) == norm_new:
                return True, act
        return False, ""

    def assign_shortcut(self, action_key: str, new_shortcut: str):
        """Set shortcut for an action and switch active preset to Custom."""
        self.custom_shortcuts[action_key] = new_shortcut
        self.shortcuts[action_key] = new_shortcut
        self.active_preset = "Custom"
        self._save()

    def reset_shortcut(self, action_key: str):
        """Reset a single shortcut to its default in active preset (or Standard)."""
        preset = PRESET_DICT.get(self.active_preset, PRESET_STANDARD)
        default_val = preset.get(action_key, PRESET_STANDARD.get(action_key, ""))
        self.shortcuts[action_key] = default_val
        self.custom_shortcuts[action_key] = default_val
        self._save()

    def reset_to_default(self):
        """Reset all shortcuts to Standard Preset."""
        self.active_preset = "Standard"
        self.shortcuts = dict(PRESET_STANDARD)
        self.custom_shortcuts = dict(PRESET_STANDARD)
        self._save()

    def _normalize_shortcut_str(self, sc: str) -> str:
        parts = [p.strip().title() for p in sc.split("+") if p.strip()]
        order = {"Ctrl": 1, "Control": 1, "Alt": 2, "Shift": 3}
        parts.sort(key=lambda x: order.get(x, 99))
        return "+".join(parts)

    def match_event(self, event) -> str:
        """Parse Tkinter KeyPress event and return matched action key, or ''."""
        keysym = event.keysym
        keycode = getattr(event, "keycode", 0)
        state = event.state

        # Modifiers
        ctrl = bool(state & 4)
        shift = bool(state & 1)
        import sys
        if sys.platform.startswith("win"):
            # On Windows Tkinter, bit 8 (0x8) is NumLock. Do NOT treat 0x8 as Alt!
            alt = bool(state & 0x20000) or bool(state & 0x40000)
        else:
            alt = bool(state & 8) or bool(state & 0x20000)

        # Build human key string
        mods = []
        if ctrl:
            mods.append("Ctrl")
        if alt:
            mods.append("Alt")
        if shift:
            mods.append("Shift")

        # Key symbol mapping
        key_name = keysym
        if keysym.lower() in ("control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r"):
            return ""  # Lone modifier press

        # Normalize special keys
        special_map = {
            "space": "Space",
            "backspace": "Backspace",
            "delete": "Delete",
            "prior": "PageUp",
            "next": "PageDown",
            "escape": "Escape",
            "return": "Enter",
            "left": "Left",
            "right": "Right",
            "up": "Up",
            "down": "Down",
        }
        if keysym.lower() in special_map:
            key_name = special_map[keysym.lower()]
        elif len(keysym) == 1:
            key_name = keysym.upper()

        if mods:
            event_combo = "+".join(mods + [key_name])
        else:
            event_combo = key_name

        norm_event = self._normalize_shortcut_str(event_combo)

        for act, sc in self.shortcuts.items():
            if self._normalize_shortcut_str(sc) == norm_event:
                return act

        # Fallback aliases (e.g. Delete vs Backspace, Ctrl+Y vs Ctrl+Shift+Z)
        if norm_event == "Backspace" and self._normalize_shortcut_str(self.shortcuts.get("delete", "")) == "Delete":
            return "delete"
        if norm_event == "Ctrl+Y" and self._normalize_shortcut_str(self.shortcuts.get("redo", "")) == "Ctrl+Shift+Z":
            return "redo"
        if norm_event == "S" and self.active_preset == "Standard" and self.shortcuts.get("split_tool") == "S":
            return "split"

        return ""


# Global singleton instance
shortcut_mgr = ShortcutManager()

def get_shortcut_manager() -> ShortcutManager:
    return shortcut_mgr


# ═════════════════════════════════════════════════════════════════════════════
# Shortcut Settings Dialog (UX Section 5)
# ═════════════════════════════════════════════════════════════════════════════

class ShortcutSettingsDialog(BaseModal):
    """Settings Modal Dialog with Tabs for Keyboard Shortcuts and General & Model Folder."""

    def __init__(self, parent, on_change_callback=None, initial_tab="shortcuts"):
        super().__init__(
            parent,
            title="Application Settings",
            subtitle="Configure keyboard shortcuts, presets, and AI model directory",
            width=640, height=680
        )
        self._on_change_callback = on_change_callback
        self._editing_action = None
        self._active_tab = initial_tab
        self._search_text = ""
        self._build_dialog()

    def _build_dialog(self):
        # Clear existing content
        for w in self.content.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()

        # ── Navigation Tabs ───────────────────────────────────────────────────
        nav_row = ctk.CTkFrame(self.content, height=36, fg_color="#10141a", corner_radius=8)
        nav_row.pack(fill="x", pady=(0, 10), padx=2)
        nav_row.pack_propagate(False)

        def _switch_tab(tab_name):
            self._active_tab = tab_name
            self._build_dialog()

        is_sc = (self._active_tab == "shortcuts")
        sc_btn = ctk.CTkButton(
            nav_row, text="⌨ Keyboard Shortcuts", height=28, corner_radius=6,
            fg_color="#3b82f6" if is_sc else "transparent",
            hover_color="#2563eb" if is_sc else "#21262d",
            text_color="#ffffff" if is_sc else "#8b949e",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=lambda: _switch_tab("shortcuts")
        )
        sc_btn.pack(side="left", padx=4, pady=4)

        is_gen = (self._active_tab == "general")
        gen_btn = ctk.CTkButton(
            nav_row, text="⚙ AI Models & Folders", height=28, corner_radius=6,
            fg_color="#3b82f6" if is_gen else "transparent",
            hover_color="#2563eb" if is_gen else "#21262d",
            text_color="#ffffff" if is_gen else "#8b949e",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=lambda: _switch_tab("general")
        )
        gen_btn.pack(side="left", padx=4, pady=4)

        if self._active_tab == "shortcuts":
            self._render_shortcuts_tab()
        else:
            self._render_general_tab()

        self.add_footer_button("Done", command=self.close, style="primary", width=90)

    def _render_shortcuts_tab(self):
        # ── Presets & Reset Row ───────────────────────────────────────────────
        top_frame = ctk.CTkFrame(self.content, fg_color="#10141a", corner_radius=8)
        top_frame.pack(fill="x", pady=(0, 8), padx=2)

        ctk.CTkLabel(
            top_frame, text="Preset:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#f0f6fc"
        ).pack(side="left", padx=10, pady=8)

        presets = ["Standard", "Premiere", "CapCut", "Custom"]
        self._preset_var = tk.StringVar(value=shortcut_mgr.active_preset)

        def _on_preset_select(choice):
            shortcut_mgr.apply_preset(choice)
            self._render_shortcuts_tab_body()
            if self._on_change_callback:
                self._on_change_callback()

        preset_menu = ctk.CTkOptionMenu(
            top_frame, values=presets, variable=self._preset_var,
            width=120, height=28, corner_radius=6,
            fg_color="#21262d", button_color="#30363d",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=_on_preset_select
        )
        preset_menu.pack(side="left", padx=(0, 8), pady=8)

        def _on_reset():
            ConfirmDialog(
                self.top_container,
                title="Reset Shortcuts",
                message=f"Reset all shortcuts to the '{shortcut_mgr.active_preset}' preset defaults?",
                confirm_text="Reset All",
                on_confirm=lambda: (
                    shortcut_mgr.reset_to_default(),
                    self._build_dialog(),
                    self._on_change_callback() if self._on_change_callback else None
                )
            )

        reset_btn = ctk.CTkButton(
            top_frame, text="🔄 Reset All", width=100, height=28, corner_radius=6,
            fg_color="#21262d", hover_color="#30363d", text_color="#f0f6fc",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=_on_reset
        )
        reset_btn.pack(side="right", padx=10, pady=8)

        # ── Search Input Box ──────────────────────────────────────────────────
        search_frame = ctk.CTkFrame(self.content, fg_color="#10141a", corner_radius=8)
        search_frame.pack(fill="x", pady=(0, 8), padx=2)

        ctk.CTkLabel(
            search_frame, text="🔍", font=ctk.CTkFont(size=11), text_color="#8b949e"
        ).pack(side="left", padx=(10, 4))

        search_ent = ctk.CTkEntry(
            search_frame, height=28, corner_radius=6,
            fg_color="#161b22", border_color="#30363d",
            placeholder_text="Search shortcuts (e.g. Split, Play, Delete, Undo)…",
            font=ctk.CTkFont(family="Segoe UI", size=10)
        )
        search_ent.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=4)
        if self._search_text:
            search_ent.insert(0, self._search_text)

        def _on_search(*args):
            self._search_text = search_ent.get().strip().lower()
            self._render_shortcuts_tab_body()

        search_ent.bind("<KeyRelease>", _on_search)

        # Container for the dynamic list
        self._table_container = ctk.CTkFrame(self.content, fg_color="transparent")
        self._table_container.pack(fill="both", expand=True, padx=2)
        self._render_shortcuts_tab_body()

    def _render_shortcuts_tab_body(self):
        for w in self._table_container.winfo_children():
            w.destroy()

        # Group by category
        filtered = []
        for act_tuple in ACTIONS_REGISTRY:
            act_key, act_name, desc = act_tuple[0], act_tuple[1], act_tuple[2]
            cat = act_tuple[3] if len(act_tuple) > 3 else "General"
            if self._search_text:
                if self._search_text not in act_name.lower() and self._search_text not in desc.lower() and self._search_text not in act_key.lower():
                    continue
            filtered.append((act_key, act_name, desc, cat))

        if not filtered:
            ctk.CTkLabel(
                self._table_container, text="No shortcuts matching your search.",
                text_color="#8b949e", font=ctk.CTkFont(size=11)
            ).pack(pady=30)
            return

        current_cat = None
        cat_colors = {
            "Playback": "#38bdf8",
            "Timeline navigation": "#a855f7",
            "Clip editing": "#f59e0b",
            "Selection": "#10b981",
            "Undo and redo": "#6366f1",
            "Media management": "#ec4899",
            "Application settings": "#64748b",
        }

        for idx, (act_key, act_name, desc, cat) in enumerate(filtered):
            if cat != current_cat:
                current_cat = cat
                cat_hdr = ctk.CTkFrame(self._table_container, height=24, fg_color="#161b22", corner_radius=5)
                cat_hdr.pack(fill="x", pady=(8, 3))
                cat_hdr.pack_propagate(False)
                pill_col = cat_colors.get(cat, "#8b949e")
                ctk.CTkLabel(
                    cat_hdr, text=f"●  {cat.upper()}",
                    font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                    text_color=pill_col
                ).pack(side="left", padx=10)

            sc_val = shortcut_mgr.get_shortcut(act_key)
            row_bg = "#10141a" if idx % 2 == 0 else "#141922"

            row = ctk.CTkFrame(self._table_container, height=36, fg_color=row_bg, corner_radius=6)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            # Left: action title
            title_fr = ctk.CTkFrame(row, fg_color="transparent")
            title_fr.pack(side="left", padx=10, fill="y")
            lbl = ctk.CTkLabel(
                title_fr, text=act_name,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                text_color="#e6edf3", anchor="w"
            )
            lbl.pack(anchor="w")

            # Right controls: Reset single, Edit, Key Badge
            r_fr = ctk.CTkFrame(row, fg_color="transparent")
            r_fr.pack(side="right", padx=6)

            # Reset single shortcut button (↺)
            def _reset_single(k=act_key):
                shortcut_mgr.reset_shortcut(k)
                self._render_shortcuts_tab_body()
                if self._on_change_callback:
                    self._on_change_callback()

            rst_single = ctk.CTkButton(
                r_fr, text="↺", width=24, height=24, corner_radius=5,
                fg_color="#1c2128", hover_color="#30363d", text_color="#8b949e",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=_reset_single
            )
            rst_single.pack(side="right", padx=(4, 0))

            # Edit button
            edit_btn = ctk.CTkButton(
                r_fr, text="Edit", width=46, height=24, corner_radius=5,
                fg_color="#21262d", hover_color="#30363d",
                text_color="#58a6ff", font=ctk.CTkFont(size=9, weight="bold"),
                command=lambda a=act_key, n=act_name: self._start_capture(a, n)
            )
            edit_btn.pack(side="right", padx=(6, 0))

            # Shortcut key badge
            badge_frame = ctk.CTkFrame(r_fr, fg_color="#1c2128", corner_radius=5, border_width=1, border_color="#30363d")
            badge_frame.pack(side="right")
            ctk.CTkLabel(
                badge_frame, text=sc_val or "None",
                font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                text_color="#58a6ff" if sc_val else "#484f58"
            ).pack(padx=8, pady=2)

    def _render_general_tab(self):
        import settings_manager as _sm
        import last_dirs as _ld

        panel = ctk.CTkFrame(self.content, fg_color="transparent")
        panel.pack(fill="both", expand=True, padx=4, pady=4)

        # ── AI Model Folder Section (Requirement F) ───────────────────────────
        m_box = ctk.CTkFrame(panel, fg_color="#10141a", corner_radius=10, border_width=1, border_color="#30363d")
        m_box.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            m_box, text="🤖 AI Whisper Model Directory",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#f0f6fc"
        ).pack(anchor="w", padx=14, pady=(12, 4))

        curr_folder = _sm.get_model_folder()
        is_valid = bool(curr_folder and os.path.isdir(curr_folder))

        stat_fr = ctk.CTkFrame(m_box, fg_color="transparent")
        stat_fr.pack(fill="x", padx=14, pady=(0, 6))

        stat_text = "🟢 Active & Verified" if is_valid else "🔴 Directory Not Found"
        stat_col = "#22c55e" if is_valid else "#ef4444"
        ctk.CTkLabel(
            stat_fr, text=stat_text,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=stat_col
        ).pack(side="left")

        clean_name = _sm.format_clean_path(curr_folder)
        ctk.CTkLabel(
            stat_fr, text=f"({clean_name})",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#8b949e"
        ).pack(side="left", padx=6)

        path_disp = ctk.CTkFrame(m_box, fg_color="#161b22", corner_radius=6, border_width=1, border_color="#30363d")
        path_disp.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            path_disp, text=curr_folder or "No model folder configured",
            font=ctk.CTkFont(family="Consolas", size=9),
            text_color="#c9d1d9" if is_valid else "#8b949e",
            wraplength=480, justify="left"
        ).pack(side="left", padx=10, pady=8)

        def _locate_model_folder():
            from tkinter import filedialog as _fd
            folder = _fd.askdirectory(
                title="Select Whisper Model Directory",
                initialdir=curr_folder if is_valid else _ld.get(_ld.WHISPER_MODEL)
            )
            if folder:
                _sm.set_model_folder(folder)
                self._build_dialog()
                if self._on_change_callback:
                    self._on_change_callback()

        btn_row = ctk.CTkFrame(m_box, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkButton(
            btn_row, text="📁 Locate / Change Model Folder",
            height=30, corner_radius=6,
            fg_color="#21262d", hover_color="#30363d", text_color="#58a6ff",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=_locate_model_folder
        ).pack(side="left")

        # Discovered Models in current folder
        models = _sm.discover_available_models(curr_folder)
        if models:
            d_box = ctk.CTkFrame(m_box, fg_color="#161b22", corner_radius=6)
            d_box.pack(fill="x", padx=14, pady=(0, 12))
            ctk.CTkLabel(
                d_box, text=f"Discovered Model Components ({len(models)}):",
                font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                text_color="#8b949e"
            ).pack(anchor="w", padx=8, pady=(6, 2))
            for m in models[:4]:
                ctk.CTkLabel(
                    d_box, text=f"  ✓ {m.get('folder_name', m.get('name'))}",
                    font=ctk.CTkFont(family="Consolas", size=8),
                    text_color="#38bdf8"
                ).pack(anchor="w", padx=8)

        # ── Audio Track Separation Setting (Requirement C) ────────────────────
        s_box = ctk.CTkFrame(panel, fg_color="#10141a", corner_radius=10, border_width=1, border_color="#30363d")
        s_box.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            s_box, text="🎬 Media Import & Timeline Tracks",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#f0f6fc"
        ).pack(anchor="w", padx=14, pady=(12, 4))

        auto_sep_v = tk.BooleanVar(value=_sm.get_setting("auto_separate_audio", True))

        def _on_sep_toggle():
            _sm.set_setting("auto_separate_audio", auto_sep_v.get())

        ctk.CTkCheckBox(
            s_box,
            text="Automatically separate video and audio into linked tracks (V1 & A1) on import",
            variable=auto_sep_v,
            command=_on_sep_toggle,
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#e6edf3"
        ).pack(anchor="w", padx=14, pady=(4, 12))

    def _start_capture(self, act_key: str, act_name: str):
        """Show non-draggable modal to capture new key combination with conflict detection."""
        cap_modal = BaseModal(
            self.top_container,
            title="Press New Shortcut",
            subtitle=f"Assign shortcut for: {act_name}",
            width=420, height=240
        )

        body = ctk.CTkFrame(cap_modal.content, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=12)

        ctk.CTkLabel(
            body,
            text="Press any key combination on your keyboard…",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#8b949e"
        ).pack(pady=(0, 10))

        key_display = ctk.CTkLabel(
            body, text="[ Waiting for Key… ]",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            text_color="#58a6ff"
        )
        key_display.pack(pady=10)

        captured = {"key": None}

        def _on_key(e):
            keysym = e.keysym
            if keysym.lower() in ("control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r"):
                return  # Skip single modifier

            ctrl = bool(e.state & 4)
            shift = bool(e.state & 1)
            import sys
            if sys.platform.startswith("win"):
                alt = bool(e.state & 0x20000) or bool(e.state & 0x40000)
            else:
                alt = bool(e.state & 8) or bool(e.state & 0x20000)

            mods = []
            if ctrl: mods.append("Ctrl")
            if alt:  mods.append("Alt")
            if shift: mods.append("Shift")

            special_map = {"space": "Space", "backspace": "Backspace", "delete": "Delete",
                           "left": "Left", "right": "Right", "up": "Up", "down": "Down", "comma": ","}
            key_name = special_map.get(keysym.lower(), keysym.upper() if len(keysym) == 1 else keysym)

            combo = "+".join(mods + [key_name]) if mods else key_name
            captured["key"] = combo
            key_display.configure(text=f"[  {combo}  ]")
            return "break"

        cap_modal.top_container.bind("<KeyPress>", _on_key, add="+")

        def _save_captured():
            cap_modal.top_container.unbind("<KeyPress>")
            cap_modal.close()
            new_key = captured.get("key")
            if not new_key:
                return

            has_conflict, existing_act = shortcut_mgr.check_conflict(act_key, new_key)
            if has_conflict:
                _name_map = {k: name for k, name, _, _ in ACTIONS_REGISTRY}
                existing_name = _name_map.get(existing_act, existing_act)
                ConflictDialog(
                    self.top_container,
                    key_str=new_key,
                    existing_action=existing_name,
                    new_action=act_name,
                    on_replace=lambda: self._apply_reassign(act_key, new_key, existing_act)
                )
            else:
                shortcut_mgr.assign_shortcut(act_key, new_key)
                self._build_dialog()
                if self._on_change_callback:
                    self._on_change_callback()

        cap_modal.add_footer_button("Apply", command=_save_captured, style="primary", width=90)
        cap_modal.add_footer_button("Cancel", command=lambda: (cap_modal.top_container.unbind("<KeyPress>"), cap_modal.close()), style="secondary", width=80)

    def _apply_reassign(self, act_key: str, new_key: str, conflicting_act: str):
        """Clear the old assignment and assign new key."""
        shortcut_mgr.shortcuts[conflicting_act] = ""
        shortcut_mgr.custom_shortcuts[conflicting_act] = ""
        shortcut_mgr.assign_shortcut(act_key, new_key)
        self._build_dialog()
        if self._on_change_callback:
            self._on_change_callback()

