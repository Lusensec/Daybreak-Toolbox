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
    # 命令行（深色控制台）
    "console_bg": "#1e1e28",
    "console_fg": "#d4d4d4",
    "cmd_fg":     "#4fc3f7",  # 用户命令
    "out_fg":     "#d4d4d4",  # 普通输出
}

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


def setup_ttk_style():
    """全局 ttk 样式（对 Treeview / Combobox / Labelframe / Scrollbar / Paned 等生效）。
    经典 tk 控件（tk.Button / tk.Text / tk.Entry）不受影响，需按 ui_theme.COLORS 单独配置。"""
    s = ttk.Style()
    try:
        s.theme_use("clam")  # clam 对自定义颜色/间距支持最好（vista 主题会忽略多数配色）
    except Exception:
        pass  # 主题缺失时退回默认，不影响功能
    s.configure(".", background=COLORS["panel"], font=F["ui"])
    s.configure("TButton", background=COLORS["accent"], foreground="white",
                font=F["ui"], padding=(8, 4), bordercolor=COLORS["accent"], focuscolor=COLORS["accent"])
    s.map("TButton", background=[("active", COLORS["accent_hi"]),
                                 ("pressed", COLORS["accent"]),
                                 ("disabled", COLORS["accent_lo"])],
          foreground=[("disabled", "#7a7a7a")])
    s.configure("TLabelframe", background=COLORS["panel"], bordercolor=COLORS["border"],
                relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=COLORS["panel"], foreground=COLORS["text"], font=F["ui_bold"])
    s.configure("TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=F["ui"])
    s.configure("TFrame", background=COLORS["panel"])
    s.configure("TPanedwindow", background=COLORS["bg"])
    s.configure("TScrollbar", background="#cfd8dc", troughcolor=COLORS["panel"], bordercolor=COLORS["panel"], arrowsize=14)
    s.configure("TCombobox", fieldbackground=COLORS["panel"], background=COLORS["panel"],
                arrowcolor=COLORS["text"], padding=4)
    s.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"],
                foreground=COLORS["text"], font=F["mono"], rowheight=24)
    s.configure("Treeview.Heading", font=F["ui_bold"], background="#e8eaed",
                foreground=COLORS["text"], relief="flat")
    s.map("Treeview.Heading", background=[("active", "#dde2e8")])
    s.map("Treeview", background=[("selected", COLORS["accent"])],
          foreground=[("selected", "white")])
    return s


def apply_console(text_widget):
    """把 Text 控件配成深色控制台并预定义好常用 tag（供 C2 命令行 / 日志复用）。"""
    text_widget.configure(
        bg=COLORS["console_bg"], fg=COLORS["console_fg"],
        insertbackground="white", selectbackground=COLORS["accent"],
        selectforeground="white", font=F["mono"], wrap="word",
    )
    text_widget.tag_configure("info", foreground=COLORS["out_fg"])
    text_widget.tag_configure("success", foreground=COLORS["success"])
    text_widget.tag_configure("warn", foreground=COLORS["warn"])
    text_widget.tag_configure("error", foreground=COLORS["error"])
    text_widget.tag_configure("cmd", foreground=COLORS["cmd_fg"])
    text_widget.tag_configure("title", foreground=COLORS["accent"], font=(F["ui"][0], F["ui"][1], "bold"))
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
