"""原生浮动子窗口 service 纯逻辑测试（v2.3.2）。

不创建真实窗口：用 sys.modules 注入假 webview，验证 URL 拼装、逻辑坐标换算、
无窗口守卫与 float.closed 广播；pywebview 的真实多窗口行为留待实机验证。
"""
import sys
import types

import pytest

from bridge import float_service as fs
from bridge import main as bmain
from bridge.server import BridgeBus


class _FakeEvent:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


class _FakeWin:
    def __init__(self) -> None:
        self.events = types.SimpleNamespace(closed=_FakeEvent())
        self.native = None
        self.destroyed = False
        self.x = 0
        self.y = 0
        self.width = 760
        self.height = 480

    def destroy(self) -> None:
        self.destroyed = True

    def move(self, x, y) -> None:
        self.x, self.y = int(x), int(y)

    def resize(self, w, h) -> None:
        self.width, self.height = int(w), int(h)


@pytest.fixture(autouse=True)
def _reset():
    fs._FLOATS.clear()
    yield
    fs._FLOATS.clear()


@pytest.fixture
def fake_webview(monkeypatch):
    captured: list = []

    def fake_create(title, url, **kw):
        win = _FakeWin()
        captured.append({"title": title, "url": url, "kwargs": kw, "window": win})
        return win

    mod = types.SimpleNamespace(create_window=fake_create)
    monkeypatch.setitem(sys.modules, "webview", mod)
    return captured


def _enable(monkeypatch, emit=None):
    monkeypatch.setattr(bmain, "_WINDOWED_UI", True)
    monkeypatch.setattr(fs, "_WINDOWED_GETTER", lambda: True)
    monkeypatch.setattr(fs, "_PORT_GETTER", lambda: 8765)
    monkeypatch.setattr(bmain, "_active_window", lambda: object())
    monkeypatch.setattr(bmain, "window_rect",
                        lambda: {"x": 100, "y": 50, "width": 1200, "height": 800})
    monkeypatch.setattr(bmain, "_monitor_info_safe", lambda: [])
    monkeypatch.setattr(fs, "_EMIT", emit or (lambda event, payload: None))


def test_service_mode_unavailable(monkeypatch):
    monkeypatch.setattr(fs, "_WINDOWED_GETTER", lambda: False)
    assert fs.available() is False
    with pytest.raises(fs.FloatError) as ei:
        fs.create("MenuA", "MenuA", "menu", "MenuA", "首页", 10, 10, 760, 480)
    assert ei.value.code == "FLOAT_UNSUPPORTED"


def test_no_window_guard(monkeypatch):
    monkeypatch.setattr(fs, "_WINDOWED_GETTER", lambda: True)
    monkeypatch.setattr(bmain, "_active_window", lambda: None)
    with pytest.raises(fs.FloatError) as ei:
        fs.create("MenuA", "MenuA", "menu", "MenuA", "首页")
    assert ei.value.code == "FLOAT_NO_WINDOW"


def test_create_menu_url_and_position(monkeypatch, fake_webview):
    _enable(monkeypatch)
    r = fs.create("MenuA", "MenuA", "menu", "MenuA", "NavA", 500, 400, 760, 480)
    assert r["ok"] is True and r["native"] is True
    cap = fake_webview[0]
    assert "/tools/MenuA/NavA?" in cap["url"]
    assert "float=1" in cap["url"] and "kind=menu" in cap["url"] and "key=MenuA" in cap["url"]
    # 松手点居中：100+500-380=220 / 50+400-240=210
    assert cap["kwargs"]["x"] == 220 and cap["kwargs"]["y"] == 210
    assert cap["kwargs"]["width"] == 760 and cap["kwargs"]["height"] == 480
    assert cap["kwargs"]["frameless"] is True
    assert cap["kwargs"]["easy_drag"] is False


def test_create_fixed_menu_uses_root_route(monkeypatch, fake_webview):
    _enable(monkeypatch)
    fs.create("首页", "首页", "menu", "首页", "首页", 30, 30, 600, 400)
    cap = fake_webview[0]
    assert cap["url"].startswith("http://127.0.0.1:8765/?")
    assert cap["kwargs"]["width"] == 600 and cap["kwargs"]["height"] == 400


def test_closed_event_removes_and_emits(monkeypatch, fake_webview):
    events: list = []
    _enable(monkeypatch, emit=lambda e, p: events.append((e, p)))
    fs.create("MenuA", "MenuA", "menu", "MenuA", "NavA", 10, 10, 760, 480)
    win = fake_webview[0]["window"]
    assert "MenuA" in fs.list_keys()["keys"]
    for fn in win.events.closed.handlers:
        fn()
    assert "MenuA" not in fs.list_keys()["keys"]
    assert events == [("float.closed", {"key": "MenuA"})]


def test_create_browser_url_carries_target(monkeypatch, fake_webview):
    _enable(monkeypatch)
    fs.create("browser::m::n", "Tab", "browser", "m", "n", 100, 100, 800, 600,
              "https://example.com/a?b=1")
    cap = fake_webview[0]
    assert "kind=browser" in cap["url"]
    assert "url=https%3A%2F%2Fexample.com%2Fa%3Fb%3D1" in cap["url"]


def test_maximize_and_drag_restore(monkeypatch, fake_webview):
    _enable(monkeypatch)
    fs.create("MenuA", "MenuA", "menu", "MenuA", "NavA", 10, 10, 760, 480)
    win = fake_webview[0]["window"]

    r = fs.maximize("MenuA")
    assert r["fullscreen"] is True
    # 无显示器信息 → 工作区回退为 window_rect()（100,50,1200,800）
    assert (win.x, win.y, win.width, win.height) == (100, 50, 1200, 800)

    # 全屏态拖标题栏：先还原到原尺寸，并按光标相对位置定位
    r = fs.drag_begin("MenuA", 500, 200, 0.5, 20)
    assert r["fullscreen"] is False
    assert (win.width, win.height) == (760, 480)
    assert (win.x, win.y) == (120, 180)  # 500-760*0.5 / 200-20
    assert fs._FLOATS["MenuA"]["fullscreen"] is False


def test_maximize_restores_normal_rect(monkeypatch, fake_webview):
    _enable(monkeypatch)
    fs.create("MenuA", "MenuA", "menu", "MenuA", "NavA", 10, 10, 760, 480)
    win = fake_webview[0]["window"]
    win.move(220, 210)
    fs.maximize("MenuA")
    r = fs.maximize("MenuA")
    assert r["fullscreen"] is False
    assert (win.x, win.y, win.width, win.height) == (220, 210, 760, 480)


def test_resize_exits_fullscreen(monkeypatch, fake_webview):
    _enable(monkeypatch)
    fs.create("MenuA", "MenuA", "menu", "MenuA", "NavA", 10, 10, 760, 480)
    fs.maximize("MenuA")
    fs.resize("MenuA", 900, 600)
    assert fs._FLOATS["MenuA"]["fullscreen"] is False


def test_close_removes_and_emits_fallback(monkeypatch, fake_webview):
    """主动关闭：即使窗口 closed 回调没赶上（FakeWin 不触发），也要移除并广播 float.closed。"""
    events: list = []
    _enable(monkeypatch, emit=lambda e, p: events.append((e, p)))
    fs.create("MenuA", "MenuA", "menu", "MenuA", "NavA", 10, 10, 760, 480)
    fs.close("MenuA")
    assert fs.list_keys()["keys"] == []
    assert events == [("float.closed", {"key": "MenuA"})]


def test_norm_size_clamps_to_min(monkeypatch):
    assert fs._norm_size(10, 10) == (420, 300)
    assert fs._norm_size(4000, 4000) == (1400, 900)
    assert fs._norm_size("900", "600") == (900, 600)


def test_bridge_bus_emit_sync():
    bus = BridgeBus()
    q = bus.subscribe()
    bus.emit("float.closed", {"key": "X"})
    frame = q.get_nowait()
    assert frame["type"] == "float.closed" and frame["payload"]["key"] == "X"
    bus.unsubscribe(q)
