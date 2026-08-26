"""editor_media.py – Sidebar navigation and media panel tabs (Assets, Text, Subs, Effects, Audio)"""

import os
import cv2
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk

from editor_utils import (
    PANEL_DARK, PANEL_MID, PANEL_LIGHT, BG_DEEP, BORD, TXT_W, TXT_G, TXT_L,
    C_BLUE, C_TEAL, C_PINK, C_PURPLE, C_AMBER, C_GREEN,
    _dark, HAS_SUBTITLES
)


class MediaPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, width=330, fg_color=PANEL_DARK, corner_radius=12, border_width=0)
        self.controller = controller
        self.pack_propagate(False)

        # Tabs references
        self._tbtn = {}

        self._build_ui()

    def _build_ui(self):
        # Top Tab Bar: 3 Equal-width rounded pill tabs (uniform grid layout)
        tab_bar = ctk.CTkFrame(self, fg_color=PANEL_MID, height=44, corner_radius=20)
        tab_bar.pack(fill="x", padx=6, pady=(6, 2))
        tab_bar.pack_propagate(False)

        tab_bar.grid_columnconfigure(0, weight=1, uniform="tab")
        tab_bar.grid_columnconfigure(1, weight=1, uniform="tab")
        tab_bar.grid_columnconfigure(2, weight=1, uniform="tab")
        tab_bar.grid_rowconfigure(0, weight=1)

        tabs = [
            ("▶", "Media", "Media"),
            ("TI", "Text", "Text"),
            ("💬", "Captions", "Captions"),
        ]

        for idx, (icon, label, name) in enumerate(tabs):
            b = ctk.CTkButton(
                tab_bar, text=f"{icon} {label}", height=34, corner_radius=14,
                fg_color="transparent", hover_color=PANEL_LIGHT,
                text_color=TXT_W, font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                command=lambda n=name: self._tab(n)
            )
            b.grid(row=0, column=idx, sticky="nsew", padx=2, pady=4)
            self._tbtn[name] = b

        # Main Content Container
        self._mpanel = ctk.CTkFrame(self, width=270, fg_color="transparent", corner_radius=0)
        self._mpanel.pack(fill="both", expand=True, padx=4, pady=4)

        # Header title
        hdr = ctk.CTkFrame(self._mpanel, fg_color="transparent", height=28)
        hdr.pack(fill="x", padx=8, pady=(2, 2))
        hdr.pack_propagate(False)

        self._ptitle = ctk.CTkLabel(
            hdr, text="Media",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=TXT_W
        )
        self._ptitle.pack(side="left")

        ctk.CTkFrame(self._mpanel, height=1, fg_color=BORD).pack(fill="x", padx=4)

        # Scrollable inner content frame
        self._pscroll = ctk.CTkScrollableFrame(
            self._mpanel, fg_color="transparent",
            scrollbar_button_color=PANEL_LIGHT
        )
        self._pscroll.pack(fill="both", expand=True, padx=4, pady=4)

        # Start on Media tab by default
        self._tab("Media")

    def _tab(self, name):
        """Switch active tab and rebuild inner components list."""
        self._ptitle.configure(text=name)
        
        # Hide transcript panel first
        if hasattr(self.controller, "transcript_panel"):
            self.controller.transcript_panel.pack_forget()

        # Clear scrollable area without destroying transcript_panel
        for w in list(self._pscroll.winfo_children()):
            if hasattr(self.controller, "transcript_panel") and w == self.controller.transcript_panel:
                continue
            w.destroy()

        self._pscroll.pack(fill="both", expand=True, padx=4, pady=4)

        if name in ("Captions", "Transcript", "Subtitle"):
            # Auto Sub button inside Captions tab
            ctk.CTkButton(
                self._pscroll, text="🎙 Auto Generate Subtitles", height=34, corner_radius=10,
                fg_color="#3b82f6", hover_color="#2563eb",
                font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                command=self.controller._sub_dialog
            ).pack(fill="x", pady=(2, 8))

            if hasattr(self.controller, "transcript_panel"):
                self.controller.transcript_panel.pack(fill="both", expand=True, padx=2, pady=2)
                self.controller.transcript_panel.refresh()
        else:
            tab_func = getattr(self, f"_pt_{name.lower()}", None)
            if tab_func:
                tab_func()

        # Highlight active pill button
        for n, b in self._tbtn.items():
            b.configure(fg_color="#3b82f6" if n == name else "transparent")

    def _pt_adjustment(self):
        """Tab Panel: Color & Adjustment Presets."""
        ctk.CTkLabel(
            self._pscroll, text="Color Presets & Filters",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=TXT_W
        ).pack(anchor="w", pady=(4, 6))

        presets = ["Cinematic Warm", "Cool Teal", "Vivid Boost", "Monochrome", "Vintage Film"]
        for p in presets:
            ctk.CTkButton(
                self._pscroll, text=f"🎨 {p}", height=32, corner_radius=8,
                fg_color=PANEL_MID, hover_color=PANEL_HOV,
                font=ctk.CTkFont(size=10),
                command=lambda name=p: self.controller._status(f"Applied filter: {name}")
            ).pack(fill="x", pady=2)

    def _pt_media(self):
        """Tab Panel: Media files loader and catalog."""
        ctk.CTkButton(
            self._pscroll, text="+ Import Media", height=32, corner_radius=6,
            fg_color=C_BLUE, hover_color=_dark(C_BLUE),
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.controller._import
        ).pack(fill="x", pady=(0, 8))

        for a in self.controller.assets:
            self._acard(a)

    def _pt_text(self):
        """Tab Panel: Text clip builder + ⚙ gear opens Global Text Style settings."""
        from editor_utils import C_PINK, PANEL_MID, BORD, TXT_G

        # ── Header row with title + gear button ───────────────────────────────
        hdr = ctk.CTkFrame(self._pscroll, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            hdr, text="Text",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TXT_G
        ).pack(side="left")

        ctk.CTkButton(
            hdr, text="⚙", width=30, height=26, corner_radius=8,
            fg_color=PANEL_MID, hover_color=PANEL_MID,
            font=ctk.CTkFont(size=14),
            command=self._open_text_style_settings
        ).pack(side="right")

        # ── Text content entry ────────────────────────────────────────────────
        ctk.CTkLabel(
            self._pscroll, text="Text Content",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TXT_G
        ).pack(anchor="w", pady=(4, 2))

        ctk.CTkEntry(
            self._pscroll, placeholder_text="Enter text…",
            height=32, corner_radius=6,
            fg_color=PANEL_MID, border_color=BORD,
            textvariable=self.controller.v_text
        ).pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            self._pscroll, text="Add Text Clip",
            height=34, corner_radius=8, fg_color=C_PINK,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.controller._add_text
        ).pack(fill="x")

    def _open_text_style_settings(self):
        """Open the Global Text Style dialog (gear ⚙ button handler)."""
        try:
            from editor_properties import GlobalTextStyleDialog
            GlobalTextStyleDialog(self.winfo_toplevel(), self.controller)
        except Exception as e:
            print(f"[TextStyleDialog] {e}")


    def _pt_effects(self):
        """Tab Panel: Drag-and-drop styles (Future effects)."""
        for eff, col in [
            ("Blur", C_PURPLE), ("Glow", C_TEAL), ("Sharpen", C_BLUE),
            ("Vignette", C_AMBER), ("Vintage", C_PINK), ("Cold", "#60a5fa"), ("Warm", C_AMBER)
        ]:
            f = ctk.CTkFrame(self._pscroll, fg_color=PANEL_MID, corner_radius=8, height=38)
            f.pack(fill="x", pady=2)
            f.pack_propagate(False)

            ctk.CTkLabel(
                f, text=eff, font=ctk.CTkFont(size=10),
                text_color=col
            ).pack(side="left", padx=10)

            ctk.CTkButton(f, text="Apply", width=52, height=22, corner_radius=5, fg_color=PANEL_LIGHT).pack(side="right", padx=6)

    def _pt_color(self):
        """Tab Panel: Primary color sliders."""
        for lbl, col, lo, hi in [
            ("Brightness", C_TEAL, -100, 100), ("Contrast", C_BLUE, -100, 100),
            ("Saturation", C_GREEN, -100, 100), ("Hue", C_PURPLE, -180, 180),
            ("Temperature", C_AMBER, -100, 100)
        ]:
            ctk.CTkLabel(
                self._pscroll, text=lbl, font=ctk.CTkFont(size=9),
                text_color=TXT_G
            ).pack(anchor="w", padx=4, pady=(8, 0))

            ctk.CTkSlider(
                self._pscroll, from_=lo, to=hi,
                progress_color=col, button_color=col
            ).pack(fill="x", padx=4, pady=(0, 2))

    def _pt_audio(self):
        """Tab Panel: Import audio elements."""
        ctk.CTkButton(
            self._pscroll, text="+ Import Audio", height=32, corner_radius=6,
            fg_color=C_TEAL, hover_color=_dark(C_TEAL),
            command=self.controller._import_audio
        ).pack(fill="x", pady=(0, 8))

        for a in [x for x in self.controller.assets if x.get("type") == "audio"]:
            self._acard(a)

    def _pt_subs(self):
        """Tab Panel: Voice transcribing and automatic subtitle options."""
        ctk.CTkLabel(
            self._pscroll, text="Auto Subtitles",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TXT_G
        ).pack(anchor="w", pady=(0, 6))

        ctk.CTkButton(
            self._pscroll, text="Generate Subtitles", height=32, corner_radius=6,
            fg_color=C_BLUE if HAS_SUBTITLES else PANEL_MID,
            command=self.controller._sub_dialog
        ).pack(fill="x")

        if self.controller.segments:
            ctk.CTkLabel(
                self._pscroll, text=f"✓ {len(self.controller.segments)} segments loaded",
                font=ctk.CTkFont(size=9), text_color=C_GREEN
            ).pack(anchor="w", pady=(6, 0))

            # Export row
            row = ctk.CTkFrame(self._pscroll, fg_color="transparent")
            row.pack(fill="x", pady=(4, 2))

            ctk.CTkButton(
                row, text="Export with Subs", height=28, corner_radius=6,
                fg_color=C_GREEN, hover_color=_dark(C_GREEN),
                command=self.controller._export_subs
            ).pack(side="left", fill="x", expand=True, padx=(0, 2))

            ctk.CTkButton(
                row, text="Clear", height=28, width=50, corner_radius=6,
                fg_color=PANEL_MID, command=self.controller._clear_subs
            ).pack(side="left")

            # Save SRT button
            ctk.CTkButton(
                self._pscroll, text="💾  Save SRT…", height=28, corner_radius=6,
                fg_color=C_AMBER, hover_color=_dark(C_AMBER),
                font=ctk.CTkFont(size=9, weight="bold"),
                command=self.controller._save_srt
            ).pack(fill="x", pady=(0, 4))

    def _acard(self, asset):
        """Render a single asset card representing an imported file."""
        f = ctk.CTkFrame(self._pscroll, fg_color=PANEL_MID, corner_radius=8)
        f.pack(fill="x", pady=3)

        thumb = self._get_thumb(asset)
        if thumb:
            lbl = tk.Label(f, image=thumb, bg=PANEL_MID)
            lbl.image = thumb
            lbl.pack(side="left", padx=5, pady=5)
        else:
            col = {"video": C_BLUE, "audio": C_TEAL, "image": C_PURPLE}.get(asset.get("type"), TXT_G)
            ctk.CTkLabel(
                f, text=asset["type"][0].upper() if asset.get("type") else "?",
                font=ctk.CTkFont(size=15, weight="bold"),
                width=32, text_color=col
            ).pack(side="left", padx=6, pady=6)

        info = ctk.CTkFrame(f, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True)

        nm = asset["name"]
        sh = nm[:18] + "…" if len(nm) > 18 else nm

        ctk.CTkLabel(info, text=sh, font=ctk.CTkFont(size=10), text_color=TXT_W).pack(anchor="w")
        ctk.CTkLabel(
            info, text=asset.get("type", "?"),
            font=ctk.CTkFont(size=8), text_color=TXT_G
        ).pack(anchor="w")

        ctk.CTkButton(
            f, text="+", width=26, height=26, corner_radius=5,
            fg_color=C_BLUE, hover_color=_dark(C_BLUE),
            font=ctk.CTkFont(size=12),
            command=lambda x=asset: self.controller._add_to_tl(x)
        ).pack(side="right", padx=6, pady=6)

    def _get_thumb(self, asset):
        """Retrieve or extract visual thumbnail for videos and images."""
        p = asset.get("path", "")
        if p in self.controller._thumbs:
            return self.controller._thumbs[p]
        if asset.get("type") not in ("video", "image"):
            return None
        try:
            cap = cv2.VideoCapture(p)
            ok, fr = cap.read()
            cap.release()
            if not ok:
                return None
            h, w = fr.shape[:2]
            tw = int(w * 40 / h)
            fr = cv2.resize(fr, (tw, 40))
            ph = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)))
            self.controller._thumbs[p] = ph
            return ph
        except Exception:
            return None
