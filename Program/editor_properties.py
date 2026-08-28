"""editor_properties.py – Context-sensitive clip properties panels and track control panels"""

import os
import math
import colorsys
import tkinter as tk
import customtkinter as ctk

from editor_utils import (
    PANEL_DARK, PANEL_MID, PANEL_LIGHT, PANEL_HOV, BORD, TXT_W, TXT_G, TXT_L,
    C_BLUE, C_TEAL, C_GREEN, C_AMBER, C_PINK, C_RED,
    _ft, _dark, _bright, HAS_SUBTITLES
)
try:
    from subtitle_config import (
        FONT_CHOICES, get_all_fonts, add_custom_font,
        ANIMATION_CHOICES, DECORATION_CHOICES, POSITION_CHOICES
    )
except ImportError:
    FONT_CHOICES = ["Tahoma", "Arial", "TH Sarabun New", "Leelawadee", "Cordia New",
                    "Angsana New", "Courier New", "Times New Roman", "Verdana", "Impact"]
    ANIMATION_CHOICES = ["none", "fade_in", "slide_up", "slide_down", "typewriter", "pop"]
    DECORATION_CHOICES = ["none", "shadow", "outline", "box", "highlight"]
    POSITION_CHOICES = ["bottom_center", "bottom_left", "bottom_right", "top_center", "top_left", "top_right", "center", "custom"]
    def get_all_fonts(): return FONT_CHOICES
    def add_custom_font(x): return x


# ═══════════════════════════════════════════════════════════════════
#  Color Wheel Dialog
# ═══════════════════════════════════════════════════════════════════
class ColorWheelDialog(ctk.CTkToplevel):
    """HSV Color Wheel + Value slider + Hex entry picker."""

    def __init__(self, parent, initial_color="#ffffff", on_pick=None):
        super().__init__(parent)
        self.title("Pick Color")
        self.geometry("340x420")
        self.resizable(False, False)
        self.configure(fg_color=PANEL_DARK)
        self._on_pick = on_pick
        self._result = initial_color

        # Parse initial color
        try:
            r = int(initial_color[1:3], 16)
            g = int(initial_color[3:5], 16)
            b = int(initial_color[5:7], 16)
        except Exception:
            r, g, b = 255, 255, 255

        h, s, v = self._rgb_to_hsv(r, g, b)
        self._hue = h
        self._sat = s
        self._val = v

        self._wheel_size = 200
        self._dragging_wheel = False

        self._build()
        self.after(100, lambda: (self.lift(), self.focus_force(), self.grab_set()))
        self._redraw_all()

    def _build(self):
        ctk.CTkLabel(self, text="🎨  Choose Color",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TXT_W).pack(pady=(12, 4))

        # Color wheel canvas
        ws = self._wheel_size
        self._wheel_canvas = tk.Canvas(self, width=ws, height=ws,
                                        bg="#0f172a", highlightthickness=0)
        self._wheel_canvas.pack(pady=(0, 6))
        self._wheel_canvas.bind("<Button-1>", self._wheel_press)
        self._wheel_canvas.bind("<B1-Motion>", self._wheel_drag)
        self._wheel_canvas.bind("<ButtonRelease-1>", self._wheel_release)

        # Value (brightness) slider
        val_row = ctk.CTkFrame(self, fg_color="transparent")
        val_row.pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkLabel(val_row, text="Brightness", font=ctk.CTkFont(size=9),
                     text_color=TXT_G, width=62).pack(side="left")
        self._val_slider = ctk.CTkSlider(
            val_row, from_=0, to=1, width=180,
            progress_color="#ffffff", button_color="#e0e0e0",
            command=self._on_val_slider
        )
        self._val_slider.set(self._val)
        self._val_slider.pack(side="left", padx=4)

        # Hex entry + preview swatch
        hex_row = ctk.CTkFrame(self, fg_color="transparent")
        hex_row.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(hex_row, text="#Hex", font=ctk.CTkFont(size=9),
                     text_color=TXT_G, width=36).pack(side="left")
        self._hex_var = tk.StringVar(value=self._result)
        self._hex_ent = ctk.CTkEntry(hex_row, textvariable=self._hex_var,
                                      width=90, height=28, corner_radius=6,
                                      fg_color=PANEL_MID)
        self._hex_ent.pack(side="left", padx=4)
        self._hex_ent.bind("<Return>", self._on_hex_enter)
        self._hex_ent.bind("<FocusOut>", self._on_hex_enter)

        self._swatch = tk.Canvas(hex_row, width=36, height=28,
                                  bg=self._result, highlightthickness=1,
                                  highlightbackground="#334155")
        self._swatch.pack(side="left", padx=4)

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 14))
        ctk.CTkButton(btn_row, text="Cancel", width=100, height=32,
                      corner_radius=8, fg_color=PANEL_MID, hover_color=PANEL_LIGHT,
                      command=self.destroy).pack(side="left")
        ctk.CTkButton(btn_row, text="✓ Select", height=32, corner_radius=8,
                      fg_color=C_BLUE, hover_color=_dark(C_BLUE),
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._submit).pack(side="right")

    # ── Drawing ───────────────────────────────────────────────────────────────
    def _redraw_all(self):
        self._draw_wheel()
        self._draw_selector()
        self._update_swatch()

    def _draw_wheel(self):
        ws = self._wheel_size
        r = ws // 2
        self._wheel_canvas.delete("wheel")
        step = 3
        for y in range(0, ws, step):
            for x in range(0, ws, step):
                dx = x - r
                dy = y - r
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > r:
                    continue
                angle = math.degrees(math.atan2(dy, dx)) % 360
                sat = dist / r
                rr, gg, bb = self._hsv_to_rgb(angle, sat, self._val)
                color = f"#{rr:02x}{gg:02x}{bb:02x}"
                self._wheel_canvas.create_rectangle(
                    x, y, x + step, y + step,
                    fill=color, outline="", tags="wheel"
                )
        self._wheel_canvas.create_oval(1, 1, ws - 1, ws - 1,
                                        outline="#334155", width=1, tags="wheel")

    def _draw_selector(self):
        self._wheel_canvas.delete("selector")
        ws = self._wheel_size
        r = ws // 2
        rad = math.radians(self._hue)
        sx = r + self._sat * r * math.cos(rad)
        sy = r + self._sat * r * math.sin(rad)
        cr = 7
        self._wheel_canvas.create_oval(sx - cr, sy - cr, sx + cr, sy + cr,
                                        outline="white", width=2, tags="selector")
        self._wheel_canvas.create_oval(sx - cr + 2, sy - cr + 2, sx + cr - 2, sy + cr - 2,
                                        outline="black", width=1, tags="selector")

    def _update_swatch(self):
        color = self._hsv_hex()
        self._result = color
        try:
            self._swatch.configure(bg=color)
            self._hex_var.set(color)
        except Exception:
            pass

    def _hsv_hex(self):
        r, g, b = self._hsv_to_rgb(self._hue, self._sat, self._val)
        return f"#{r:02x}{g:02x}{b:02x}"

    # ── Events ────────────────────────────────────────────────────────────────
    def _wheel_press(self, event):
        self._dragging_wheel = True
        self._update_from_wheel(event.x, event.y)

    def _wheel_drag(self, event):
        if self._dragging_wheel:
            self._update_from_wheel(event.x, event.y)

    def _wheel_release(self, event):
        self._dragging_wheel = False

    def _update_from_wheel(self, x, y):
        ws = self._wheel_size
        r = ws // 2
        dx = x - r
        dy = y - r
        dist = math.sqrt(dx * dx + dy * dy)
        self._hue = math.degrees(math.atan2(dy, dx)) % 360
        self._sat = min(1.0, dist / r)
        self._draw_selector()
        self._update_swatch()

    def _on_val_slider(self, val):
        self._val = float(val)
        self._draw_wheel()
        self._draw_selector()
        self._update_swatch()

    def _on_hex_enter(self, event=None):
        raw = self._hex_var.get().strip()
        if not raw.startswith("#"):
            raw = "#" + raw
        try:
            if len(raw) == 7:
                r = int(raw[1:3], 16)
                g = int(raw[3:5], 16)
                b = int(raw[5:7], 16)
                h, s, v = self._rgb_to_hsv(r, g, b)
                self._hue = h; self._sat = s; self._val = v
                self._val_slider.set(v)
                self._draw_wheel()
                self._draw_selector()
                self._update_swatch()
        except Exception:
            pass

    def _submit(self):
        if self._on_pick:
            self._on_pick(self._result)
        self.destroy()

    @staticmethod
    def _hsv_to_rgb(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, v)
        return int(r * 255), int(g * 255), int(b * 255)

    @staticmethod
    def _rgb_to_hsv(r, g, b):
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        return h * 360.0, s, v


# ═══════════════════════════════════════════════════════════════════
#  Global Text Style Dialog (opened from ⚙ gear in Text tab)
# ═══════════════════════════════════════════════════════════════════
class GlobalTextStyleDialog(ctk.CTkToplevel):
    """Global default text / subtitle style settings opened from ⚙ gear button in Text tab."""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.title("⚙  Global Text Style Settings")
        self.geometry("400x640")
        self.resizable(False, False)
        self.configure(fg_color=PANEL_DARK)
        self._ctrl = controller
        import copy
        self._style = copy.deepcopy(getattr(controller, "style", None))
        self._build()
        self.after(100, lambda: (self.lift(), self.focus_force(), self.grab_set()))

    def _build(self):
        style = self._style
        if style is None:
            ctk.CTkLabel(self, text="No subtitle style available.",
                         text_color=TXT_G).pack(pady=40)
            return

        # Header title
        ctk.CTkLabel(self, text="🌐  Global Subtitle Style",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#60a5fa").pack(pady=(16, 2))
        ctk.CTkLabel(self, text="ตั้งค่า default ของสไตล์ข้อความในโปรเจกต์",
                     font=ctk.CTkFont(size=9), text_color=TXT_G).pack(pady=(0, 6))
        ctk.CTkFrame(self, height=1, fg_color=BORD).pack(fill="x", padx=14)

        sc = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                     scrollbar_button_color=PANEL_LIGHT)
        sc.pack(fill="both", expand=True, padx=14, pady=(8, 6))

        def _sec(t):
            ctk.CTkLabel(sc, text=t, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=TXT_G).pack(anchor="w", pady=(10, 2))

        # ── FONT ──────────────────────────────────────────────────────────────
        _sec("FONT")
        frow = ctk.CTkFrame(sc, fg_color="transparent")
        frow.pack(fill="x", pady=2)
        ctk.CTkLabel(frow, text="ฟอนต์", font=ctk.CTkFont(size=10),
                     text_color=TXT_L, width=44).pack(side="left")
        self._fv = tk.StringVar(value=style.font_name)
        all_fonts = get_all_fonts()
        self._fmenu = ctk.CTkOptionMenu(
            frow, values=all_fonts, variable=self._fv,
            width=220, height=26, corner_radius=6,
            fg_color=PANEL_MID, button_color=PANEL_HOV,
            font=ctk.CTkFont(size=9),
            command=self._preview_font
        )
        self._fmenu.pack(side="right")

        ctk.CTkButton(
            sc, text="+ Import Font", height=22, corner_radius=6,
            fg_color=PANEL_MID, hover_color=PANEL_HOV,
            font=ctk.CTkFont(size=8, weight="bold"),
            command=self._import_font
        ).pack(fill="x", pady=(2, 2))

        _fp_fr = ctk.CTkFrame(sc, fg_color=PANEL_MID, corner_radius=6)
        _fp_fr.pack(fill="x", pady=(0, 4))
        self._fp_lbl = ctk.CTkLabel(
            _fp_fr, text="ตัวอย่าง  ABC abc 123",
            font=ctk.CTkFont(family=style.font_name, size=13),
            text_color=TXT_W
        )
        self._fp_lbl.pack(padx=8, pady=6)

        # ── Bold / Italic ─────────────────────────────────────────────────────
        _sec("STYLE")
        bi_row = ctk.CTkFrame(sc, fg_color="transparent")
        bi_row.pack(fill="x", pady=2)
        self._bv = tk.BooleanVar(value=getattr(style, "bold", False))
        self._iv = tk.BooleanVar(value=getattr(style, "italic", False))

        self._bb = ctk.CTkButton(
            bi_row, text="B", width=42, height=28, corner_radius=6,
            fg_color=C_BLUE if self._bv.get() else PANEL_MID, hover_color=PANEL_HOV,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._tog_b)
        self._bb.pack(side="left", padx=(0, 4))
        self._ib = ctk.CTkButton(
            bi_row, text="I", width=42, height=28, corner_radius=6,
            fg_color=C_BLUE if self._iv.get() else PANEL_MID, hover_color=PANEL_HOV,
            font=ctk.CTkFont(size=11, slant="italic"),
            command=self._tog_i)
        self._ib.pack(side="left")

        # ── FONT SIZE ─────────────────────────────────────────────────────────
        _sec("FONT SIZE")
        sz_row = ctk.CTkFrame(sc, fg_color="transparent")
        sz_row.pack(fill="x", pady=2)
        self._sz_lbl = ctk.CTkLabel(sz_row, text=f"{style.font_size}px",
                                     font=ctk.CTkFont(size=9), text_color=TXT_W, width=38)
        self._sz_lbl.pack(side="right")
        self._sz_slider = ctk.CTkSlider(
            sz_row, from_=14, to=72, number_of_steps=58,
            progress_color=C_BLUE, button_color=C_BLUE,
            command=self._on_sz
        )
        self._sz_slider.set(style.font_size)
        self._sz_slider.pack(side="left", fill="x", expand=True, padx=(0, 4))

        # ── FONT COLOR ────────────────────────────────────────────────────────
        _sec("FONT COLOR")
        crow = ctk.CTkFrame(sc, fg_color="transparent")
        crow.pack(fill="x", pady=2)
        self._cv = tk.StringVar(value=style.font_color)
        try:
            self._swatch = tk.Canvas(crow, width=26, height=26,
                                      bg=style.font_color, highlightthickness=1,
                                      highlightbackground="#334155")
            self._swatch.pack(side="left", padx=(0, 4))
            self._swatch.bind("<Button-1>", lambda e: self._open_color_wheel())
        except Exception:
            pass
        ctk.CTkButton(crow, text="🎨", width=30, height=26, corner_radius=6,
                      fg_color=PANEL_MID, hover_color=PANEL_HOV,
                      command=self._open_color_wheel).pack(side="left", padx=(0, 4))
        ce = ctk.CTkEntry(crow, textvariable=self._cv, width=90, height=26,
                          corner_radius=6, fg_color=PANEL_MID)
        ce.pack(side="left")
        ce.bind("<Return>", lambda e: self._update_swatch())
        ce.bind("<FocusOut>", lambda e: self._update_swatch())

        # ── DECORATION ────────────────────────────────────────────────────────
        _sec("DECORATION")
        self._dv = tk.StringVar(value=style.decoration)
        ctk.CTkOptionMenu(sc, values=DECORATION_CHOICES, variable=self._dv,
                          height=26, corner_radius=6, fg_color=PANEL_MID,
                          button_color=PANEL_HOV, font=ctk.CTkFont(size=9)
                          ).pack(fill="x", pady=(0, 4))

        # ── ANIMATION ─────────────────────────────────────────────────────────
        _sec("ANIMATION")
        self._av = tk.StringVar(value=style.animation)
        ctk.CTkOptionMenu(sc, values=ANIMATION_CHOICES, variable=self._av,
                          height=26, corner_radius=6, fg_color=PANEL_MID,
                          button_color=PANEL_HOV, font=ctk.CTkFont(size=9)
                          ).pack(fill="x", pady=(0, 4))

        # ── POSITION ──────────────────────────────────────────────────────────
        _sec("POSITION")
        self._pv = tk.StringVar(value=style.position)
        ctk.CTkOptionMenu(sc, values=POSITION_CHOICES, variable=self._pv,
                          height=26, corner_radius=6, fg_color=PANEL_MID,
                          button_color=PANEL_HOV, font=ctk.CTkFont(size=9)
                          ).pack(fill="x", pady=(0, 4))

        # ── ALIGN ────────────────────────────────────────────────────────────
        _sec("ALIGN")
        self._alv = tk.StringVar(value=getattr(style, "align", "center"))
        ctk.CTkOptionMenu(sc, values=["left", "center", "right"], variable=self._alv,
                          height=26, corner_radius=6, fg_color=PANEL_MID,
                          button_color=PANEL_HOV, font=ctk.CTkFont(size=9)
                          ).pack(fill="x", pady=(0, 4))

        # ── Apply to ALL Subtitle Clips ───────────────────────────────────────
        ctk.CTkButton(
            sc, text="⊙ Apply Font/Style to ALL Subs",
            height=28, corner_radius=8,
            fg_color=C_AMBER, hover_color=_dark(C_AMBER),
            font=ctk.CTkFont(size=9, weight="bold"),
            command=self._apply_to_all
        ).pack(fill="x", pady=(8, 0))

        # ── Bottom action buttons ─────────────────────────────────────────────
        br = ctk.CTkFrame(self, fg_color="transparent")
        br.pack(fill="x", padx=14, pady=(6, 14))
        ctk.CTkButton(br, text="Cancel", width=90, height=32, corner_radius=8,
                      fg_color=PANEL_MID, hover_color=PANEL_LIGHT,
                      command=self.destroy).pack(side="left")
        ctk.CTkButton(br, text="✓ Apply", height=32, corner_radius=8,
                      fg_color=C_BLUE, hover_color=_dark(C_BLUE),
                      font=ctk.CTkFont(size=11, weight="bold"),
                      command=self._apply).pack(side="right")

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def _preview_font(self, val):
        try:
            self._fp_lbl.configure(font=ctk.CTkFont(family=val, size=13))
        except Exception:
            pass

    def _import_font(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Import Font File",
            filetypes=[("Font Files", "*.ttf *.otf"), ("All Files", "*.*")]
        )
        if path:
            name = add_custom_font(path)
            if name:
                nl = get_all_fonts()
                self._fmenu.configure(values=nl)
                self._fv.set(name)
                self._preview_font(name)

    def _tog_b(self):
        self._bv.set(not self._bv.get())
        self._bb.configure(fg_color=C_BLUE if self._bv.get() else PANEL_MID)

    def _tog_i(self):
        self._iv.set(not self._iv.get())
        self._ib.configure(fg_color=C_BLUE if self._iv.get() else PANEL_MID)

    def _on_sz(self, v):
        self._sz_lbl.configure(text=f"{int(float(v))}px")

    def _update_swatch(self):
        try:
            color = self._cv.get().strip()
            if not color.startswith("#"):
                color = "#" + color
            self._swatch.configure(bg=color)
        except Exception:
            pass

    def _open_color_wheel(self):
        current = self._cv.get()
        def _pk(c):
            self._cv.set(c)
            self._update_swatch()
        ColorWheelDialog(self, initial_color=current, on_pick=_pk)

    def _apply(self):
        style = self._style
        if style is None:
            self.destroy()
            return
        style.font_name  = self._fv.get()
        try:
            sz_val = int(self._sz_lbl.cget("text").replace("px", ""))
        except Exception:
            sz_val = style.font_size
        style.font_size  = sz_val
        style.font_color = self._cv.get()
        style.bold       = self._bv.get()
        style.italic     = self._iv.get()
        style.decoration = self._dv.get()
        style.animation  = self._av.get()
        style.position   = self._pv.get()
        style.align      = self._alv.get()

        # Update controller.style
        ctrl_style = getattr(self._ctrl, "style", None)
        if ctrl_style is not None:
            for attr in ("font_name", "font_size", "font_color", "bold", "italic",
                          "decoration", "animation", "position", "align"):
                setattr(ctrl_style, attr, getattr(style, attr))
        self._ctrl._refresh_preview()
        self.destroy()

    def _apply_to_all(self):
        self._apply()
        fn = getattr(self._ctrl.style, "font_name",  "Tahoma")
        fs = getattr(self._ctrl.style, "font_size",  36)
        fc = getattr(self._ctrl.style, "font_color", "#ffffff")
        bl = getattr(self._ctrl.style, "bold",   False)
        it = getattr(self._ctrl.style, "italic", False)
        dc = getattr(self._ctrl.style, "decoration", "shadow")
        al = getattr(self._ctrl.style, "align", "center")
        for sub_clip in self._ctrl.tracks.get("subtitle", []):
            sub_clip.update({"font_name": fn, "font_size": fs, "font_color": fc,
                             "bold": bl, "italic": it, "decoration": dc, "align": al})
        self._ctrl._push_undo()
        self._ctrl._refresh_preview()
        n = len(self._ctrl.tracks.get("subtitle", []))
        self._ctrl._status(f"✓ Applied to all {n} subtitle clips")


# ═══════════════════════════════════════════════════════════════════
#  Properties Panel (Right Side)
# ═══════════════════════════════════════════════════════════════════
class PropertiesPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, width=270, fg_color=PANEL_DARK, corner_radius=12, border_width=0)
        self.controller = controller

        self._build_ui()

    def _build_ui(self):
        # Header
        phdr = ctk.CTkFrame(self, fg_color=PANEL_MID, height=36, corner_radius=8)
        phdr.pack(fill="x", padx=6, pady=(6, 2))
        phdr.pack_propagate(False)

        ctk.CTkLabel(
            phdr, text="⚙  Clip Properties",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=TXT_W
        ).pack(side="left", padx=12, pady=6)

        ctk.CTkFrame(self, height=1, fg_color=BORD).pack(fill="x", padx=6, pady=2)

        # Dynamic scrollable area
        self._pp_dyn = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=PANEL_LIGHT
        )
        self._pp_dyn.pack(fill="both", expand=True, padx=6, pady=(2, 6))

        # Placeholder frame for track controls compatibility
        self._track_ctrl_frame = ctk.CTkFrame(self, fg_color="transparent", height=0)

        self._refresh_props()

    def _refresh_props(self):
        """Clear dynamic area and rebuild layout matching the selected clip kind."""
        sc = self._pp_dyn
        for w in sc.winfo_children():
            w.destroy()

        items = self.controller.tracks.get(self.controller.sel_track, [])
        if not (0 <= self.controller.sel_idx < len(items)):
            # Clean empty placeholder when nothing is selected
            ctk.CTkLabel(
                sc, text="เลือก clip ใน timeline\nเพื่อปรับการตั้งค่า",
                font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TXT_G,
                justify="center"
            ).pack(pady=50)
            return

        clip = items[self.controller.sel_idx]
        kind = self.controller._track_kind(self.controller.sel_track)

        if self.controller.sel_track == "subtitle":
            self._props_clip_text(sc, clip, is_subtitle=True)
        elif clip.get("path", "") == "":
            self._props_clip_text(sc, clip, is_subtitle=False)
        elif kind == "audio":
            self._props_audio(sc, clip)
        else:
            self._props_video(sc, clip)

    def _plbl(self, sc, text, col=None):
        ctk.CTkLabel(
            sc, text=text, font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=col or C_TEAL
        ).pack(anchor="w", pady=(10, 2))

    # ── Video Properties (Original Reliable Sliders + Entries) ─────────────────
    def _props_video(self, sc, clip):
        """Video properties: Transform (Scale/Rotate), Speed, and Volume with direct numeric typing."""
        # 1. Transform Section (Scale, Rotate)
        self._plbl(sc, "Transform")

        # Scale (%)
        scale_val = int(clip.get("scale", 1.0) * 100)
        sc_row = ctk.CTkFrame(sc, fg_color="transparent")
        sc_row.pack(fill="x", pady=2)
        ctk.CTkLabel(sc_row, text="Scale (%)", font=ctk.CTkFont(size=10),
                     text_color=TXT_L).pack(side="left")

        sc_ent = ctk.CTkEntry(sc_row, width=54, height=24, corner_radius=6,
                               font=ctk.CTkFont(size=10, weight="bold"))
        sc_ent.insert(0, str(scale_val))
        sc_ent.pack(side="right")

        sc_slider = ctk.CTkSlider(
            sc, from_=10, to=300, number_of_steps=290,
            progress_color=C_BLUE, button_color=C_BLUE
        )
        sc_slider.set(scale_val)
        sc_slider.pack(fill="x", padx=2, pady=(0, 6))

        def _apply_scale(val_str):
            try:
                v = max(10, min(500, float(val_str)))
                clip["scale"] = v / 100.0
                sc_slider.set(v)
                sc_ent.delete(0, "end")
                sc_ent.insert(0, str(int(v)))
                self.controller._render(self.controller.fi)
            except ValueError:
                pass

        sc_slider.configure(command=lambda v: (
            sc_ent.delete(0, "end"),
            sc_ent.insert(0, str(int(v))),
            clip.update({"scale": int(v) / 100.0}),
            self.controller._render(self.controller.fi)
        ))
        sc_ent.bind("<Return>", lambda e: _apply_scale(sc_ent.get()))
        sc_ent.bind("<FocusOut>", lambda e: _apply_scale(sc_ent.get()))

        # Rotate (°)
        rot_val = clip.get("rotate", 0)
        rot_row = ctk.CTkFrame(sc, fg_color="transparent")
        rot_row.pack(fill="x", pady=2)
        ctk.CTkLabel(rot_row, text="Rotate (°)", font=ctk.CTkFont(size=10),
                     text_color=TXT_L).pack(side="left")

        rot_ent = ctk.CTkEntry(rot_row, width=54, height=24, corner_radius=6,
                               font=ctk.CTkFont(size=10, weight="bold"))
        rot_ent.insert(0, str(int(rot_val)))
        rot_ent.pack(side="right")

        rot_slider = ctk.CTkSlider(
            sc, from_=-180, to=180, number_of_steps=360,
            progress_color=C_BLUE, button_color=C_BLUE
        )
        rot_slider.set(rot_val)
        rot_slider.pack(fill="x", padx=2, pady=(0, 8))

        def _apply_rot(val_str):
            try:
                v = int(float(val_str))
                clip["rotate"] = v
                rot_slider.set(v)
                rot_ent.delete(0, "end")
                rot_ent.insert(0, str(v))
                self.controller._render(self.controller.fi)
            except ValueError:
                pass

        rot_slider.configure(command=lambda v: (
            rot_ent.delete(0, "end"),
            rot_ent.insert(0, str(int(v))),
            clip.update({"rotate": int(v)}),
            self.controller._render(self.controller.fi)
        ))
        rot_ent.bind("<Return>", lambda e: _apply_rot(rot_ent.get()))
        rot_ent.bind("<FocusOut>", lambda e: _apply_rot(rot_ent.get()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=4)

        # 2. Speed Section
        self._plbl(sc, "Speed")
        cur_spd = float(clip.get("speed", 1.0))
        self.controller.v_speed.set(cur_spd)

        spd_row = ctk.CTkFrame(sc, fg_color="transparent")
        spd_row.pack(fill="x", pady=2)
        ctk.CTkLabel(spd_row, text="Playback Speed", font=ctk.CTkFont(size=10),
                     text_color=TXT_L).pack(side="left")

        spd_ent = ctk.CTkEntry(spd_row, width=54, height=24, corner_radius=6,
                                font=ctk.CTkFont(size=10, weight="bold"))
        spd_ent.insert(0, f"{cur_spd:.2f}")
        spd_ent.pack(side="right")

        spd_slider = ctk.CTkSlider(
            sc, from_=0.1, to=3.0, variable=self.controller.v_speed,
            progress_color=C_TEAL, button_color=C_TEAL
        )
        spd_slider.pack(fill="x", padx=2, pady=(0, 8))

        def _apply_spd_num(val_str):
            try:
                v = max(0.1, min(5.0, float(val_str)))
                self.controller.v_speed.set(v)
                self.controller._apply_speed(v)
                spd_ent.delete(0, "end")
                spd_ent.insert(0, f"{v:.2f}")
            except ValueError:
                pass

        spd_slider.configure(command=lambda v: (
            spd_ent.delete(0, "end"),
            spd_ent.insert(0, f"{v:.2f}"),
            self.controller._apply_speed(v)
        ))
        spd_ent.bind("<Return>", lambda e: _apply_spd_num(spd_ent.get()))
        spd_ent.bind("<FocusOut>", lambda e: _apply_spd_num(spd_ent.get()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=4)

        # 3. Volume Section
        self._plbl(sc, "Volume")
        cur_vol = float(clip.get("volume", 1.0))
        self.controller.v_vol.set(cur_vol)

        vol_row = ctk.CTkFrame(sc, fg_color="transparent")
        vol_row.pack(fill="x", pady=2)
        ctk.CTkLabel(vol_row, text="Audio Level (%)", font=ctk.CTkFont(size=10),
                     text_color=TXT_L).pack(side="left")

        vol_ent = ctk.CTkEntry(vol_row, width=54, height=24, corner_radius=6,
                                font=ctk.CTkFont(size=10, weight="bold"))
        vol_ent.insert(0, str(int(cur_vol * 100)))
        vol_ent.pack(side="right")

        vol_slider = ctk.CTkSlider(
            sc, from_=0.0, to=2.0, variable=self.controller.v_vol,
            progress_color=C_GREEN, button_color=C_GREEN
        )
        vol_slider.pack(fill="x", padx=2, pady=(0, 6))

        def _apply_vol_num(val_str):
            try:
                v = max(0, min(300, float(val_str)))
                vol_ratio = v / 100.0
                self.controller.v_vol.set(vol_ratio)
                self.controller._apply_vol(vol_ratio)
                vol_ent.delete(0, "end")
                vol_ent.insert(0, str(int(v)))
            except ValueError:
                pass

        vol_slider.configure(command=lambda v: (
            vol_ent.delete(0, "end"),
            vol_ent.insert(0, str(int(v * 100))),
            self.controller._apply_vol(v)
        ))
        vol_ent.bind("<Return>", lambda e: _apply_vol_num(vol_ent.get()))
        vol_ent.bind("<FocusOut>", lambda e: _apply_vol_num(vol_ent.get()))

        self._props_info(sc, clip)

    # ── Audio Properties ──────────────────────────────────────────────────────
    def _props_audio(self, sc, clip):
        """Audio clip properties: Volume & Speed controls."""
        self._plbl(sc, "Volume")
        cur_vol = float(clip.get("volume", 1.0))
        self.controller.v_vol.set(cur_vol)

        vol_row = ctk.CTkFrame(sc, fg_color="transparent")
        vol_row.pack(fill="x", pady=2)
        ctk.CTkLabel(vol_row, text="Audio Level (%)", font=ctk.CTkFont(size=10),
                     text_color=TXT_L).pack(side="left")

        vol_ent = ctk.CTkEntry(vol_row, width=54, height=24, corner_radius=6,
                                font=ctk.CTkFont(size=10, weight="bold"))
        vol_ent.insert(0, str(int(cur_vol * 100)))
        vol_ent.pack(side="right")

        vol_slider = ctk.CTkSlider(
            sc, from_=0.0, to=2.0, variable=self.controller.v_vol,
            progress_color=C_GREEN, button_color=C_GREEN
        )
        vol_slider.pack(fill="x", padx=2, pady=(0, 6))

        def _apply_vol_num(val_str):
            try:
                v = max(0, min(300, float(val_str)))
                vol_ratio = v / 100.0
                self.controller.v_vol.set(vol_ratio)
                self.controller._apply_vol(vol_ratio)
                vol_ent.delete(0, "end")
                vol_ent.insert(0, str(int(v)))
            except ValueError:
                pass

        vol_slider.configure(command=lambda v: (
            vol_ent.delete(0, "end"),
            vol_ent.insert(0, str(int(v * 100))),
            self.controller._apply_vol(v)
        ))
        vol_ent.bind("<Return>", lambda e: _apply_vol_num(vol_ent.get()))
        vol_ent.bind("<FocusOut>", lambda e: _apply_vol_num(vol_ent.get()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=4)

        # Speed
        self._plbl(sc, "Speed")
        cur_spd = float(clip.get("speed", 1.0))
        self.controller.v_speed.set(cur_spd)

        spd_row = ctk.CTkFrame(sc, fg_color="transparent")
        spd_row.pack(fill="x", pady=2)
        ctk.CTkLabel(spd_row, text="Audio Speed", font=ctk.CTkFont(size=10),
                     text_color=TXT_L).pack(side="left")

        spd_ent = ctk.CTkEntry(spd_row, width=54, height=24, corner_radius=6,
                                font=ctk.CTkFont(size=10, weight="bold"))
        spd_ent.insert(0, f"{cur_spd:.2f}")
        spd_ent.pack(side="right")

        spd_slider = ctk.CTkSlider(
            sc, from_=0.1, to=3.0, variable=self.controller.v_speed,
            progress_color=C_TEAL, button_color=C_TEAL
        )
        spd_slider.pack(fill="x", padx=2, pady=(0, 6))

        def _apply_spd_num(val_str):
            try:
                v = max(0.1, min(5.0, float(val_str)))
                self.controller.v_speed.set(v)
                self.controller._apply_speed(v)
                spd_ent.delete(0, "end")
                spd_ent.insert(0, f"{v:.2f}")
            except ValueError:
                pass

        spd_slider.configure(command=lambda v: (
            spd_ent.delete(0, "end"),
            spd_ent.insert(0, f"{v:.2f}"),
            self.controller._apply_speed(v)
        ))
        spd_ent.bind("<Return>", lambda e: _apply_spd_num(spd_ent.get()))
        spd_ent.bind("<FocusOut>", lambda e: _apply_spd_num(spd_ent.get()))

        self._props_info(sc, clip)

    # ── Text / Subtitle Clip Properties (Individual Customization) ────────────
    def _props_clip_text(self, sc, clip, is_subtitle=False):
        """Individual clip text customization panel."""
        accent = C_AMBER if is_subtitle else C_PINK

        # Text Content
        if is_subtitle:
            self._plbl(sc, "◉ ข้อความซับ", accent)
            txt_box = ctk.CTkTextbox(
                sc, height=64, corner_radius=8, fg_color=PANEL_MID,
                border_color=accent, border_width=1, text_color=TXT_W,
                font=ctk.CTkFont(family="Segoe UI", size=11), wrap="word"
            )
            txt_box.pack(fill="x", padx=4, pady=(0, 2))
            current_text = clip.get("sub_text", clip.get("name", ""))
            txt_box.insert("1.0", current_text)

            def _save_sub():
                t = txt_box.get("1.0", "end").strip()
                if not t:
                    return
                clip["sub_text"] = t
                clip["name"] = t[:24]
                for seg in self.controller.segments:
                    if abs(seg["start"] - clip.get("tl", 0)) < 0.1:
                        seg["text"] = t
                        break
                self.controller._push_undo()
                self.controller._draw_tl()
                self.controller._refresh_preview()

            txt_box.bind("<Control-Return>", lambda e: _save_sub())
            txt_box.bind("<FocusOut>", lambda e: _save_sub())
            ctk.CTkButton(
                sc, text="✓ บันทึก", height=22, corner_radius=6,
                fg_color=accent, hover_color=_dark(accent),
                font=ctk.CTkFont(size=9, weight="bold"), command=_save_sub
            ).pack(fill="x", padx=4, pady=(0, 6))
        else:
            self._plbl(sc, "◉ ข้อความ", accent)
            tv = tk.StringVar(value=clip.get("name", ""))

            def _on_txt_edit(*args):
                clip["name"] = tv.get()
                self.controller._draw_tl()
                self.controller._refresh_preview()

            tv.trace_add("write", _on_txt_edit)
            e = ctk.CTkEntry(sc, textvariable=tv, height=28, corner_radius=6,
                             fg_color=PANEL_MID, border_color=accent)
            e.pack(fill="x", padx=4, pady=(0, 6))
            e.bind("<FocusOut>", lambda ev: self.controller._push_undo())
            e.bind("<Return>", lambda ev: (self.controller._push_undo(), sc.focus_set()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=(2, 4))

        # Font Family
        self._plbl(sc, "ฟอนต์")
        font_row = ctk.CTkFrame(sc, fg_color="transparent")
        font_row.pack(fill="x", pady=2)
        font_var = tk.StringVar(value=clip.get("font_name", "Tahoma"))

        def _on_font(val):
            clip["font_name"] = val
            if is_subtitle:
                self.controller.style.font_name = val
            self.controller._refresh_preview()

        all_fonts = get_all_fonts()
        ctk.CTkOptionMenu(
            font_row, values=all_fonts, variable=font_var,
            width=220, height=26, corner_radius=6,
            fg_color=PANEL_MID, button_color=PANEL_HOV,
            font=ctk.CTkFont(size=9), command=_on_font,
        ).pack(fill="x")

        # Bold / Italic
        style_row = ctk.CTkFrame(sc, fg_color="transparent")
        style_row.pack(fill="x", pady=3)
        bold_val   = tk.BooleanVar(value=bool(clip.get("bold",   False)))
        italic_val = tk.BooleanVar(value=bool(clip.get("italic", False)))

        def _toggle_bold():
            bold_val.set(not bold_val.get())
            clip["bold"] = bold_val.get()
            if is_subtitle:
                self.controller.style.bold = bold_val.get()
            bold_btn.configure(fg_color=accent if bold_val.get() else PANEL_MID)
            self.controller._refresh_preview()

        def _toggle_italic():
            italic_val.set(not italic_val.get())
            clip["italic"] = italic_val.get()
            if is_subtitle:
                self.controller.style.italic = italic_val.get()
            italic_btn.configure(fg_color=accent if italic_val.get() else PANEL_MID)
            self.controller._refresh_preview()

        bold_btn = ctk.CTkButton(
            style_row, text="B", width=42, height=26, corner_radius=6,
            fg_color=accent if bold_val.get() else PANEL_MID,
            hover_color=PANEL_HOV, font=ctk.CTkFont(size=11, weight="bold"),
            command=_toggle_bold
        )
        bold_btn.pack(side="left", padx=(0, 4))

        italic_btn = ctk.CTkButton(
            style_row, text="I", width=42, height=26, corner_radius=6,
            fg_color=accent if italic_val.get() else PANEL_MID,
            hover_color=PANEL_HOV, font=ctk.CTkFont(family="Georgia", size=11),
            command=_toggle_italic
        )
        italic_btn.pack(side="left")

        # Font Size (px)
        sz_row = ctk.CTkFrame(sc, fg_color="transparent")
        sz_row.pack(fill="x", pady=2)
        ctk.CTkLabel(sz_row, text="ขนาด (px)",
                     font=ctk.CTkFont(size=10), text_color=TXT_L, width=64).pack(side="left")
        default_sz = getattr(self.controller.style, "font_size", 44) if is_subtitle else 44
        sz_ent = ctk.CTkEntry(sz_row, width=60, height=26, corner_radius=6,
                               font=ctk.CTkFont(size=10, weight="bold"))
        sz_ent.insert(0, str(clip.get("font_size", default_sz)))
        sz_ent.pack(side="right")

        def _apply_sz(val_str):
            try:
                v = max(8, min(200, int(float(val_str))))
                clip["font_size"] = v
                if is_subtitle:
                    self.controller.style.font_size = v
                sz_ent.delete(0, "end")
                sz_ent.insert(0, str(v))
                self.controller._refresh_preview()
            except ValueError:
                pass

        sz_ent.bind("<Return>", lambda e: _apply_sz(sz_ent.get()))
        sz_ent.bind("<FocusOut>", lambda e: _apply_sz(sz_ent.get()))

        # Letter Spacing (px)
        lsp_row = ctk.CTkFrame(sc, fg_color="transparent")
        lsp_row.pack(fill="x", pady=2)
        ctk.CTkLabel(lsp_row, text="ระยะห่างอักษร",
                     font=ctk.CTkFont(size=10), text_color=TXT_L, width=80).pack(side="left")
        default_lsp = getattr(self.controller.style, "letter_spacing", 0) if is_subtitle else 0
        lsp_ent = ctk.CTkEntry(lsp_row, width=60, height=26, corner_radius=6,
                               font=ctk.CTkFont(size=10, weight="bold"))
        lsp_ent.insert(0, str(clip.get("letter_spacing", default_lsp)))
        lsp_ent.pack(side="right")

        def _apply_lsp(val_str):
            try:
                v = max(0, min(60, int(float(val_str))))
                clip["letter_spacing"] = v
                if is_subtitle:
                    self.controller.style.letter_spacing = v
                lsp_ent.delete(0, "end")
                lsp_ent.insert(0, str(v))
                self.controller._refresh_preview()
            except ValueError:
                pass

        lsp_ent.bind("<Return>", lambda e: _apply_lsp(lsp_ent.get()))
        lsp_ent.bind("<FocusOut>", lambda e: _apply_lsp(lsp_ent.get()))

        # Color (#hex) + Swatch + Color Wheel
        self._plbl(sc, "สี (#hex)")
        color_row = ctk.CTkFrame(sc, fg_color="transparent")
        color_row.pack(fill="x", pady=2)
        cv = tk.StringVar(value=clip.get("font_color", "#ffffff"))

        def _apply_color_from_val(c):
            if not c.startswith("#"):
                c = "#" + c
            clip["font_color"] = c
            if is_subtitle:
                self.controller.style.font_color = c
            cv.set(c)
            try:
                cswatch.configure(bg=c)
            except Exception:
                pass
            self.controller._refresh_preview()

        try:
            cswatch = tk.Canvas(color_row, width=24, height=24,
                                bg=clip.get("font_color", "#ffffff"),
                                highlightthickness=1, highlightbackground="#334155")
            cswatch.pack(side="left", padx=(0, 4))
            cswatch.bind("<Button-1>", lambda e: ColorWheelDialog(
                self.winfo_toplevel(), initial_color=cv.get(), on_pick=_apply_color_from_val
            ))
        except Exception:
            pass

        ctk.CTkButton(
            color_row, text="🎨", width=28, height=26, corner_radius=6,
            fg_color=PANEL_MID, hover_color=PANEL_HOV,
            command=lambda: ColorWheelDialog(
                self.winfo_toplevel(), initial_color=cv.get(), on_pick=_apply_color_from_val
            )
        ).pack(side="left", padx=(0, 4))

        ce = ctk.CTkEntry(color_row, textvariable=cv, height=26, corner_radius=6,
                          fg_color=PANEL_MID, width=120)
        ce.pack(side="left")
        ce.bind("<Return>", lambda e: _apply_color_from_val(cv.get()))
        ce.bind("<FocusOut>", lambda e: _apply_color_from_val(cv.get()))

        # Alignment (Left, Center, Right)
        self._plbl(sc, "การจัดตำแหน่ง (Align)")
        align_row = ctk.CTkFrame(sc, fg_color="transparent")
        align_row.pack(fill="x", pady=2)

        cur_align = clip.get("align", getattr(self.controller.style, "align", "center") if is_subtitle else "center")
        align_var = tk.StringVar(value=cur_align)

        def _set_align(mode):
            align_var.set(mode)
            clip["align"] = mode
            if is_subtitle:
                self.controller.style.align = mode
            btn_l.configure(fg_color=accent if mode == "left" else PANEL_MID)
            btn_c.configure(fg_color=accent if mode == "center" else PANEL_MID)
            btn_r.configure(fg_color=accent if mode == "right" else PANEL_MID)
            self.controller._push_undo()
            self.controller._refresh_preview()

        btn_l = ctk.CTkButton(
            align_row, text="⬅ Left", width=68, height=26, corner_radius=6,
            fg_color=accent if cur_align == "left" else PANEL_MID,
            hover_color=PANEL_HOV, font=ctk.CTkFont(size=9, weight="bold"),
            command=lambda: _set_align("left")
        )
        btn_l.pack(side="left", padx=(0, 3), fill="x", expand=True)

        btn_c = ctk.CTkButton(
            align_row, text="☰ Center", width=68, height=26, corner_radius=6,
            fg_color=accent if cur_align == "center" else PANEL_MID,
            hover_color=PANEL_HOV, font=ctk.CTkFont(size=9, weight="bold"),
            command=lambda: _set_align("center")
        )
        btn_c.pack(side="left", padx=3, fill="x", expand=True)

        btn_r = ctk.CTkButton(
            align_row, text="➡ Right", width=68, height=26, corner_radius=6,
            fg_color=accent if cur_align == "right" else PANEL_MID,
            hover_color=PANEL_HOV, font=ctk.CTkFont(size=9, weight="bold"),
            command=lambda: _set_align("right")
        )
        btn_r.pack(side="left", padx=(3, 0), fill="x", expand=True)

        # Position X and Y
        self._plbl(sc, "พิกัดตำแหน่ง (Position X, Y)")

        # X Row
        pos_x_row = ctk.CTkFrame(sc, fg_color="transparent")
        pos_x_row.pack(fill="x", pady=2)
        ctk.CTkLabel(pos_x_row, text="X (0-100%)", font=ctk.CTkFont(size=10), text_color=TXT_L, width=70).pack(side="left")

        cur_x_pct = int(round(float(clip.get("custom_x", 0.5)) * 100))
        x_ent = ctk.CTkEntry(pos_x_row, width=45, height=24, corner_radius=5, font=ctk.CTkFont(size=9, weight="bold"))
        x_ent.insert(0, str(cur_x_pct))
        x_ent.pack(side="right")

        def _on_x_change(val):
            try:
                v = max(0, min(100, int(float(val))))
                clip["custom_x"] = v / 100.0
                if is_subtitle:
                    self.controller.style.position = "custom"
                    self.controller.style.custom_x = v / 100.0
                x_ent.delete(0, "end"); x_ent.insert(0, str(v))
                self.controller._refresh_preview()
            except ValueError: pass

        x_slider = ctk.CTkSlider(pos_x_row, from_=0, to=100, number_of_steps=100,
                                progress_color=accent, button_color=accent, width=120)
        x_slider.set(cur_x_pct)
        x_slider.pack(side="left", fill="x", expand=True, padx=(2, 4))
        x_slider.configure(command=lambda v: _on_x_change(v))
        x_ent.bind("<Return>", lambda e: (_on_x_change(x_ent.get()), self.controller._push_undo()))
        x_ent.bind("<FocusOut>", lambda e: (_on_x_change(x_ent.get()), self.controller._push_undo()))

        # Y Row
        pos_y_row = ctk.CTkFrame(sc, fg_color="transparent")
        pos_y_row.pack(fill="x", pady=2)
        ctk.CTkLabel(pos_y_row, text="Y (0-100%)", font=ctk.CTkFont(size=10), text_color=TXT_L, width=70).pack(side="left")

        default_y = 0.85 if is_subtitle else 0.2
        cur_y_pct = int(round(float(clip.get("custom_y", default_y)) * 100))
        y_ent = ctk.CTkEntry(pos_y_row, width=45, height=24, corner_radius=5, font=ctk.CTkFont(size=9, weight="bold"))
        y_ent.insert(0, str(cur_y_pct))
        y_ent.pack(side="right")

        def _on_y_change(val):
            try:
                v = max(0, min(100, int(float(val))))
                clip["custom_y"] = v / 100.0
                if is_subtitle:
                    self.controller.style.position = "custom"
                    self.controller.style.custom_y = v / 100.0
                y_ent.delete(0, "end"); y_ent.insert(0, str(v))
                self.controller._refresh_preview()
            except ValueError: pass

        y_slider = ctk.CTkSlider(pos_y_row, from_=0, to=100, number_of_steps=100,
                                progress_color=accent, button_color=accent, width=120)
        y_slider.set(cur_y_pct)
        y_slider.pack(side="left", fill="x", expand=True, padx=(2, 4))
        y_slider.configure(command=lambda v: _on_y_change(v))
        y_ent.bind("<Return>", lambda e: (_on_y_change(y_ent.get()), self.controller._push_undo()))
        y_ent.bind("<FocusOut>", lambda e: (_on_y_change(y_ent.get()), self.controller._push_undo()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=(6, 4))

        # Apply to ALL subtitles button
        if is_subtitle:
            def _apply_to_all():
                fn  = clip.get("font_name",  getattr(self.controller.style, "font_name", "Tahoma"))
                fs  = clip.get("font_size",  getattr(self.controller.style, "font_size", 44))
                fc  = clip.get("font_color", "#ffffff")
                bl  = clip.get("bold",   False)
                it  = clip.get("italic", False)
                lsp = clip.get("letter_spacing", 0)
                al  = clip.get("align", "center")
                cx  = clip.get("custom_x", 0.5)
                cy  = clip.get("custom_y", 0.85)

                self.controller.style.font_name      = fn
                self.controller.style.font_size      = fs
                self.controller.style.font_color     = fc
                self.controller.style.bold           = bl
                self.controller.style.italic         = it
                self.controller.style.letter_spacing = lsp
                self.controller.style.align          = al
                self.controller.style.position       = "custom"
                self.controller.style.custom_x       = cx
                self.controller.style.custom_y       = cy

                for sub_clip in self.controller.tracks.get("subtitle", []):
                    sub_clip["font_name"]      = fn
                    sub_clip["font_size"]      = fs
                    sub_clip["font_color"]     = fc
                    sub_clip["bold"]           = bl
                    sub_clip["italic"]         = it
                    sub_clip["letter_spacing"] = lsp
                    sub_clip["align"]          = al
                    sub_clip["custom_x"]       = cx
                    sub_clip["custom_y"]       = cy

                self.controller._push_undo()
                self.controller._refresh_preview()
                self.controller._status(f"✓ สไตล์ & ตำแหน่งถูก apply ไปทุก subtitle ({len(self.controller.tracks.get('subtitle', []))} คลิป)")

            ctk.CTkButton(
                sc,
                text="⊙ Apply Font/Style to ALL Subs",
                height=28, corner_radius=8,
                fg_color=C_AMBER, hover_color=_dark(C_AMBER),
                font=ctk.CTkFont(size=9, weight="bold"),
                command=_apply_to_all
            ).pack(fill="x", padx=4, pady=(0, 4))

        self._plbl(sc, "◎ ลากบนวิดีโอหรือปรับแกน X,Y เพื่อเลื่อนตำแหน่ง", C_AMBER)
        self._props_info(sc, clip)

    # ── Info Block ────────────────────────────────────────────────────────────
    def _props_info(self, sc, clip):
        """Clip metadata block displaying filename, duration, and starting timecode."""
        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=(10, 4))
        dur = (clip["end"] - clip["start"]) / max(clip.get("speed", 1.0), 0.01)
        ctk.CTkLabel(
            sc,
            text=f"Name: {clip.get('name', '')[:18]}\nDur:  {_ft(dur)}\nPos:  {_ft(clip.get('tl', 0))}",
            font=ctk.CTkFont(size=8), text_color=TXT_G,
            justify="left"
        ).pack(anchor="w", padx=4)

    # ── Tracks Mute / Solo Dashboard ──────────────────────────────────────────
    def _build_track_controls(self):
        """Draw and update the tracks mute/solo dashboard at the bottom of properties panel."""
        for w in self._track_ctrl_frame.winfo_children():
            w.destroy()

        for key, lbl, col, _h, _k in self.controller._all_track_rows():
            if key == "__empty_layer__":
                continue
            muted = self.controller._muted.get(key, False)
            soloed = self.controller._solo_key == key
            row_bg = "#1a0a0a" if muted else "#0a1a2a" if soloed else PANEL_MID
            lbl_c = TXT_G if muted else C_AMBER if soloed else col

            row = ctk.CTkFrame(self._track_ctrl_frame, fg_color=row_bg, corner_radius=6, height=26)
            row.pack(fill="x", pady=2)
            row.pack_propagate(False)

            ctk.CTkLabel(
                row, text=lbl, font=ctk.CTkFont(size=8, weight="bold"),
                text_color=lbl_c, width=55
            ).pack(side="left", padx=6)

            if muted:
                ctk.CTkLabel(row, text="MUTED", font=ctk.CTkFont(size=7), text_color=C_RED).pack(side="left")
            elif soloed:
                ctk.CTkLabel(row, text="SOLO", font=ctk.CTkFont(size=7), text_color=C_AMBER).pack(side="left")

            # Mute Button
            m_col = C_RED if muted else PANEL_LIGHT
            ctk.CTkButton(
                row, text="M", width=22, height=18, corner_radius=4,
                fg_color=m_col, hover_color=PANEL_HOV,
                font=ctk.CTkFont(size=7),
                command=lambda k=key: self.controller._toggle_mute_track(k)
            ).pack(side="right", padx=(0, 4))

            # Solo Button
            s_col = C_AMBER if soloed else PANEL_LIGHT
            ctk.CTkButton(
                row, text="S", width=22, height=18, corner_radius=4,
                fg_color=s_col, hover_color=C_BLUE,
                font=ctk.CTkFont(size=7),
                command=lambda k=key: self.controller._solo_track(k)
            ).pack(side="right", padx=2)

    def _psec(self, text):
        ctk.CTkLabel(
            self, text=text,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TXT_G
        ).pack(anchor="w", padx=12, pady=(12, 3))
