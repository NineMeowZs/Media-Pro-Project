"""editor_properties.py – Context-sensitive clip properties panels and track control panels"""

import tkinter as tk
import customtkinter as ctk

from editor_utils import (
    PANEL_DARK, PANEL_MID, PANEL_LIGHT, PANEL_HOV, BORD, TXT_W, TXT_G, TXT_L,
    C_BLUE, C_TEAL, C_GREEN, C_AMBER, C_PINK, C_RED,
    _ft, _dark, _bright, HAS_SUBTITLES
)
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
            ctk.CTkLabel(
                sc, text="เลือก clip ใน timeline\nเพื่อปรับการตั้งค่า",
                font=ctk.CTkFont(family="Segoe UI", size=11), text_color=TXT_G,
                justify="center"
            ).pack(pady=50)
            return

        clip = items[self.controller.sel_idx]
        kind = self.controller._track_kind(self.controller.sel_track)

        if self.controller.sel_track == "subtitle":
            self._props_subtitle(sc, clip)
        elif clip.get("path", "") == "":
            self._props_text(sc, clip)
        elif kind == "audio":
            self._props_audio(sc, clip)
        else:
            self._props_video(sc, clip)

    def _plbl(self, sc, text, col=None):
        ctk.CTkLabel(
            sc, text=text, font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=col or C_TEAL
        ).pack(anchor="w", pady=(10, 2))

    def _props_video(self, sc, clip):
        """Video properties: Transform (Scale/Rotate), Speed, and Volume with direct numeric typing."""
        # 1. Transform Section (Scale, Rotate)
        self._plbl(sc, "Transform")
        
        scale_val = int(clip.get("scale", 1.0) * 100)
        sc_row = ctk.CTkFrame(sc, fg_color="transparent")
        sc_row.pack(fill="x", pady=2)
        ctk.CTkLabel(sc_row, text="Scale (%)", font=ctk.CTkFont(size=10), text_color=TXT_L).pack(side="left")
        
        sc_ent = ctk.CTkEntry(sc_row, width=54, height=24, corner_radius=6, font=ctk.CTkFont(size=10, weight="bold"))
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

        sc_slider.configure(command=lambda v: (sc_ent.delete(0, "end"), sc_ent.insert(0, str(int(v))), clip.update({"scale": int(v)/100.0}), self.controller._render(self.controller.fi)))
        sc_ent.bind("<Return>", lambda e: _apply_scale(sc_ent.get()))
        sc_ent.bind("<FocusOut>", lambda e: _apply_scale(sc_ent.get()))

        # Rotate
        rot_val = clip.get("rotate", 0)
        rot_row = ctk.CTkFrame(sc, fg_color="transparent")
        rot_row.pack(fill="x", pady=2)
        ctk.CTkLabel(rot_row, text="Rotate (°)", font=ctk.CTkFont(size=10), text_color=TXT_L).pack(side="left")
        
        rot_ent = ctk.CTkEntry(rot_row, width=54, height=24, corner_radius=6, font=ctk.CTkFont(size=10, weight="bold"))
        rot_ent.insert(0, str(rot_val))
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

        rot_slider.configure(command=lambda v: (rot_ent.delete(0, "end"), rot_ent.insert(0, str(int(v))), clip.update({"rotate": int(v)}), self.controller._render(self.controller.fi)))
        rot_ent.bind("<Return>", lambda e: _apply_rot(rot_ent.get()))
        rot_ent.bind("<FocusOut>", lambda e: _apply_rot(rot_ent.get()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=4)

        # 2. Speed Section
        self._plbl(sc, "Speed")
        cur_spd = clip.get("speed", 1.0)
        self.controller.v_speed.set(cur_spd)
        
        spd_row = ctk.CTkFrame(sc, fg_color="transparent")
        spd_row.pack(fill="x", pady=2)
        ctk.CTkLabel(spd_row, text="Playback Speed", font=ctk.CTkFont(size=10), text_color=TXT_L).pack(side="left")
        
        spd_ent = ctk.CTkEntry(spd_row, width=54, height=24, corner_radius=6, font=ctk.CTkFont(size=10, weight="bold"))
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

        spd_slider.configure(command=lambda v: (spd_ent.delete(0, "end"), spd_ent.insert(0, f"{v:.2f}"), self.controller._apply_speed(v)))
        spd_ent.bind("<Return>", lambda e: _apply_spd_num(spd_ent.get()))
        spd_ent.bind("<FocusOut>", lambda e: _apply_spd_num(spd_ent.get()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=4)

        # 3. Volume Section
        self._plbl(sc, "Volume")
        cur_vol = clip.get("volume", 1.0)
        self.controller.v_vol.set(cur_vol)

        vol_row = ctk.CTkFrame(sc, fg_color="transparent")
        vol_row.pack(fill="x", pady=2)
        ctk.CTkLabel(vol_row, text="Audio Level (%)", font=ctk.CTkFont(size=10), text_color=TXT_L).pack(side="left")
        
        vol_ent = ctk.CTkEntry(vol_row, width=54, height=24, corner_radius=6, font=ctk.CTkFont(size=10, weight="bold"))
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

        vol_slider.configure(command=lambda v: (vol_ent.delete(0, "end"), vol_ent.insert(0, str(int(v * 100))), self.controller._apply_vol(v)))
        vol_ent.bind("<Return>", lambda e: _apply_vol_num(vol_ent.get()))
        vol_ent.bind("<FocusOut>", lambda e: _apply_vol_num(vol_ent.get()))

        self._props_info(sc, clip)

    def _props_audio(self, sc, clip):
        """Audio clip properties: Volume & Speed controls with numeric entry typing."""
        self._plbl(sc, "Volume")
        cur_vol = clip.get("volume", 1.0)
        self.controller.v_vol.set(cur_vol)

        vol_row = ctk.CTkFrame(sc, fg_color="transparent")
        vol_row.pack(fill="x", pady=2)
        ctk.CTkLabel(vol_row, text="Audio Level (%)", font=ctk.CTkFont(size=10), text_color=TXT_L).pack(side="left")
        
        vol_ent = ctk.CTkEntry(vol_row, width=54, height=24, corner_radius=6, font=ctk.CTkFont(size=10, weight="bold"))
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

        vol_slider.configure(command=lambda v: (vol_ent.delete(0, "end"), vol_ent.insert(0, str(int(v * 100))), self.controller._apply_vol(v)))
        vol_ent.bind("<Return>", lambda e: _apply_vol_num(vol_ent.get()))
        vol_ent.bind("<FocusOut>", lambda e: _apply_vol_num(vol_ent.get()))

        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=4)

        # Speed
        self._plbl(sc, "Speed")
        cur_spd = clip.get("speed", 1.0)
        self.controller.v_speed.set(cur_spd)

        spd_row = ctk.CTkFrame(sc, fg_color="transparent")
        spd_row.pack(fill="x", pady=2)
        ctk.CTkLabel(spd_row, text="Audio Speed", font=ctk.CTkFont(size=10), text_color=TXT_L).pack(side="left")

        spd_ent = ctk.CTkEntry(spd_row, width=54, height=24, corner_radius=6, font=ctk.CTkFont(size=10, weight="bold"))
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

        spd_slider.configure(command=lambda v: (spd_ent.delete(0, "end"), spd_ent.insert(0, f"{v:.2f}"), self.controller._apply_speed(v)))
        spd_ent.bind("<Return>", lambda e: _apply_spd_num(spd_ent.get()))
        spd_ent.bind("<FocusOut>", lambda e: _apply_spd_num(spd_ent.get()))

        self._props_info(sc, clip)

    def _props_text(self, sc, clip):
        """Text clip properties: edit label text and font customizations."""
        self._plbl(sc, "ข้อความ", C_PINK)
        tv = tk.StringVar(value=clip.get("name", ""))

        def _on_txt_edit(*args):
            clip["name"] = tv.get()
            self.controller._draw_tl()
            self.controller._refresh_preview()

        tv.trace_add("write", _on_txt_edit)

        entry = ctk.CTkEntry(
            sc, textvariable=tv, height=28, corner_radius=6,
            fg_color=PANEL_MID, border_color=C_PINK
        )
        entry.pack(fill="x", padx=4, pady=(0, 6))

        # Push undo and lose focus on Enter, push undo on FocusOut
        entry.bind("<FocusOut>", lambda e: self.controller._push_undo())
        entry.bind("<Return>", lambda e: (
            self.controller._push_undo(),
            sc.focus_set()
        ))

        self._plbl(sc, "ขนาดฟอนต์")
        sz_v = tk.IntVar(value=clip.get("font_size", 36))
        sz_lbl = ctk.CTkLabel(
            sc, text=f"{sz_v.get()}px",
            font=ctk.CTkFont(size=9), text_color=TXT_G
        )
        ctk.CTkSlider(
            sc, from_=12, to=96, variable=sz_v,
            progress_color=C_PINK, button_color=C_PINK,
            command=lambda v: (
                clip.update({"font_size": int(float(v))}),
                sz_lbl.configure(text=f"{int(float(v))}px"),
                self.controller._refresh_preview()
            )
        ).pack(fill="x", padx=4)
        sz_lbl.pack(anchor="e", padx=4)

        self._plbl(sc, "สี (#hex)")
        cv = tk.StringVar(value=clip.get("font_color", "#ffffff"))
        ce = ctk.CTkEntry(sc, textvariable=cv, height=26, corner_radius=6, fg_color=PANEL_MID)
        ce.pack(fill="x", padx=4, pady=(0, 4))
        ce.bind("<Return>", lambda e: (
            clip.update({"font_color": cv.get()}),
            self.controller._refresh_preview()
        ))

        self._plbl(sc, "◎ ลากบนวิดีโอเพื่อย้าย", C_AMBER)
        self._props_info(sc, clip)

    def _props_subtitle(self, sc, clip):
        """Subtitle clip properties: text editor and global subtitle font sizes."""
        self._plbl(sc, "ข้อความซับ", C_AMBER)
        sv = tk.StringVar(value=clip.get("sub_text", clip.get("name", "")))
        ctk.CTkEntry(
            sc, textvariable=sv, height=28, corner_radius=6,
            fg_color=PANEL_MID, border_color=C_AMBER
        ).pack(fill="x", padx=4, pady=(0, 3))

        def _save_sub():
            t = sv.get().strip()
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

        ctk.CTkButton(
            sc, text="✓ บันทึก", height=24, corner_radius=6,
            fg_color=C_AMBER, hover_color=_dark(C_AMBER),
            font=ctk.CTkFont(size=9, weight="bold"),
            command=_save_sub
        ).pack(fill="x", padx=4, pady=(0, 6))

        self._plbl(sc, "ขนาดฟอนต์ (ทั้งหมด)")
        sz_v = tk.IntVar(value=self.controller.style.font_size)
        sz_lbl = ctk.CTkLabel(
            sc, text=f"{sz_v.get()}px",
            font=ctk.CTkFont(size=9), text_color=TXT_G
        )
        ctk.CTkSlider(
            sc, from_=12, to=72, variable=sz_v,
            progress_color=C_AMBER, button_color=C_AMBER,
            command=lambda v: (
                setattr(self.controller.style, "font_size", int(float(v))),
                sz_lbl.configure(text=f"{int(float(v))}px"),
                self.controller._refresh_preview()
            )
        ).pack(fill="x", padx=4)
        sz_lbl.pack(anchor="e", padx=4)

        self._plbl(sc, "◎ ลากบนวิดีโอเพื่อย้าย", C_AMBER)
        self._props_info(sc, clip)

    def _props_info(self, sc, clip):
        """Clip metadata block displaying filename, duration, and starting timecode."""
        ctk.CTkFrame(sc, height=1, fg_color=BORD).pack(fill="x", pady=(10, 4))
        dur = (clip["end"] - clip["start"]) / max(clip.get("speed", 1.0), 0.01)
        ctk.CTkLabel(
            sc,
            text=f"Name: {clip['name'][:18]}\nDur:  {_ft(dur)}\nPos:  {_ft(clip.get('tl', 0))}",
            font=ctk.CTkFont(size=8), text_color=TXT_G,
            justify="left"
        ).pack(anchor="w", padx=4)

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
