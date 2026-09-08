"""tooltip.py – Modern dark-themed tooltip helper for Tkinter and CustomTkinter widgets.
Displays action name, description/function, and optional shortcut key badge.
"""

import tkinter as tk

class Tooltip:
    """Modern dark tooltip popup that shows on hover."""

    def __init__(self, widget, title: str, text: str = "", description: str = "", shortcut: str = "", delay_ms: int = 400):
        self.widget = widget
        self.title = title
        self.text = description if description else text
        self.shortcut = shortcut
        self.delay_ms = delay_ms
        self._tip_window = None
        self._id = None

        self.widget.bind("<Enter>", self._schedule, add="+")
        self.widget.bind("<Leave>", self._hide, add="+")
        self.widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None):
        self._unschedule()
        self._id = self.widget.after(self.delay_ms, self._show)

    def _unschedule(self):
        if self._id:
            try:
                self.widget.after_cancel(self._id)
            except Exception:
                pass
            self._id = None

    def _hide(self, event=None):
        self._unschedule()
        if self._tip_window:
            try:
                self._tip_window.destroy()
            except Exception:
                pass
            self._tip_window = None

    def _show(self):
        if self._tip_window or not self.widget.winfo_exists():
            return

        # Coordinates
        try:
            x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2)
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return

        self._tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)

        # Outer border frame
        border = tk.Frame(tw, bg="#3b4252", bd=1)
        border.pack()

        # Inner container
        body = tk.Frame(border, bg="#161b22", padx=8, pady=5)
        body.pack()

        # Top row: Title + Shortcut badge
        top_row = tk.Frame(body, bg="#161b22")
        top_row.pack(fill="x", anchor="w")

        title_lbl = tk.Label(
            top_row, text=self.title,
            font=("Segoe UI", 9, "bold"),
            fg="#f0f6fc", bg="#161b22"
        )
        title_lbl.pack(side="left")

        if self.shortcut:
            badge = tk.Label(
                top_row, text=f" {self.shortcut} ",
                font=("Consolas", 8, "bold"),
                fg="#58a6ff", bg="#21262d",
                relief="flat"
            )
            badge.pack(side="left", padx=(6, 0))

        # Description if provided
        if self.text:
            desc_lbl = tk.Label(
                body, text=self.text,
                font=("Segoe UI", 8),
                fg="#8b949e", bg="#161b22",
                justify="left", wraplength=220
            )
            desc_lbl.pack(anchor="w", pady=(2, 0))

        # Position correction to not overflow screen
        tw.update_idletasks()
        w = tw.winfo_width()
        h = tw.winfo_height()
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()

        pos_x = max(10, min(x - w // 2, screen_w - w - 10))
        pos_y = y
        if pos_y + h > screen_h - 20:
            pos_y = max(10, self.widget.winfo_rooty() - h - 6)

        tw.wm_geometry(f"+{pos_x}+{pos_y}")


def attach_tooltip(widget, title: str, text: str = "", shortcut: str = "") -> Tooltip:
    """Convenience helper to attach tooltip to any Tkinter / CTk widget."""
    return Tooltip(widget, title, text, shortcut)

# Alias for capitalization flexibility
ToolTip = Tooltip
