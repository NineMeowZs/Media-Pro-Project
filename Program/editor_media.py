"""editor_media.py – Sidebar navigation and media panel tabs (Assets, Text, Subs, Effects, Audio)"""

import os
import cv2
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk

from editor_utils import (
    PANEL_DARK, PANEL_MID, PANEL_LIGHT, PANEL_HOV, BG_DEEP, BORD, TXT_W, TXT_G, TXT_L,
    C_BLUE, C_TEAL, C_PINK, C_PURPLE, C_AMBER, C_GREEN, C_RED,
    _dark, _bright, _ft_ms, HAS_SUBTITLES, TARGET_FPS
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
        # Top Tab Bar: 4 Equal-width rounded pill tabs (uniform grid layout)
        tab_bar = ctk.CTkFrame(self, fg_color=PANEL_MID, height=48, corner_radius=14)
        tab_bar.pack(fill="x", padx=6, pady=(6, 2))
        tab_bar.pack_propagate(False)

        tab_bar.grid_columnconfigure(0, weight=1, uniform="tab")
        tab_bar.grid_columnconfigure(1, weight=1, uniform="tab")
        tab_bar.grid_columnconfigure(2, weight=1, uniform="tab")
        tab_bar.grid_columnconfigure(3, weight=1, uniform="tab")
        tab_bar.grid_rowconfigure(0, weight=1)

        tabs = [
            ("🎬", "Media", "Media"),
            ("🔤", "Text", "Text"),
            ("⚡", "DeadAir", "DeadAir"),
            ("💬", "Captions", "Captions"),
        ]

        for idx, (icon, label, name) in enumerate(tabs):
            b = ctk.CTkButton(
                tab_bar, text=f"{icon}\n{label}", height=40, corner_radius=10,
                fg_color="transparent", hover_color=PANEL_LIGHT,
                text_color=TXT_W, font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
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

    def _pt_deadair(self):
        """Tab Panel: DeadAir Cut (Auto Silence Remover)."""
        import threading
        from editor_utils import C_RED, C_AMBER, C_BLUE, C_GREEN, _ft_ms, TARGET_FPS

        # ── Header Description ──
        ctk.CTkLabel(
            self._pscroll, text="⚡ ระบบตัด Dead Air อัตโนมัติ",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TXT_W
        ).pack(anchor="w", pady=(0, 2))

        ctk.CTkLabel(
            self._pscroll, text="ตรวจจับช่วงที่คลื่นเสียงเงียบนิ่งและตัดต่ออัตโนมัติ",
            font=ctk.CTkFont(size=9), text_color=TXT_G
        ).pack(anchor="w", pady=(0, 6))

        # ── Settings Box ──
        cfg_box = ctk.CTkFrame(self._pscroll, fg_color=PANEL_MID, corner_radius=8)
        cfg_box.pack(fill="x", pady=(0, 6), padx=2)

        ctk.CTkLabel(
            cfg_box, text="ความยาวเสียงเงียบขั้นต่ำ (ms)",
            font=ctk.CTkFont(size=9, weight="bold"), text_color=TXT_L
        ).pack(anchor="w", padx=8, pady=(6, 2))

        ms_row = ctk.CTkFrame(cfg_box, fg_color="transparent")
        ms_row.pack(fill="x", padx=8, pady=(0, 6))

        cur_ms = getattr(self.controller, "_deadair_min_ms", 500)
        ms_var = tk.IntVar(value=cur_ms)

        ms_ent = ctk.CTkEntry(
            ms_row, width=54, height=26, corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"), fg_color=PANEL_LIGHT
        )
        ms_ent.insert(0, str(cur_ms))
        ms_ent.pack(side="right", padx=(4, 0))

        ms_slider = ctk.CTkSlider(
            ms_row, from_=200, to=3000, number_of_steps=56,
            variable=ms_var, progress_color=C_AMBER, button_color=C_AMBER
        )
        ms_slider.pack(side="left", fill="x", expand=True)

        def _on_ms_slider(val):
            v = int(float(val))
            self.controller._deadair_min_ms = v
            ms_ent.delete(0, "end"); ms_ent.insert(0, str(v))

        def _on_ms_entry():
            try:
                v = max(100, min(10000, int(ms_ent.get())))
                ms_var.set(v)
                self.controller._deadair_min_ms = v
            except ValueError:
                pass

        ms_slider.configure(command=_on_ms_slider)
        ms_ent.bind("<Return>", lambda e: _on_ms_entry())
        ms_ent.bind("<FocusOut>", lambda e: _on_ms_entry())

        # ── Detect Button ──
        status_lbl = ctk.CTkLabel(
            self._pscroll, text="", font=ctk.CTkFont(size=9), text_color=TXT_G
        )

        def _run_detect():
            if not self.controller.tracks.get("main"):
                from tkinter import messagebox
                messagebox.showwarning("DeadAir Cut", "กรุณานำเข้าวิดีโอบน Main Track ก่อน")
                return

            _on_ms_entry()
            min_ms = getattr(self.controller, "_deadair_min_ms", 500)

            detect_btn.configure(state="disabled", text="⏳ กำลังวิเคราะห์เสียง...")
            status_lbl.configure(text="🔍 กำลังประมวลผล Voice Activity & Waveform Silence...", text_color=TXT_G)
            status_lbl.pack(anchor="w", pady=(2, 4))

            def _worker():
                try:
                    audio_path = self.controller._render_main_track_audio()
                    from transcriber import detect_deadair_segments
                    deadair = detect_deadair_segments(
                        audio_path,
                        min_silence_ms=min_ms,
                        sample_rate=16000,
                        progress_cb=lambda pct_or_msg, msg="": self.controller.after(
                            0, lambda: self.controller._status(str(pct_or_msg) if not msg else f"[{pct_or_msg}%] {msg}")
                        )
                    )
                    self.controller.after(0, lambda: _on_detect_done(deadair))
                except Exception as ex:
                    err_msg = str(ex)
                    self.controller.after(0, lambda: _on_detect_error(err_msg))

            threading.Thread(target=_worker, daemon=True).start()

        def _on_detect_done(deadair):
            detect_btn.configure(state="normal", text="🔍 ตรวจหา Dead Air")
            self.controller._deadair_segments = deadair
            self.controller._selected_deadair_id = None
            self.controller._draw_tl()
            self._tab("DeadAir")

        def _on_detect_error(err):
            detect_btn.configure(state="normal", text="🔍 ตรวจหา Dead Air")
            status_lbl.configure(text=f"❌ Error: {err[:60]}", text_color=C_RED)
            from tkinter import messagebox
            messagebox.showerror("DeadAir Detection Error", err)

        detect_btn = ctk.CTkButton(
            self._pscroll, text="🔍 ตรวจหา Dead Air", height=34, corner_radius=8,
            fg_color=C_BLUE, hover_color=_dark(C_BLUE),
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=_run_detect
        )
        detect_btn.pack(fill="x", pady=(2, 6))

        deadair_list = getattr(self.controller, "_deadair_segments", [])
        if not deadair_list:
            ph = ctk.CTkFrame(self._pscroll, fg_color="transparent")
            ph.pack(fill="both", expand=True, pady=16)
            ctk.CTkLabel(
                ph, text="ยังไม่ได้ตรวจหา Dead Air ในคลิป\nกดปุ่ม 'ตรวจหา Dead Air' ด้านบนเพื่อเริ่มวิเคราะห์",
                font=ctk.CTkFont(size=10), text_color=TXT_L, justify="center"
            ).pack()
            return

        # ── Results & Actions Bar ──
        if not hasattr(self, "_deadair_checks"):
            self._deadair_checks = {}

        # Ensure all existing items have a checkbox var (default True)
        for d in deadair_list:
            did = d["id"]
            if did not in self._deadair_checks:
                self._deadair_checks[did] = tk.BooleanVar(value=True)

        summary_card = ctk.CTkFrame(self._pscroll, fg_color=PANEL_MID, corner_radius=8)
        summary_card.pack(fill="x", pady=(2, 6), padx=2)

        stats_lbl = ctk.CTkLabel(
            summary_card,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=TXT_W, justify="left"
        )
        stats_lbl.pack(anchor="w", padx=8, pady=(6, 2))

        # Select All / None Row
        toggle_row = ctk.CTkFrame(summary_card, fg_color="transparent")
        toggle_row.pack(fill="x", padx=8, pady=(2, 6))

        all_checked = all(self._deadair_checks[d["id"]].get() for d in deadair_list if d["id"] in self._deadair_checks)
        select_all_var = tk.BooleanVar(value=all_checked)

        def _on_toggle_all():
            new_val = select_all_var.get()
            for d in deadair_list:
                did = d["id"]
                if did in self._deadair_checks:
                    self._deadair_checks[did].set(new_val)
            _update_summary()

        select_all_cb = ctk.CTkCheckBox(
            toggle_row,
            text="เลือกทั้งหมด",
            variable=select_all_var,
            command=_on_toggle_all,
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            checkbox_width=18, checkbox_height=18, corner_radius=4,
            fg_color=C_BLUE, hover_color="#2563eb"
        )
        select_all_cb.pack(side="left")

        def _update_summary():
            selected_items = [d for d in deadair_list if self._deadair_checks.get(d["id"], tk.BooleanVar(value=False)).get()]
            num_sel = len(selected_items)
            tot_sel_dur = sum(d["duration"] for d in selected_items)
            total_dur = sum(d["duration"] for d in deadair_list)
            stats_lbl.configure(
                text=f"📊 พบทั้งหมด {len(deadair_list)} ช่วง (รวม {total_dur:.2f}s)\n☑ เลือก {num_sel}/{len(deadair_list)} ช่วง (รวม {tot_sel_dur:.2f}s)"
            )
            if num_sel > 0:
                delete_btn.configure(
                    text=f"🗑  ตัดช่วงที่เลือก ({num_sel} ช่วง)",
                    state="normal",
                    fg_color=C_RED
                )
            else:
                delete_btn.configure(
                    text="🗑  ตัดช่วงที่เลือก (0 ช่วง)",
                    state="disabled",
                    fg_color=PANEL_LIGHT
                )
            select_all_var.set(num_sel == len(deadair_list) and len(deadair_list) > 0)

        # ── Red Delete Selected Button ──
        def _delete_selected_deadair_action():
            from tkinter import messagebox
            selected_items = [d for d in deadair_list if self._deadair_checks.get(d["id"], tk.BooleanVar(value=False)).get()]
            if not selected_items:
                messagebox.showinfo("DeadAir Cut", "กรุณาติ๊กเลือกช่วง Dead Air ที่ต้องการตัดอย่างน้อย 1 ช่วง")
                return

            tot_dur = sum(d["duration"] for d in selected_items)
            if messagebox.askyesno(
                "ตัด Dead Air ที่เลือก",
                f"คุณต้องการตัดช่วง Dead Air ที่เลือกทั้งหมด {len(selected_items)} ช่วง (รวมเวลา {tot_dur:.2f} วินาที) ออกจากโปรเจกต์ใช่หรือไม่?"
            ):
                delete_btn.configure(state="disabled", text="⏳ กำลังตัดต่อ...")
                self.controller._status("⏳ กำลังตัด Dead Air และจัดเรียงแทร็ก...")

                def _do_cut_async():
                    try:
                        self.controller._cut_all_deadair(selected_items)
                        cut_ranges = sorted([(d["start"], d["end"]) for d in selected_items], key=lambda x: x[0], reverse=True)
                        remaining = [d for d in deadair_list if not self._deadair_checks.get(d["id"], tk.BooleanVar(value=False)).get()]
                        for cut_st, cut_en in cut_ranges:
                            dt = cut_en - cut_st
                            shifted = []
                            for x in remaining:
                                if x["start"] >= cut_en:
                                    shifted.append({
                                        "id": x["id"],
                                        "start": round(max(0.0, x["start"] - dt), 3),
                                        "end": round(max(0.0, x["end"] - dt), 3),
                                        "duration": x["duration"]
                                    })
                                elif x["end"] <= cut_st:
                                    shifted.append(x)
                            remaining = shifted
                        for i, r in enumerate(remaining, 1):
                            r["id"] = i
                        self.controller._deadair_segments = remaining
                        self.controller._selected_deadair_id = None
                        self.controller.after(0, lambda: self._tab("DeadAir"))
                    except Exception as ex:
                        err_text = str(ex)
                        self.controller.after(0, lambda: messagebox.showerror("Error", err_text))

                threading.Thread(target=_do_cut_async, daemon=True).start()

        delete_btn = ctk.CTkButton(
            self._pscroll,
            text="🗑  ตัดช่วงที่เลือก",
            height=34, corner_radius=8,
            fg_color=C_RED, hover_color="#dc2626",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=_delete_selected_deadair_action
        )
        delete_btn.pack(fill="x", pady=(0, 8))

        ctk.CTkFrame(self._pscroll, height=1, fg_color=BORD).pack(fill="x", pady=4)

        current_selected_id = getattr(self.controller, "_selected_deadair_id", None)
        card_widgets = {}

        def _highlight_card(active_id):
            self.controller._selected_deadair_id = active_id
            for d_id, (c_row, b_lbl) in card_widgets.items():
                if d_id == active_id:
                    c_row.configure(border_color="#38bdf8", fg_color="#1e293b", border_width=2)
                    b_lbl.configure(text_color="#38bdf8")
                else:
                    c_row.configure(border_color=BORD, fg_color=PANEL_MID, border_width=1)
                    b_lbl.configure(text_color=C_AMBER)

        # ── Progressive Non-Blocking List Population ──
        def _populate_chunk(start_i=0, chunk_size=15):
            if not self.winfo_exists():
                return
            end_i = min(start_i + chunk_size, len(deadair_list))
            for idx in range(start_i, end_i):
                item = deadair_list[idx]
                st = item["start"]
                en = item["end"]
                dur = item["duration"]
                did = item["id"]
                is_active = (did == current_selected_id)

                card_border = "#38bdf8" if is_active else BORD
                card_bg = "#1e293b" if is_active else PANEL_MID
                card_bw = 2 if is_active else 1

                row = ctk.CTkFrame(
                    self._pscroll, fg_color=card_bg, corner_radius=8,
                    border_color=card_border, border_width=card_bw,
                    cursor="hand2"
                )
                row.pack(fill="x", pady=3, padx=2)

                chk = ctk.CTkCheckBox(
                    row, text="", width=18, height=18, corner_radius=4,
                    variable=self._deadair_checks[did],
                    command=_update_summary,
                    fg_color=C_BLUE, hover_color="#2563eb"
                )
                chk.pack(side="left", padx=(8, 2))

                info_col = ctk.CTkFrame(row, fg_color="transparent", cursor="hand2")
                info_col.pack(side="left", fill="both", expand=True, padx=4, pady=6)

                title_row = ctk.CTkFrame(info_col, fg_color="transparent", cursor="hand2")
                title_row.pack(fill="x")

                badge_col = "#38bdf8" if is_active else C_AMBER
                badge_lbl = ctk.CTkLabel(
                    title_row, text=f"#{idx+1}",
                    font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                    text_color=badge_col, width=24, cursor="hand2"
                )
                badge_lbl.pack(side="left")

                time_lbl = ctk.CTkLabel(
                    title_row, text=f"{_ft_ms(st)}  ➜  {_ft_ms(en)}",
                    font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                    text_color=TXT_W, cursor="hand2"
                )
                time_lbl.pack(side="left", padx=4)

                dur_lbl = ctk.CTkLabel(
                    info_col, text=f"ความยาว: {dur:.3f} วินาที",
                    font=ctk.CTkFont(size=8), text_color=TXT_G, cursor="hand2"
                )
                dur_lbl.pack(anchor="w", padx=28)

                btn_col = ctk.CTkFrame(row, fg_color="transparent")
                btn_col.pack(side="right", padx=6, pady=4)

                card_widgets[did] = (row, badge_lbl)

                def _select_card(event=None, s=st, d_id=did):
                    self.controller._stop()
                    self.controller.fi = max(0, int(s * TARGET_FPS))
                    self.controller._render(self.controller.fi)
                    self.controller._scroll_tl_to_time(s)
                    self.controller._draw_tl()
                    _highlight_card(d_id)

                for w in (row, info_col, title_row, badge_lbl, time_lbl, dur_lbl):
                    w.bind("<Button-1>", _select_card)

                def _cut_one(s=st, e=en, item_idx=idx):
                    self.controller._status("⏳ กำลังตัดช่วง Dead Air...")
                    self.controller._cut_timeline_range(s, e)
                    remaining = [x for i, x in enumerate(deadair_list) if i != item_idx]
                    cut_dt = e - s
                    shifted = []
                    for x in remaining:
                        if x["start"] >= e:
                            shifted.append({
                                "id": x["id"],
                                "start": round(max(0.0, x["start"] - cut_dt), 3),
                                "end": round(max(0.0, x["end"] - cut_dt), 3),
                                "duration": x["duration"]
                            })
                        elif x["end"] <= s:
                            shifted.append(x)
                    for i, r in enumerate(shifted, 1):
                        r["id"] = i
                    self.controller._deadair_segments = shifted
                    self.controller._selected_deadair_id = None
                    self._tab("DeadAir")

                ctk.CTkButton(
                    btn_col, text="✂", width=32, height=24, corner_radius=5,
                    fg_color="#dc2626", hover_color="#b91c1c",
                    font=ctk.CTkFont(size=9, weight="bold"),
                    command=_cut_one
                ).pack(side="left", padx=2)

            if end_i < len(deadair_list):
                self.after(5, lambda: _populate_chunk(end_i, chunk_size))
            else:
                _update_summary()

        _populate_chunk(0, 15)

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
