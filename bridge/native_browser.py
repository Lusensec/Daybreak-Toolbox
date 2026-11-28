"""原生 WebView2 内嵌浏览器（v2.3.0，仅 Windows 窗口模式）。

为什么需要它：链接类工具原先用 `<iframe>` 承载，目标站点只要返回
`X-Frame-Options: SAMEORIGIN/DENY` 或 CSP `frame-ancestors`，WebView2 就会拒绝渲染
（Bing / Google 等主流站点均如此）。本模块在主窗口内创建一个无边框子窗体，子窗体里放
**独立的原生 WebView2 控件**——目标网页成为顶层文档，不再受「被嵌入」限制，Cookie 也是
第一方并可随 profile 持久化。

实现要点：
- 子窗体 `TopLevel=False` 挂到 pywebview 主窗体，坐标用物理像素（DPI 换算由后端完成）；
- 每个浏览器标签一个子窗体 + WebView2，切换标签只显隐、不销毁，保留页面状态；
- 所有 WinForms 操作经 `form.Invoke` 切到 UI 线程；
- 任何环境问题（非 Windows / 窗口未就绪 / WebView2 初始化失败）都抛 NativeBrowserError，
  由前端回退到 iframe 方案。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.RLock()
_HOSTS: dict[str, "_Host"] = {}
_SUSPENDED = False


class NativeBrowserError(Exception):
    """原生浏览器不可用/操作失败；main.py 会转成 BridgeError 返回前端。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def available() -> bool:
    """当前进程是否具备原生嵌入条件（仅判断平台，真正成功与否以 attach 为准）。"""
    return sys.platform == "win32"


def _winforms():
    from webview.platforms import winforms as wf

    return wf


def _edge():
    from webview.platforms import edgechromium as ec

    return ec


def _active_form():
    """pywebview 主窗体（native）；未创建/服务模式 → None。"""
    try:
        import webview

        w = webview.windows[0] if webview.windows else None
        return getattr(w, "native", None) if w is not None else None
    except Exception:
        return None


def _ui(form, fn):
    """在主窗体 UI 线程同步执行 fn（RPC 在 asyncio 线程里跑）。"""
    from System import Action

    if form.InvokeRequired:
        form.Invoke(Action(fn))
    else:
        fn()


def _dpi_scale(form) -> float:
    try:
        import ctypes

        h = form.Handle
        hwnd = h.ToInt32() if hasattr(h, "ToInt32") else int(h)
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        return (dpi / 96.0) if dpi else 1.0
    except Exception:
        return 1.0


def _profile_dir() -> str:
    """浏览器专用 WebView2 profile：与主界面 profile 分开，避免互相清理。"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent / "data"
    else:
        from .menu_service import project_root as _pr

        base = Path(_pr()) / "data"
    target = base / "browser-webview2"
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def _norm_rect(rect: dict) -> tuple[float, float, float, float]:
    try:
        x = float(rect.get("x", 0))
        y = float(rect.get("y", 0))
        w = float(rect.get("width", 0))
        h = float(rect.get("height", 0))
    except Exception:
        raise NativeBrowserError("BROWSER_BAD_RECT", "浏览器区域参数无效")
    if w <= 1 or h <= 1:
        raise NativeBrowserError("BROWSER_BAD_RECT", "浏览器区域尺寸无效")
    return x, y, w, h


class _Host:
    """单个标签的宿主子窗体 + WebView2。"""

    def __init__(self, form, tab_id: str, profile_dir: str) -> None:
        wf = _winforms()
        ec = _edge()
        self.tab_id = tab_id
        self.form = form  # v2.3.2：记住宿主窗体（主窗口或某个浮动子窗口）
        self.url = ""
        self.ready = False
        self._pending_url = ""

        self.container = wf.WinForms.Form()
        # .NET 枚举成员名 None 与 Python 关键字冲突，只能 getattr
        self.container.FormBorderStyle = getattr(wf.WinForms.FormBorderStyle, "None")
        self.container.TopLevel = False
        self.container.AutoScaleMode = getattr(wf.WinForms.AutoScaleMode, "None")
        self.container.BackColor = wf.Color.White
        self.container.Visible = False
        form.Controls.Add(self.container)

        self.view = ec.WebView2()
        props = ec.CoreWebView2CreationProperties()
        props.UserDataFolder = profile_dir
        # 与 pywebview 主 WebView2 保持相同的滚动行为，避免幽灵回弹
        props.AdditionalBrowserArguments = "--disable-features=ElasticOverscroll"
        self.view.CreationProperties = props
        self.container.Controls.Add(self.view)
        self.view.Dock = ec.WinForms.DockStyle.Fill
        # 先 Show 再隐藏：WebView2 需要控件已有窗口句柄才能完成异步初始化
        self.container.Show()
        self.container.Visible = False
        self.view.CoreWebView2InitializationCompleted += self._on_ready
        self.view.EnsureCoreWebView2Async(None)

    # ---- WebView2 生命周期 ----
    def _on_ready(self, _sender, args) -> None:
        try:
            if not args.IsSuccess:
                print(f"[bridge] 原生浏览器初始化失败 tab={self.tab_id}: {args.InitializationException}")
                return
            self.ready = True
            core = self.view.CoreWebView2
            try:
                core.NewWindowRequested += self._on_new_window
                settings = core.Settings
                settings.AreDefaultContextMenusEnabled = True
                settings.AreDevToolsEnabled = False
                settings.IsStatusBarEnabled = False
                settings.IsSwipeNavigationEnabled = False
            except Exception as e:
                print(f"[bridge] 原生浏览器设置项应用失败（忽略）：{e}")
            if self._pending_url:
                core.Navigate(self._pending_url)
                self._pending_url = ""
            print(f"[bridge] 原生浏览器初始化完成 tab={self.tab_id} url={self.url}")
        except Exception as e:
            print(f"[bridge] 原生浏览器 ready 回调异常 tab={self.tab_id}: {e}")

    def _on_new_window(self, _sender, args) -> None:
        """target=_blank / window.open：在当前标签内跳转，避免弹出无壳窗口。"""
        try:
            uri = args.Uri
            args.Handled = True
            if uri and self.ready:
                self.view.CoreWebView2.Navigate(uri)
        except Exception as e:
            print(f"[bridge] 原生浏览器新窗口处理失败（忽略）：{e}")

    def navigate(self, url: str) -> None:
        self.url = url
        if self.ready:
            self.view.CoreWebView2.Navigate(url)
        else:
            self._pending_url = url

    def reload(self) -> None:
        if self.ready:
            self.view.CoreWebView2.Reload()

    def set_rect(self, x: float, y: float, w: float, h: float, scale: float) -> None:
        wf = _winforms()
        px = int(round(x * scale))
        py = int(round(y * scale))
        pw = max(1, int(round(w * scale)))
        ph = max(1, int(round(h * scale)))
        self.container.Location = wf.Point(px, py)
        self.container.Size = wf.Size(pw, ph)

    def set_visible(self, visible: bool) -> None:
        if visible:
            self.container.Show()
        self.container.Visible = bool(visible)
        if visible:
            self.container.BringToFront()
            try:
                self.view.Focus()
            except Exception:
                pass

    def dispose(self) -> None:
        try:
            self.container.Visible = False
        except Exception:
            pass
        try:
            self.container.Controls.Remove(self.view)
        except Exception:
            pass
        try:
            self.view.Dispose()
        except Exception:
            pass
        try:
            self.container.Dispose()
        except Exception:
            pass


def _form_hosts(form) -> list["_Host"]:
    """只返回挂在指定窗体上的宿主：主窗口切标签不能误伤浮动子窗口里的浏览器，反之亦然。"""
    return [h for h in _HOSTS.values() if h.form is form]


def _require_form():
    if not available():
        raise NativeBrowserError("BROWSER_UNSUPPORTED", "当前平台不支持原生内嵌浏览器")
    form = _active_form()
    if form is None:
        raise NativeBrowserError("BROWSER_NO_WINDOW", "主窗口尚未就绪，无法创建原生浏览器")
    return form


def attach(tab_id: str, url: str, rect: dict, show: bool = True) -> dict:
    """创建/更新标签宿主并（可选）激活显示。"""
    if not tab_id:
        raise NativeBrowserError("BROWSER_BAD_TAB", "缺少浏览器标签标识")
    if not url:
        raise NativeBrowserError("BROWSER_BAD_URL", "链接地址为空")
    x, y, w, h = _norm_rect(rect)
    form = _require_form()

    global _SUSPENDED
    with _LOCK:
        def _do():
            global _SUSPENDED
            host = _HOSTS.get(tab_id)
            if host is None:
                host = _Host(form, tab_id, _profile_dir())
                _HOSTS[tab_id] = host
            scale = _dpi_scale(form)
            host.set_rect(x, y, w, h, scale)
            if host.url != url:
                host.navigate(url)
            if show:
                _SUSPENDED = False
                for other in _form_hosts(form):
                    other.set_visible(other.tab_id == tab_id)
            else:
                host.set_visible(False)

        _ui(form, _do)
    return {"ok": True}


def set_rect(rect: dict) -> dict:
    x, y, w, h = _norm_rect(rect)
    form = _require_form()
    with _LOCK:
        def _do():
            scale = _dpi_scale(form)
            for host in _form_hosts(form):
                host.set_rect(x, y, w, h, scale)

        _ui(form, _do)
    return {"ok": True}


def activate(tab_id: str) -> dict:
    form = _require_form()
    global _SUSPENDED
    with _LOCK:
        def _do():
            global _SUSPENDED
            _SUSPENDED = False
            for host in _form_hosts(form):
                host.set_visible(host.tab_id == tab_id)

        _ui(form, _do)
    return {"ok": True}


def hide() -> dict:
    form = _require_form()
    global _SUSPENDED
    with _LOCK:
        def _do():
            global _SUSPENDED
            _SUSPENDED = True
            for host in _form_hosts(form):
                host.set_visible(False)

        _ui(form, _do)
    return {"ok": True}


def reload(tab_id: str) -> dict:
    form = _require_form()
    with _LOCK:
        host = _HOSTS.get(tab_id)
        if host is None:
            raise NativeBrowserError("BROWSER_NO_TAB", "浏览器标签不存在")

    _ui(form, host.reload)
    return {"ok": True}


def navigate(tab_id: str, url: str) -> dict:
    if not url:
        raise NativeBrowserError("BROWSER_BAD_URL", "链接地址为空")
    form = _require_form()
    with _LOCK:
        host = _HOSTS.get(tab_id)
        if host is None:
            raise NativeBrowserError("BROWSER_NO_TAB", "浏览器标签不存在")

    _ui(form, lambda: host.navigate(url))
    return {"ok": True}


def close(tab_id: str) -> dict:
    with _LOCK:
        host = _HOSTS.pop(tab_id, None)
    if host is not None:
        try:
            _ui(host.form, host.dispose)
        except Exception as e:
            print(f"[bridge] 原生浏览器释放失败 tab={tab_id}: {e}")
    return {"ok": True}


def close_all() -> None:
    """应用退出时释放全部原生控件（best-effort）。"""
    with _LOCK:
        hosts = list(_HOSTS.values())
        _HOSTS.clear()
    for host in hosts:
        try:
            _ui(host.form, host.dispose)
        except Exception:
            pass


# ---- v2.3.2：把原生 WebView2 嵌入任意 pywebview 窗体（浮动子窗口里的浏览器标签） ----

def attach_to(form, tab_id: str, url: str, rect: dict, show: bool = True) -> dict:
    """在指定窗体上创建/更新一个独立浏览器宿主（不参与主窗口的标签互斥）。"""
    if not tab_id:
        raise NativeBrowserError("BROWSER_BAD_TAB", "缺少浏览器标签标识")
    if not url:
        raise NativeBrowserError("BROWSER_BAD_URL", "链接地址为空")
    x, y, w, h = _norm_rect(rect)
    if form is None:
        raise NativeBrowserError("BROWSER_NO_WINDOW", "目标窗口尚未就绪")

    with _LOCK:
        def _do():
            host = _HOSTS.get(tab_id)
            if host is None or host.form is not form:
                if host is not None:
                    try:
                        host.dispose()
                    except Exception:
                        pass
                host = _Host(form, tab_id, _profile_dir())
                _HOSTS[tab_id] = host
            host.set_rect(x, y, w, h, _dpi_scale(form))
            if host.url != url:
                host.navigate(url)
            host.set_visible(bool(show))

        _ui(form, _do)
    return {"ok": True}


def set_rect_for(tab_id: str, rect: dict) -> dict:
    x, y, w, h = _norm_rect(rect)
    with _LOCK:
        host = _HOSTS.get(tab_id)
    if host is None:
        raise NativeBrowserError("BROWSER_NO_TAB", "浏览器标签不存在")

    def _do():
        host.set_rect(x, y, w, h, _dpi_scale(host.form))

    _ui(host.form, _do)
    return {"ok": True}


def hide_for(tab_id: str) -> dict:
    with _LOCK:
        host = _HOSTS.get(tab_id)
    if host is not None:
        try:
            _ui(host.form, lambda: host.set_visible(False))
        except Exception as e:
            print(f"[bridge] 浮动浏览器隐藏失败 tab={tab_id}: {e}")
    return {"ok": True}
