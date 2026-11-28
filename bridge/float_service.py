"""原生浮动子窗口服务（v2.3.2，仅 Windows 窗口模式）。

为什么不用 HTML 浮层：旧实现（web/src/features/floating/FloatingWindow.tsx）是主窗口内的一层
绝对定位 div，坐标被 `clampFloatPos` 钳死在主窗口视口里，永远拖不出主窗口；而且主窗口内容区
里的原生 WebView2 浏览器是「主窗体上的子窗体」，z 序天然高于 HTML 浮层 → 浏览网页时盖住浮窗。

本模块用 pywebview 运行时 `webview.create_window` 创建**真正的顶层 OS 窗口**：
- 独立窗口天然可以拖出主窗口；窗口层级与普通顶层窗口一致（点击主窗口会让主窗前置），
  浮窗在前时也不会被主窗口内的 WebView2 浏览器子窗体盖住；
- `frameless=True` + 前端自绘标题栏（拖动走 `float.drag_begin` + `float.move` 流式跟随，
  双击走 `float.maximize` 在「原尺寸 / 当前显示器工作区」之间切换）；
- 窗口加载同一套前端资源（`?float=1` → FloatShell），正文复用 FloatingMenuCanvas；
- 关闭时经 `window.events.closed` 回调 → 广播 `float.closed`，主窗口按钮「已脱离」态同步收回。

任何不可用情形（非窗口形态 / 非 Windows / 未建窗 / pywebview 异常）都抛 FloatError，
由前端回退到旧 HTML 浮层（dev / 服务形态）。
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable, Optional
from urllib.parse import quote, urlencode


class FloatError(Exception):
    """浮动窗口不可用/操作失败；main.py 会转成 BridgeError 返回前端。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_LOCK = threading.RLock()
_FLOATS: "dict[str, dict[str, Any]]" = {}
_EMIT: Optional[Callable[[str, dict], None]] = None
_PORT_GETTER: Optional[Callable[[], Optional[int]]] = None
_WINDOWED_GETTER: Optional[Callable[[], bool]] = None

# 尺寸约束（与前端 detachStore 的 FLOAT_MIN/FLOAT_MAX 同源；不强制超过屏幕）
_FLOAT_MIN_W, _FLOAT_MIN_H = 420, 300
_FLOAT_MAX_W, _FLOAT_MAX_H = 1400, 900
_EDGE_KEEP = 48  # 松手位置换算后，至少留 48px 在可放置区域内


def configure(port_getter: Callable[[], Optional[int]],
              emit: Callable[[str, dict], None],
              windowed_getter: Callable[[], bool]) -> None:
    """由 main._register_builtin_commands 注入依赖（避免 float_service ↔ main 循环导入）。"""
    global _EMIT, _PORT_GETTER, _WINDOWED_GETTER
    _EMIT = emit
    _PORT_GETTER = port_getter
    _WINDOWED_GETTER = windowed_getter


def available() -> bool:
    """当前进程是否具备创建原生浮动窗口的条件。"""
    return sys.platform == "win32" and bool(_WINDOWED_GETTER and _WINDOWED_GETTER())


def _emit(event: str, payload: dict) -> None:
    if _EMIT is None:
        return
    try:
        _EMIT(event, payload)
    except Exception as e:  # 广播失败绝不影响窗口生命周期
        print(f"[bridge] 浮动窗口事件广播失败（{event}）：{e}")


def _main():
    from . import main as _m

    return _m


def _require_windowed():
    if not available():
        raise FloatError("FLOAT_UNSUPPORTED", "当前环境不支持原生浮动窗口")
    form = _main()._active_window()
    if form is None:
        raise FloatError("FLOAT_NO_WINDOW", "主窗口尚未就绪，无法创建浮动窗口")
    return form


def _clamp_pos(sx: float, sy: float, w: int, h: int) -> "tuple[int, int]":
    """把目标左上角收进虚拟桌面范围（至少 _EDGE_KEEP 可见），跨屏也允许。"""
    m = _main()
    try:
        mons = m._monitor_info_safe()
        if mons:
            left = top = 10 ** 9
            right = bottom = -10 ** 9
            for mon in mons:
                l, t, mw, mh = mon["mon"]
                lx, ly, lw, lh = m._physical_to_logical(l, t, mw, mh, mons)
                left, top = min(left, lx), min(top, ly)
                right, bottom = max(right, lx + lw), max(bottom, ly + lh)
            min_x = left - w + _EDGE_KEEP
            max_x = right - _EDGE_KEEP
            min_y = top - h + _EDGE_KEEP
            max_y = bottom - _EDGE_KEEP
            return int(min(max(sx, min_x), max_x)), int(min(max(sy, min_y), max_y))
    except Exception as e:
        print(f"[bridge] 浮动窗口位置钳制失败（忽略）：{e}")
    return int(sx), int(sy)


def _float_tab_id(key: str) -> str:
    """浮动子窗口内嵌浏览器宿主的 id（与主窗口标签命名空间隔离）。"""
    return f"float::{key}"


def _dispose_browser(key: str) -> None:
    """浮动窗口关闭/重建时释放其中的原生浏览器宿主（best-effort）。"""
    try:
        from . import native_browser as _nb

        _nb.close(_float_tab_id(key))
    except Exception as e:
        print(f"[bridge] 浮动窗口内浏览器释放失败（忽略）：{e}")


def _build_url(key: str, kind: str, label: str, menu: str, nav: str,
               url: str = "") -> str:
    port = _PORT_GETTER() if _PORT_GETTER else None
    if not port:
        raise FloatError("FLOAT_NO_PORT", "桥接服务未就绪，无法创建浮动窗口")
    # 固定菜单（当前只有「首页」）没有 /tools/:menu 路由，直接回首页
    fixed = menu == "首页"
    path = "/" if fixed else f"/tools/{quote(menu)}/{quote(nav or '首页')}"
    query = {"float": "1", "kind": kind, "key": key, "label": label,
             "menu": menu, "nav": nav or "首页"}
    if kind == "browser" and url:
        query["url"] = url
    return f"http://127.0.0.1:{port}{path}?{urlencode(query)}"


def _norm_size(width: Any, height: Any) -> "tuple[int, int]":
    try:
        w = int(width)
        h = int(height)
    except (TypeError, ValueError):
        w, h = 760, 480
    if w <= 1 or h <= 1:
        w, h = 760, 480
    w = max(_FLOAT_MIN_W, min(_FLOAT_MAX_W, w))
    h = max(_FLOAT_MIN_H, min(_FLOAT_MAX_H, h))
    return w, h


def _closed_cb(key: str, win) -> None:
    """窗口被关闭（标题栏 × / 外部销毁）：移除记录并通知主窗口。"""
    with _LOCK:
        rec = _FLOATS.get(key)
        if rec is not None and rec.get("window") is win:
            _FLOATS.pop(key, None)
        else:
            return
    _dispose_browser(key)
    _emit("float.closed", {"key": key})


def _work_area_logical(rect: dict) -> "Optional[tuple[int, int, int, int]]":
    """窗口所在显示器的**工作区**（逻辑像素，已排除任务栏）；用于双击全屏。"""
    try:
        m = _main()
        mons = m._monitor_info_safe()
        if mons:
            px, py, pw, ph = m._logical_to_physical(
                int(rect["x"]), int(rect["y"]), int(rect["width"]), int(rect["height"]), mons
            )
            cx, cy = px + pw / 2, py + ph / 2
            target = None
            for mon in mons:
                l, t, w, h = mon["mon"]
                if l <= cx < l + w and t <= cy < t + h:
                    target = mon
                    break
            target = target or next((x for x in mons if x.get("primary")), mons[0])
            lx, ly, lw, lh = m._physical_to_logical(*target["work"], mons)
            return lx, ly, lw, lh
    except Exception as e:
        print(f"[bridge] 浮动窗口工作区计算失败（忽略）：{e}")
    r = _main().window_rect()
    if r:
        return int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])
    return None


def _win_rect(win) -> dict:
    return {"x": int(win.x), "y": int(win.y),
            "width": int(win.width), "height": int(win.height)}


def create(key: str, label: str, kind: str, menu: str, nav: str,
           x: Any = None, y: Any = None, width: Any = 760, height: Any = 480,
           url: str = "") -> dict:
    """创建（或重建）一个原生浮动窗口。x/y 为拖拽松手处相对主窗口视口的 CSS 坐标。

    kind=browser 时会把目标网页地址带进 URL，由 FloatShell 在窗口内再嵌一个原生 WebView2。
    """
    key = str(key or "").strip()
    if not key:
        raise FloatError("FLOAT_BAD_KEY", "缺少浮动窗口标识")
    label = str(label or key)
    kind = "nav" if str(kind) == "nav" else ("browser" if str(kind) == "browser" else "menu")
    menu = str(menu or key)
    nav = str(nav or "首页")
    _require_windowed()  # 仅校验主窗口就绪（浮窗为普通顶层窗口，不再绑定 owner）
    w, h = _norm_size(width, height)

    rect = _main().window_rect()
    if rect and x is not None and y is not None:
        # 拖拽松手处（视口 CSS 坐标）→ 让浮窗标题栏落在光标下
        sx = float(rect["x"]) + float(x) - w / 2
        sy = float(rect["y"]) + float(y) - h / 2
    elif rect:
        sx = float(rect["x"]) + (float(rect["width"]) - w) / 2
        sy = float(rect["y"]) + (float(rect["height"]) - h) / 2
    else:
        sx, sy = 0.0, 0.0
    sx, sy = _clamp_pos(sx, sy, w, h)
    url = _build_url(key, kind, label, menu, nav, str(url or ""))

    import webview as _webview

    with _LOCK:
        old = _FLOATS.pop(key, None)
        if old is not None:
            _dispose_browser(key)
            try:
                old["window"].destroy()
            except Exception as e:
                print(f"[bridge] 旧浮动窗口销毁失败（忽略）：{e}")
        win = _webview.create_window(
            label, url,
            x=int(sx), y=int(sy), width=w, height=h,
            frameless=True, easy_drag=False, resizable=True,
            min_size=(_FLOAT_MIN_W, _FLOAT_MIN_H),
            text_select=True, on_top=False, confirm_close=False,
            background_color="#f4f6f8",
        )
        if win is None:
            raise FloatError("FLOAT_CREATE_FAILED", "浮动窗口创建失败")
        _FLOATS[key] = {"window": win, "kind": kind, "menu": menu, "nav": nav,
                        "label": label, "fullscreen": False, "normal": None}
        try:
            win.events.closed += (lambda: _closed_cb(key, win))
        except Exception as e:
            print(f"[bridge] 浮动窗口关闭事件挂载失败（忽略）：{e}")
    return {"ok": True, "key": key, "native": True}


def _get(key: str) -> dict:
    with _LOCK:
        rec = _FLOATS.get(str(key))
    if rec is None:
        raise FloatError("FLOAT_NO_TAB", "浮动窗口不存在")
    return rec


def _destroy_and_notify(key: str, rec: dict) -> None:
    """销毁窗口并确保主窗口收到 float.closed（closed 回调异步，这里做幂等兜底）。"""
    _dispose_browser(key)
    try:
        rec["window"].destroy()
    except Exception as e:
        print(f"[bridge] 浮动窗口关闭失败（忽略）：{e}")
    # window.events.closed 的回调通常在 destroy 期间/之后另起线程执行；若它没赶上，
    # 这里补一次「移除 + 广播」，回调随后再跑时会因记录已不存在而自动跳过（不重复广播）。
    with _LOCK:
        still = _FLOATS.get(key)
        if still is rec:
            _FLOATS.pop(key, None)
    if still is rec:
        _emit("float.closed", {"key": key})


def close(key: str) -> dict:
    with _LOCK:
        rec = _FLOATS.get(str(key))
    if rec is not None:
        _destroy_and_notify(str(key), rec)
    return {"ok": True}


def close_all() -> dict:
    with _LOCK:
        recs = list(_FLOATS.items())
    for key, rec in recs:
        _destroy_and_notify(key, rec)
    return {"ok": True}


def focus(key: str) -> dict:
    rec = _get(key)
    try:
        rec["window"].show()
    except Exception as e:
        print(f"[bridge] 浮动窗口前置失败（忽略）：{e}")
    return {"ok": True}


def move(key: str, x: Any, y: Any) -> dict:
    """流式移动（标题栏拖动）：绝对逻辑屏幕坐标。

    为什么不用 Win32 WM_NCLBUTTONDOWN：WebView2 子窗口持有鼠标捕获，
    从宿主 UI 线程 ReleaseCapture/SendMessage 触发原生拖动不可靠；
    这里复用 pywebview easy_drag 同款「screenX - 初始 clientX」流式方案。
    """
    rec = _get(key)
    try:
        rec["window"].move(int(x), int(y))
    except Exception as e:
        raise FloatError("FLOAT_MOVE_FAILED", f"浮动窗口移动失败：{e}")
    return {"ok": True}


def maximize(key: str) -> dict:
    """双击标题栏：在「原尺寸」与「当前显示器工作区」之间切换。

    不用 Win32 WS_MAXIMIZE：frameless 窗口最大化后拖动会出现系统还原位置的跳变，
    这里用普通窗口 + 明确的工作区矩形，拖动/还原行为完全可控。
    """
    rec = _get(key)
    win = rec["window"]
    cur = _win_rect(win)
    if rec.get("fullscreen"):
        n = rec.get("normal") or cur
        rec["fullscreen"] = False
        rec["normal"] = None
        win.resize(int(n["width"]), int(n["height"]))
        win.move(int(n["x"]), int(n["y"]))
        return {"fullscreen": False, "rect": n}
    area = _work_area_logical(cur)
    if area is None:
        raise FloatError("FLOAT_NO_AREA", "无法计算显示器工作区")
    rec["normal"] = cur
    rec["fullscreen"] = True
    win.resize(int(area[2]), int(area[3]))
    win.move(int(area[0]), int(area[1]))
    return {"fullscreen": True,
            "rect": {"x": int(area[0]), "y": int(area[1]),
                     "width": int(area[2]), "height": int(area[3])}}


def drag_begin(key: str, sx: Any, sy: Any, ratio: Any = 0.5, title_h: Any = 0) -> dict:
    """标题栏拖动开始：若处于双击全屏态，先还原成原尺寸并让光标落在标题栏同一相对位置。

    返回当前窗口矩形，前端据此计算 `screenX - 窗口x` 的固定偏移，后续只用 float.move 跟随。
    """
    rec = _get(key)
    win = rec["window"]
    if not rec.get("fullscreen"):
        return {"fullscreen": False, "rect": _win_rect(win)}
    n = rec.get("normal") or _win_rect(win)
    nw, nh = int(n["width"]), int(n["height"])
    try:
        r = min(0.95, max(0.05, float(ratio)))
    except (TypeError, ValueError):
        r = 0.5
    try:
        th = max(0.0, float(title_h))
    except (TypeError, ValueError):
        th = 0.0
    x = float(sx) - nw * r
    y = float(sy) - th
    rec["fullscreen"] = False
    rec["normal"] = None
    cx, cy = _clamp_pos(x, y, nw, nh)
    win.resize(nw, nh)
    win.move(cx, cy)
    return {"fullscreen": False,
            "rect": {"x": cx, "y": cy, "width": nw, "height": nh}}


def resize(key: str, width: Any, height: Any) -> dict:
    """右下角流式拉伸：固定左上角，仅改尺寸（逻辑像素，pywebview 内做 DPI 换算）。"""
    rec = _get(key)
    # 全屏态直接拉伸 → 退出全屏（以当前全屏尺寸为起点跟随把手收缩）
    if rec.get("fullscreen"):
        rec["fullscreen"] = False
        rec["normal"] = None
    w, h = _norm_size(width, height)
    try:
        rec["window"].resize(w, h)
    except Exception as e:
        raise FloatError("FLOAT_RESIZE_FAILED", f"浮动窗口缩放失败：{e}")
    return {"ok": True, "width": w, "height": h}


def browser_attach(key: str, url: str, rect: dict) -> dict:
    """在浮动子窗口内嵌一个原生 WebView2（拖出的浏览器标签）。

    复用 native_browser 的宿主实现，但父窗体是**浮窗自己的窗体**，与主窗口的标签互不干扰。
    """
    rec = _get(key)
    from . import native_browser as _nb

    form = getattr(rec["window"], "native", None)
    if form is None:
        raise FloatError("FLOAT_NO_WINDOW", "浮动窗口尚未就绪")
    if not url:
        raise FloatError("FLOAT_BAD_URL", "浏览器地址为空")
    try:
        return _nb.attach_to(form, _float_tab_id(str(key)), str(url), rect)
    except _nb.NativeBrowserError as e:
        raise FloatError(e.code, e.message)


def browser_set_rect(key: str, rect: dict) -> dict:
    from . import native_browser as _nb

    _get(key)
    try:
        return _nb.set_rect_for(_float_tab_id(str(key)), rect)
    except _nb.NativeBrowserError as e:
        raise FloatError(e.code, e.message)


def browser_hide(key: str) -> dict:
    from . import native_browser as _nb

    return _nb.hide_for(_float_tab_id(str(key)))


def list_keys() -> dict:
    with _LOCK:
        return {"keys": list(_FLOATS.keys())}
