"""editor_preview.py – Video preview canvas and playback transport controls"""

import os
import cv2
import math
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk
import numpy as np
from video_display_engine import SmartVideoReader

from editor_utils import (
    BG_DEEP, PANEL_DARK, PANEL_MID, PANEL_LIGHT, PANEL_HOV,
    C_BLUE, C_RED, C_GREEN, C_AMBER, TXT_W, TXT_G, TXT_L, BORD,
    TARGET_FPS, _ft, _bright, _dark, HAS_SUBTITLES
)

if HAS_SUBTITLES:
    from subtitle_config import SubtitleStyle
    from subtitle_renderer import draw_subtitles_on_frame


# ── Snap constants ────────────────────────────────────────────────────────────
SNAP_GRID_DIVISIONS = 10   # 10×10 grid by default
SNAP_THRESHOLD_PX   = 14   # pixels within which snap activates


class PreviewPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color=PANEL_DARK, bg_color="transparent", corner_radius=20, border_width=2, border_color="#ffffff")
        self.controller = controller

        # Preview-specific states
        self._disp_img = None
        self._last_raw_bgr = None
        self._canvas_img_id = None
        self._cv_w = 640
        self._cv_h = 360
        self._ov_dragging = False
        self._ov_drag_clip = None

        # Move-only transform states
        self._tf_mode = None
        self._tf_active_clip = None
        self._tf_start_mouse = (0, 0)
        self._tf_start_cx = 0.5
        self._tf_start_cy = 0.5
        self._tf_center = (320, 180)

        # Snap
        self._snap_grid = False   # toggle state

        self._build_ui()

    def _build_ui(self):
        # 1. Canvas for rendering video (minimal padding for full-fill preview)
        self.canvas = tk.Canvas(self, bg="#08080c", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=4, pady=(4, 2))

        # Canvas overlay drag bindings
        self.canvas.bind("<Button-1>",        self._canvas_ov_press)
        self.canvas.bind("<B1-Motion>",       self._canvas_ov_drag)
        self.canvas.bind("<ButtonRelease-1>",  self._canvas_ov_release)
        self.canvas.bind("<Configure>",       self._on_cv_configure)

        # Scrub slider (thin red progress bar)
        self._scrub_v = tk.DoubleVar(value=0)
        self._scrub = ctk.CTkSlider(
            self, from_=0, to=1000, variable=self._scrub_v,
            height=6, corner_radius=3,
            button_color=C_RED, progress_color=C_RED,
            button_hover_color=_bright(C_RED),
            fg_color=PANEL_MID, command=self.controller._scrub_seek
        )
        self._scrub.pack(fill="x", padx=8, pady=(2, 0))

        # 2. Transport Bar
        ctrl = ctk.CTkFrame(self, height=44, fg_color="transparent", corner_radius=0)
        ctrl.pack(fill="x", padx=10, pady=4)
        ctrl.pack_propagate(False)

        # Time label (left)
        self._tlbl = ctk.CTkLabel(
            ctrl, text="00:00.00 / 00:00.00",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=TXT_L
        )
        self._tlbl.place(relx=0.0, rely=0.5, anchor="w")

        # Center Play/Pause button
        row = ctk.CTkFrame(ctrl, fg_color="transparent")
        row.place(relx=0.5, rely=0.5, anchor="center")

        self._pbtn = ctk.CTkButton(
            row, text="▶", width=42, height=34, corner_radius=17,
            fg_color=TXT_W, text_color=BG_DEEP, hover_color="#d0d0e0",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.controller._toggle_play
        )
        self._pbtn.pack(side="left", padx=4)

        # Right controls cluster
        rclust = ctk.CTkFrame(ctrl, fg_color="transparent")
        rclust.place(relx=1.0, rely=0.5, anchor="e")

        # Aspect ratio dropdown
        from editor_utils import RATIO_OPT
        ctk.CTkOptionMenu(
            rclust, values=RATIO_OPT, variable=self.controller.v_ratio,
            width=78, height=26, corner_radius=6,
            fg_color=PANEL_MID, button_color=PANEL_HOV,
            font=ctk.CTkFont(size=9, weight="bold"),
            command=lambda v: self.controller._render(self.controller.fi)
        ).pack(side="left", padx=3)

    # ── Canvas hit-test helpers ───────────────────────────────────────────────
    def _get_clip_bbox_canvas(self, clip):
        """Return (cx_px, cy_px, half_w, half_h) bounding box of clip in canvas coords."""
        cw = max(self._cv_w, 1)
        ch = max(self._cv_h, 1)
        cx = clip.get("custom_x", 0.5) * cw
        cy = clip.get("custom_y", 0.5) * ch
        scale = float(clip.get("scale", 1.0))
        hw = int(cw * 0.30 * scale / 2)
        hh = int(ch * 0.30 * scale / 2)
        return cx, cy, hw, hh

    def _hit_test_clip(self, mx, my, clip):
        """Return True if canvas point (mx,my) is inside this clip's bounding box."""
        cx, cy, hw, hh = self._get_clip_bbox_canvas(clip)
        rotate = float(clip.get("rotate", 0.0))
        if rotate != 0.0:
            # Rotate point into clip local space
            rad = math.radians(-rotate)
            dx = mx - cx; dy = my - cy
            lx = dx * math.cos(rad) - dy * math.sin(rad)
            ly = dx * math.sin(rad) + dy * math.cos(rad)
            return abs(lx) <= hw and abs(ly) <= hh
        return abs(mx - cx) <= hw and abs(my - cy) <= hh

    # ── Canvas interaction ────────────────────────────────────────────────────
    def _canvas_ov_press(self, event):
        """Click to select or start moving clip. Tries all layer tracks."""
        mx = self.canvas.canvasx(event.x)
        my = self.canvas.canvasy(event.y)
        t = self.controller.fi / float(TARGET_FPS)

        # 1. Try to hit-test every active layer clip
        hit_track = None
        hit_idx = None
        hit_clip = None

        for lk in reversed(self.controller._layer_keys()):  # top layers first
            clips = self.controller.tracks.get(lk, [])
            for idx, clip in enumerate(clips):
                dur = max(clip["end"] - clip["start"], 0.05) / max(clip.get("speed", 1.0), 0.01)
                tl = clip.get("tl", 0.0)
                if not (tl <= t <= tl + dur):
                    continue
                if self._hit_test_clip(mx, my, clip):
                    hit_track = lk
                    hit_idx = idx
                    hit_clip = clip
                    break
            if hit_clip:
                break

        # 2. Try subtitle track if no layer clip was hit
        if not hit_clip:
            subs = self.controller.tracks.get("subtitle", [])
            for idx, clip in enumerate(subs):
                dur = max(clip["end"] - clip["start"], 0.05) / max(clip.get("speed", 1.0), 0.01)
                tl = clip.get("tl", 0.0)
                if tl <= t <= tl + dur:
                    hit_track = "subtitle"
                    hit_idx = idx
                    hit_clip = clip
                    break

        # 3. Try main track video if no overlay was hit
        if not hit_clip:
            main_clips = self.controller.tracks.get("main", [])
            for idx, clip in enumerate(main_clips):
                dur = max(clip["end"] - clip["start"], 0.05) / max(clip.get("speed", 1.0), 0.01)
                tl = clip.get("tl", 0.0)
                if tl <= t <= tl + dur:
                    hit_track = "main"
                    hit_idx = idx
                    hit_clip = clip
                    break

        if not hit_clip:
            # Clicked empty background
            self._ov_drag_clip = None
            self._ov_dragging = False
            self.canvas.delete("transform_ui")
            self.controller.sel_track = ""
            self.controller.sel_idx = -1
            self.controller._refresh_props()
            self._refresh_preview()
            return

        # 4. Select the hit clip
        self.controller.sel_track = hit_track
        self.controller.sel_idx = hit_idx
        self.controller._refresh_props()

        # 5. Start drag
        self._ov_drag_clip = hit_clip
        self._tf_mode = "move"
        self._ov_dragging = True
        self._tf_start_mouse = (mx, my)
        self._tf_start_cx = float(hit_clip.get("custom_x", 0.5))
        self._tf_start_cy = float(hit_clip.get("custom_y", 0.5))

        self._refresh_preview()

    def _canvas_ov_drag(self, event):
        """Move selected clip smoothly across canvas."""
        if not self._ov_dragging or self._ov_drag_clip is None:
            return

        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        mx = self.canvas.canvasx(event.x)
        my = self.canvas.canvasy(event.y)
        start_mx, start_my = self._tf_start_mouse
        clip = self._ov_drag_clip

        dx = (mx - start_mx) / cw
        dy = (my - start_my) / ch
        clip["custom_x"] = max(0.0, min(1.0, self._tf_start_cx + dx))
        clip["custom_y"] = max(0.0, min(1.0, self._tf_start_cy + dy))

        if getattr(self.controller, "sel_track", "") == "subtitle":
            self.controller.style.position = "custom"
            self.controller.style.custom_x = clip["custom_x"]
            self.controller.style.custom_y = clip["custom_y"]

        self.controller._refresh_props()
        self._refresh_preview()

    def _canvas_ov_release(self, event):
        """Finish dragging."""
        if self._ov_dragging:
            self.controller._push_undo()
        self._ov_dragging = False
        self._ov_drag_clip = None
        self._tf_mode = None

    # ── Frame display ─────────────────────────────────────────────────────────
    def _show(self, frame):
        """Render frame with clean, crisp, pixel-perfect aspect ratio on Canvas."""
        if self.controller.playing:
            # ── Fast playback path ──────────────────────────────────────────
            cw = max(self._cv_w, 640)
            ch = max(self._cv_h, 360)

            h, w = frame.shape[:2]
            try:
                img_pil = Image.frombuffer("RGB", (w, h), frame, "raw", "RGB", 0, 1)
            except Exception:
                img_pil = Image.fromarray(frame)

            img = ImageTk.PhotoImage(img_pil)

            if self._canvas_img_id is None:
                self.canvas.delete("all")
                self._canvas_img_id = self.canvas.create_image(
                    cw // 2, ch // 2, anchor="center", image=img
                )
            else:
                self.canvas.itemconfig(self._canvas_img_id, image=img)
                self.canvas.coords(self._canvas_img_id, cw // 2, ch // 2)

            self._disp_img = img

            # ── Draw text clips in fast playback path ──────────────────────
            self.canvas.delete("text_overlay")
            t = self.controller.fi / float(TARGET_FPS)
            for lk in self.controller._layer_keys():
                for tc in self.controller.tracks.get(lk, []):
                    if tc.get("path", "") != "":
                        continue
                    dur = max(tc["end"] - tc["start"], 0.05) / max(tc.get("speed", 1.0), 0.01)
                    tl = tc.get("tl", 0.0)
                    if tl <= t <= tl + dur and tc.get("name", "").strip():
                        self._draw_text_on_canvas(tc, cw, ch, tag="text_overlay")

            # ── Draw subtitles ─────────────────────────────────────────────
            if HAS_SUBTITLES:
                sub_visible = getattr(self.controller, "_sub_visible", True)
                if sub_visible:
                    sub, prog, sub_clip = self._find_sub(t)
                    if sub:
                        self.canvas.delete("sub_overlay")
                        self._draw_sub_on_canvas(sub, sub_clip, cw, ch)

            self._draw_transform_overlay()
            return

        # --- Pause / Scrub Path (High quality + Subtitles) ---
        bgr = self._crop_ratio(frame)
        self._last_raw_bgr = bgr.copy()

        # Render subtitle & text overlays via OpenCV
        if HAS_SUBTITLES:
            t = self.controller.fi / float(TARGET_FPS)
            for lk in self.controller._layer_keys():
                for tc in self.controller.tracks.get(lk, []):
                    if tc.get("path", "") != "":
                        continue
                    dur = max(tc["end"] - tc["start"], 0.05) / max(tc.get("speed", 1.0), 0.01)
                    tl = tc.get("tl", 0.0)
                    if tl <= t <= tl + dur and tc.get("name", "").strip():
                        try:
                            ts = SubtitleStyle()
                            ts.font_name = tc.get("font_name", "Tahoma")
                            ts.font_size = tc.get("font_size", 36)
                            ts.font_color = tc.get("font_color", "#ffffff")
                            ts.decoration = tc.get("decoration", "shadow")
                            ts.bold = bool(tc.get("bold", False))
                            ts.italic = bool(tc.get("italic", False))
                            ts.animation = "none"
                            ts.position = "custom"
                            ts.custom_x = tc.get("custom_x", 0.5)
                            ts.custom_y = tc.get("custom_y", 0.2)
                            bgr = draw_subtitles_on_frame(bgr, tc["name"], ts, 0.5)
                        except Exception:
                            pass

            sub_visible = getattr(self.controller, "_sub_visible", True)
            if sub_visible:
                sub, prog, sub_clip = self._find_sub(t)
                if sub:
                    try:
                        import copy
                        render_style = copy.copy(self.controller.style)
                        if sub_clip is not None:
                            if "font_name" in sub_clip:
                                render_style.font_name = sub_clip["font_name"]
                            if "font_size" in sub_clip:
                                render_style.font_size = sub_clip["font_size"]
                            if "font_color" in sub_clip:
                                render_style.font_color = sub_clip["font_color"]
                            if "bold" in sub_clip:
                                render_style.bold = sub_clip["bold"]
                            if "italic" in sub_clip:
                                render_style.italic = sub_clip["italic"]
                            if "decoration" in sub_clip:
                                render_style.decoration = sub_clip["decoration"]
                            if "custom_x" in sub_clip:
                                render_style.custom_x = sub_clip["custom_x"]
                            if "custom_y" in sub_clip:
                                render_style.custom_y = sub_clip["custom_y"]
                        bgr = draw_subtitles_on_frame(bgr, sub, render_style, prog)
                    except Exception:
                        pass

        cw = max(self._cv_w, 640)
        ch = max(self._cv_h, 360)
        h, w = bgr.shape[:2]
        sc = min(cw / w, ch / h)
        ow, oh = int(w * sc), int(h * sc)
        bgr = cv2.resize(bgr, (ow, oh), interpolation=cv2.INTER_LINEAR)
        img = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))

        if self._canvas_img_id is None:
            self.canvas.delete("all")
            self._canvas_img_id = self.canvas.create_image(
                cw // 2, ch // 2, anchor="center", image=img
            )
        else:
            self.canvas.itemconfig(self._canvas_img_id, image=img)
            self.canvas.coords(self._canvas_img_id, cw // 2, ch // 2)
        self._disp_img = img
        self._draw_grid_overlay()
        self._draw_transform_overlay()

    # ── Text clip canvas rendering ────────────────────────────────────────────
    def _draw_text_on_canvas(self, tc, cw, ch, tag="text_overlay"):
        """Draw a text clip on canvas (fast path, no OpenCV)."""
        cx_pos = tc.get("custom_x", 0.5)
        cy_pos = tc.get("custom_y", 0.2)
        font_size = tc.get("font_size", 36)
        color = tc.get("font_color", "#ffffff")
        try:
            # Validate hex color
            if not color.startswith("#"):
                color = "#ffffff"
        except Exception:
            color = "#ffffff"

        x_px = int(cx_pos * cw)
        y_px = int(cy_pos * ch)
        display_size = max(10, min(int(font_size * 0.7), 40))

        decoration = tc.get("decoration", "shadow")
        text = tc.get("name", "")
        if not text:
            return

        if decoration in ("outline", "shadow"):
            offsets = [(1, 1), (-1, 1), (1, -1), (-1, -1)] if decoration == "outline" else [(2, 2)]
            for dx, dy in offsets:
                self.canvas.create_text(
                    x_px + dx, y_px + dy, text=text,
                    fill="#000000", anchor="center",
                    font=("Tahoma", display_size, "bold"),
                    tags=tag
                )

        self.canvas.create_text(
            x_px, y_px, text=text,
            fill=color, anchor="center",
            font=("Tahoma", display_size, "bold"),
            tags=tag
        )

    # ── Transform overlay (move + bounding box only) ──────────────────────────
    def _draw_transform_overlay(self):
        """Draw bounding box + move cursor for the selected clip. No scale/rotate handles."""
        self.canvas.delete("transform_ui")

        sel_track = getattr(self.controller, "sel_track", "")
        sel_idx = getattr(self.controller, "sel_idx", -1)
        if not sel_track or sel_idx < 0:
            return

        items = self.controller.tracks.get(sel_track, [])
        if not (0 <= sel_idx < len(items)):
            return

        clip = items[sel_idx]
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)

        scale = float(clip.get("scale", 1.0))
        rotate = float(clip.get("rotate", 0.0))

        cx = int(clip.get("custom_x", 0.5) * cw)
        cy = int(clip.get("custom_y", 0.5) * ch)
        self._tf_center = (cx, cy)

        bw = int(cw * 0.30 * scale)
        bh = int(ch * 0.30 * scale)
        bw = min(bw, cw - 20)
        bh = min(bh, ch - 20)
        sw = bw / 2.0
        sh = bh / 2.0

        rad = math.radians(rotate)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        local_corners = [(-sw, -sh), (sw, -sh), (sw, sh), (-sw, sh)]
        world_corners = []
        for lx, ly in local_corners:
            wx = cos_a * lx - sin_a * ly + cx
            wy = sin_a * lx + cos_a * ly + cy
            world_corners.append((wx, wy))

        # Draw bounding box
        poly_pts = []
        for wx, wy in world_corners:
            poly_pts.extend([wx, wy])
        self.canvas.create_polygon(poly_pts, fill="", outline="#00d4ff",
                                   width=2, dash=(6, 3), tags="transform_ui")

        # Draw centre cross
        cs = 6
        self.canvas.create_line(cx - cs, cy, cx + cs, cy,
                                 fill="#00d4ff", width=2, tags="transform_ui")
        self.canvas.create_line(cx, cy - cs, cx, cy + cs,
                                 fill="#00d4ff", width=2, tags="transform_ui")

        # Clip name badge
        name = clip.get("name", "")
        if name:
            badge_y = min(world_corners[0][1], world_corners[1][1]) - 14
            badge_y = max(badge_y, 4)
            badge_x = cx
            self.canvas.create_rectangle(
                badge_x - 42, badge_y - 9, badge_x + 42, badge_y + 9,
                fill="#0f172a", outline="#00d4ff", width=1, tags="transform_ui"
            )
            self.canvas.create_text(
                badge_x, badge_y, text=name[:16],
                fill="#00d4ff", font=("Consolas", 8), tags="transform_ui"
            )

        # "✥ Move" cursor icon near centre
        self.canvas.create_text(
            cx + 16, cy - 16, text="✥",
            fill="#ffffff", font=("Segoe UI", 11), tags="transform_ui"
        )

    # ── Subtitle canvas drawing ───────────────────────────────────────────────
    def _draw_sub_on_canvas(self, text: str, sub_clip, cw: int, ch: int):
        """Draw subtitle text directly on canvas during fast playback."""
        style = self.controller.style
        if sub_clip is not None:
            cx_pos = sub_clip.get("custom_x", style.custom_x)
            cy_pos = sub_clip.get("custom_y", style.custom_y)
            font_size = sub_clip.get("font_size", style.font_size)
        else:
            pos_map = {
                "bottom_center": (0.5, 0.88), "bottom_left": (0.2, 0.88),
                "bottom_right": (0.8, 0.88), "top_center": (0.5, 0.08),
                "top_left": (0.2, 0.08), "top_right": (0.8, 0.08),
                "center": (0.5, 0.5), "custom": (style.custom_x, style.custom_y),
            }
            cx_pos, cy_pos = pos_map.get(style.position, (0.5, 0.88))
            font_size = style.font_size

        x_px = int(cx_pos * cw)
        y_px = int(cy_pos * ch)
        display_size = max(10, min(int(font_size * 0.7), 36))
        try:
            color = style.font_color if sub_clip is None else sub_clip.get("font_color", style.font_color)
        except Exception:
            color = "#ffffff"

        decoration = style.decoration
        if decoration in ("outline", "shadow"):
            offsets = [(1, 1), (-1, 1), (1, -1), (-1, -1)] if decoration == "outline" else [(2, 2)]
            for dx, dy in offsets:
                self.canvas.create_text(
                    x_px + dx, y_px + dy, text=text,
                    fill="#000000", anchor="center",
                    font=("Tahoma", display_size, "bold"),
                    tags="sub_overlay"
                )

        self.canvas.create_text(
            x_px, y_px, text=text,
            fill=color, anchor="center",
            font=("Tahoma", display_size, "bold"),
            tags="sub_overlay"
        )

    # ── Misc helpers ──────────────────────────────────────────────────────────
    def _open_fullscreen(self):
        """Open borderless true fullscreen video window."""
        top = tk.Toplevel(self)
        top.title("MediaPro Fullscreen Player")
        top.attributes("-fullscreen", True)
        top.configure(bg="#000000")

        fs_canvas = tk.Canvas(top, bg="#000000", highlightthickness=0)
        fs_canvas.pack(fill="both", expand=True)

        def _update_fs():
            if not top.winfo_exists(): return
            if self._disp_img:
                w, h = top.winfo_width(), top.winfo_height()
                if w > 10 and h > 10:
                    if self._last_raw_bgr is not None:
                        try:
                            rgb = cv2.cvtColor(self._last_raw_bgr, cv2.COLOR_BGR2RGB)
                            img = Image.fromarray(rgb)
                            iw, ih = img.size
                            ratio = min(w / iw, h / ih)
                            nw, nh = int(iw * ratio), int(ih * ratio)
                            img = img.resize((nw, nh), Image.LANCZOS)
                            photo = ImageTk.PhotoImage(img)
                            fs_canvas.delete("all")
                            fs_canvas.create_image(w // 2, h // 2, anchor="center", image=photo)
                            fs_canvas._photo = photo
                        except Exception:
                            pass
            top.after(50, _update_fs)

        top.after(100, _update_fs)
        top.bind("<Escape>", lambda e: top.destroy())
        top.bind("<Button-1>", lambda e: top.destroy())

    def _mb(self, parent, text, command):
        return ctk.CTkButton(
            parent, text=text, width=32, height=28, corner_radius=7,
            fg_color="transparent", hover_color=PANEL_MID,
            font=ctk.CTkFont(size=12), command=command
        )

    def _on_cv_configure(self, event):
        """Cache canvas size on resize."""
        self._cv_w = max(event.width, 1)
        self._cv_h = max(event.height, 1)
        self._canvas_img_id = None

    def _refresh_preview(self):
        """Re-composite onto cached raw frame without seeking video file."""
        if self._last_raw_bgr is not None:
            self._show(self._last_raw_bgr.copy())
        else:
            self.controller._render(self.controller.fi)

    def _crop_ratio(self, frame):
        h, w = frame.shape[:2]
        rm = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "2.35:1": 2.35}
        r = rm.get(self.controller.v_ratio.get(), 16 / 9)
        cur = w / h
        if abs(cur - r) < 0.01:
            return frame
        if cur > r:
            nw = int(h * r)
            x = (w - nw) // 2
            return frame[:, x:x + nw]
        else:
            nh = int(w / r)
            y = (h - nh) // 2
            return frame[y:y + nh, :]

    def _find_sub(self, t):
        for clip in self.controller.tracks.get("subtitle", []):
            dur = max(clip["end"] - clip["start"], 0.05) / max(clip.get("speed", 1.0), 0.01)
            tl = clip.get("tl", 0.0)
            if tl <= t <= tl + dur:
                prog = (t - tl) / max(dur, 0.001)
                return clip.get("sub_text", clip.get("name", "")), prog, clip
        for s in self.controller.segments:
            if s["start"] <= t <= s["end"]:
                return s["text"], (t - s["start"]) / max(s["end"] - s["start"], 0.001), None
        return "", 0.5, None

    def _apply_overlay(self, frame, t):
        """Overlay image/video elements from timeline layers at timestamp t."""
        active_overlays = []
        for lk in self.controller._layer_keys():
            for item in self.controller.tracks.get(lk, []):
                dur = (item["end"] - item["start"]) / max(item.get("speed", 1.0), 0.01)
                tl = item.get("tl", 0.0)
                if tl <= t < tl + dur:
                    active_overlays.append(item)

        active_overlays = sorted(active_overlays, key=lambda c: c.get("tl", 0.0))

        if not active_overlays:
            return frame

        for overlay_clip in active_overlays:
            path = overlay_clip.get("path")
            if not path or not os.path.exists(path):
                continue

            ext = os.path.splitext(path)[1].lower()
            is_image = ext in (".jpg", ".jpeg", ".png")

            overlay_frame = None
            if is_image:
                if not hasattr(self.controller, "_img_cache"):
                    self.controller._img_cache = {}
                if path in self.controller._img_cache:
                    overlay_frame = self.controller._img_cache[path]
                else:
                    overlay_frame = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                    if overlay_frame is not None:
                        self.controller._img_cache[path] = overlay_frame
            else:
                src_fps = overlay_clip.get("fps", TARGET_FPS)
                src_t = (t - overlay_clip.get("tl", 0.0)) * overlay_clip["speed"] + overlay_clip["start"]
                cap_key = f"_ov_cap_{path.replace(':', '_').replace('/', '_').replace('\\', '_')}"
                if not hasattr(self.controller, cap_key):
                    setattr(self.controller, cap_key, SmartVideoReader(path))
                cap_obj = getattr(self.controller, cap_key)
                ok, ofr = cap_obj.get_frame_at_time(src_t)
                if ok:
                    overlay_frame = ofr

            if overlay_frame is None:
                continue

            sc = overlay_clip.get("scale", 1.0)
            rot = overlay_clip.get("rotate", 0.0)
            if sc != 1.0 or rot != 0.0:
                overlay_frame = self.controller._apply_clip_transform(overlay_frame, sc, rot)

            h, w = frame.shape[:2]
            oh, ow = overlay_frame.shape[:2]
            scale = min(w / ow, h / oh) * 0.5
            if scale > 0:
                nw, nh = int(ow * scale), int(oh * scale)
                if nw > 0 and nh > 0:
                    overlay_resized = cv2.resize(overlay_frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
                    x_offset = (w - nw) // 2
                    y_offset = (h - nh) // 2
                    try:
                        if overlay_resized.shape[2] == 4:
                            alpha = overlay_resized[:, :, 3] / 255.0
                            alpha = np.expand_dims(alpha, axis=2)
                            overlay_color = overlay_resized[:, :, :3]
                            target_roi = frame[y_offset:y_offset + nh, x_offset:x_offset + nw]
                            blended = (overlay_color * alpha + target_roi * (1.0 - alpha)).astype(np.uint8)
                            frame[y_offset:y_offset + nh, x_offset:x_offset + nw] = blended
                        else:
                            frame[y_offset:y_offset + nh, x_offset:x_offset + nw] = overlay_resized[:, :, :3]
                    except Exception:
                        pass
        return frame

    def _upd_time(self, t):
        total = self.controller._dur()
        self._tlbl.configure(text=f"{_ft(t)} / {_ft(total)}")

        if getattr(self.controller, "playing", False):
            return

        if hasattr(self.controller, "transcript_panel"):
            active_idx = self.controller.find_active_segment()
            if active_idx != self.controller.transcript_panel.selected_idx:
                self.controller.transcript_panel.select_segment(active_idx)
                self.controller.transcript_panel.scroll_to_segment(active_idx)

    def _upd_scrub(self, t):
        total = max(self.controller._dur(), 0.1)
        self._scrub_v.set(t / total * 1000)
