"""app.py – MediaPro · Launcher  (Minimal Dark — matches editor palette)"""

import customtkinter as ctk
from tkinter import filedialog, simpledialog
import tkinter as tk
import os, json, time, threading
from PIL import Image, ImageTk, ImageDraw
import last_dirs as _ld

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ── Design Tokens — matches editor_utils.py palette ───────────────────────────
BG_DEEP     = "#0d1117"     # deep dark matching editor BG_DEEP
PANEL_DARK  = "#161b22"     # card/panel dark (like editor PANEL_DARK)
PANEL_MID   = "#1c2128"     # slightly lighter panel (editor PANEL_MID)
CARD_BG     = "#1c2128"     # project card background
CARD_HOV    = "#252d38"     # hover state
BORDER_CLR  = "#30363d"     # subtle border
BORDER_HOV  = "#58a6ff"     # hover border accent (editor C_BLUE)
ACCENT_BLUE = "#58a6ff"     # matches editor's blue accent
TEXT_WHITE  = "#e6edf3"     # slightly warm white (editor TXT_W)
TEXT_DIM    = "#7d8590"     # dimmed text
TEXT_FAINT  = "#484f58"     # very faint text


# ── Video Thumbnail Extractor ──────────────────────────────────────────────────
_thumb_cache: dict = {}

def _extract_thumb(path, w=160, h=100, cb=None):
    if path in _thumb_cache:
        if cb: cb(_thumb_cache[path])
        return

    def run():
        try:
            import cv2
            cap = cv2.VideoCapture(path)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                raise RuntimeError("no frame")
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame)

            iw, ih = img.size
            target_ratio = w / h
            if iw / ih > target_ratio:
                new_w = int(ih * target_ratio)
                img = img.crop(((iw - new_w) // 2, 0, (iw + new_w) // 2, ih))
            else:
                new_h = int(iw / target_ratio)
                img = img.crop((0, (ih - new_h) // 2, iw, (ih + new_h) // 2))
            img = img.resize((w, h), Image.LANCZOS)

            _thumb_cache[path] = img
            if cb: cb(img)
        except Exception:
            _thumb_cache[path] = None
            if cb: cb(None)

    threading.Thread(target=run, daemon=True).start()


# ── Recent Projects Helper ─────────────────────────────────────────────────────
def _load_recents():
    f = os.path.join(os.path.dirname(__file__), "recent_projects.json")
    try:
        with open(f) as fp:
            return json.load(fp)
    except Exception:
        return []

def _save_recents(lst):
    f = os.path.join(os.path.dirname(__file__), "recent_projects.json")
    try:
        with open(f, "w") as fp:
            json.dump(lst, fp, indent=2)
    except Exception as e:
        print(f"[Recents] {e}")


# ── Project Card Sizing ────────────────────────────────────────────────────────
CARD_W   = 180         # clean proportional card width
CARD_GAP = 14          # gap between cards
THUMB_W  = 160         # thumbnail width
THUMB_H  = 100         # 16:10 ratio thumbnail


class ProjectCard(ctk.CTkFrame):
    """Minimal dark project card with 3-dot context menu."""

    def __init__(self, parent, proj: dict, on_open, on_refresh, **kw):
        super().__init__(parent,
                         fg_color=CARD_BG,
                         corner_radius=12,
                         border_width=1,
                         border_color=BORDER_CLR,
                         width=CARD_W,
                         cursor="hand2", **kw)
        self._proj = proj
        self._on_open = on_open
        self._on_refresh = on_refresh
        self.pack_propagate(False)
        self._build(proj)

        self.bind("<Button-1>", lambda e: on_open(proj))
        self.bind("<Enter>", self._hover_on)
        self.bind("<Leave>", self._hover_off)

    def _hover_on(self, e=None):
        self.configure(fg_color=CARD_HOV, border_color=BORDER_HOV)

    def _hover_off(self, e=None):
        self.configure(fg_color=CARD_BG, border_color=BORDER_CLR)

    def _build(self, proj):
        # ── Thumbnail canvas ──────────────────────────────────────────────
        pad_x = (CARD_W - THUMB_W) // 2
        thumb_wrap = tk.Frame(self, bg=CARD_BG)
        thumb_wrap.pack(fill="x", padx=pad_x, pady=(pad_x, 0))

        self._tc = tk.Canvas(thumb_wrap, width=THUMB_W, height=THUMB_H,
                             bg=CARD_BG, highlightthickness=0, cursor="hand2")
        self._tc.pack(anchor="center")
        self._tc.bind("<Button-1>", lambda e: self._on_open(self._proj))
        self._tc.bind("<Enter>", self._hover_on)
        self._tc.bind("<Leave>", self._hover_off)

        # Placeholder icon
        self._tc.create_rectangle(0, 0, THUMB_W, THUMB_H, fill="#161b22", outline="")
        self._tc.create_text(THUMB_W // 2, THUMB_H // 2 - 8, text="🎬",
                             font=("Segoe UI", 20), fill="#30363d", tags="icon")
        self._tc.create_text(THUMB_W // 2, THUMB_H // 2 + 14, text="No Preview",
                             font=("Segoe UI", 8), fill="#484f58", tags="icon")

        video = proj.get("main_video", "")
        if video and os.path.exists(video):
            def _on_ready(img, tc=self._tc):
                try:
                    if img and tc.winfo_exists():
                        photo = ImageTk.PhotoImage(img) if not isinstance(img, ImageTk.PhotoImage) else img
                        tc.delete("icon")
                        tc.create_image(THUMB_W // 2, THUMB_H // 2, anchor="center", image=photo, tags="thumb")
                        tc._photo = photo
                except Exception:
                    pass

            def _safe_cb(p):
                try:
                    if self.winfo_exists():
                        self.after(0, lambda: _on_ready(p))
                except Exception:
                    pass

            _extract_thumb(video, THUMB_W, THUMB_H, cb=_safe_cb)


        # ── Info row ──────────────────────────────────────────────────────
        info = tk.Frame(self, bg=CARD_BG)
        info.pack(fill="x", padx=10, pady=(6, 8))
        info.bind("<Button-1>", lambda e: self._on_open(self._proj))
        info.bind("<Enter>", self._hover_on)
        info.bind("<Leave>", self._hover_off)

        name = proj.get("name", "Untitled")
        name_display = (name[:16] + "…") if len(name) > 16 else name

        name_lbl = tk.Label(info, text=name_display,
                            font=("Segoe UI", 10, "bold"),
                            fg=TEXT_WHITE, bg=CARD_BG,
                            anchor="w", cursor="hand2")
        name_lbl.pack(fill="x", anchor="w")
        name_lbl.bind("<Button-1>", lambda e: self._on_open(self._proj))
        name_lbl.bind("<Enter>", self._hover_on)
        name_lbl.bind("<Leave>", self._hover_off)

        ts = proj.get("modified", 0.0)
        date_str = time.strftime("%d/%m/%Y", time.localtime(ts)) if ts else "—"
        p = proj.get("path", "")
        try:
            sz = os.path.getsize(p)
            sz_str = f"{sz // 1024} KB" if sz < 1024 * 1024 else f"{sz // 1048576} MB"
        except Exception:
            sz_str = "—"

        meta_lbl = tk.Label(info, text=f"{date_str}  {sz_str}",
                            font=("Segoe UI", 8),
                            fg=TEXT_DIM, bg=CARD_BG, anchor="w", cursor="hand2")
        meta_lbl.pack(fill="x", anchor="w")
        meta_lbl.bind("<Button-1>", lambda e: self._on_open(self._proj))
        meta_lbl.bind("<Enter>", self._hover_on)
        meta_lbl.bind("<Leave>", self._hover_off)

        # ── 3-dot button (bottom right corner) ───────────────────────────
        dots = tk.Label(self, text="⋯",
                        font=("Segoe UI", 11),
                        fg=TEXT_FAINT, bg=CARD_BG,
                        cursor="hand2", padx=3, pady=1)
        dots.place(relx=1.0, rely=1.0, anchor="se", x=-6, y=-6)
        dots.bind("<Enter>", lambda e: dots.configure(fg=TEXT_WHITE))
        dots.bind("<Leave>", lambda e: dots.configure(fg=TEXT_FAINT))
        dots.bind("<Button-1>", self._show_dots_menu)

    def _show_dots_menu(self, event):
        """Show context menu with Delete / Rename options."""
        event.widget.configure(fg=TEXT_WHITE)

        m = tk.Menu(self, tearoff=0,
                    bg=PANEL_MID, fg=TEXT_WHITE,
                    activebackground=ACCENT_BLUE, activeforeground="#ffffff",
                    relief="flat", bd=0,
                    font=("Segoe UI", 10))
        m.add_command(label="  ✏  เปลี่ยนชื่อโปรเจกต์", command=self._rename_proj)
        m.add_separator()
        m.add_command(label="  🗑  ลบโปรเจกต์", command=self._delete_proj)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _delete_proj(self):
        """Ask for confirmation then remove this project from recents."""
        from tkinter import messagebox
        proj_name = self._proj.get("name", "โปรเจกต์นี้")
        confirmed = messagebox.askyesno(
            "ยืนยันการลบ",
            f'แน่ใจจริง ๆ ใช่มั้ยว่าจะลบ\n"{proj_name}"\nออกจากรายการล่าสุด?',
            icon="warning",
            parent=self.winfo_toplevel()
        )
        if not confirmed:
            return
        proj_path = self._proj.get("path", "")
        recents = _load_recents()
        recents = [p for p in recents if p.get("path") != proj_path]
        _save_recents(recents)
        self._on_refresh()

    def _rename_proj(self):
        """Rename this project in recents list."""
        old_name = self._proj.get("name", "Untitled")
        new_name = simpledialog.askstring(
            "เปลี่ยนชื่อโปรเจกต์",
            "ชื่อใหม่:",
            initialvalue=old_name,
            parent=self.winfo_toplevel()
        )
        if new_name and new_name.strip() and new_name.strip() != old_name:
            new_name = new_name.strip()
            proj_path = self._proj.get("path", "")
            recents = _load_recents()
            for p in recents:
                if p.get("path") == proj_path:
                    p["name"] = new_name
                    try:
                        proj_dir = os.path.dirname(proj_path)
                        new_path = os.path.join(proj_dir, new_name + ".json")
                        if not os.path.exists(new_path):
                            os.rename(proj_path, new_path)
                            p["path"] = new_path
                    except Exception:
                        pass
            _save_recents(recents)
            self._on_refresh()


# ── HomePage Component ─────────────────────────────────────────────────────────
class HomePage(ctk.CTkFrame):
    def __init__(self, master, on_start, on_start_project):
        super().__init__(master, fg_color=BG_DEEP, corner_radius=0)
        self._on_start = on_start
        self._on_start_project = on_start_project
        self._last_cols = -1
        self._cards_built = False
        self._build()

    def _build(self):
        self.configure(fg_color=BG_DEEP)
        for w in self.winfo_children():
            w.destroy()

        # ── Top bar ───────────────────────────────────────────────────────────
        topbar = tk.Frame(self, bg=PANEL_DARK, height=58)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        # Thin accent line at very top
        tk.Frame(self, bg=ACCENT_BLUE, height=2).pack(fill="x", side="top")

        # Left: brand
        brand = tk.Frame(topbar, bg=PANEL_DARK)
        brand.pack(side="left", padx=20, pady=8)

        tk.Label(brand, text="MediaPro",
                 font=("Segoe UI", 17, "bold"),
                 fg=TEXT_WHITE, bg=PANEL_DARK).pack(side="left", padx=(0, 8))
        tk.Label(brand, text="Video Editor",
                 font=("Segoe UI", 10),
                 fg=TEXT_DIM, bg=PANEL_DARK).pack(side="left", pady=(3, 0))

        # Right: Create button + Browse button
        right_bar = tk.Frame(topbar, bg=PANEL_DARK)
        right_bar.pack(side="right", padx=20, pady=10)

        browse_btn = ctk.CTkButton(
            right_bar, text="📂  Browse",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=PANEL_MID, hover_color=CARD_HOV,
            border_width=1, border_color=BORDER_CLR,
            corner_radius=8, height=36, width=110,
            text_color=TEXT_WHITE, cursor="hand2",
            command=self._open_project_dialog
        )
        browse_btn.pack(side="left", padx=(0, 8))

        create_btn = ctk.CTkButton(
            right_bar, text="＋  New Project",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=ACCENT_BLUE, hover_color="#4393d9",
            border_width=0,
            corner_radius=8, height=36, width=140,
            text_color="#ffffff", cursor="hand2",
            command=lambda: self._on_start(None)
        )
        create_btn.pack(side="left")

        # ── Content area ──────────────────────────────────────────────────────
        content = tk.Frame(self, bg=BG_DEEP)
        content.pack(fill="both", expand=True, padx=28, pady=16)

        # Section header
        hdr = tk.Frame(content, bg=BG_DEEP)
        hdr.pack(fill="x", pady=(0, 8))

        tk.Label(hdr, text="Recent Projects",
                 font=("Segoe UI", 13, "bold"),
                 fg=TEXT_WHITE, bg=BG_DEEP).pack(side="left")

        # Subtle horizontal divider
        tk.Frame(content, bg=BORDER_CLR, height=1).pack(fill="x", pady=(0, 14))

        # ── Projects scrollable area ──────────────────────────────────────────
        self._scroll_container = ctk.CTkScrollableFrame(
            content,
            fg_color=BG_DEEP,
            corner_radius=0,
            scrollbar_button_color=PANEL_MID,
            scrollbar_button_hover_color=CARD_HOV,
        )
        self._scroll_container.pack(fill="both", expand=True)

        recents = _load_recents()

        if not recents:
            empty_frame = tk.Frame(self._scroll_container, bg=BG_DEEP)
            empty_frame.pack(expand=True, fill="both", pady=60)

            tk.Label(empty_frame,
                     text="🎬",
                     font=("Segoe UI", 40),
                     fg=TEXT_FAINT, bg=BG_DEEP).pack(pady=(0, 12))
            tk.Label(empty_frame,
                     text="ยังไม่มีโปรเจกต์",
                     font=("Segoe UI", 14, "bold"),
                     fg=TEXT_DIM, bg=BG_DEEP).pack()
            tk.Label(empty_frame,
                     text='กด "＋ New Project" หรือ "📂 Browse" เพื่อเริ่มใช้งาน',
                     font=("Segoe UI", 10),
                     fg=TEXT_FAINT, bg=BG_DEEP).pack(pady=(4, 0))
        else:
            self._grid_frame = tk.Frame(self._scroll_container, bg=BG_DEEP)
            self._grid_frame.pack(fill="both", expand=True)

            self._recents = recents
            self._cards_built = False
            self._last_cols = -1

            # Bind resize to the main window container
            self.bind("<Configure>", self._on_resize)
            self.after(50, self._layout_cards)

    def _on_resize(self, event):
        if event.widget == self:
            self._layout_cards()

    def _layout_cards(self):
        """Arrange project cards in a strict wrapping grid based on visible container width."""
        if not hasattr(self, "_grid_frame") or not self._grid_frame.winfo_exists():
            return
        recents = getattr(self, "_recents", [])
        if not recents:
            return

        frame = self._grid_frame

        # Use visible width from scroll container
        container_w = self._scroll_container.winfo_width()
        if container_w <= 50:
            container_w = self.winfo_width() - 56

        # Deduct margins & scrollbar width (~24px)
        avail_w = max(100, container_w - 24)

        card_slot = CARD_W + CARD_GAP
        cols = max(1, avail_w // card_slot)

        # Avoid redundant rebuilds if column count hasn't changed
        if hasattr(self, "_last_cols") and self._last_cols == cols and self._cards_built:
            return
        self._last_cols = cols
        self._cards_built = True

        for w in frame.winfo_children():
            w.destroy()

        for i, proj in enumerate(recents):
            row = i // cols
            col = i % cols
            card = ProjectCard(frame, proj,
                               on_open=lambda p: self._on_start_project(p.get("path", "")),
                               on_refresh=self._refresh)
            card.grid(row=row, column=col,
                      padx=CARD_GAP // 2,
                      pady=CARD_GAP // 2,
                      sticky="nw")

    def _refresh(self):
        """Refresh the entire page (after delete/rename)."""
        self._build()

    def _open_project_dialog(self):
        path = filedialog.askopenfilename(
            title="Open Project",
            initialdir=_ld.get(_ld.BROWSE_PROJECT),
            filetypes=[("MediaPro Project", "*.json"), ("All Files", "*.*")]
        )
        if path:
            _ld.remember(_ld.BROWSE_PROJECT, path)
            self._on_start_project(path)


# ── App Window ─────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MediaPro")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.configure(fg_color=BG_DEEP)
        self._page = None
        self._show_home()
        self.protocol("WM_DELETE_WINDOW", self._on_close_window)
        threading.Thread(target=self._prewarm, daemon=True).start()

    def _prewarm(self):
        try:
            import editor_page
            import video_exporter
            import subtitle_renderer
        except Exception:
            pass

    def _show_home(self):
        self.geometry("1100x720")
        self.minsize(900, 600)
        self._swap(HomePage, on_start=self._on_start, on_start_project=self._on_start_project)

    def _on_start(self, initial_video):
        from editor_page import EditorPage
        self.geometry("1680x960")
        self.minsize(1200, 700)
        self._swap(EditorPage, initial_video=initial_video, on_back=self._show_home)

    def _on_start_project(self, project_path):
        from editor_page import EditorPage
        self.geometry("1680x960")
        self.minsize(1200, 700)
        self._swap(EditorPage, initial_video=None, initial_project=project_path, on_back=self._show_home)

    def _on_close_window(self):
        from editor_page import EditorPage
        if isinstance(self._page, EditorPage):
            self._page._back()
        else:
            self.destroy()

    def _swap(self, PageClass, **kw):
        if self._page:
            self._page.destroy()
        self._page = PageClass(self, **kw)
        self._page.pack(fill="both", expand=True)


if __name__ == "__main__":
    app = App()
    app.mainloop()
