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

# Standard actions registry: (action_key, display_name, description)
ACTIONS_REGISTRY = [
    ("play_pause",       "Play / Pause",       "Toggle timeline video and audio playback"),
    ("split",            "Split Clip",         "Cut selected clip at playhead position"),
    ("delete",           "Delete",             "Delete selected clip(s) from timeline"),
    ("ripple_delete",    "Ripple Delete",      "Delete selected clip and pull following clips left"),
    ("undo",             "Undo",               "Revert previous timeline or property action"),
    ("redo",             "Redo",               "Reapply previously undone action"),
    ("mute",             "Mute Track / Clip",  "Toggle mute status on active track or clip"),
    ("selection_tool",   "Selection Tool",     "Activate normal clip selection and move tool"),
    ("split_tool",       "Split Tool",         "Quick split tool shortcut"),
    ("step_back",        "Step 1 Frame Back",  "Move playhead back by one frame (Shift=1s)"),
    ("step_forward",     "Step 1 Frame Fwd",   "Move playhead forward by one frame (Shift=1s)"),
    ("save",             "Save Project",       "Save current project to file"),
    ("save_as",          "Save Project As",    "Save project with new filename"),
    ("open_project",     "Open Project",       "Open existing project JSON file"),
    ("import_media",     "Import Media",       "Import video, audio, or image asset"),
    ("export_video",     "Export Video",       "Open video export render dialog"),
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
    "save":           "Ctrl+S",
    "save_as":        "Ctrl+Shift+S",
    "open_project":   "Ctrl+O",
    "import_media":   "Ctrl+I",
    "export_video":   "Ctrl+E",
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
    "save":           "Ctrl+S",
    "save_as":        "Ctrl+Shift+S",
    "open_project":   "Ctrl+O",
    "import_media":   "Ctrl+I",
    "export_video":   "Ctrl+M",
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
    "save":           "Ctrl+S",
    "save_as":        "Ctrl+Shift+S",
    "open_project":   "Ctrl+O",
    "import_media":   "Ctrl+I",
    "export_video":   "Ctrl+E",
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
    """Shortcut Settings Modal Dialog with table layout, Preset dropdown,
    inline key editor, conflict detection, and reset to default button.
    """

    def __init__(self, parent, on_change_callback=None):
        super().__init__(
            parent,
            title="Keyboard Shortcuts",
            subtitle="Configure action shortcuts and presets",
            width=580, height=640
        )
        self._on_change_callback = on_change_callback
        self._editing_action = None
        self._build_table()

    def _build_table(self):
        # Clear existing content
        for w in self.content.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()

        # ── Top Bar: Preset Dropdown ───────────────────────────────────────────
        top_frame = ctk.CTkFrame(self.content, fg_color="#10141a", corner_radius=8)
        top_frame.pack(fill="x", pady=(0, 10), padx=2)

        ctk.CTkLabel(
            top_frame, text="Shortcut Preset:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#f0f6fc"
        ).pack(side="left", padx=12, pady=10)

        presets = ["Standard", "Premiere", "CapCut", "Custom"]
        self._preset_var = tk.StringVar(value=shortcut_mgr.active_preset)

        def _on_preset_select(choice):
            shortcut_mgr.apply_preset(choice)
            self._build_table()
            if self._on_change_callback:
                self._on_change_callback()

        def _on_reset():
            ConfirmDialog(
                self.top_container,
                title="Reset Shortcuts",
                message="Are you sure you want to reset all shortcuts to Standard defaults?",
                confirm_text="Reset to Default",
                on_confirm=lambda: (
                    shortcut_mgr.reset_to_default(),
                    self._build_table(),
                    self._on_change_callback() if self._on_change_callback else None
                )
            )

        preset_menu = ctk.CTkOptionMenu(
            top_frame, values=presets, variable=self._preset_var,
            width=130, height=30, corner_radius=6,
            fg_color="#21262d", button_color="#30363d",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=_on_preset_select
        )
        preset_menu.pack(side="right", padx=12, pady=10)

        reset_btn = ctk.CTkButton(
            top_frame, text="🔄 Reset to Default", width=130, height=30, corner_radius=6,
            fg_color="#21262d", hover_color="#30363d", text_color="#f0f6fc",
            border_width=1, border_color="#30363d",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=_on_reset
        )
        reset_btn.pack(side="right", padx=(0, 4), pady=10)

        # ── Table Header ───────────────────────────────────────────────────────
        tbl_hdr = ctk.CTkFrame(self.content, height=28, fg_color="#1c2128", corner_radius=6)
        tbl_hdr.pack(fill="x", padx=2, pady=(0, 4))
        tbl_hdr.pack_propagate(False)

        ctk.CTkLabel(
            tbl_hdr, text="Action",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#8b949e", anchor="w"
        ).pack(side="left", padx=14)

        ctk.CTkLabel(
            tbl_hdr, text="Edit",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#8b949e", anchor="e"
        ).pack(side="right", padx=24)

        ctk.CTkLabel(
            tbl_hdr, text="Shortcut",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#8b949e", anchor="e"
        ).pack(side="right", padx=30)

        # ── Table Rows ─────────────────────────────────────────────────────────
        rows_container = ctk.CTkFrame(self.content, fg_color="transparent")
        rows_container.pack(fill="both", expand=True, padx=2)

        for idx, (act_key, act_name, desc) in enumerate(ACTIONS_REGISTRY):
            sc_val = shortcut_mgr.get_shortcut(act_key)
            row_bg = "#12171f" if idx % 2 == 0 else "#161b22"

            row = ctk.CTkFrame(rows_container, height=36, fg_color=row_bg, corner_radius=6)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            # Action name
            ctk.CTkLabel(
                row, text=act_name,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color="#e6edf3", anchor="w"
            ).pack(side="left", padx=14)

            # Edit button
            edit_btn = ctk.CTkButton(
                row, text="Edit", width=54, height=24, corner_radius=6,
                fg_color="#21262d", hover_color="#30363d",
                text_color="#58a6ff", font=ctk.CTkFont(size=9, weight="bold"),
                command=lambda a=act_key, n=act_name: self._start_capture(a, n)
            )
            edit_btn.pack(side="right", padx=10)

            # Shortcut key badge
            badge_frame = ctk.CTkFrame(row, fg_color="#21262d", corner_radius=5)
            badge_frame.pack(side="right", padx=10)

            ctk.CTkLabel(
                badge_frame, text=sc_val or "None",
                font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                text_color="#58a6ff" if sc_val else "#484f58"
            ).pack(padx=8, pady=2)

        # ── Footer: Reset to Default + Close ──────────────────────────────────
        def _on_reset():
            ConfirmDialog(
                self.top_container,
                title="Reset Shortcuts",
                message="Are you sure you want to reset all shortcuts to Standard defaults?",
                confirm_text="Reset to Default",
                on_confirm=lambda: (
                    shortcut_mgr.reset_to_default(),
                    self._build_table(),
                    self._on_change_callback() if self._on_change_callback else None
                )
            )

        self.add_footer_button("Done", command=self.close, style="primary", width=90)
        self.add_footer_button("Reset to Default", command=_on_reset, style="secondary", width=130)

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
                           "left": "Left", "right": "Right", "up": "Up", "down": "Down"}
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
                existing_name = dict(ACTIONS_REGISTRY).get(existing_act, existing_act)
                ConflictDialog(
                    self.top_container,
                    key_str=new_key,
                    existing_action=existing_name,
                    new_action=act_name,
                    on_replace=lambda: self._apply_reassign(act_key, new_key, existing_act)
                )
            else:
                shortcut_mgr.assign_shortcut(act_key, new_key)
                self._build_table()
                if self._on_change_callback:
                    self._on_change_callback()

        cap_modal.add_footer_button("Apply", command=_save_captured, style="primary", width=90)
        cap_modal.add_footer_button("Cancel", command=lambda: (cap_modal.top_container.unbind("<KeyPress>"), cap_modal.close()), style="secondary", width=80)

    def _apply_reassign(self, act_key: str, new_key: str, conflicting_act: str):
        """Clear the old assignment and assign new key."""
        shortcut_mgr.shortcuts[conflicting_act] = ""
        shortcut_mgr.custom_shortcuts[conflicting_act] = ""
        shortcut_mgr.assign_shortcut(act_key, new_key)
        self._build_table()
        if self._on_change_callback:
            self._on_change_callback()
