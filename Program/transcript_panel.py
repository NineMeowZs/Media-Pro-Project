import tkinter as tk
import customtkinter as ctk
from editor_utils import (
    PANEL_DARK, PANEL_MID, PANEL_LIGHT, PANEL_HOV,
    TXT_W, TXT_G, TXT_L, BORD, C_BLUE, C_AMBER, C_RED, C_GREEN, TARGET_FPS
)

class TranscriptPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="transparent")
        self.controller = controller
        self._segments = []
        self.row_widgets = {}
        self.selected_idx = -1
        self._editing_idx = -1

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=4, pady=(4, 2))

        ctk.CTkLabel(
            hdr,
            text="📝 Transcript",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TXT_W
        ).pack(side="left")

        # Divider
        ctk.CTkFrame(self, height=1, fg_color=BORD).pack(fill="x", pady=4)

        # Search Entry
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        
        self.search_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.search_frame.pack(fill="x", padx=4, pady=(0, 4))
        
        self.search = ctk.CTkEntry(
            self.search_frame,
            placeholder_text="🔍 Search...",
            textvariable=self.search_var,
            height=28,
            corner_radius=6,
            fg_color=PANEL_MID,
            border_color=BORD,
            text_color=TXT_W,
            placeholder_text_color=TXT_G
        )
        self.search.pack(side="left", fill="x", expand=True, padx=(0, 2))

        # Persistent Import SRT Button
        self.import_btn = ctk.CTkButton(
            self.search_frame,
            text="📂 Import",
            height=28,
            width=58,
            corner_radius=6,
            fg_color=PANEL_MID,
            hover_color=PANEL_HOV,
            font=ctk.CTkFont(size=9, weight="bold"),
            command=self.controller._import_srt
        )
        self.import_btn.pack(side="left", padx=2)

        # Persistent Auto Subtitle Button
        self.regen_btn = ctk.CTkButton(
            self.search_frame,
            text="🎙 Auto",
            height=28,
            width=50,
            corner_radius=6,
            fg_color=C_BLUE,
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=9, weight="bold"),
            command=self.controller._sub_dialog
        )
        self.regen_btn.pack(side="left", padx=2)

        # Scrollable Frame for transcript rows
        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=PANEL_LIGHT
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Bind search shortcut
        if hasattr(self.controller, "master"):
            self.controller.master.bind("<Control-f>", self._focus_search)
            self.controller.master.bind("<Control-F>", self._focus_search)

    def _focus_search(self, event=None):
        self.search.focus_set()
        self.search.select_range(0, 'end')
        return "break"

    def set_segments(self, segments):
        self._segments = segments or []
        self.refresh()

    def refresh(self):
        # Stop inline editing if any
        self._editing_idx = -1
        try:
            self.focus_set()
        except Exception:
            pass

        # Clear existing row widgets
        for w in list(self.scroll_frame.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        self.row_widgets.clear()

        # If no segments, show placeholder with options
        if not self._segments:
            self._show_placeholder()
            return

        # Build row widgets
        self.scroll_frame.columnconfigure(0, weight=1)

        for idx, seg in enumerate(self._segments):
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent", corner_radius=6)
            row.grid(row=idx, column=0, sticky="ew", padx=4, pady=2)

            # Format start time mm:ss
            t = seg.get("start", 0)
            mm = int(t // 60)
            ss = int(t % 60)
            time_str = f"{mm:02d}:{ss:02d}"

            time_lbl = ctk.CTkLabel(
                row,
                text=time_str,
                font=ctk.CTkFont(family="Courier", size=10, weight="bold"),
                text_color=C_AMBER,
                width=45
            )
            time_lbl.pack(side="left", padx=(6, 4), pady=6)

            text_lbl = ctk.CTkLabel(
                row,
                text=seg.get("text", ""),
                font=ctk.CTkFont(size=11),
                text_color=TXT_W,
                justify="left",
                anchor="w",
                wraplength=180
            )
            text_lbl.pack(side="left", fill="x", expand=True, padx=(4, 6), pady=6)

            # Keep references
            self.row_widgets[idx] = row
            row.time_lbl = time_lbl
            row.text_lbl = text_lbl

            # Bind mouse clicks and hovers
            for w in (row, time_lbl, text_lbl):
                w.bind("<Button-1>", lambda e, segment_idx=idx: self._on_row_click(segment_idx))
                w.bind("<Double-Button-1>", lambda e, segment_idx=idx: self._on_row_double_click(segment_idx))
                w.bind("<Enter>", lambda e, r=row, segment_idx=idx: self._on_row_hover(r, segment_idx, True))
                w.bind("<Leave>", lambda e, r=row, segment_idx=idx: self._on_row_hover(r, segment_idx, False))
                # Bind key events for navigation
                w.bind("<Key>", self._on_key_down)

        # Re-apply filtering
        self.filter(self.search_var.get())
        # Re-apply selection
        self.select_segment(self.selected_idx)

    def _show_placeholder(self):
        self.scroll_frame.columnconfigure(0, weight=1)
        ph = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        ph.grid(row=0, column=0, sticky="nsew", pady=40)

        ctk.CTkLabel(
            ph,
            text="No Subtitles Loaded",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TXT_L
        ).pack(pady=(0, 10))

        ctk.CTkButton(
            ph,
            text="🎙  Generate Subtitles",
            fg_color=C_BLUE,
            hover_color="#1d4ed8",
            height=32,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.controller._sub_dialog
        ).pack(fill="x", padx=20, pady=4)

        if hasattr(self.controller, "_import_srt"):
            ctk.CTkButton(
                ph,
                text="📂  Import SRT...",
                fg_color=PANEL_MID,
                hover_color=PANEL_LIGHT,
                height=32,
                font=ctk.CTkFont(size=10),
                command=self.controller._import_srt
            ).pack(fill="x", padx=20, pady=4)

    def _on_row_hover(self, row, idx, hover):
        if idx == self.selected_idx:
            return  # keep selection background
        if hover:
            row.configure(fg_color=PANEL_MID)
        else:
            row.configure(fg_color="transparent")

    def _on_row_click(self, idx):
        self.controller.seek_to_segment(idx)
        # Request focus so keyboard events go here
        self.row_widgets[idx].focus_set()

    def _on_row_double_click(self, idx):
        self._start_inline_edit(idx)

    def _on_search_change(self, *args):
        self.filter(self.search_var.get())

    def filter(self, text):
        text = text.lower().strip()
        for idx, row in self.row_widgets.items():
            seg = self._segments[idx]
            if text in seg.get("text", "").lower():
                row.grid(row=idx, column=0, sticky="ew", padx=4, pady=2)
            else:
                row.grid_forget()

    def select_segment(self, index):
        self.selected_idx = index
        for idx, row in self.row_widgets.items():
            if idx == index:
                row.configure(fg_color="#1e3a8a")  # beautiful dark blue highlight
                row.time_lbl.configure(text_color=TXT_W)
                row.text_lbl.configure(text_color=TXT_W)
            else:
                row.configure(fg_color="transparent")
                row.time_lbl.configure(text_color=C_AMBER)
                row.text_lbl.configure(text_color=TXT_W)

    def scroll_to_segment(self, index):
        if index not in self.row_widgets:
            return
        row = self.row_widgets[index]
        self.update_idletasks()

        y = row.winfo_y()
        h = row.winfo_height()

        canvas = self.scroll_frame._parent_canvas
        canvas_h = canvas.winfo_height()
        total_h = self.scroll_frame.winfo_height()

        if total_h <= canvas_h or canvas_h <= 0:
            return

        top, bottom = canvas.yview()
        view_top = top * total_h
        view_bottom = bottom * total_h

        # Scroll to bring row into view with some margin
        if y < view_top:
            canvas.yview_moveto(max(0.0, y / total_h))
        elif (y + h) > view_bottom:
            canvas.yview_moveto(min(1.0, (y + h - canvas_h + 10) / total_h))

    # --- Inline Editing ---
    def _is_inline_editing(self):
        return self._editing_idx != -1

    def _start_inline_edit(self, idx):
        if self._editing_idx == idx:
            return
        if self._editing_idx != -1:
            self._cancel_inline_edit(self._editing_idx)

        self._editing_idx = idx
        row = self.row_widgets[idx]
        
        # Hide original text label
        row.text_lbl.pack_forget()

        # Create entry
        entry = ctk.CTkEntry(
            row,
            height=26,
            corner_radius=4,
            fg_color=PANEL_LIGHT,
            border_color=C_BLUE,
            text_color=TXT_W
        )
        entry.insert(0, self._segments[idx].get("text", ""))
        entry.pack(side="left", fill="x", expand=True, padx=(4, 6), pady=6)
        entry.focus_set()
        entry.select_range(0, 'end')

        entry.bind("<Return>", lambda e: self._save_inline_edit(idx, entry.get()))
        entry.bind("<FocusOut>", lambda e: self._save_inline_edit(idx, entry.get()))
        entry.bind("<Escape>", lambda e: self._cancel_inline_edit(idx))
        row.edit_entry = entry

    def _save_inline_edit(self, idx, text):
        if self._editing_idx != idx:
            return
        text = text.strip()
        
        # Update data structures
        self._segments[idx]["text"] = text
        
        # Update timeline subtitles clip in controller
        if idx < len(self.controller.tracks.get("subtitle", [])):
            clip = self.controller.tracks["subtitle"][idx]
            clip["sub_text"] = text
            clip["name"] = text[:24]

        # Destroy entry & restore label
        row = self.row_widgets[idx]
        if hasattr(row, "edit_entry"):
            row.edit_entry.destroy()
            del row.edit_entry

        row.text_lbl.configure(text=text)
        row.text_lbl.pack(side="left", fill="x", expand=True, padx=(4, 6), pady=6)
        
        self._editing_idx = -1

        # Redraw timeline, refresh preview and push undo state
        self.controller._draw_tl()
        self.controller._refresh_preview()
        self.controller._push_undo()

        # Refocus row
        row.focus_set()

    def _cancel_inline_edit(self, idx):
        if self._editing_idx != idx:
            return
        row = self.row_widgets[idx]
        if hasattr(row, "edit_entry"):
            row.edit_entry.destroy()
            del row.edit_entry

        row.text_lbl.pack(side="left", fill="x", expand=True, padx=(4, 6), pady=6)
        self._editing_idx = -1
        row.focus_set()

    # --- Keyboard Navigation ---
    def _navigate_segments(self, direction):
        if not self._segments:
            return
        
        # If no selection, select first segment
        if self.selected_idx == -1:
            idx = 0
        else:
            idx = max(0, min(len(self._segments) - 1, self.selected_idx + direction))
            
        self.controller.seek_to_segment(idx)
        if idx in self.row_widgets:
            self.row_widgets[idx].focus_set()

    def _on_key_down(self, event):
        # Check global typing state to ensure shortcuts don't conflict with editing text
        if self.controller._is_typing() and not self._is_inline_editing():
            if event.keysym in ("Up", "Down"):
                self._navigate_segments(-1 if event.keysym == "Up" else 1)
                return "break"
            return
            
        if event.keysym == "Up":
            self._navigate_segments(-1)
            return "break"
        elif event.keysym == "Down":
            self._navigate_segments(1)
            return "break"
        elif event.keysym == "space":
            self.controller._toggle_play()
            return "break"
        elif event.keysym == "Return":
            self._start_inline_edit(self.selected_idx)
            return "break"