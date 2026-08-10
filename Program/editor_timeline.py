"""editor_timeline.py – Timeline panel UI component and clip editing interactions"""

import copy
import os
import random
import tkinter as tk
import customtkinter as ctk

from editor_utils import (
    PANEL_DARK, PANEL_MID, BG_DARK, TL_BG, TL_ROW_BG, TL_RULER, BORD, TXT_W, TXT_G, TXT_L,
    C_BLUE, C_RED, C_AMBER, C_TEAL, C_GREEN, C_PURPLE,
    RULER_H, TGAP, LABEL_W, EDGE_PX, TARGET_FPS, SNAP_PX, FADE_ZONE,
    _ft, _bright, _dark, _nice_step
)


class TimelinePanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color=PANEL_DARK, corner_radius=12, border_width=0)
        self.controller = controller

        # Drag state variables
        self._dm = None   # drag mode: move/trim_l/trim_r/scrub/rubber
        self._dtk = None  # drag track key
        self._di = -1     # drag index
        self._dx0 = 0.0
        self._tl0 = 0.0
        self._st0 = 0.0
        self._en0 = 0.0
        # Rubber-band selection state
        self._rb_x0 = 0.0
        self._rb_y0 = 0.0
        self._rb_rect = None  # canvas item ID

        self._build_ui()

    def _build_ui(self):
        # 1. Timeline Toolbar
        tb = ctk.CTkFrame(self, height=26, fg_color=BG_DARK, corner_radius=0)
        tb.pack(fill="x")
        tb.pack_propagate(False)

        ctk.CTkLabel(
            tb, text="TIMELINE",
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            text_color=TXT_G
        ).pack(side="left", padx=12)

        ctk.CTkLabel(tb, text="Zoom", font=ctk.CTkFont(size=9), text_color=TXT_G).pack(side="right", padx=(0, 4))
        ctk.CTkSlider(
            tb, from_=0.2, to=14.0, width=100, variable=self.controller.v_zoom,
            progress_color=C_BLUE, button_color=C_BLUE,
            command=lambda v: self._draw_tl()
        ).pack(side="right", padx=(0, 10), pady=4)

        # 2. Main Timeline Body
        body = tk.Frame(self, bg=PANEL_DARK)
        body.pack(fill="both", expand=True)

        # Label Canvas (Sidebar next to main canvas)
        self._lcc = tk.Canvas(body, bg=PANEL_DARK, highlightthickness=0, width=LABEL_W)
        self._lcc.pack(side="left", fill="y")

        # Canvas for Drawing Clips
        self._tlc = tk.Canvas(body, bg=TL_BG, highlightthickness=0, height=230)
        self._tlc.pack(side="left", fill="both", expand=True)

        # Sync vertical scroll of labels and clips canvases
        def _on_yview(*args):
            self._lcc.yview(*args)
            self._tlc.yview(*args)

        vs = tk.Scrollbar(body, orient="vertical", command=_on_yview)
        vs.pack(side="right", fill="y")

        def _on_tlc_yscroll(*args):
            vs.set(*args)
            self._lcc.yview_moveto(args[0])

        self._tlc.configure(yscrollcommand=_on_tlc_yscroll)

        # Horizontal scrollbar
        hs = tk.Scrollbar(self, orient="horizontal", command=self._tlc.xview)
        hs.pack(fill="x")
        self._tlc.configure(xscrollcommand=hs.set)

        # Interaction Bindings
        self._tlc.bind("<Button-1>",        self._tl_press)
        self._tlc.bind("<B1-Motion>",       self._tl_drag)
        self._tlc.bind("<ButtonRelease-1>",  self._tl_release)
        self._tlc.bind("<Button-3>",        self._tl_rclick)
        self._tlc.bind("<Configure>",       lambda e: self._draw_tl())
        self._tlc.bind("<Motion>",          self._tl_hover)

        # Sync scrolling on mouse wheel
        self._tlc.bind("<MouseWheel>",       lambda e: self._tlc.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self._tlc.bind("<Control-MouseWheel>", self._tl_zoom)
        self._lcc.bind("<MouseWheel>",       lambda e: self._tlc.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self._tlc.bind("<Shift-MouseWheel>",  lambda e: self._tlc.xview_scroll(int(-1 * (e.delta / 120)), "units"))

    def _scale(self):
        W = self._tlc.winfo_width()
        total = max(20.0, self.controller._dur() * 1.3 + 5)
        return (W - 10) / total * self.controller.v_zoom.get()

    def _rebuild_label_column(self):
        """No-op stub – drawing is handled inside _draw_tl directly."""
        self._draw_tl()

    def _draw_tl(self):
        """Full timeline render loop (grid tracks, clips, waveforms, and playhead)."""
        if not hasattr(self, "_tlc"):
            return
        c = self._tlc
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 10:
            return
        c.delete("all")

        # Clear and redraw label canvas
        self._lcc.delete("all")

        total = max(20.0, self.controller._dur() * 1.3 + 5)
        scale = self._scale()
        cw = max(W, int(total * scale) + 120)

        # Draw Ruler on main canvas
        c.create_rectangle(0, 0, cw, RULER_H, fill=TL_RULER, outline="")
        step = _nice_step(total / self.controller.v_zoom.get())
        t = 0.0
        while t <= total + step:
            x = t * scale
            maj = (round(t / step) * step - t) < 0.001 if step else True
            c.create_line(x, RULER_H - (9 if maj else 4), x, RULER_H, fill="#363650")
            if maj:
                c.create_text(
                    x + 3, RULER_H // 2, text=_ft(t),
                    fill=TXT_G, anchor="w", font=("Courier", 7)
                )
            t = round(t + step / 2, 6)

        # Draw Ruler/Header on label canvas
        self._lcc.create_rectangle(0, 0, LABEL_W, RULER_H, fill=TL_RULER, outline="")
        self._lcc.create_text(
            LABEL_W // 2, RULER_H // 2, text="TRACKS",
            fill=TXT_G, font=("Helvetica", 8, "bold")
        )
        self._lcc.create_line(0, RULER_H, LABEL_W, RULER_H, fill=BORD)

        # Tracks — dynamic rows via _all_track_rows()
        y = RULER_H + 2
        for key, lbl, col, th, kind in self.controller._all_track_rows():
            if key == "__empty_layer__":
                continue
            row_h = th + TGAP * 2
            active = self.controller._is_active(key)
            row_bg = "#0a0a0d" if not active else TL_ROW_BG
            lbl_bg = "#0a0a0d" if not active else PANEL_MID

            # Draw row background on main canvas
            c.create_rectangle(0, y, cw, y + row_h, fill=row_bg, outline="")
            c.create_line(0, y + row_h, cw, y + row_h, fill=BORD)
            if key == "main":
                c.create_line(0, y, cw, y, fill="#252535", width=1)

            # Draw row background & label text on label canvas
            self._lcc.create_rectangle(0, y, LABEL_W, y + row_h, fill=lbl_bg, outline="")
            self._lcc.create_line(0, y + row_h, LABEL_W, y + row_h, fill=BORD)
            self._lcc.create_text(
                12, y + row_h // 2, text=lbl,
                fill=col, anchor="w", font=("Helvetica", 8, "bold")
            )

            # Muted/Solo badge on row
            if self.controller._muted.get(key):
                c.create_text(
                    8, y + row_h // 2, text="MUTED",
                    fill=C_RED, anchor="w", font=("Helvetica", 7, "bold")
                )
            elif self.controller._solo_key == key:
                c.create_text(
                    8, y + row_h // 2, text="SOLO",
                    fill=C_AMBER, anchor="w", font=("Helvetica", 7, "bold")
                )

            # Draw Clips
            for i, item in enumerate(self.controller.tracks.get(key, [])):
                dur = (item["end"] - item["start"]) / max(item["speed"], 0.01)
                tl = item.get("tl", 0.0)
                x1 = tl * scale
                x2 = (tl + dur) * scale
                ty1 = y + TGAP
                ty2 = y + TGAP + th
                sel = (self.controller.sel_track == key and self.controller.sel_idx == i)

                # Dim clip if track is muted/not active
                clip_col = _dark(col, 40) if not active else col

                # Shadow
                c.create_rectangle(x1 + 2, ty1 + 2, x2 + 2, ty2 + 2, fill="#030306", outline="")
                # Body
                c.create_rectangle(x1, ty1, x2, ty2, fill=clip_col, outline="")
                # Darker inner
                c.create_rectangle(x1 + 1, ty1 + 6, x2 - 1, ty2 - 1, fill=_dark(clip_col, 18), outline="")

                # Waveforms for Audio Tracks
                if kind == "audio":
                    self._draw_waveform(c, item, x1, ty1, x2, ty2, clip_col)

                # Overlay icon hints
                if kind in ("layer", "video") and key != "main" and x2 - x1 > 20:
                    c.create_rectangle(x1 + 2, ty1 + 2, x1 + 28, ty2 - 2, fill=_dark(clip_col, 30), outline="")

                # Sheen highlights
                c.create_rectangle(x1, ty1, x2, ty1 + 4, fill=_bright(clip_col), outline="")

                # Selection glow borders
                multi_sel = (key, i) in self.controller._multi_sel
                if sel:
                    c.create_rectangle(x1 - 1, ty1 - 1, x2 + 1, ty2 + 1, fill="", outline="#ffffff", width=2)
                    c.create_rectangle(x1 - 3, ty1 - 3, x2 + 3, ty2 + 3, fill="", outline=clip_col, width=1)
                    # Visual edge handles for trimming
                    c.create_rectangle(x1 - 3, ty1 + 3, x1 + 3, ty2 - 3, fill="#ffffff", outline="")
                    c.create_rectangle(x2 - 3, ty1 + 3, x2 + 3, ty2 - 3, fill="#ffffff", outline="")
                elif multi_sel:
                    c.create_rectangle(x1 - 1, ty1 - 1, x2 + 1, ty2 + 1, fill="", outline="#22d3ee", width=1)

                # Fade-in triangle
                fade_in = item.get("fade_in", 0.0)
                if fade_in > 0:
                    fx = x1 + fade_in * scale
                    c.create_polygon(x1, ty2, fx, ty2, x1, ty1 + th // 2, fill="#000000", outline="", stipple="gray50")

                # Fade-out triangle
                fade_out = item.get("fade_out", 0.0)
                if fade_out > 0:
                    fx = x2 - fade_out * scale
                    c.create_polygon(x2, ty2, fx, ty2, x2, ty1 + th // 2, fill="#000000", outline="", stipple="gray50")

                # Fade handles
                c.create_polygon(x1, ty1, x1 + FADE_ZONE, ty1, x1, ty1 + FADE_ZONE, fill=_bright(clip_col, 60), outline="")
                c.create_polygon(x2, ty1, x2 - FADE_ZONE, ty1, x2, ty1 + FADE_ZONE, fill=_bright(clip_col, 60), outline="")

                # Label texts
                if x2 - x1 > 16:
                    name = item.get("name", "")
                    name = name[:16] + "…" if len(name) > 16 else name
                    dur_str = _ft(dur)
                    dark_txt = key in ("main",)
                    tc_color = "#00111f" if dark_txt else "#ffffff"
                    c.create_text(
                        x1 + 7, ty1 + th // 2 - (5 if th > 30 else 0),
                        text=name, fill=tc_color, anchor="w", font=("Helvetica", 7, "bold")
                    )
                    if th > 28:
                        c.create_text(x1 + 7, ty1 + th // 2 + 8, text=dur_str, fill=tc_color, anchor="w", font=("Courier", 6))
                    if x2 - x1 > 70:
                        et = _ft(tl + dur)
                        bw = len(et) * 5 + 4
                        c.create_rectangle(x2 - bw - 2, ty1 + 2, x2 - 2, ty1 + 11, fill="#000000", outline="", stipple="gray50")
                        c.create_text(x2 - 4, ty1 + 6, text=et, fill="#dddddd", anchor="e", font=("Courier", 6))

                # Resize drag handles
                for ex in (x1, x2):
                    c.create_rectangle(ex - 3, ty1 + 4, ex + 3, ty2 - 4, fill="#ffffff", outline="")

            y += row_h

        # Playhead (ruler diamond indicator + center line)
        px = (self.controller.fi / float(TARGET_FPS)) * scale
        self._tl_ph_line = c.create_line(px, 0, px, max(H, y), fill=C_RED, width=1)
        self._tl_ph_cap = c.create_polygon(px - 6, 0, px + 6, 0, px + 2, 10, px - 2, 10, fill=C_RED, outline="")

        # Update scrollregions of both canvases dynamically
        total_h = y + 40
        self._tlc.configure(scrollregion=(0, 0, cw, max(H, total_h)))
        self._lcc.configure(scrollregion=(0, 0, LABEL_W, max(H, total_h)))

    def _draw_waveform(self, c, item, x1, ty1, x2, ty2, col):
        """Draw waveform amplitude bars for audio clips."""
        path = item.get("path", "")
        bars = self.controller._waveforms.get(path)

        clip_w = x2 - x1
        mid    = (ty1 + ty2) // 2
        amp    = (ty2 - ty1) // 2 - 3

        if bars is None:
            # Real waveform not ready yet — draw subtle placeholder lines
            bar_count = max(20, int(clip_w / 4))
            bar_w = max(1.0, clip_w / bar_count)
            for i in range(bar_count):
                bx = x1 + i * bar_w + bar_w / 2
                if bx > x2:
                    break
                c.create_line(bx, mid - 2, bx, mid + 2, fill=_bright(col, 20))
            return

        bar_w = max(1.0, clip_w / len(bars))
        for i, a in enumerate(bars):
            bx = x1 + i * bar_w
            if bx > x2:
                break
            hh = max(1, int(a * amp))
            c.create_line(bx, mid - hh, bx, mid + hh, fill=_bright(col, 20))

    def _tl_press(self, e):
        self.controller._stop()
        sc = self._scale()
        cx = self._tlc.canvasx(e.x)
        cy = self._tlc.canvasy(e.y)
        t_click = cx / sc

        # Check if clicking on/near ruler or playhead to scrub playhead
        ph_x = (self.controller.fi / float(TARGET_FPS)) * sc
        if cy <= RULER_H + 10 or abs(cx - ph_x) <= 16:
            self._dm = "scrub"
            self.controller.fi = max(0, int(t_click * TARGET_FPS))
            self.controller._render(self.controller.fi)
            self._draw_tl()
            return

        hit_k = hit_i = None
        mode = "scrub"
        y = RULER_H + 2
        for key, lbl, col, th, kind in self.controller._all_track_rows():
            row_h = th + TGAP * 2
            if y <= cy <= y + row_h and key != "__empty_layer__":
                for i, item in enumerate(self.controller.tracks.get(key, [])):
                    dur = (item["end"] - item["start"]) / max(item["speed"], 0.01)
                    tl = item.get("tl", 0.0)
                    x1 = tl * sc
                    x2 = (tl + dur) * sc
                    if x1 - 12 <= cx <= x2 + 12:
                        hit_k = key
                        hit_i = i
                        clip_w = x2 - x1
                        if clip_w <= 30:
                            if cx < (x1 + x2) / 2.0:
                                mode = "trim_l"
                            else:
                                mode = "trim_r"
                        else:
                            if cx <= x1 + 12 or abs(cx - x1) <= 12:
                                mode = "trim_l"
                            elif cx >= x2 - 12 or abs(cx - x2) <= 12:
                                mode = "trim_r"
                            else:
                                mode = "move"
                        break
                break
            y += row_h

        if hit_k is not None:
            # Shift+click: toggle item in multi_sel without clearing others
            if e.state & 1:  # Shift held
                entry = (hit_k, hit_i)
                if entry in self.controller._multi_sel:
                    self.controller._multi_sel.remove(entry)
                else:
                    self.controller._multi_sel.append(entry)
            else:
                self.controller._multi_sel = []
            self.controller.sel_track = hit_k
            self.controller.sel_idx = hit_i
            self._dm = mode
            self._dtk = hit_k
            self._di = hit_i
            cl = self.controller.tracks[hit_k][hit_i]
            self._tl0 = cl.get("tl", 0.0)
            self._st0 = cl["start"]
            self._en0 = cl["end"]
            self._dx0 = cx
            self.controller.v_speed.set(cl.get("speed", 1.0))
            self.controller.v_vol.set(cl.get("volume", 1.0))

            if hit_k == "subtitle" and hasattr(self.controller, "transcript_panel"):
                self.controller.transcript_panel.select_segment(hit_i)
                self.controller.transcript_panel.scroll_to_segment(hit_i)

            # Sync labels in properties panel
            self.controller._refresh_props()
        else:
            if not (e.state & 1):  # Clear multi-sel and clip selection when clicking empty space
                self.controller._multi_sel = []
                self.controller.sel_track = ""
                self.controller.sel_idx = -1
                if hasattr(self.controller, "properties_panel"):
                    self.controller.properties_panel._refresh_props()
            # Start rubber-band drag
            self._dm = "rubber"
            self._rb_x0 = cx
            self._rb_y0 = cy
            self._rb_rect = None
            # Also scrub to that position
            self.controller.fi = max(0, int(t_click * TARGET_FPS))
            self.controller._render(self.controller.fi)

        self._draw_tl()

    def _tl_drag(self, e):
        cx = self._tlc.canvasx(e.x)
        cy = self._tlc.canvasy(e.y)
        sc = self._scale()
        dx = (cx - self._dx0) / sc

        if self._dm == "rubber":
            # Draw rubber-band rectangle
            if self._rb_rect:
                self._tlc.delete(self._rb_rect)
            self._rb_rect = self._tlc.create_rectangle(
                self._rb_x0, self._rb_y0, cx, cy,
                outline="#60a5fa", fill="", dash=(4, 3)
            )
            return

        if self._dm == "scrub":
            self.controller.fi = max(0, int(cx / sc * TARGET_FPS))
            self.controller._render(self.controller.fi)
            return

        if not self._dm or not self._dtk:
            return

        cl = self.controller.tracks[self._dtk][self._di]

        if self._dm == "move":
            raw = max(0.0, self._tl0 + dx)
            cl["tl"] = self.controller._snap(raw, self._dtk, self._di)

            # Drag vertically to switch tracks in real-time
            target_track = None
            cy = self._tlc.canvasy(e.y)
            y_curr = RULER_H + 2
            for key, lbl, col, th, kind in self.controller._all_track_rows():
                if key == "__empty_layer__":
                    continue
                row_h = th + TGAP * 2
                ty1 = y_curr
                ty2 = y_curr + row_h
                if ty1 <= cy < ty2:
                    target_track = key
                    break
                y_curr += row_h

            if target_track and target_track != self._dtk:
                # Check track compatibility
                is_audio_clip = self._dtk.startswith("audio_")
                is_target_audio = target_track.startswith("audio_")
                is_subtitle_clip = (self._dtk == "subtitle")
                is_target_subtitle = (target_track == "subtitle")

                compatible = False
                if is_subtitle_clip and is_target_subtitle:
                    compatible = True
                elif is_audio_clip and is_target_audio:
                    compatible = True
                elif not is_audio_clip and not is_subtitle_clip and not is_target_audio and not is_target_subtitle:
                    # Video, image, or text clip can move between main and layer_* tracks
                    compatible = True

                if compatible:
                    old_list = self.controller.tracks[self._dtk]
                    clip = old_list.pop(self._di)
                    if target_track not in self.controller.tracks:
                        self.controller.tracks[target_track] = []
                    new_list = self.controller.tracks[target_track]
                    new_list.append(clip)

                    # Update indexing and controller tracking variables
                    self._dtk = target_track
                    self._di = len(new_list) - 1
                    self.controller.sel_track = target_track
                    self.controller.sel_idx = self._di
                    self.controller._rebuild_label_column()

            self._draw_tl()
            self.controller._refresh_preview()
        elif self._dm == "trim_l":
            ns = max(0.0, min(self._st0 + dx, cl["end"] - 0.05))
            d = ns - self._st0
            cl["start"] = ns
            cl["tl"] = max(0.0, self._tl0 + d / cl["speed"])
            self._draw_tl()
            self.controller._refresh_preview()
        elif self._dm == "trim_r":
            ext = os.path.splitext(cl.get("path", ""))[1].lower()
            is_unlimited = ext in (".jpg", ".jpeg", ".png", ".wav", ".mp3", ".aac", ".ogg", "") or self._dtk.startswith("audio_") or self._dtk == "subtitle"
            max_dur = 999999.0 if is_unlimited else cl.get("source_dur", 999999.0)
            cl["end"] = min(max_dur, max(cl["start"] + 0.05, self._en0 + dx))
            self._draw_tl()
            self.controller._refresh_preview()

    def _tl_release(self, e):
        if self._dm == "rubber":
            # Finalize rubber-band: select all clips overlapping the rect
            if self._rb_rect:
                self._tlc.delete(self._rb_rect)
                self._rb_rect = None
            cx = self._tlc.canvasx(e.x)
            cy = self._tlc.canvasy(e.y)
            rx1, rx2 = min(self._rb_x0, cx), max(self._rb_x0, cx)
            ry1, ry2 = min(self._rb_y0, cy), max(self._rb_y0, cy)
            sc = self._scale()
            new_sel = []
            y = RULER_H + 2
            for key, lbl, col, th, kind in self.controller._all_track_rows():
                row_h = th + TGAP * 2
                ty1 = y + TGAP
                ty2 = y + TGAP + th
                if ty1 <= ry2 and ty2 >= ry1 and key != "__empty_layer__":
                    for i, item in enumerate(self.controller.tracks.get(key, [])):
                        dur = (item["end"] - item["start"]) / max(item["speed"], 0.01)
                        tl = item.get("tl", 0.0)
                        x1 = tl * sc
                        x2 = (tl + dur) * sc
                        if x1 <= rx2 and x2 >= rx1:
                            new_sel.append((key, i))
                y += row_h
            if new_sel:
                self.controller._multi_sel = new_sel
                # Set primary selection to first found
                self.controller.sel_track, self.controller.sel_idx = new_sel[0]
                self.controller._refresh_props()
                self._draw_tl()
            self._dm = None
            return

        if self._dm in ("move", "trim_l", "trim_r"):
            self.controller._push_undo()
        self._dm = None
        self._dtk = None

    def _tl_hover(self, e):
        cx = self._tlc.canvasx(e.x)
        sc = self._scale()
        y = RULER_H + 2
        for key, lbl, col, th, kind in self.controller._all_track_rows():
            row_h = th + TGAP * 2
            ty1 = y + TGAP
            ty2 = y + TGAP + th
            if ty1 <= e.y <= ty2 and key != "__empty_layer__":
                for item in self.controller.tracks.get(key, []):
                    dur = (item["end"] - item["start"]) / max(item["speed"], 0.01)
                    tl = item.get("tl", 0.0)
                    x1 = tl * sc
                    x2 = (tl + dur) * sc
                    if abs(cx - x1) <= EDGE_PX or abs(cx - x2) <= EDGE_PX:
                        self._tlc.configure(cursor="sb_h_double_arrow")
                        return
            y += row_h
        self._tlc.configure(cursor="arrow")

    def _tl_rclick(self, e):
        cx = self._tlc.canvasx(e.x)
        sc = self._scale()
        y = RULER_H + 2
        for key, lbl, col, th, kind in self.controller._all_track_rows():
            row_h = th + TGAP * 2
            ty1 = y + TGAP
            ty2 = y + TGAP + th
            if ty1 <= e.y <= ty2 and key != "__empty_layer__":
                for i, item in enumerate(self.controller.tracks.get(key, [])):
                    dur = (item["end"] - item["start"]) / max(item["speed"], 0.01)
                    tl = item.get("tl", 0.0)
                    x1 = tl * sc
                    x2 = (tl + dur) * sc
                    if x1 <= cx <= x2:
                        self.controller.sel_track = key
                        self.controller.sel_idx = i
                        if key == "subtitle" and hasattr(self.controller, "transcript_panel"):
                            self.controller.transcript_panel.select_segment(i)
                            self.controller.transcript_panel.scroll_to_segment(i)
                        self.controller._refresh_props()
                        self._ctx_menu(e, key, i)
                        return
            y += row_h

    def _ctx_menu(self, e, tk_key, idx):
        m = tk.Menu(
            self, tearoff=0, bg=PANEL_MID, fg=TXT_W,
            activebackground=C_BLUE, activeforeground=TXT_W,
            relief="flat", bd=0, font=("Helvetica", 10)
        )
        m.add_command(label=" Split Here",          command=self.controller._split)
        m.add_command(label=" Delete",              command=self.controller._del_sel)
        m.add_command(label=" Ripple Delete [G]",   command=self.controller._ripple_delete)
        m.add_command(label=" Duplicate",           command=lambda: self.controller._dup(tk_key, idx))
        m.add_separator()
        for sp in (4.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25):
            m.add_command(label=f" Speed ×{sp}", command=lambda s=sp: self.controller._set_speed(idx, tk_key, s))
        m.add_separator()
        m.add_command(label=" Fade In 0.5s",        command=lambda: self.controller._set_fade(idx, tk_key, "fade_in", 0.5))
        m.add_command(label=" Fade In 1.0s",        command=lambda: self.controller._set_fade(idx, tk_key, "fade_in", 1.0))
        m.add_command(label=" Fade Out 0.5s",       command=lambda: self.controller._set_fade(idx, tk_key, "fade_out", 0.5))
        m.add_command(label=" Fade Out 1.0s",       command=lambda: self.controller._set_fade(idx, tk_key, "fade_out", 1.0))
        m.add_command(label=" Remove Fades",        command=lambda: self.controller._set_fade(idx, tk_key, "both", 0.0))
        m.add_separator()
        m.add_command(label=" Move to Main Video",  command=lambda: self.controller._move_track(idx, tk_key, "main"))
        m.add_command(label=" Move to Audio 1",      command=lambda: self.controller._move_track(idx, tk_key, "audio_0"))
        m.add_command(label=" Move to Audio 2",      command=lambda: self.controller._move_track(idx, tk_key, "audio_1"))
        # Dynamic layers
        for lk in self.controller._layer_keys():
            n = int(lk.split("_")[1])
            m.add_command(label=f" Move to Layer {n+1}", command=lambda k=lk: self.controller._move_track(idx, tk_key, k))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _tl_zoom(self, e):
        d = 1.13 if e.delta > 0 else 0.88
        self.controller.v_zoom.set(max(0.2, min(14.0, self.controller.v_zoom.get() * d)))
        self._draw_tl()
