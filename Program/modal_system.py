"""modal_system.py – Unified non-draggable, centered modal system for MediaPro.
Follows UX & Functional specification (Sections 15 & 16):
- Strictly centered on screen/window
- Cannot be dragged or dragged outside viewport
- Scrolls only internal content; background does not scroll
- Clear [ ✕ ] close button
- Unified Header / Content (Scrollable) / Footer structure
"""

import os
import subprocess
import tkinter as tk
import customtkinter as ctk

# Design tokens matching editor
BG_MODAL_CARD = "#161b22"
BG_MODAL_INNER = "#0d1117"
BG_BACKDROP = "#000000"
BORDER_CLR = "#30363d"
BORDER_ACCENT = "#58a6ff"
TXT_W = "#f0f6fc"
TXT_DIM = "#8b949e"
TXT_FAINT = "#484f58"
ACCENT_BLUE = "#3b82f6"
ACCENT_RED = "#ef4444"
ACCENT_AMBER = "#f59e0b"


class BaseModal:
    """Reusable in-window modal component with backdrop, non-draggable center card,
    internal scrolling frame, and standardized Header/Content/Footer structure.
    """

    def __init__(self, parent, title: str, subtitle: str = "",
                 width: int = 560, height: int = 620, on_close=None):
        # Find top container (either parent or parent's toplevel)
        self.top_container = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent
        self.on_close_cb = on_close
        self.width = width
        self.height = height

        # 1. Full-screen backdrop frame covering the entire window
        self.backdrop = ctk.CTkFrame(
            self.top_container,
            fg_color="#080b10",
            corner_radius=0
        )
        self.backdrop.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        self.backdrop.lift()

        # Block background clicks and background mouse wheel scrolling
        self.backdrop.bind("<Button-1>", lambda e: "break")
        self.backdrop.bind("<MouseWheel>", lambda e: "break")

        # 2. Centered Card (Fixed position, NOT draggable)
        self.card = ctk.CTkFrame(
            self.backdrop,
            width=width,
            height=height,
            fg_color=BG_MODAL_CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER_CLR
        )
        self.card.place(relx=0.5, rely=0.5, anchor="center")
        self.card.pack_propagate(False)

        # 3. Header
        self._header = ctk.CTkFrame(self.card, height=54, fg_color="transparent", corner_radius=0)
        self._header.pack(fill="x", padx=16, pady=(12, 0))
        self._header.pack_propagate(False)

        # Title & Subtitle
        title_box = ctk.CTkFrame(self._header, fg_color="transparent")
        title_box.pack(side="left", fill="both", expand=True)

        self._title_lbl = ctk.CTkLabel(
            title_box, text=title,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=TXT_W, anchor="w"
        )
        self._title_lbl.pack(anchor="w")

        if subtitle:
            self._subtitle_lbl = ctk.CTkLabel(
                title_box, text=subtitle,
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=TXT_DIM, anchor="w"
            )
            self._subtitle_lbl.pack(anchor="w")

        # Clear Close Button [ ✕ ]
        self._close_btn = ctk.CTkButton(
            self._header, text="✕", width=32, height=32, corner_radius=8,
            fg_color="transparent", hover_color="#dc2626",
            text_color=TXT_DIM,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.close
        )
        self._close_btn.pack(side="right")

        # Divider line
        div = ctk.CTkFrame(self.card, height=1, fg_color=BORDER_CLR)
        div.pack(fill="x", padx=16, pady=(8, 4))

        # 5. Footer (Pack footer first to the bottom so it is never pushed off by content)
        self.footer = ctk.CTkFrame(self.card, height=52, fg_color="transparent", corner_radius=0)
        self.footer.pack(side="bottom", fill="x", padx=16, pady=(4, 12))
        self.footer.pack_propagate(False)

        # 4. Content Area (Scrollable internally)
        self.content = ctk.CTkScrollableFrame(
            self.card,
            fg_color="transparent",
            scrollbar_button_color="#21262d",
            scrollbar_button_hover_color="#30363d"
        )
        self.content.pack(side="top", fill="both", expand=True, padx=16, pady=4)

        # Escape key closes modal
        self.top_container.bind("<Escape>", self._on_escape, add="+")

    def _on_escape(self, event=None):
        self.close()

    def set_title(self, title: str, subtitle: str = ""):
        self._title_lbl.configure(text=title)
        if hasattr(self, "_subtitle_lbl") and subtitle:
            self._subtitle_lbl.configure(text=subtitle)

    def add_footer_button(self, text: str, command=None, style: str = "secondary", width: int = 90):
        """Add button to footer (right-aligned).
        style: 'primary' (blue), 'secondary' (mid-dark), 'danger' (red), 'amber' (warning).
        """
        if style == "primary":
            fg = ACCENT_BLUE; hov = "#2563eb"; txt = "#ffffff"
        elif style == "danger":
            fg = ACCENT_RED; hov = "#b91c1c"; txt = "#ffffff"
        elif style == "amber":
            fg = ACCENT_AMBER; hov = "#d97706"; txt = "#ffffff"
        else:
            fg = "#21262d"; hov = "#30363d"; txt = TXT_W

        btn = ctk.CTkButton(
            self.footer, text=text, width=width, height=34, corner_radius=8,
            fg_color=fg, hover_color=hov, text_color=txt,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold" if style == "primary" else "normal"),
            command=command or self.close
        )
        btn.pack(side="right", padx=(6, 0))
        return btn

    def close(self):
        """Clean up and remove modal overlay."""
        try:
            if hasattr(self, "top_container") and self.top_container:
                self.top_container.unbind("<Escape>")
        except Exception:
            pass

        if hasattr(self, "backdrop") and self.backdrop.winfo_exists():
            try:
                self.backdrop.destroy()
            except Exception:
                pass

        if self.on_close_cb:
            try:
                self.on_close_cb()
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════════════════════
# Pre-built Standard Dialogs
# ═════════════════════════════════════════════════════════════════════════════

class AlertDialog(BaseModal):
    """Clean alert / error dialog with detailed error explanation."""

    def __init__(self, parent, title: str, message: str, details: str = "",
                 is_error: bool = False, on_close=None):
        sub = "Please review the information below" if not is_error else "An error occurred during operation"
        super().__init__(parent, title=title, subtitle=sub, width=460, height=340, on_close=on_close)

        icon_char = "❌" if is_error else "ℹ️"
        icon_col = ACCENT_RED if is_error else ACCENT_BLUE

        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=10)

        top_row = ctk.CTkFrame(body, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(top_row, text=icon_char, font=ctk.CTkFont(size=24)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            top_row, text=message,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=TXT_W, justify="left", wraplength=340
        ).pack(side="left", fill="x", expand=True)

        if details:
            dt_box = ctk.CTkFrame(body, fg_color=BG_MODAL_INNER, corner_radius=8, border_width=1, border_color=BORDER_CLR)
            dt_box.pack(fill="both", expand=True, pady=(4, 0))
            ctk.CTkLabel(
                dt_box, text=details,
                font=ctk.CTkFont(family="Consolas", size=10),
                text_color=TXT_DIM, justify="left", anchor="nw", wraplength=380
            ).pack(fill="both", expand=True, padx=10, pady=8)

        self.add_footer_button("Close", command=self.close, style="primary", width=100)


class ConfirmDialog(BaseModal):
    """Confirmation modal with Yes / Cancel action buttons."""

    def __init__(self, parent, title: str, message: str, on_confirm, on_cancel=None,
                 confirm_text: str = "Confirm", cancel_text: str = "Cancel", is_danger: bool = False):
        super().__init__(parent, title=title, width=440, height=260, on_close=on_cancel)
        self._on_confirm = on_confirm

        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=12)

        icon = "⚠️" if is_danger else "❓"
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text=icon, font=ctk.CTkFont(size=22)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            row, text=message,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TXT_W, justify="left", wraplength=330
        ).pack(side="left", fill="x", expand=True)

        def _do_confirm():
            self.close()
            if self._on_confirm:
                self._on_confirm()

        self.add_footer_button(confirm_text, command=_do_confirm, style="danger" if is_danger else "primary", width=100)
        self.add_footer_button(cancel_text, command=self.close, style="secondary", width=90)


class ConflictDialog(BaseModal):
    """Shortcut conflict dialog (Section 4):
    'Shortcut conflict: <Key> is already assigned to another action.'
    Options: [Replace] [Cancel]
    """

    def __init__(self, parent, key_str: str, existing_action: str, new_action: str,
                 on_replace, on_cancel=None):
        super().__init__(
            parent,
            title="Shortcut Conflict",
            subtitle=f"Conflict detected for key '{key_str}'",
            width=460, height=280,
            on_close=on_cancel
        )
        self._on_replace = on_replace

        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=10)

        msg_box = ctk.CTkFrame(body, fg_color=BG_MODAL_INNER, corner_radius=8, border_width=1, border_color=BORDER_CLR)
        msg_box.pack(fill="x", padx=4, pady=(0, 10))

        ctk.CTkLabel(
            msg_box,
            text=f"Shortcut conflict: {key_str} is already assigned to another action.",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=ACCENT_AMBER, wraplength=390, justify="left"
        ).pack(padx=12, pady=(10, 4), anchor="w")

        ctk.CTkLabel(
            msg_box,
            text=f"• Currently assigned to:  {existing_action}\n• Reassigning to:  {new_action}",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=TXT_DIM, justify="left"
        ).pack(padx=12, pady=(0, 10), anchor="w")

        ctk.CTkLabel(
            body,
            text="Do you want to replace the current assignment with the new one?",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=TXT_W
        ).pack(anchor="w", padx=4)

        def _do_replace():
            self.close()
            if self._on_replace:
                self._on_replace()

        self.add_footer_button("Replace", command=_do_replace, style="primary", width=100)
        self.add_footer_button("Cancel", command=self.close, style="secondary", width=90)


class PathWarningDialog(BaseModal):
    """Model folder missing warning dialog (Section 12):
    'Model folder cannot be found.' with [Locate Folder] button.
    """

    def __init__(self, parent, missing_path: str = "", on_locate=None, on_continue=None):
        super().__init__(
            parent,
            title="Model Folder Not Found",
            subtitle="The specified AI model directory is inaccessible or was moved",
            width=480, height=290
        )
        self._on_locate = on_locate
        self._on_continue = on_continue

        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=8)

        ctk.CTkLabel(
            body,
            text="⚠️ Model folder cannot be found.",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=ACCENT_AMBER
        ).pack(anchor="w", pady=(0, 6))

        p_box = ctk.CTkFrame(body, fg_color=BG_MODAL_INNER, corner_radius=6, border_width=1, border_color=BORDER_CLR)
        p_box.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            p_box, text=missing_path or "—",
            font=ctk.CTkFont(family="Consolas", size=9),
            text_color=TXT_DIM, wraplength=410, justify="left"
        ).pack(padx=8, pady=6, anchor="w")

        ctk.CTkLabel(
            body,
            text="Please locate the model directory on your machine to enable AI transcription.",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=TXT_W
        ).pack(anchor="w")

        def _do_locate():
            from tkinter import filedialog as _fd
            folder = _fd.askdirectory(title="Locate Whisper Model Directory")
            if folder:
                self.close()
                if self._on_locate:
                    self._on_locate(folder)

        def _do_continue():
            self.close()
            if self._on_continue:
                self._on_continue()

        self.add_footer_button("Locate Folder", command=_do_locate, style="primary", width=120)
        self.add_footer_button("Dismiss", command=_do_continue, style="secondary", width=80)


class DetachResultDialog(BaseModal):
    """Detach Audio Success Dialog (Section 10):
    Shows path of physical file in filesystem and provides button to open directory.
    """

    def __init__(self, parent, audio_path: str, duration: float = 0.0, track_placed: str = ""):
        super().__init__(
            parent,
            title="Audio Detached Successfully",
            subtitle=f"Physical WAV created on track {track_placed.upper()}" if track_placed else "Physical audio file created and added to timeline track",
            width=520, height=300
        )
        self.audio_path = audio_path

        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=8)

        ctk.CTkLabel(
            body,
            text="🔊 Physical Audio Extracted",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=TXT_W
        ).pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(
            body,
            text="The audio has been saved to your filesystem and will persist across sessions:",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=TXT_DIM
        ).pack(anchor="w", pady=(0, 8))

        path_box = ctk.CTkFrame(body, fg_color=BG_MODAL_INNER, corner_radius=8, border_width=1, border_color=BORDER_CLR)
        path_box.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            path_box,
            text=os.path.basename(audio_path),
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=ACCENT_BLUE
        ).pack(anchor="w", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            path_box,
            text=audio_path,
            font=ctk.CTkFont(family="Consolas", size=9),
            text_color=TXT_DIM, wraplength=460, justify="left"
        ).pack(anchor="w", padx=10, pady=(0, 8))

        def _open_folder():
            try:
                folder = os.path.dirname(os.path.abspath(audio_path))
                if os.name == "nt":
                    # Reveal file in explorer
                    subprocess.Popen(f'explorer /select,"{os.path.abspath(audio_path)}"')
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                print(f"[Open Folder] {e}")

        self.add_footer_button("Close", command=self.close, style="primary", width=80)
        self.add_footer_button("📁 Open in Explorer", command=_open_folder, style="secondary", width=140)


class ProgressModal(BaseModal):
    """Loading State Modal (Section 25):
    Displays progress bar, percentage, message, and optional cancel button.
    """

    def __init__(self, parent, title: str, message: str = "Processing…", on_cancel=None):
        super().__init__(parent, title=title, width=440, height=220, on_close=on_cancel)
        self.on_cancel = on_cancel

        body = ctk.CTkFrame(self.content, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=10)

        self._msg_lbl = ctk.CTkLabel(
            body, text=message,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=TXT_W, anchor="w"
        )
        self._msg_lbl.pack(fill="x", pady=(0, 8))

        # Progress bar
        self._prog_bar = ctk.CTkProgressBar(body, height=12, corner_radius=6, progress_color=ACCENT_BLUE)
        self._prog_bar.pack(fill="x", pady=(0, 6))
        self._prog_bar.set(0.0)

        # Percent label
        self._pct_lbl = ctk.CTkLabel(
            body, text="0%",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color=TXT_DIM, anchor="e"
        )
        self._pct_lbl.pack(fill="x")

        if on_cancel:
            self.add_footer_button("Cancel", command=self._cancel, style="secondary", width=90)

    def update_progress(self, pct: float, message: str = ""):
        """Update progress: pct is 0.0 to 1.0 (or 0 to 100)."""
        if pct > 1.0:
            pct = pct / 100.0
        pct = max(0.0, min(1.0, float(pct)))
        try:
            self._prog_bar.set(pct)
            self._pct_lbl.configure(text=f"{int(pct * 100)}%")
            if message:
                self._msg_lbl.configure(text=message)
        except Exception:
            pass

    def _cancel(self):
        self.close()
        if self.on_cancel:
            self.on_cancel()
