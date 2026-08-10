"""editor_preview.py – Video preview canvas and playback transport controls"""

import os
import cv2
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

        # Interactive Transform UI states (Scale, Rotate, Move)
        self._tf_mode = None
        self._tf_active_clip = None
        self._tf_start_mouse = (0, 0)
        self._tf_start_scale = 1.0
        self._tf_start_rotate = 0.0
        self._tf_start_cx = 0.5
        self._tf_start_cy = 0.5
        self._tf_corners = []
        self._tf_rot_handle = (0, 0)
        self._tf_center = (320, 180)

        self._build_ui()

    def _build_ui(self):
        # 1. Canvas for rendering video (inset by 12px so dark canvas never overlaps top 20px rounded border)
        self.canvas = tk.Canvas(self, bg="#08080c", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(12, 4))

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

        # Time label (left) matching reference "01:46.13 / 04:58.15"
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

        # Right control: Aspect ratio dropdown
        rclust = ctk.CTkFrame(ctrl, fg_color="transparent")
        rclust.place(relx=1.0, rely=0.5, anchor="e")

        from editor_utils import RATIO_OPT
        ctk.CTkOptionMenu(
            rclust, values=RATIO_OPT, variable=self.controller.v_ratio,
            width=78, height=26, corner_radius=6,
            fg_color=PANEL_MID, button_color=PANEL_HOV,
            font=ctk.CTkFont(size=9, weight="bold"),
            command=lambda v: self.controller._render(self.controller.fi)
        ).pack(side="left", padx=3)

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
                    from PIL import Image, ImageTk
                    # Scale last raw BGR frame to fullscreen
                    if self._last_raw_bgr is not None:
                        try:
                            import cv2
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
        """Cache canvas size on resize — avoids winfo() on every frame."""
        self._cv_w = max(event.width, 640)
        self._cv_h = max(event.height, 360)
        self._canvas_img_id = None  # force fresh create_image on next frame

    def _canvas_ov_press(self, event):
        """Start interactive Scale / Rotate / Move transform or deselect clip if clicking empty canvas space."""
        import math
        sel_track = getattr(self.controller, "sel_track", "")
        sel_idx = getattr(self.controller, "sel_idx", -1)
        items = self.controller.tracks.get(sel_track, [])

        if not sel_track or not (0 <= sel_idx < len(items)):
            # Auto-select main track clip if active at current time
            t = self.controller.fi / float(TARGET_FPS)
            main_clip = self.controller._at("main", t)
            if main_clip and "main" in self.controller.tracks:
                self.controller.sel_track = "main"
                self.controller.sel_idx = self.controller.tracks["main"].index(main_clip)
                self.controller._refresh_props()
                items = self.controller.tracks["main"]
                sel_idx = self.controller.sel_idx
            else:
                self.controller.sel_track = ""
                self.controller.sel_idx = -1
                self.controller._refresh_props()
                self._refresh_preview()
                return

        clip = items[sel_idx]
        self._ov_drag_clip = clip
        mx, my = event.x, event.y
        self._tf_start_mouse = (mx, my)
        self._tf_start_scale = float(clip.get("scale", 1.0))
        self._tf_start_rotate = float(clip.get("rotate", 0.0))
        self._tf_start_cx = float(clip.get("custom_x", 0.5))
        self._tf_start_cy = float(clip.get("custom_y", 0.5))

        # 1. Check hit test on Rotation Handle
        if hasattr(self, "_tf_rot_handle") and self._tf_rot_handle:
            rx, ry = self._tf_rot_handle
            if math.hypot(mx - rx, my - ry) <= 18:
                self._tf_mode = "rotate"
                self._ov_dragging = True
                return

        # 2. Check hit test on 4 Corner Scale Handles
        if hasattr(self, "_tf_corners") and self._tf_corners:
            for idx, (cx, cy) in enumerate(self._tf_corners):
                if math.hypot(mx - cx, my - cy) <= 18:
                    self._tf_mode = "scale"
                    self._ov_dragging = True
                    return

        # 3. Default to Move / Transform mode
        self._tf_mode = "move"
        self._ov_dragging = True

    def _canvas_ov_drag(self, event):
        """Live update Scale, Rotate, or Position of selected clip based on mouse dragging."""
        import math
        if not self._ov_dragging or self._ov_drag_clip is None:
            return

        cw = max(self.canvas.winfo_width(), 640)
        ch = max(self.canvas.winfo_height(), 360)
        mx, my = event.x, event.y
        start_mx, start_my = self._tf_start_mouse
        clip = self._ov_drag_clip

        cx, cy = self._tf_center if hasattr(self, "_tf_center") else (cw // 2, ch // 2)

        if self._tf_mode == "rotate":
            # Calculate angle relative to clip center
            angle_rad = math.atan2(my - cy, mx - cx)
            angle_deg = math.degrees(angle_rad) + 90.0
            while angle_deg > 180.0: angle_deg -= 360.0
            while angle_deg < -180.0: angle_deg += 360.0
            clip["rotate"] = round(angle_deg, 2)

        elif self._tf_mode == "scale":
            # Calculate distance ratio relative to center
            d_cur = math.hypot(mx - cx, my - cy)
            d_start = math.hypot(start_mx - cx, start_my - cy)
            if d_start > 2:
                scale_ratio = d_cur / d_start
                new_scale = max(0.1, min(4.0, round(self._tf_start_scale * scale_ratio, 2)))
                clip["scale"] = new_scale

        else:  # "move"
            dx = (mx - start_mx) / cw
            dy = (my - start_my) / ch
            clip["custom_x"] = max(0.0, min(1.0, self._tf_start_cx + dx))
            clip["custom_y"] = max(0.0, min(1.0, self._tf_start_cy + dy))
            if getattr(self.controller, "sel_track", "") == "subtitle":
                self.controller.style.position = "custom"
                self.controller.style.custom_x = clip["custom_x"]
                self.controller.style.custom_y = clip["custom_y"]

        # Live refresh Properties Panel and Player Canvas
        self.controller._refresh_props()
        self._refresh_preview()

    def _canvas_ov_release(self, event):
        """Finish dragging and push state to undo stack."""
        if self._ov_dragging:
            self.controller._push_undo()
        self._ov_dragging = False
        self._ov_drag_clip = None
        self._tf_mode = None

    def _show(self, frame):
        """Render frame with clean, crisp, pixel-perfect aspect ratio on Canvas."""
        if self.controller.playing:
            # Fast playback path
            cw = max(self._cv_w, 640)
            ch = max(self._cv_h, 360)
            img = ImageTk.PhotoImage(Image.fromarray(frame))

            if self._canvas_img_id is None:
                self.canvas.delete("all")
                self._canvas_img_id = self.canvas.create_image(
                    cw // 2, ch // 2, anchor="center", image=img
                )
            else:
                self.canvas.itemconfig(self._canvas_img_id, image=img)
                self.canvas.coords(self._canvas_img_id, cw // 2, ch // 2)
            self._disp_img = img
            self._draw_transform_overlay()
            return

        # --- Pause / Scrub Path (High quality + Subtitles) ---
        bgr = self._crop_ratio(frame)
        self._last_raw_bgr = bgr.copy()

        # Render subtitle & text overlays
        if HAS_SUBTITLES:
            t = self.controller.fi / float(TARGET_FPS)
            # Text clips
            for tc in self.controller.tracks.get("text", []):
                dur = max(tc["end"] - tc["start"], 0.05) / max(tc.get("speed", 1.0), 0.01)
                tl = tc.get("tl", 0.0)
                if tl <= t <= tl + dur and tc.get("name", "").strip():
                    try:
                        ts = SubtitleStyle()
                        ts.font_name = tc.get("font_name", "Tahoma")
                        ts.font_size = tc.get("font_size", 36)
                        ts.font_color = tc.get("font_color", "#ffffff")
                        ts.decoration = tc.get("decoration", "shadow")
                        ts.animation = "none"
                        ts.position = "custom"
                        ts.custom_x = tc.get("custom_x", 0.5)
                        ts.custom_y = tc.get("custom_y", 0.2)
                        bgr = draw_subtitles_on_frame(bgr, tc["name"], ts, 0.5)
                    except Exception:
                        pass
            # Auto subtitles
            sub_visible = getattr(self.controller, "_sub_visible", True)
            if sub_visible:
                sub, prog = self._find_sub(t)
                if sub:
                    try:
                        bgr = draw_subtitles_on_frame(bgr, sub, self.controller.style, prog)
                    except Exception:
                        pass

        # Resize and render high quality BGR
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
        self._draw_transform_overlay()

    def _draw_transform_overlay(self):
        """Draw interactive Transform Bounding Box, 4 Corner Scale Handles, Rotation Handle, and Degree Angle Badge."""
        import math
        self.canvas.delete("transform_ui")

        sel_track = getattr(self.controller, "sel_track", "")
        sel_idx = getattr(self.controller, "sel_idx", -1)
        if not sel_track or sel_idx < 0:
            return

        items = self.controller.tracks.get(sel_track, [])
        if not (0 <= sel_idx < len(items)):
            return

        clip = items[sel_idx]

        cw = max(self.canvas.winfo_width(), 640)
        ch = max(self.canvas.winfo_height(), 360)

        scale = float(clip.get("scale", 1.0))
        rotate = float(clip.get("rotate", 0.0))

        cx = int(clip.get("custom_x", 0.5) * cw)
        cy = int(clip.get("custom_y", 0.5) * ch)
        self._tf_center = (cx, cy)

        # Base aspect box dimensions
        bw = int(cw * 0.65)
        bh = int(ch * 0.65)

        sw = (bw * scale) / 2.0
        sh = (bh * scale) / 2.0

        rad = math.radians(rotate)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        local_corners = [
            (-sw, -sh),  # TL
            (sw, -sh),   # TR
            (sw, sh),    # BR
            (-sw, sh)    # BL
        ]

        world_corners = []
        for lx, ly in local_corners:
            wx = cos_a * lx - sin_a * ly + cx
            wy = sin_a * lx + cos_a * ly + cy
            world_corners.append((wx, wy))

        # Draw bounding box polygon lines
        poly_pts = []
        for wx, wy in world_corners:
            poly_pts.extend([wx, wy])
        self.canvas.create_polygon(poly_pts, fill="", outline="#ffffff", width=2, tags="transform_ui")

        # Top center position for rotation stem
        top_cx = (world_corners[0][0] + world_corners[1][0]) / 2.0
        top_cy = (world_corners[0][1] + world_corners[1][1]) / 2.0

        stem_len = 35.0
        rot_hx = top_cx - sin_a * stem_len
        rot_hy = top_cy - cos_a * stem_len
        self._tf_rot_handle = (rot_hx, rot_hy)

        # Stem connecting line
        self.canvas.create_line(top_cx, top_cy, rot_hx, rot_hy, fill="#ffffff", width=2, tags="transform_ui")

        # Rotation handle circle with 🔄 icon
        self.canvas.create_oval(rot_hx-11, rot_hy-11, rot_hx+11, rot_hy+11, fill="#ffffff", outline="#0f172a", width=2, tags="transform_ui")
        self.canvas.create_text(rot_hx, rot_hy, text="🔄", font=("Segoe UI", 9, "bold"), fill="#0f172a", tags="transform_ui")

        # Degree angle badge above rotation handle (e.g. 84.86°)
        badge_hx = rot_hx - sin_a * 25.0
        badge_hy = rot_hy - cos_a * 25.0
        angle_str = f"{rotate:.2f}°"

        badge_w = 34 + len(angle_str) * 4
        self.canvas.create_oval(badge_hx-badge_w, badge_hy-13, badge_hx+badge_w, badge_hy+13, fill="#ffffff", outline="#000000", width=1, tags="transform_ui")
        self.canvas.create_text(badge_hx, badge_hy, text=angle_str, font=("Consolas", 11, "bold"), fill="#0f172a", tags="transform_ui")

        # Draw 4 white corner scale handles
        for idx, (wx, wy) in enumerate(world_corners):
            r = 7
            self.canvas.create_oval(wx-r, wy-r, wx+r, wy+r, fill="#ffffff", outline="#0f172a", width=2, tags="transform_ui")

        self._tf_corners = world_corners

    def _refresh_preview(self):
        """Re-composite subtitle onto cached raw frame without seeking video file."""
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
        # Look in the dedicated subtitle track
        for clip in self.controller.tracks.get("subtitle", []):
            dur = max(clip["end"] - clip["start"], 0.05) / max(clip.get("speed", 1.0), 0.01)
            tl = clip.get("tl", 0.0)
            if tl <= t <= tl + dur:
                prog = (t - tl) / max(dur, 0.001)
                return clip.get("sub_text", clip.get("name", "")), prog
        # Fallback to transcribe segments
        for s in self.controller.segments:
            if s["start"] <= t <= s["end"]:
                return s["text"], (t - s["start"]) / max(s["end"] - s["start"], 0.001)
        return "", 0.5

    def _apply_overlay(self, frame, t):
        """Overlay image/video elements from timeline overlay layers at timestamp t."""
        active_overlays = []
        for lk in self.controller._layer_keys():
            for item in self.controller.tracks.get(lk, []):
                dur = (item["end"] - item["start"]) / max(item.get("speed", 1.0), 0.01)
                tl = item.get("tl", 0.0)
                if tl <= t < tl + dur:
                    active_overlays.append(item)

        # Sort by start time to stack them properly
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
                # Video overlay clip
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

            # Apply clip Scale & Rotate
            sc = overlay_clip.get("scale", 1.0)
            rot = overlay_clip.get("rotate", 0.0)
            if sc != 1.0 or rot != 0.0:
                overlay_frame = self.controller._apply_clip_transform(overlay_frame, sc, rot)

            # Composite onto main frame
            h, w = frame.shape[:2]
            oh, ow = overlay_frame.shape[:2]

            # Fit overlay size (max 50% height/width of main frame)
            scale = min(w / ow, h / oh) * 0.5
            if scale > 0:
                nw, nh = int(ow * scale), int(oh * scale)
                if nw > 0 and nh > 0:
                    overlay_resized = cv2.resize(overlay_frame, (nw, nh), interpolation=cv2.INTER_LINEAR)

                    # Center overlay
                    x_offset = (w - nw) // 2
                    y_offset = (h - nh) // 2

                    try:
                        # Overlay alpha blend if it has 4 channels
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

        if hasattr(self.controller, "transcript_panel"):
            active_idx = self.controller.find_active_segment()
            if active_idx != self.controller.transcript_panel.selected_idx:
                self.controller.transcript_panel.select_segment(active_idx)
                self.controller.transcript_panel.scroll_to_segment(active_idx)

    def _upd_scrub(self, t):
        total = max(self.controller._dur(), 0.1)
        self._scrub_v.set(t / total * 1000)
