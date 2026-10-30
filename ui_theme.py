# 破晓·工具箱 —— 统一 UI 主题
# 把散落在 app.py 各处的硬编码配色 / 字体收敛到本模块，一处改动、全局生效。
# 使用：import ui_theme；在创建各面板前调用 ui_theme.setup_ttk_style()。
import tkinter.ttk as ttk
import tkinter.font as tkfont
import tkinter as tk

# ---- 配色（浅色主题；深色值已备好，后续可扩展切换）----
COLORS = {
    "bg":         "#f4f6f8",  # 主窗口背景
    "panel":      "#ffffff",  # 面板 / 卡片背景
    "border":     "#d9dde3",  # 描边 / 分隔
    "text":       "#202124",  # 正文
    "muted":      "#5f6368",  # 次要文字
    "accent":     "#1a73e8",  # 主操作（蓝）
    "accent_hi":  "#2b86f5",  # hover
    "accent_lo":  "#b6c5e0",  # disabled
    "success":    "#188038",
    "warn":       "#f9ab00",
    "error":      "#d93025",
    # 命令行（浅色主题用浅色控制台；深色主题在 DARK 里用深色）
    "console_bg": "#ffffff",
    "console_fg": "#202124",
    "cmd_fg":     "#1a73e8",
    "out_fg":     "#202124",
}

# 给浅色 COLORS 补上 setup_ttk_style 需要的 3 个键，保持与 DARK 结构一致
COLORS["scroll"] = "#cfd8dc"
COLORS["heading_bg"] = "#e8eaed"
COLORS["heading_active"] = "#dde2e8"
# 经典控件（笔记编辑器 / 输入框 / 分屏子框 / 行号槽）浅色调色板
COLORS["note_bg"] = "#f4f6f8"
COLORS["note_fg"] = "#202124"
COLORS["note_gutter_bg"] = "#e8eaed"
COLORS["note_gutter_fg"] = "#9aa0a6"
COLORS["note_line_hl"] = "#d1e7ff"
COLORS["note_cursor"] = "#1a73e8"
COLORS["note_sel"] = "#a8d1ff"
COLORS["note_sel_fg"] = "#000000"
COLORS["tint_blue"] = "#e8f0fe"
COLORS["tint_green"] = "#e6f4ea"
COLORS["entry_bg"] = "#ffffff"

# ---- 深色调色板（结构同 COLORS；切换用）----
DARK = {
    "bg":         "#1e1f24",  # 主窗口背景（深）
    "panel":      "#262830",  # 卡片（比窗口稍浅，营造层次）
    "border":     "#3a3d46",
    "text":       "#e6e6e6",
    "muted":      "#9aa0a6",
    "accent":     "#4f9cf9",
    "accent_hi":  "#6cb0ff",
    "accent_lo":  "#33425a",
    "success":    "#34a853",
    "warn":       "#fdd663",
    "error":      "#f28b82",
    "console_bg": "#14151a",
    "console_fg": "#e6e6e6",
    "cmd_fg":     "#82d1ff",
    "out_fg":     "#e6e6e6",
    "scroll":     "#44474f",
    "heading_bg": "#31343d",
    "heading_active": "#3a3d46",
    # 经典控件（笔记编辑器 / 输入框 / 分屏子框 / 行号槽）深色调色板
    "note_bg": "#1e1f24",
    "note_fg": "#e6e6e6",
    "note_gutter_bg": "#262830",
    "note_gutter_fg": "#9aa0a6",
    "note_line_hl": "#2a3a52",
    "note_cursor": "#4f9cf9",
    "note_sel": "#2a4a75",
    "note_sel_fg": "#ffffff",
    "tint_blue": "#263447",
    "tint_green": "#24382e",
    "entry_bg": "#1e1f24",
}

# ---- 主题状态（浅/深切换）与"经典控件"注册表 ----
_dark = {"on": False}
_registry = []  # [(widget, kind)]，kind ∈ {"console", "panel_text"}

def is_dark():
    return _dark["on"]

def set_dark(on):
    _dark["on"] = bool(on)

def active_palette():
    return DARK if _dark["on"] else COLORS

def register(widget, kind):
    """注册一个需随主题切换重套色的经典 tk 控件；
    kind: 'console' | 'panel_text' | 'navbar' | 'nav_button' | 'menu_bar' | 'menu_button'。"""
    _registry.append((widget, kind))

def restyle_classic():
    """按当前主题重套已注册的经典控件。"""
    p = active_palette()
    for w, kind in list(_registry):
        try:
            if kind == "console":
                apply_console(w, p)
            elif kind == "console_light":
                # 命令行区跟随面板配色（浅=白、深=深），不用恒暗的 console_bg
                w.config(bg=p["panel"], fg=p["text"],
                         insertbackground=p["text"],
                         selectbackground=p["accent"], selectforeground="white")
                w.tag_configure("info", foreground=p["text"])
                w.tag_configure("success", foreground=p["success"])
                w.tag_configure("warn", foreground=p["warn"])
                w.tag_configure("error", foreground=p["error"])
                w.tag_configure("cmd", foreground=p["accent"])
                w.tag_configure("orange", foreground=p["accent"])
            elif kind == "panel_text":
                w.config(bg=p["panel"], fg=p["text"])
            elif kind == "navbar":
                w.config(bg=p["heading_bg"])
            elif kind == "nav_button":
                w.config(bg=p["heading_bg"], fg=p["text"],
                         activebackground=p["heading_active"], activeforeground=p["accent"])
            elif kind == "menu_bar":
                w.config(bg=p["bg"])
            elif kind == "menu_button":
                # 当前选中菜单项保持 accent 高亮，其余回落正文色
                fg = p["accent"] if getattr(w, "menu_active", False) else p["text"]
                w.config(bg=p["bg"], fg=fg,
                         activebackground=p["heading_active"], activeforeground=p["accent"])
            elif kind == "menu_sep":
                w.config(bg=p["border"])
            elif kind == "panel_frame":
                w.config(bg=p["panel"], highlightbackground=p["border"])
            elif kind == "entry":
                w.config(bg=p["entry_bg"], fg=p["text"])
            elif kind == "classic_text":
                w.config(bg=p["panel"], fg=p["text"])
            elif kind == "classic_scroll":
                w.config(bg=p["scroll"], troughcolor=p["panel"])
            elif kind == "note_gutter":
                w.config(bg=p["note_gutter_bg"])
            elif kind == "note":
                w.config(bg=p["note_bg"], fg=p["note_fg"],
                         insertbackground=p["note_cursor"],
                         selectbackground=p["note_sel"],
                         selectforeground=p["note_sel_fg"])
            elif kind == "tint":
                # 注册时给 widget 设置 tint_key 属性（"tint_blue" / "tint_green"）
                w.config(bg=p.get(getattr(w, "tint_key", "tint_blue"), p["panel"]))
            elif kind in ("fanyi_button", "rouji_button"):
                w.config(bg=p["heading_bg"], fg=p["text"],
                         activebackground=p["heading_active"], activeforeground=p["accent"])
            elif kind == "panel_button":
                w.config(bg=p["accent"], fg="white",
                         activebackground=p["accent_hi"], activeforeground="white")
            elif kind in ("fanyi_label", "rouji_label"):
                w.config(bg=p["panel"], fg=p["text"])
            elif kind in ("rouji_input",):
                w.config(bg=p["entry_bg"], fg=p["text"])
        except Exception:
            pass


# ---- 字体（高 DPI 下可在 setup_ttk_style 里做 scaling）----
_UI = "Microsoft YaHei"
_MONO = "Consolas"
F = {
    "ui":        (_UI, 10),
    "ui_small":  (_UI, 9),
    "ui_bold":   (_UI, 10, "bold"),
    "title":     (_UI, 14, "bold"),
    "mono":      (_MONO, 11),
    "mono_small":(_MONO, 10),
}


def setup_ttk_style(palette=None):
    """全局 ttk 样式（对 Treeview / Combobox / Labelframe / Scrollbar / Paned 等生效）。
    palette 传 ui_theme.COLORS（浅）或 ui_theme.DARK（深）；不传则用当前主题。
    经典 tk 控件（tk.Button / tk.Text / tk.Entry）不受影响，需单独重套。"""
    p = palette or active_palette()
    s = ttk.Style()
    try:
        s.theme_use("clam")  # clam 对自定义颜色/间距支持最好（vista 主题会忽略多数配色）
    except Exception:
        pass  # 主题缺失时退回默认，不影响功能
    s.configure(".", background=p["panel"], font=F["ui"])
    s.configure("TButton", background=p["accent"], foreground="white",
                font=F["ui"], padding=(8, 4), bordercolor=p["accent"], focuscolor=p["accent"])
    s.map("TButton", background=[("active", p["accent_hi"]),
                                 ("pressed", p["accent"]),
                                 ("disabled", p["accent_lo"])],
          foreground=[("disabled", "#7a7a7a")])
    s.configure("TLabelframe", background=p["panel"], bordercolor=p["border"],
                relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=p["panel"], foreground=p["text"], font=F["ui_bold"])
    s.configure("TLabel", background=p["panel"], foreground=p["text"], font=F["ui"])
    s.configure("TFrame", background=p["panel"])
    s.configure("TPanedwindow", background=p["bg"])
    s.configure("TScrollbar", background=p["scroll"], troughcolor=p["panel"], bordercolor=p["panel"], arrowsize=14)
    s.configure("TCombobox", fieldbackground=p["panel"], background=p["panel"],
                arrowcolor=p["text"], padding=4)
    s.configure("Treeview", background=p["panel"], fieldbackground=p["panel"],
                foreground=p["text"], font=F["mono"], rowheight=24)
    s.configure("Treeview.Heading", font=F["ui_bold"], background=p["heading_bg"],
                foreground=p["text"], relief="flat")
    s.map("Treeview.Heading", background=[("active", p["heading_active"])])
    s.map("Treeview", background=[("selected", p["accent"])],
          foreground=[("selected", "white")])
    s.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["border"],
                bordercolor=p["panel"], lightcolor=p["accent"], darkcolor=p["accent"],
                thickness=8)
    return s


def apply_console(text_widget, palette=None):
    """把 Text 控件配成控制台并预定义常用 tag。palette 不传则用当前主题。"""
    p = palette or active_palette()
    text_widget.configure(
        bg=p["console_bg"], fg=p["console_fg"],
        insertbackground="white", selectbackground=p["accent"],
        selectforeground="white", font=F["mono"], wrap="word",
    )
    text_widget.tag_configure("info", foreground=p["out_fg"])
    text_widget.tag_configure("success", foreground=p["success"])
    text_widget.tag_configure("warn", foreground=p["warn"])
    text_widget.tag_configure("error", foreground=p["error"])
    text_widget.tag_configure("cmd", foreground=p["cmd_fg"])
    text_widget.tag_configure("title", foreground=p["accent"], font=(F["ui"][0], F["ui"][1], "bold"))
    return text_widget


def make_tooltip(widget, text, delay_ms=400):
    """给任意控件加 hover 悬浮提示（轻量、无第三方依赖）。
    用法：ui_theme.make_tooltip(button, "连接服务端并列出肉鸡")。"""
    state = {"win": None, "after": None}

    def _show():
        state["after"] = None
        if state["win"] is not None:
            return
        x = widget.winfo_rootx() + 22
        y = widget.winfo_rooty() + 22
        tipwin = tk.Toplevel(widget)
        tipwin.wm_overrideredirect(True)
        tipwin.wm_geometry(f"+{x}+{y}")
        lb = tk.Label(tipwin, text=text, bg="#3c3f41", fg="white",
                      font=F["ui_small"], padx=8, pady=4, anchor="w")
        lb.pack()
        state["win"] = tipwin

    def _hide():
        if state["after"] is not None:
            try:
                widget.after_cancel(state["after"])
            except Exception:
                pass
            state["after"] = None
        if state["win"] is not None:
            state["win"].destroy()
            state["win"] = None

    def _on_enter(_event):
        if state["win"] is None:
            state["after"] = widget.after(delay_ms, _show)

    widget.bind("<Enter>", _on_enter)
    widget.bind("<Leave>", _hide)
