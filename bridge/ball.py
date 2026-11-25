"""破晓·工具箱 原生悬浮球（纯 Win32：WS_EX_LAYERED 窗口 + 32bit ARGB DIB + UpdateLayeredWindow）。

像素级透明圆形 logo 小球（web/public/logo.png），不依赖 WebView2 / WinForms / pythonnet：
  - 左键点按 = 浏览器打开工具箱；按住拖动 = 换位置（持久化 config/ball_pos.json）
  - 右键 = 弹出原生菜单（隐藏悬浮球 / 取消置顶·置顶 / 关闭小球）
  - 置顶 / 隐藏状态与设置页（工具箱设置 → 悬浮球）双向同步，变更广播 ball.state
  - 随 bridge 启动（start_ball + run_main_loop）；DAYBREAK_NO_BALL=1 / 非 Windows → 跳过

线程模型：窗口与消息泵在独立 daemon 线程；跨线程控制一律 PostMessage（线程安全）。
坐标一律物理像素（进程 PER_MONITOR_AWARE_V2）；st 的 x/y = 球左上角。
"""

from __future__ import annotations

import json
import logging
import time
import traceback
import os
import struct
import sys
import threading
import webbrowser
from pathlib import Path

log = logging.getLogger("bridge.ball")

# ---- 逻辑尺寸（96dpi 单位；运行时 × 屏幕缩放）----
_MW, _BALLDX = 128, 80            # 窗宽 / 球框 x 偏移（球居右）
_CLOSED_H = 48                     # 关菜单时窗高
_MENU_H = 84                       # 菜单面板高
_OPEN_H = _CLOSED_H + _MENU_H      # 开菜单时窗高
_PANEL_X0, _PANEL_W = 4, 120      # 菜单面板 x 范围
_ITEM_H, _ITEM_PAD, _SEPR_GAP = 20, 6, 4
_SEP = _ITEM_PAD + 2 * _ITEM_H + _SEPR_GAP          # 分隔线相对面板顶
_ITEM3 = _ITEM_PAD + 2 * _ITEM_H + _SEPR_GAP + _ITEM_H  # 第三项 y
# 面板配色（RGB 记法；_draw_panel_fill 按 BGRA 缓冲写成 B,G,R）
_PANEL_RGB = (0x1C, 0x26, 0x38)  # 屏幕 藏青 #1C2638
_SEP_RGB = (0x3A, 0x44, 0x52)    # 屏幕 分隔 #3A4452
_TEXT_BGR = 0xF5EDE8              # #E8EDF5 (BGR)
_BALL_D, _MARGIN = 44, 2          # 球直径 / 留白


def _ensure_dpi_aware() -> None:
    try:
        import ctypes as _ct

        try:
            _ct.windll.shcore.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
        except Exception:
            _ct.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_ensure_dpi_aware()

import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_kernel32 = ctypes.windll.kernel32

# ---- 64 位句柄安全：显式声明常用函数原型（HWND/HDC/HBITMAP = 指针宽）----
_H = ctypes.c_void_p
_user32.CreateWindowExW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    _H, _H, _H, _H]
_user32.CreateWindowExW.restype = _H
_user32.RegisterClassExW.argtypes = [_H]
_user32.RegisterClassExW.restype = ctypes.c_uint
_user32.LoadCursorW.argtypes = [_H, _H]
_user32.LoadCursorW.restype = _H
_user32.PostMessageW.argtypes = [_H, ctypes.c_uint, ctypes.c_long, ctypes.c_long]
_user32.SetWindowPos.argtypes = [_H, _H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_user32.ShowWindow.argtypes = [_H, ctypes.c_int]
_user32.DestroyWindow.argtypes = [_H]
_user32.ValidateRect.argtypes = [_H, _H]
_user32.SetCapture.argtypes = [_H]
_user32.ReleaseCapture.argtypes = []
_user32.UpdateLayeredWindow.argtypes = [_H, _H, _H, _H, _H, _H, ctypes.c_uint, _H, ctypes.c_uint]
_user32.UpdateLayeredWindow.restype = ctypes.c_int
_user32.DefWindowProcW.argtypes = [_H, ctypes.c_uint, ctypes.c_long, ctypes.c_long]
_gdi32.TextOutW.argtypes = [_H, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int]
_gdi32.CreateCompatibleDC.argtypes = [_H]
_gdi32.CreateCompatibleDC.restype = _H
_gdi32.CreateDIBSection.argtypes = [_H, _H, ctypes.c_uint, _H, _H]
_gdi32.CreateDIBSection.restype = _H
_gdi32.SelectObject.argtypes = [_H, _H]
_gdi32.SelectObject.restype = _H
_gdi32.DeleteDC.argtypes = [_H]
_gdi32.DeleteObject.argtypes = [_H]
_gdi32.SetBkMode.argtypes = [_H, ctypes.c_int]
_gdi32.SetTextColor.argtypes = [_H, ctypes.c_uint]
_gdi32.CreateFontW.argtypes = ([ctypes.c_int] * 12 + [ctypes.c_wchar_p])
_gdi32.CreateFontW.restype = _H

_user32.BeginPaint.argtypes = [_H, ctypes.c_void_p]
_user32.BeginPaint.restype = _H
_user32.EndPaint.argtypes = [_H, ctypes.c_void_p]
_user32.FillRect.argtypes = [_H, ctypes.c_void_p, _H]
_user32.InvalidateRect.argtypes = [_H, ctypes.c_void_p, ctypes.c_int]
_user32.SetLayeredWindowAttributes.argtypes = [_H, ctypes.c_uint, ctypes.c_ubyte, ctypes.c_uint]
_gdi32.CreateSolidBrush.argtypes = [ctypes.c_uint]
_gdi32.CreateSolidBrush.restype = _H
_gdi32.BitBlt.argtypes = [_H, ctypes.c_int, ctypes.c_int, _H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_gdi32.GetPixel.argtypes = [_H, ctypes.c_int, ctypes.c_int]
_gdi32.GetPixel.restype = ctypes.c_uint

# ---- use_last_error 实例（必须在 argtypes 声明之后复制原型）----
_u32_le = ctypes.WinDLL("user32", use_last_error=True)
_gdi_le = ctypes.WinDLL("gdi32", use_last_error=True)
_u32_le.CreateWindowExW.argtypes = _user32.CreateWindowExW.argtypes
_u32_le.CreateWindowExW.restype = _user32.CreateWindowExW.restype
_u32_le.RegisterClassExW.argtypes = _user32.RegisterClassExW.argtypes
_u32_le.UpdateLayeredWindow.argtypes = _user32.UpdateLayeredWindow.argtypes
_u32_le.UpdateLayeredWindow.restype = ctypes.c_int
_u32_le.SetLayeredWindowAttributes.argtypes = _user32.SetLayeredWindowAttributes.argtypes
_u32_le.SetLayeredWindowAttributes.restype = ctypes.c_int
_user32.PeekMessageW.argtypes = [ctypes.c_void_p, _H, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
_user32.PeekMessageW.restype = ctypes.c_int
_user32.SetTimer.argtypes = [_H, ctypes.c_uint, ctypes.c_uint, _H]
_user32.SetTimer.restype = ctypes.c_void_p
_user32.KillTimer.argtypes = [_H, ctypes.c_uint]
_user32.SetWindowLongPtrW.argtypes = [_H, ctypes.c_int, ctypes.c_void_p]
_user32.SetWindowLongPtrW.restype = ctypes.c_void_p
_gdi32.CreateEllipticRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_gdi32.CreateEllipticRgn.restype = ctypes.c_void_p
_gdi32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_gdi32.CreateRectRgn.restype = ctypes.c_void_p
_gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
_user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
_user32.SystemParametersInfoW.restype = ctypes.c_int
_gdi32.CombineRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
_gdi32.CombineRgn.restype = ctypes.c_int
_user32.SetWindowRgn.argtypes = [_H, ctypes.c_void_p, ctypes.c_int]
_user32.SetWindowRgn.restype = ctypes.c_int
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetCursorPos.restype = ctypes.c_int
_user32.GetDC.argtypes = [ctypes.c_int]
_user32.GetDC.restype = ctypes.c_void_p
_user32.ReleaseDC.argtypes = [ctypes.c_int, ctypes.c_void_p]
_user32.ReleaseDC.restype = ctypes.c_void_p
_gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_gdi32.GetPixel.restype = ctypes.c_ulong

_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_VK_LBUTTON, _VK_RBUTTON = 0x0001, 0x0002
_gdi_le.CreateDIBSection.argtypes = _gdi32.CreateDIBSection.argtypes
_gdi_le.CreateDIBSection.restype = _gdi32.CreateDIBSection.restype

# ---- 每显示器 DPI / 工作区（Win10 1607+；旧系统调用抛异常 → 返回 0 优雅降级）----
class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.UINT),
        ("szDevice", ctypes.c_wchar * 32),
    ]


_user32.GetDpiForWindow.argtypes = [_H]
_user32.GetDpiForWindow.restype = ctypes.c_uint
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, ctypes.c_uint]
_user32.MonitorFromPoint.restype = _H
_user32.GetMonitorInfoW.argtypes = [_H, ctypes.POINTER(_MONITORINFOEXW)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL

_WM_PAINT, _WM_DESTROY = 0x000F, 0x0002
_WM_MOUSEMOVE, _WM_LBUTTONDOWN, _WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
_WM_RBUTTONUP, _WM_CONTEXTMENU = 0x0205, 0x007B
_WM_APP = 0x8000
_WM_TOPMOST, _WM_HIDDEN, _WM_CLOSED_REQUEST, _WM_RECREATE = (_WM_APP + 1, _WM_APP + 2, _WM_APP + 3, _WM_APP + 4)
_SW_HIDE, _SW_SHOW = 0, 5
_HWND_TOPMOST, _HWND_NOTOPMOST = -1, -2
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOZORDER, _SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
_WS_EX_LAYERED, _WS_EX_TOOLWINDOW = 0x00080000, 0x00000080
_ULW_ALPHA = 0x0002
_TRANSPARENT_BK = 1

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_void_p, ctypes.c_ulong,
                             ctypes.c_void_p, ctypes.c_void_p)
_user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
_user32.DefWindowProcW.restype = ctypes.c_longlong


class _WNDCLASSEX(ctypes.Structure):
    """x64 布局：cbClsExtra/cbWndExtra 为 C int（32 位），其余指针 8 字节；共 80 字节。"""
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("style", ctypes.c_uint32),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", ctypes.c_void_p),
    ]


# ---------------------------------------------------------------------- 表面
# 逐像素透明：32bpp 顶部朝下 DIB + UpdateLayeredWindow(flag 0)；GDI 文本写 DIB 内存 DC
_PENDING_TEXTS: list[tuple[str, int, int]] = []  # (text, x, y) 物理像素


class _BMPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def _make_dib(width: int, height: int) -> tuple[ctypes.Array, int]:
    """32bit 顶部朝下 DIB → (共享像素缓冲 BGRA, HBITMAP)。"""
    bi = _BMPINFOHEADER()
    bi.biSize = ctypes.sizeof(_BMPINFOHEADER)
    bi.biWidth = width
    bi.biHeight = -height
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    bi.biSizeImage = width * height * 4
    ptr = ctypes.POINTER(ctypes.c_ubyte)()
    hbit = _gdi32.CreateDIBSection(0, ctypes.byref(bi), 0, ctypes.byref(ptr), 0)
    if not hbit:
        raise RuntimeError("CreateDIBSection failed")
    buf = (ctypes.c_ubyte * (width * height * 4)).from_address(ctypes.cast(ptr, ctypes.c_void_p).value)
    for i in range(len(buf)):  # 清零：未 blit 区域保持全透明
        buf[i] = 0
    return buf, hbit


_BALL_CACHE: dict = {}


def _ball_image(root: Path, d: int):
    """logo 圆球 RGBA（d×d，圆形 alpha）；无 logo 返回 None。带缓存（重建窗口高频调用）。"""
    key = (str(Path(root)), d)
    if key in _BALL_CACHE:
        return _BALL_CACHE[key]
    res = _ball_image_uncached(root, d)
    _BALL_CACHE[key] = res
    return res


def _ball_image_uncached(root: Path, d: int):
    for rel in ("web/public/logo.png", "web/dist/logo.png"):
        p = Path(root) / rel
        if not p.is_file():
            continue
        try:
            from PIL import Image

            im = Image.open(p).convert("RGBA").resize((d, d), Image.LANCZOS)
            px = im.load()
            c = (d - 1) / 2
            r = d / 2
            data = bytearray(d * d * 4)
            for yy in range(d):
                for xx in range(d):
                    dist = ((xx - c) ** 2 + (yy - c) ** 2) ** 0.5
                    edge = r - 0.5 - dist
                    mask = 255 if edge >= 0.5 else max(0, int(255 * (edge + 1)))
                    rr, gg, bb, aa = px[xx, yy]
                    o = (yy * d + xx) * 4
                    data[o:o + 4] = struct.pack("BBBB", rr, gg, bb, min(aa, mask))
            return (d, data)
        except Exception as e:
            log.warning("ball logo load failed (%s): %s", rel, e)
    return None  # 缓存由调用方 _ball_image 统一写入


def _gradient_pixels(d: int) -> bytes:
    """无 logo 兜底：蓝→橙渐变圆盘（RGBA）。"""
    data = bytearray(d * d * 4)
    c = (d - 1) / 2
    r = d / 2
    for yy in range(d):
        for xx in range(d):
            dist = ((xx - c) ** 2 + (yy - c) ** 2) ** 0.5
            if dist > r:
                continue
            t = (xx + yy) / (2 * (d - 1))
            cr = int(0x4C + (0xF5 - 0x4C) * t)
            cg = int(0x8D + (0xA6 - 0x8D) * t)
            cb = int(0xD9 + (0x23 - 0xD9) * t)
            o = (yy * d + xx) * 4
            data[o:o + 4] = struct.pack("BBBB", cr, cg, cb, 255)
    return bytes(data)


_GEN_BAD_STREAK = 0  # 连续「首刷失败/表面不可见」代数上限保护
_BALL_CLASS_PROC = None


def _get_ball_class_proc():
    """探针形态的类 WNDPROC（纯 DefWindowProc thunk，永久持有）。"""
    global _BALL_CLASS_PROC
    if _BALL_CLASS_PROC is None:

        @WNDPROC
        def _cp(h, m, w_, l):
            return _user32.DefWindowProcW(h, m, w_, l)

        _BALL_CLASS_PROC = _cp
    return _BALL_CLASS_PROC


def _blit_ball(buf, w: int, bx: int, by: int, ball) -> None:
    """球 → DIB 缓冲（BGRA，全不透明；圆形边缘由窗口区域裁剪实现）。"""
    d, data = ball
    for yy in range(d):
        row = yy * d * 4
        base = (by + yy) * w * 4
        for xx in range(d):
            i = base + (bx + xx) * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = (
                data[row + xx * 4 + 2], data[row + xx * 4 + 1], data[row + xx * 4], 255,
            )


def _draw_panel_fill(buf, w: int, h: int, panel_top: int, s: float) -> None:
    """菜单面板底色 + 分隔线（不透明，alpha 255）。"""
    px, pw = int(_PANEL_X0 * s), int(_PANEL_W * s)
    pr, pg, pb = _PANEL_RGB  # RGB → BGRA 缓冲按 B,G,R 写
    y2 = min(h, panel_top + int(_MENU_H * s))
    for yy in range(panel_top, y2):
        base = yy * w * 4
        for xx in range(px, px + pw):
            i = base + xx * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = pb, pg, pr, 255
    sep_y = panel_top + int(_SEP * s)
    if sep_y < h:
        sr, sg, sb = _SEP_RGB  # RGB → BGRA 缓冲按 B,G,R 写
        base = sep_y * w * 4
        for xx in range(px + int(8 * s), px + pw - int(8 * s)):
            i = base + xx * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = sb, sg, sr, 255


_SRCCOPY = 0x00CC0020


def _work_area() -> tuple[int, int, int, int]:
    """主屏工作区（排除任务栏，物理像素）；失败回退整屏。"""
    rc = wintypes.RECT()
    if _user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rc), 0):
        return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top
    return 0, 0, _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


def _window_dpi(hwnd) -> int:
    """窗口所在显示器的实际 DPI（PMAV2；Win10 1607+）。不可用返回 0。"""
    try:
        return int(_user32.GetDpiForWindow(hwnd))
    except Exception:
        return 0


def _work_area_at(x: int, y: int) -> tuple[int, int, int, int]:
    """光标所在显示器的工作区（物理像素）；失败回退主屏工作区。
    跨屏拖拽钳制用：旧实现只用主屏工作区，球拖不出主屏边界。"""
    try:
        hmon = _user32.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
        mi = _MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            l, t, r, b = mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom
            if r > l and b > t:
                return l, t, r - l, b - t
    except Exception:
        pass
    return _work_area()


def _menu_texts(st: dict, panel_top: int, s: float) -> list[tuple[str, int, int]]:
    labels = ["隐藏悬浮球", "取消置顶" if st.get("topmost", True) else "置顶在最前", "关闭小球"]
    yss = [_ITEM_PAD, _ITEM_PAD + _ITEM_H, _ITEM3]
    px = int(_PANEL_X0 * s)
    return [(lab, px + int(10 * s), panel_top + int((yr + 3) * s)) for lab, yr in zip(labels, yss)]


# ---------------------------------------------------------------------- 状态
_state: dict = {
    "running": False,
    "hwnd": 0,
    "x": None,
    "y": None,
    "port": 8765,
    "root": Path.cwd(),
    "pos_file": Path("config/ball_pos.json"),
    "loop_alive": False,
    "topmost": True,
    "hidden": False,
    "scale": 1.0,
}

_pending = threading.Event()
_stop = threading.Event()
_state_hook = None
_ball_thread: threading.Thread | None = None


def set_state_hook(fn) -> None:
    global _state_hook
    _state_hook = fn


def _notify() -> None:
    if _state_hook is not None:
        try:
            _state_hook(get_state())
        except Exception:
            pass


def get_state() -> dict:
    st = _state
    top, hid = bool(st.get("topmost", True)), bool(st.get("hidden", False))
    if not st.get("running") and st["pos_file"] is not None:
        try:
            p = json.loads(Path(st["pos_file"]).read_text(encoding="utf-8"))
            top = bool(p.get("topmost", True))
            hid = bool(p.get("hidden", False))
        except Exception:
            pass
    return {
        "available": _available(),
        "running": bool(st.get("running")),
        "topmost": top,
        "hidden": hid,
    }


def _save_full(st: dict) -> None:
    try:
        p = Path(st["pos_file"])
        data = {}
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
        data.update(x=st["x"], y=st["y"],
                    topmost=bool(st.get("topmost", True)), hidden=bool(st.get("hidden", False)))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        log.warning("ball persist failed: %s", e)


def _persist_field(st: dict, key: str, val: bool) -> None:
    try:
        p = Path(st["pos_file"])
        data = {}
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
        data[key] = bool(val)
        if isinstance(st.get("x"), int) and isinstance(st.get("y"), int):
            data["x"], data["y"] = st["x"], st["y"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        log.warning("ball persist %s failed: %s", key, e)


def _available() -> bool:
    if os.environ.get("DAYBREAK_NO_BALL") == "1":
        return False
    return sys.platform == "win32"


def set_topmost(on: bool) -> dict:
    st = _state
    st["topmost"] = bool(on)
    _persist_field(st, "topmost", on)
    if st.get("hwnd"):
        _user32.PostMessageW(st["hwnd"], _WM_TOPMOST, 1 if on else 0, 0)
    _notify()
    return get_state()


def set_hidden(hidden: bool) -> dict:
    st = _state
    st["hidden"] = bool(hidden)
    _persist_field(st, "hidden", hidden)
    if st.get("hwnd"):
        _user32.PostMessageW(st["hwnd"], _WM_HIDDEN, 1 if hidden else 0, 0)
    _notify()
    return get_state()


# ---------------------------------------------------------------------- 窗口
class _NativeBall:
    def __init__(self, st: dict) -> None:
        self.st = st
        self.hwnd = 0
        self.font = 0
        self.ball = None
        self.dragging = False
        self.moved = False
        self.drag_sx = self.drag_sy = 0
        self.drag_ox = self.drag_oy = 0
        self.menu_open = False
        self.menu_up = False
        self._wndproc_ref = None
        self._hbits: list[int] = []
        self._pump_active = False
        self._cb_holds: list = []  # 持有所有 WNDPROC 实例（类 thunk 永久引用）
        self._rgn = 0
        self._first_ulw_ok = True
        self._lb_prev = False
        self._rb_prev = False
        self._lb_seen_idle = False
        self._rb_seen_idle = False
        self._hdc = 0

    # ---- 几何（物理像素）：球左上角恒在 (st.x, st.y)
    def _origin(self) -> tuple[int, int]:
        st = self.st
        s = st["scale"]
        ox = int(st["x"] - _BALLDX * s)
        oy = int(st["y"]) - (int((_OPEN_H - _CLOSED_H) * s) if self.menu_open and self.menu_up else 0)
        return ox, oy

    def _ball_box(self) -> tuple[int, int, float]:
        """球圆心与半径（窗内物理像素）。"""
        st = self.st
        s = st["scale"]
        bx = int(_BALLDX * s) + int(_MARGIN * s)
        by = int((_MENU_H + _MARGIN) * s) if (self.menu_open and self.menu_up) else int(_MARGIN * s)
        return bx + int(_BALL_D * s) / 2, by + int(_BALL_D * s) / 2, _BALL_D * s / 2

    def _in_ball(self, x: int, y: int) -> bool:
        cx, cy, r = self._ball_box()
        dx, dy = x - cx, y - cy
        return dx * dx + dy * dy <= r * r

    def _menu_item(self, x: int, y: int):
        st = self.st
        s = st["scale"]
        px, pw = int(_PANEL_X0 * s), int(_PANEL_W * s)
        panel_top = 0 if self.menu_up else int(_CLOSED_H * s)
        ry = (y - panel_top) / s
        if not (px <= x < px + pw):
            return None
        acts = [_ITEM_PAD, _ITEM_PAD + _ITEM_H, _ITEM3]
        for act, yrel in zip(("hide", "top", "close"), acts):
            if yrel <= ry < yrel + _ITEM_H:
                return act
        return "panel"

    def _keep_hbit(self, hbit: int) -> None:
        """DIB 保留最近 2 个，其余释放（UpdateLayeredWindow 已拷贝表面）。"""
        self._hbits.append(hbit)
        while len(self._hbits) > 2:
            old = self._hbits.pop(0)
            _gdi32.DeleteObject(old)

    def _assemble_surface(self, buf, w: int, h: int) -> None:
        """DIB 内容：不透明底色 + 球 logo + 面板（菜单展开时）。"""
        st = self.st
        s = st["scale"]
        nb, ng, nr = 0x38, 0x26, 0x1C  # BGR = 深藏青
        for i in range(w * h):
            buf[i * 4:i * 4 + 4] = bytes([nb, ng, nr, 255])
        bx = int(_BALLDX * s) + int(_MARGIN * s)
        by = int((_MENU_H + _MARGIN) * s) if (self.menu_open and self.menu_up) else int(_MARGIN * s)
        _blit_ball(buf, w, bx, by, self.ball or (int(_BALL_D * s), _gradient_pixels(int(_BALL_D * s))))
        _PENDING_TEXTS.clear()
        if self.menu_open:
            panel_top = 0 if self.menu_up else int(_CLOSED_H * s)
            _draw_panel_fill(buf, w, h, panel_top, s)
            _PENDING_TEXTS.extend(_menu_texts(st, panel_top, s))
        self._set_region()

    def _draw_texts(self, hdc) -> None:
        if not _PENDING_TEXTS:
            return
        _gdi32.SetBkMode(hdc, _TRANSPARENT_BK)
        _gdi32.SetTextColor(hdc, _TEXT_BGR)
        if self.font:
            _gdi32.SelectObject(hdc, self.font)
        for text, tx, ty in _PENDING_TEXTS:
            ws = ctypes.create_unicode_buffer(text)
            _gdi32.TextOutW(hdc, tx, ty, ws, len(text))
        _PENDING_TEXTS.clear()

    def _set_region(self) -> None:
        """窗口形状：收拢=球圆，展开=圆角面板条带 ∪ 球圆（其余不绘制=透明）。"""
        st = self.st
        s = st["scale"]
        W = int(_MW * s)
        H = int((_OPEN_H if self.menu_open else _CLOSED_H) * s)
        if self.menu_open:
            px, pw = int(_PANEL_X0 * s), int(_PANEL_W * s)
            panel_top = 0 if self.menu_up else int(_CLOSED_H * s)
            strip = int(_MENU_H * s)
            rad = int(8 * s)
            rgn = _gdi32.CreateRoundRectRgn(px, panel_top, px + pw, panel_top + strip, rad * 2, rad * 2)
            bcx, bcy, r = self._ball_box()
            cxb, cyb, ir = int(bcx), int(bcy), int(r)
            ell = _gdi32.CreateEllipticRgn(cxb - ir, cyb - ir, cxb + ir, cyb + ir)
            _gdi32.CombineRgn(rgn, rgn, ell, 2)  # RGN_OR
            _gdi32.DeleteObject(ell)
        else:
            d = int(_BALL_D * s)
            bx = int(_BALLDX * s) + int(_MARGIN * s)
            by = int(_MARGIN * s)
            cx = bx + d // 2
            cy = by + d // 2
            r = d // 2
            rgn = _gdi32.CreateEllipticRgn(cx - r, cy - r, cx + r, cy + r)
        old = self._rgn
        _user32.SetWindowRgn(self.hwnd, rgn, 1)
        if old:
            _gdi32.DeleteObject(old)
        self._rgn = rgn

    def _check_visible(self) -> bool:
        """自检表面是否真的合成可见：球内 3 点 vs 全布局下都在填充外的角点(3,3)。"""
        st = self.st
        try:
            hdc_s = _user32.GetDC(0)
            hdc_m = _gdi32.CreateCompatibleDC(hdc_s)
            hbm = _gdi32.CreateCompatibleBitmap(hdc_s, 4, 4)
            sel = _gdi32.SelectObject(hdc_m, hbm)

            def px(x: int, y: int):
                _gdi32.BitBlt(hdc_m, 0, 0, 4, 4, hdc_s, x, y, _SRCCOPY)
                return _gdi32.GetPixel(hdc_m, 0, 0) & 0xFFFFFF

            ox, oy = self._origin()
            corner = px(ox + 3, oy + 3)  # 收拢/展开、上开/下开 均在任何填充之外
            bcx, bcy, r = self._ball_box()
            a = px(ox + bcx, oy + bcy)
            b = px(ox + bcx - int(r * 0.5), oy + bcy + int(r * 0.5))
            c = px(ox + bcx + int(r * 0.5), oy + bcy + int(r * 0.5))
            _user32.ReleaseDC(0, hdc_s)
            _gdi32.SelectObject(hdc_m, sel)
            _gdi32.DeleteObject(hbm)
            _gdi32.DeleteDC(hdc_m)
            return not (a == corner and b == corner and c == corner)
        except Exception:
            return True  # 自检失败不误杀


    def _ulw(self, hdc, x: int, y: int, w: int, h: int) -> bool:
        """UpdateLayeredWindow：pywin32（win32gui）优先；失败回退 ctypes。"""
        try:
            import win32gui
            win32gui.UpdateLayeredWindow(self.hwnd, None, (x, y), (w, h),
                                         int(hdc), (0, 0), 0, None, 0)
            return True
        except Exception as e:
            log.warning("win32gui.UpdateLayeredWindow failed: %s", e)
        ret = _u32_le.UpdateLayeredWindow(self.hwnd, 0, ctypes.byref(wintypes.POINT(x, y)),
                                          ctypes.byref(wintypes.SIZE(w, h)),
                                          hdc, ctypes.byref(wintypes.POINT(0, 0)), 0, None, 0)
        return bool(ret)

    def _release_gdi(self) -> None:
        for h in list(self._hbits):
            _gdi32.DeleteObject(h)
        self._hbits = []
        if self.font:
            _gdi32.DeleteObject(self.font)
            self.font = 0
        if self._rgn:
            _gdi32.DeleteObject(self._rgn)
            self._rgn = 0

    def _new_window(self) -> None:
        """窗口创建 + 首次表面提交（本机 DWM 仅首个 ULW 可提交表面）。"""
        st = self.st
        global _GEN_BAD_STREAK
        s = st["scale"]
        if st.get("x") is None:
            wl, wt, ww, wh = _work_area()
            st["x"] = wl + max(0, ww - int(_CLOSED_H * s) - int(24 * s))
            st["y"] = wt + max(0, wh - int(_CLOSED_H * s) - int(80 * s))
        self.ball = _ball_image(st["root"], int(_BALL_D * s))
        self.font = _gdi32.CreateFontW(int(-12 * s), 0, 0, 0, 400, 0, 0, 0,
                                       0x0049, 0, 0, 49, "Microsoft YaHei")

        # 类注册：纯 DefWindowProc thunk（Python 处理器在首刷后 SetWindowLongPtrW 换入）
        wc = _WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEX)
        wc.style = 0
        wc.lpfnWndProc = _get_ball_class_proc()
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        wc.hCursor = _user32.LoadCursorW(0, 32512)
        wc.lpszClassName = "DaybreakBall"
        atom = _u32_le.RegisterClassExW(ctypes.byref(wc))
        if atom == 0:
            log.warning("ball RegisterClassExW err=%s (复用已注册类)", ctypes.get_last_error())

        ex = _WS_EX_LAYERED | _WS_EX_TOOLWINDOW
        W = int(_MW * s)
        H = int((_OPEN_H if self.menu_open else _CLOSED_H) * s)
        ox, oy = self._origin()
        cls = ctypes.create_unicode_buffer("DaybreakBall")
        title = ctypes.create_unicode_buffer("破晓·工具箱")
        self.hwnd = _u32_le.CreateWindowExW(
            ex, cls, title, 0x16000000, ox, oy, W, H, 0, 0,
            ctypes.c_void_p(wc.hInstance), None)
        if not self.hwnd:
            log.warning("ball CreateWindowExW failed err=%s", ctypes.get_last_error())
            _user32.PostQuitMessage(0)
            return
        st["hwnd"] = self.hwnd
        st["running"] = True

        # 首次表面提交：内容组装 + ULW 在同一函数栈内完成
        buf, hbit = _make_dib(W, H)
        self._assemble_surface(buf, W, H)
        hdc = _gdi32.CreateCompatibleDC(0)
        old_sel = _gdi32.SelectObject(hdc, hbit)
        self._draw_texts(hdc)  # 文字必须先画入 hbit，再随 ULW 提交
        pt, sz, z = wintypes.POINT(ox, oy), wintypes.SIZE(W, H), wintypes.POINT(0, 0)
        ret = self._ulw(hdc, ox, oy, W, H)
        if not ret and not self._pump_active:
            # 泵未运行时同步重试一次（保持线程消息活跃）
            mmsg = wintypes.MSG()
            time.sleep(0.1)
            while _user32.PeekMessageW(ctypes.byref(mmsg), 0, 0, 0, 1):
                _user32.TranslateMessage(ctypes.byref(mmsg))
                _user32.DispatchMessageW(ctypes.byref(mmsg))
            ret = self._ulw(hdc, ox, oy, W, H)
        _gdi32.SelectObject(hdc, old_sel)
        _gdi32.DeleteDC(hdc)
        self._keep_hbit(hbit)
        if not ret:
            log.warning("ball first ULW failed hwnd=%s err=%s (立即重建)", self.hwnd, ctypes.get_last_error())
            self._first_ulw_ok = False
        else:
            self._first_ulw_ok = True
            _user32.SetTimer(self.hwnd, 0xB3, 2000, 0)  # 延迟自检表面可见性

        # 首刷后换入 Python 处理器（表面已注册，swap 不影响已提交内容）
        _wrap = WNDPROC(self._wndproc)
        self._cb_holds.append(_wrap)
        _user32.SetWindowLongPtrW(self.hwnd, -4, ctypes.cast(_wrap, ctypes.c_void_p))
        self._wndproc_ref = _wrap

        ins = _HWND_TOPMOST if st.get("topmost") else _HWND_NOTOPMOST
        _user32.SetWindowPos(self.hwnd, ins, 0, 0, 0, 0,
                             _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
        if not st.get("hidden"):
            _user32.ShowWindow(self.hwnd, _SW_SHOW)
        _user32.SetTimer(self.hwnd, 0xB2, 50, 0)
        log.info("ball window created hwnd=%s menu_open=%s", self.hwnd, self.menu_open)
        if not self._first_ulw_ok:
            _GEN_BAD_STREAK += 1
            log.warning("ball invisible window (gen fail %s/10); recreating", _GEN_BAD_STREAK)
            if _GEN_BAD_STREAK >= 10:
                log.warning("ball gave up after 10 bad generations; stopping ball")
                stop_ball()
                return
            _user32.DestroyWindow(self.hwnd)

        # DPI 校正：窗口所在显示器的实际 DPI 可能与创建时用的 scale 不符（scale 在线程
        # 启动时用 GetDpiForSystem 计算，取到的是系统 DPI，而非球实际所在显示器的 DPI；
        # 多屏 125%/150% 混布时尺寸会系统性偏小）。尺寸不符的窗口在系统后续 DPI 相关
        # 自动 resize 时会把旧提交表面非比例拉伸 → 球变椭圆。不符立即重建（新代际 =
        # 新尺寸 + 新表面提交）。
        win_dpi = _window_dpi(self.hwnd)
        if win_dpi and abs(win_dpi / 96.0 - s) > 0.01:
            log.warning("ball dpi mismatch: scale %.2f but window dpi %d; recreating", s, win_dpi)
            st["scale"] = win_dpi / 96.0
            _user32.DestroyWindow(self.hwnd)  # WM_DESTROY → PostQuitMessage → run() 重建


    def _open_menu(self) -> None:
        import time as _t
        now = _t.time()
        if now - getattr(self, "_menu_act_t", 0) < 0.5:
            return
        self._menu_act_t = now
        st = self.st
        sh = _user32.GetSystemMetrics(1)
        self.menu_up = st["y"] + int(_OPEN_H * st["scale"]) > sh
        self.menu_open = True
        self._menu_recreate()

    def _close_menu(self) -> None:
        if not self.menu_open:
            return
        import time as _t
        now = _t.time()
        if now - getattr(self, "_menu_act_t", 0) < 0.5:
            return
        self._menu_act_t = now
        self.menu_open = False
        self._menu_recreate()

    def _menu_recreate(self) -> None:
        """内容/位置变化 = 重建窗口（新窗口获得一次性表面提交）。"""
        import time as _t
        self._last_recreate_t = _t.time()
        if self.dragging:
            _user32.ReleaseCapture()
        _user32.DestroyWindow(self.hwnd)  # WM_DESTROY → PostQuitMessage → run() 重建

    def _act(self, act) -> None:
        st = self.st
        if act == "hide":
            set_hidden(True)
        elif act == "top":
            set_topmost(not st.get("topmost", False))
        elif act == "close":
            stop_ball()

    def _poll_input(self) -> None:
        """50ms 轮询鼠标：拖拽 / 右键开关菜单 / 单击开浏览器。"""
        st = self.st
        # 尺寸守护（兜底）：任何外部 resize（系统 DPI 自动 resize、DWM 行为等）都会让
        # 已提交表面 与 窗口尺寸 脱节 → DWM 拉伸 → 球变椭圆。检测即重建（限频 0.5s）。
        rc_g = wintypes.RECT()
        if _user32.GetWindowRect(self.hwnd, ctypes.byref(rc_g)):
            s2 = st["scale"]
            dpi2 = _window_dpi(self.hwnd)
            if dpi2:
                s2 = dpi2 / 96.0
                st["scale"] = s2
            ew = int(_MW * s2)
            eh = int((_OPEN_H if self.menu_open else _CLOSED_H) * s2)
            if (rc_g.right - rc_g.left, rc_g.bottom - rc_g.top) != (ew, eh):
                now_g = time.time()
                if now_g - getattr(self, "_guard_recreate_t", 0) >= 0.5:
                    self._guard_recreate_t = now_g
                    log.warning("ball size drift %dx%d (expect %dx%d @scale %.2f); recreating",
                                rc_g.right - rc_g.left, rc_g.bottom - rc_g.top, ew, eh, s2)
                    self._menu_recreate()
                    return
        pos = wintypes.POINT()
        if not _user32.GetCursorPos(ctypes.byref(pos)):
            return
        wr = wintypes.RECT()
        _user32.GetWindowRect(self.hwnd, ctypes.byref(wr))
        cx, cy = pos.x - wr.left, pos.y - wr.top
        lb = bool(_user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000)
        rb = bool(_user32.GetAsyncKeyState(_VK_RBUTTON) & 0x8000)
        # 边沿门控：只响应从“松开→按下/松开”的真实变化（防本机按键状态粘滞）
        if not lb:
            self._lb_seen_idle = True
        if not rb:
            self._rb_seen_idle = True
        in_ball = self._in_ball(cx, cy)
        import time as _t
        now = _t.time()
        # 右键：边沿触发（需先观察到松开，400ms 去抖）
        in_win = 0 <= cx < (wr.right - wr.left) and 0 <= cy < (wr.bottom - wr.top)
        if rb and self._rb_seen_idle and now - getattr(self, "_poll_toggle_t", 0) > 0.4:
            self._poll_toggle_t = now
            if in_ball:
                if not self.menu_open:
                    self._open_menu()
                else:
                    self._close_menu()
            elif in_win and self.menu_open:
                self._close_menu()  # 点窗口其他区域收起
            return
        self._rb_prev = rb
        # 左键拖拽（拖拽中跟随光标，无需保持在球内；需先观察到松开）
        if lb:
            if not self._lb_seen_idle and not self.dragging:
                self._lb_prev = lb
                return
            if self.dragging:
                dx, dy = pos.x - self.drag_sx, pos.y - self.drag_sy
                if abs(dx) + abs(dy) > 4:
                    self.moved = True
                    nx, ny = self.drag_ox + dx, self.drag_oy + dy
                    wl, wt, ww, wh = _work_area_at(pos.x, pos.y)  # 光标所在显示器工作区（跨屏拖拽）
                    s2 = st["scale"]
                    nx = min(max(wl, nx), wl + ww - int(_BALLDX * s2))
                    ny = min(max(wt, ny), wt + wh - int(_CLOSED_H * s2))
                    last = getattr(self, "_last_recreate_t", 0.0)
                    if (nx, ny) != (self.drag_ox, self.drag_oy) and now - last >= (0.0 if last == 0 else 0.05):
                        self.drag_ox, self.drag_oy = nx, ny
                        st["x"] = nx + int(_BALLDX * s2)
                        st["y"] = ny
                        self._last_recreate_t = now
                        self._menu_recreate()  # 本机 DWM 无法移动已提交表面：重建到新位置
            elif in_ball:
                self.dragging, self.moved = True, False
                self.drag_sx, self.drag_sy = pos.x, pos.y
                self.drag_ox, self.drag_oy = self._origin()
        elif self.dragging:
            # 松开边沿（1→0）
            if self._lb_prev:
                self.dragging = False
                if not self.moved:
                    # 单击（未移动）：打开工具箱
                    try:
                        webbrowser.open(f"http://127.0.0.1:{st.get('port', 8765)}/")
                    except Exception:
                        pass
                else:
                    _save_full(st)
            # 拖拽中 lb 粘滞：不强制结束，继续跟随（无害）
        elif self._lb_prev:
            # 非球区松开：点面板项执行动作 / 点空白收起菜单
            if self.menu_open and in_win and not in_ball:
                item = self._menu_item(cx, cy)
                if item in ("hide", "top"):
                    self._act(item)
                    self._close_menu()
                elif item == "close":
                    _save_full(st)
                    stop_ball()
                else:
                    self._close_menu()
        self._lb_prev = lb

    def _wndproc(self, hwnd, msg, w, l):
        global _GEN_BAD_STREAK
        st = self.st
        if msg == _WM_PAINT:
            ps = _PAINTSTRUCT()
            _user32.BeginPaint(hwnd, ctypes.byref(ps))
            _user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        if msg == 0x0113:  # WM_TIMER
            if w == 0xB2:  # 输入轮询（本机鼠标消息投递不可靠）
                self._poll_input()
            elif w == 0xB3:  # 表面可见性自检（布局感知）
                _user32.KillTimer(hwnd, 0xB3)
                if not self._check_visible():
                    _GEN_BAD_STREAK += 1
                    log.warning("ball surface invisible after first ULW (gen fail %s/10); recreating", _GEN_BAD_STREAK)
                    if _GEN_BAD_STREAK >= 10:
                        log.warning("ball gave up after 10 invisible generations; stopping ball")
                        stop_ball()
                        return
                    _user32.DestroyWindow(hwnd)
                else:
                    _GEN_BAD_STREAK = 0
            return 0
        if msg == 0x0014:  # WM_ERASEBKGND：抑制擦除
            return 1
        if msg == _WM_CONTEXTMENU:
            # 顶级窗口 WM_CONTEXTMENU：lParam = 屏幕坐标 MAKELONG(x, y)。
            # 本机 DWM 下 ScreenToClient 不可靠，改用 GetWindowRect 自行换算。
            sx, sy = l & 0xFFFF, (l >> 16) & 0xFFFF
            wr = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(wr))
            cx2, cy2 = sx - wr.left, sy - wr.top
            if self._in_ball(cx2, cy2):
                self._open_menu() if not self.menu_open else self._close_menu()
            elif self.menu_open:
                self._close_menu()
            return 0
        if msg in (0x0204, 0x0205):  # WM_RBUTTONDOWN / WM_RBUTTONUP
            x, y = (l or 0) & 0xFFFF, ((l or 0) >> 16) & 0xFFFF
            if self._in_ball(x, y):
                if not self.menu_open:
                    self._open_menu()
                else:
                    self._close_menu()
            elif self.menu_open:
                self._close_menu()
            return 0
        if msg == _WM_TOPMOST:
            st["topmost"] = bool(w)
            _persist_field(st, "topmost", st["topmost"])
            self._close_menu() if self.menu_open else None
            _user32.SetWindowPos(hwnd, _HWND_TOPMOST if st["topmost"] else _HWND_NOTOPMOST,
                                 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
            _notify()
            return 0
        if msg == _WM_HIDDEN:
            st["hidden"] = bool(w)
            _persist_field(st, "hidden", st["hidden"])
            if st["hidden"]:
                _user32.ShowWindow(hwnd, _SW_HIDE)
            else:
                self._close_menu()
                _user32.ShowWindow(hwnd, _SW_SHOW)
            _notify()
            return 0
        if msg == _WM_CLOSED_REQUEST:
            _save_full(st)
            stop_ball()
            _user32.DestroyWindow(hwnd)
            return 0
        if msg == _WM_RECREATE:
            _GEN_BAD_STREAK = 0
            _user32.DestroyWindow(hwnd)  # run() 循环重建（新窗口新一次表面提交）
            return 0
        if msg == 0x02E0:  # WM_DPICHANGED：跨显示器 / 系统缩放变更
            # wParam 低 16 位 = 新 DPI。必须自行处理：默认 DefWindowProc 会按新 DPI 自动
            # resize 窗口，而已提交的 32 位表面会被 DWM 拉伸到新尺寸 → 球变椭圆。
            # 处理 = 按新 DPI 重建窗口（新尺寸 + 新表面提交）。
            new_dpi = w & 0xFFFF
            if new_dpi:
                st["scale"] = new_dpi / 96.0
                self._menu_recreate()
            return 0
        if msg == _WM_DESTROY:
            self._release_gdi()
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, w, l)

    def _pump(self) -> None:

        self._pump_active = True
        m = wintypes.MSG()
        try:
            while True:
                r = _user32.GetMessageW(ctypes.byref(m), 0, 0, 0)
                if r == 0:
                    break
                if r == -1:
                    log.warning("ball GetMessage error: %s", ctypes.get_last_error())
                    break
                _user32.TranslateMessage(ctypes.byref(m))
                _user32.DispatchMessageW(ctypes.byref(m))
        finally:
            self._pump_active = False

    def run(self) -> None:
        st = self.st
        started = False
        while not _stop.is_set():
            if not started:
                _pending.wait()
                if _stop.is_set():
                    break
                _pending.clear()
                started = True
            try:
                self._new_window()
                self._pump()
                if not _stop.is_set():
                    self._gen = getattr(self, "_gen", 1) + 1
                    log.info("ball window recycled (gen %s)", self._gen)
            except Exception:
                log.warning("ball window loop ended:\n%s", traceback.format_exc())
            finally:
                if _stop.is_set():
                    st["running"] = False
                    st["hwnd"] = 0
                    _notify()


def _ball_thread_main() -> None:
    st = _state
    st["scale"] = (_user32.GetDpiForSystem() / 96.0) if _user32.GetDpiForSystem() else 1.0
    st["x"], st["y"] = None, None
    try:
        p = json.loads(Path(st["pos_file"]).read_text(encoding="utf-8"))
        if isinstance(p.get("x"), int) and isinstance(p.get("y"), int):
            st["x"], st["y"] = p["x"], p["y"]
        st["topmost"] = bool(p.get("topmost", True))
        st["hidden"] = bool(p.get("hidden", False))
    except Exception:
        st["topmost"], st["hidden"] = True, False
    _NativeBall(st).run()


def start_ball(port: int, root: Path) -> bool:
    """登记参数并启动小球线程（非阻塞；主线程由 run_main_loop 保活）。"""
    global _ball_thread
    st = _state
    if not _available():
        return False
    st.update(port=port, root=Path(root))
    st["pos_file"] = Path(root) / "config" / "ball_pos.json"
    if _ball_thread is None or not _ball_thread.is_alive():
        _ball_thread = threading.Thread(target=_ball_thread_main, name="daybreak-ball", daemon=True)
        _ball_thread.start()
    _pending.set()
    return True


def run_main_loop() -> None:
    """主线程保活（小球实际跑在独立 daemon 线程）。"""
    _state["loop_alive"] = True
    while not _stop.is_set():
        _stop.wait(0.5)
    _state["loop_alive"] = False


def stop_ball() -> None:
    _stop.set()
    _pending.set()
    hwnd = _state.get("hwnd")
    if hwnd:
        _user32.PostMessageW(hwnd, _WM_CLOSED_REQUEST, 0, 0)


def show_ball() -> None:
    """托盘「显示悬浮球」：隐藏态先解除；已关则重建。"""
    st = _state
    if st.get("hidden"):
        set_hidden(False)
        return
    if st.get("running") and st.get("hwnd"):
        _user32.PostMessageW(st["hwnd"], _WM_RECREATE, 0, 0)  # 重建窗口（新表面提交）
        return
    if st.get("loop_alive"):
        _pending.set()


def tray_items() -> list[tuple[str, object]]:
    return [("显示悬浮球", show_ball)] if _available() else []
