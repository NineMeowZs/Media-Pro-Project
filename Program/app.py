"""app.py – MediaPro · Launcher (Zero Black Corners & Matching Card Colors)"""

import customtkinter as ctk
from tkinter import filedialog
import tkinter as tk
import os, json, time, math, threading
from PIL import Image, ImageTk, ImageDraw

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ── Design Tokens ──────────────────────────────────────────────────────────────
BG_DEEP     = "#070b14"      # deep cosmic background
CARD_NAVY   = "#0a1936"      # main card dark navy blue
CARD_MID    = "#0f2347"      # project card navy background (matching card blue)
CARD_HOV    = "#183261"      # hover state
BORDER_CLR  = "#ffffff"      # crisp white border line
ACCENT_CYAN = "#00d4ff"
ACCENT_BLUE = "#3b82f6"
TEXT_WHITE  = "#ffffff"
TEXT_DIM    = "#a0aec0"
TEXT_FAINT  = "#64748b"


# ── PIL Helper: High-DPI Rounded Rectangle Image Generator ────────────────────
_card_img_cache: dict = {}

def get_rounded_card_image(width, height, radius=20, bg_color=CARD_NAVY, border_color="#ffffff", border_width=2):
    """Generate 100% alpha-transparent corners rounded rectangle image via PIL antialiasing."""
    key = (width, height, radius, bg_color, border_color, border_width)
    if key in _card_img_cache:
        return _card_img_cache[key]

    scale = 3  # 3x supersampling for ultra-crisp antialiasing
    w, h = max(10, width * scale), max(10, height * scale)
    r = radius * scale
    bw = border_width * scale

    # 100% Alpha transparent RGBA canvas
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def hex_to_rgba(hex_str, alpha=255):
        hex_str = hex_str.lstrip('#')
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16), alpha)

    bg_rgba = hex_to_rgba(bg_color)
    border_rgba = hex_to_rgba(border_color)

    # Outer border rounded rect
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=border_rgba)
    # Inner fill rounded rect
    draw.rounded_rectangle([bw, bw, w - 1 - bw, h - 1 - bw], radius=max(1, r - bw), fill=bg_rgba)

    # Supersampled Lanczos resize
    img = img.resize((max(1, width), max(1, height)), Image.LANCZOS)
    photo = ImageTk.PhotoImage(img)
    _card_img_cache[key] = photo
    return photo


# ── Full Seamless Aurora & Stars Background Canvas ─────────────────────────────
class AuroraCanvas(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, highlightthickness=0, **kw)
        self._ph = 0.0
        import random
        random.seed(42)
        self._stars = [(random.randint(0, 1920), random.randint(0, 1080), random.choice([1, 2]), random.choice(["#ffffff", "#94a3b8", "#38bdf8"])) for _ in range(90)]
        self._win_w, self._win_h = 0, 0
        self._items_created = False
        self._bg_rects = []
        self._glow_ovals = []
        
        self.bind("<Configure>", self._on_resize)
        self._tick()

    def _on_resize(self, event):
        if event.widget == self:
            if abs(event.width - self._win_w) > 4 or abs(event.height - self._win_h) > 4:
                self._win_w = event.width
                self._win_h = event.height
                self._build_items()

    def _build_items(self):
        self.delete("all")
        w, h = self._win_w, self._win_h
        if w < 10 or h < 10:
            return

        self._bg_rects = []
        rows = max(1, h // 6)
        for i in range(rows + 1):
            y0 = int(i * h / rows)
            y1 = int((i + 1) * h / rows)
            item = self.create_rectangle(0, y0, w, y1, fill="#070b14", outline="", tags="bg")
            self._bg_rects.append((item, i / rows))

        for sx, sy, sr, scol in self._stars:
            if sx < w and sy < h:
                self.create_oval(sx-sr, sy-sr, sx+sr, sy+sr, fill=scol, outline="", tags="bg")

        self._glow_ovals = []
        cx = int(w * 0.88)
        cy = int(h * 0.45)
        for rad in range(280, 0, -18):
            item = self.create_oval(cx-rad, cy-rad, cx+rad, cy+rad, fill="#000000", outline="", tags="bg")
            self._glow_ovals.append((item, rad / 280))

        self._items_created = True

    def _tick(self):
        self._ph += 0.006
        self._update_colors()
        self.after(45, self._tick)

    def _update_colors(self):
        if not self._items_created or self._win_w < 10 or self._win_h < 10:
            return

        for item, t in self._bg_rects:
            pulse = 0.5 + 0.5 * math.sin(self._ph + t * 2.0)
            r = max(0, min(255, int(6  + 8 * t * pulse)))
            g = max(0, min(255, int(8  + 6  * (1 - t))))
            b = max(0, min(255, int(16 + 32 * (1 - t) + 12 * pulse)))
            self.itemconfig(item, fill=f"#{r:02x}{g:02x}{b:02x}")

        for item, a in self._glow_ovals:
            rr = max(0, min(255, int(10 * a)))
            gg = max(0, min(255, int(55 * a * (0.6 + 0.4 * math.sin(self._ph)))))
            bb = max(0, min(255, int(65 * a * (0.5 + 0.5 * math.cos(self._ph * 0.8)))))
            self.itemconfig(item, fill=f"#{rr:02x}{gg:02x}{bb:02x}")


# ── True Alpha Transparent Canvas Card ────────────────────────────────────────
class AlphaCard:
    """Card backdrop drawn directly on AuroraCanvas to blend alpha corners natively."""
    def __init__(self, canvas: AuroraCanvas, x_rel, y_rel, w_rel, h_rel=None, height_px=None, radius=20, bg_color=CARD_NAVY, border_color="#ffffff"):
        self.canvas = canvas
        self.x_rel = x_rel
        self.y_rel = y_rel
        self.w_rel = w_rel
        self.h_rel = h_rel
        self.height_px = height_px
        self.radius = radius
        self.bg_color = bg_color
        self.border_color = border_color
        
        self.img_tag = None
        self.win_tag = None
        self._cur_w = 0
        self._cur_h = 0
        
        # Content frame placed inside card
        self.frame = tk.Frame(canvas, bg=bg_color)
        canvas.bind("<Configure>", self._on_resize, add="+")

    def _on_resize(self, event):
        if event.widget == self.canvas:
            w_total = event.width
            h_total = event.height
            card_w = int(w_total * self.w_rel)
            card_h = self.height_px if self.height_px else int(h_total * self.h_rel)
            card_x = int(w_total * self.x_rel)
            card_y = int(h_total * self.y_rel)

            if abs(card_w - self._cur_w) > 2 or abs(card_h - self._cur_h) > 2:
                self._cur_w = card_w
                self._cur_h = card_h
                self._redraw(card_x, card_y, card_w, card_h)

    def _redraw(self, x, y, w, h):
        if self.img_tag: self.canvas.delete(self.img_tag)
        if self.win_tag: self.canvas.delete(self.win_tag)
        if w < 10 or h < 10: return

        photo = get_rounded_card_image(w, h, self.radius, self.bg_color, self.border_color)
        self.img_tag = self.canvas.create_image(x, y, anchor="nw", image=photo)
        self.canvas._photos = getattr(self.canvas, "_photos", []) + [photo]

        # Inner content window inset safely by 12px so child frames never clip the 20px rounded border
        bw = 12
        self.win_tag = self.canvas.create_window(x + bw, y + bw, anchor="nw",
                                                  window=self.frame,
                                                  width=max(1, w - bw*2),
                                                  height=max(1, h - bw*2))

    def set_colors(self, bg_color, border_color):
        self.bg_color = bg_color
        self.border_color = border_color
        self.frame.configure(bg=bg_color)
        w_total = self.canvas.winfo_width()
        h_total = self.canvas.winfo_height()
        if w_total > 10 and h_total > 10:
            card_w = int(w_total * self.w_rel)
            card_h = self.height_px if self.height_px else int(h_total * self.h_rel)
            card_x = int(w_total * self.x_rel)
            card_y = int(h_total * self.y_rel)
            self._redraw(card_x, card_y, card_w, card_h)


# ── Video Thumbnail Extractor ──────────────────────────────────────────────────
_thumb_cache: dict = {}

def _extract_thumb(path, w=150, h=160, cb=None):
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
            
            photo = ImageTk.PhotoImage(img)
            _thumb_cache[path] = photo
            if cb: cb(photo)
        except Exception:
            _thumb_cache[path] = None
            if cb: cb(None)

    threading.Thread(target=run, daemon=True).start()


# ── Project Thumbnail Card Component ──────────────────────────────────────────
THUMB_W = 150
THUMB_H = 160

class ProjectCard(ctk.CTkFrame):
    """Project card using matching CARD_MID navy background (NO BLACK)."""

    def __init__(self, parent, proj: dict, on_open, **kw):
        super().__init__(parent, fg_color=CARD_MID,
                         corner_radius=18,
                         border_width=2,
                         border_color="#ffffff",
                         width=THUMB_W + 12,
                         cursor="hand2", **kw)
        self._proj = proj
        self._on_open = on_open
        self._build(proj)
        self.bind("<Button-1>", lambda e=None: on_open(proj))
        self.bind("<Enter>", lambda e=None: self.configure(fg_color=CARD_HOV, border_color=ACCENT_CYAN))
        self.bind("<Leave>", lambda e=None: self.configure(fg_color=CARD_MID, border_color="#ffffff"))

    def _build(self, proj):
        # Video thumbnail canvas — using CARD_MID navy background (matching card blue!)
        self._tc = tk.Canvas(self, width=THUMB_W, height=THUMB_H,
                             bg=CARD_MID, highlightthickness=0,
                             cursor="hand2")
        self._tc.pack(padx=6, pady=(6, 4))
        self._tc.bind("<Button-1>", lambda e=None: self._on_open(self._proj))
        self._tc.bind("<Enter>", lambda e=None: self.configure(fg_color=CARD_HOV, border_color=ACCENT_CYAN))
        self._tc.bind("<Leave>", lambda e=None: self.configure(fg_color=CARD_MID, border_color="#ffffff"))

        self._tc.create_text(THUMB_W//2, THUMB_H//2 - 10, text="🖼",
                             font=("Segoe UI", 36), fill="#2a4365", tags="icon")
        self._tc.create_text(THUMB_W//2, THUMB_H//2 + 25, text="Video Preview",
                             font=("Segoe UI", 9), fill="#4a5568", tags="icon")

        video = proj.get("main_video", "")
        if video and os.path.exists(video):
            def _on_ready(photo, tc=self._tc):
                try:
                    if photo:
                        tc.delete("icon")
                        tc.create_image(0, 0, anchor="nw", image=photo, tags="img")
                        tc._photo = photo
                except Exception:
                    pass
            _extract_thumb(video, THUMB_W, THUMB_H, cb=lambda p: self.after(0, lambda: _on_ready(p)))

        info = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        info.pack(fill="x", padx=8, pady=(2, 8))
        info.bind("<Button-1>", lambda e=None: self._on_open(self._proj))
        info.bind("<Enter>", lambda e=None: self.configure(fg_color=CARD_HOV, border_color=ACCENT_CYAN))
        info.bind("<Leave>", lambda e=None: self.configure(fg_color=CARD_MID, border_color="#ffffff"))

        name = proj.get("name", "Untitled")
        name_display = (name[:16] + "…") if len(name) > 16 else name
        lbl_name = ctk.CTkLabel(info, text=name_display,
                                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                                text_color=TEXT_WHITE, anchor="w", cursor="hand2")
        lbl_name.pack(fill="x")
        lbl_name.bind("<Button-1>", lambda e=None: self._on_open(self._proj))
        lbl_name.bind("<Enter>", lambda e=None: self.configure(fg_color=CARD_HOV, border_color=ACCENT_CYAN))
        lbl_name.bind("<Leave>", lambda e=None: self.configure(fg_color=CARD_MID, border_color="#ffffff"))

        ts = proj.get("modified", 0.0)
        date_str = time.strftime("%d/%m/%Y", time.localtime(ts))
        p = proj.get("path", "")
        try:
            sz = os.path.getsize(p)
            sz_str = f"{sz//1024} KB" if sz < 1024*1024 else f"{sz//1048576} MB"
        except Exception:
            sz_str = "0 KB"

        meta_str = f"{date_str} │ {sz_str}"
        meta = ctk.CTkLabel(info, text=meta_str,
                            font=ctk.CTkFont(family="Segoe UI", size=9),
                            text_color=TEXT_DIM, anchor="w", cursor="hand2")
        meta.pack(fill="x")
        meta.bind("<Button-1>", lambda e=None: self._on_open(self._proj))
        meta.bind("<Enter>", lambda e=None: self.configure(fg_color=CARD_HOV, border_color=ACCENT_CYAN))
        meta.bind("<Leave>", lambda e=None: self.configure(fg_color=CARD_MID, border_color="#ffffff"))


# ── HomePage Component ─────────────────────────────────────────────────────────
class HomePage(ctk.CTkFrame):
    def __init__(self, master, on_start, on_start_project):
        super().__init__(master, fg_color=BG_DEEP, corner_radius=0)
        self._on_start = on_start
        self._on_start_project = on_start_project
        self._build()

    def _build(self):
        aurora = AuroraCanvas(self, bg=BG_DEEP)
        aurora.place(relwidth=1.0, relheight=1.0)
        self._aurora = aurora

        # ── 1. Top-Left Card: MediaPro ────────────────────────────────────────
        card1 = AlphaCard(aurora, x_rel=0.05, y_rel=0.05, w_rel=0.30, height_px=90, radius=20, bg_color=CARD_NAVY, border_color="#ffffff")
        inner1 = tk.Frame(card1.frame, bg=CARD_NAVY)
        inner1.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(inner1, text="MediaPro", font=("Segoe UI", 20, "bold"),
                 fg=TEXT_WHITE, bg=CARD_NAVY).pack(anchor="center")
        tk.Label(inner1, text="Editing Software ที่พยายามครบจบในที่เดียว", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=CARD_NAVY).pack(anchor="center", pady=(2, 0))

        # ── 2. Top-Right Card: + Create Project ───────────────────────────────
        card2 = AlphaCard(aurora, x_rel=0.37, y_rel=0.05, w_rel=0.58, height_px=90, radius=20, bg_color=CARD_NAVY, border_color="#ffffff")
        lbl2 = tk.Label(card2.frame, text="＋  Create Project", font=("Segoe UI", 18, "bold"),
                        fg=TEXT_WHITE, bg=CARD_NAVY, cursor="hand2")
        lbl2.place(relx=0.5, rely=0.5, anchor="center")

        def _hover2_on(e):
            card2.set_colors(CARD_HOV, ACCENT_CYAN)
            lbl2.configure(bg=CARD_HOV, fg=ACCENT_CYAN)
        def _hover2_off(e):
            card2.set_colors(CARD_NAVY, "#ffffff")
            lbl2.configure(bg=CARD_NAVY, fg=TEXT_WHITE)

        for w in [card2.frame, lbl2]:
            w.bind("<Button-1>", lambda e: self._browse())
            w.bind("<Enter>", _hover2_on)
            w.bind("<Leave>", _hover2_off)

        # ── 3. Bottom Card: Projects ──────────────────────────────────────────
        card3 = AlphaCard(aurora, x_rel=0.05, y_rel=0.20, w_rel=0.90, h_rel=0.74, radius=20, bg_color=CARD_NAVY, border_color="#ffffff")
        
        # Header inside Projects card
        hdr = tk.Frame(card3.frame, bg=CARD_NAVY, height=48)
        hdr.pack(fill="x", padx=16, pady=(10, 0))
        hdr.pack_propagate(False)

        tk.Label(hdr, text="Projects", font=("Segoe UI", 20, "bold"),
                 fg=TEXT_WHITE, bg=CARD_NAVY).pack(side="left", padx=6, pady=4)

        # Browse button with radius 20
        browse_box = tk.Frame(hdr, bg=CARD_NAVY, cursor="hand2")
        browse_box.pack(side="right", padx=6, pady=2)
        
        browse_btn = ctk.CTkButton(
            browse_box, text="＋ Browse",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=CARD_MID, hover_color=CARD_HOV,
            border_width=2, border_color="#ffffff",
            corner_radius=20, height=36, width=110,
            text_color=TEXT_WHITE, cursor="hand2",
            command=self._open_project_dialog
        )
        browse_btn.pack()

        # White Divider Line
        tk.Frame(card3.frame, bg="#ffffff", height=1.5).pack(fill="x", padx=16, pady=(4, 0))

        # Scrollable Thumbnail Grid (using matching CARD_NAVY background)
        scroll = ctk.CTkScrollableFrame(
            card3.frame,
            fg_color=CARD_NAVY,
            corner_radius=0,
            orientation="horizontal",
            scrollbar_button_color="#1a365d",
            scrollbar_button_hover_color=CARD_HOV,
        )
        scroll.pack(fill="both", expand=True, padx=14, pady=12)

        recents = self._load_recents()

        if not recents:
            ctk.CTkLabel(scroll,
                         text="ยังไม่มีโปรเจกต์\nกด  ＋ Create Project  หรือ  ＋ Browse  เพื่อเริ่มใช้งาน",
                         font=ctk.CTkFont(family="Segoe UI", size=13),
                         text_color=TEXT_DIM,
                         justify="center"
                         ).pack(expand=True, pady=50)
        else:
            for proj in recents:
                p_card = ProjectCard(scroll, proj,
                                     on_open=lambda p: self._on_start_project(p.get("path", "")))
                p_card.pack(side="left", padx=(0, 16), pady=6, anchor="n")

    # ── File Dialog Helpers ───────────────────────────────────────────────────
    def _load_recents(self):
        f = os.path.join(os.path.dirname(__file__), "recent_projects.json")
        try:
            with open(f) as fp:
                return json.load(fp)
        except Exception:
            return []

    def _open_project_dialog(self):
        path = filedialog.askopenfilename(
            title="Open Project",
            filetypes=[("MediaPro Project", "*.json"), ("All Files", "*.*")]
        )
        if path:
            self._on_start_project(path)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Import Video",
            filetypes=[("Video Files", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v"),
                       ("All Files", "*.*")]
        )
        if path:
            self._on_start(path)


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
