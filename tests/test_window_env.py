"""窗口控件 service 纯逻辑测试（v2.0.8 无边框窗口：app.env / 窗口几何 / 尺寸钳制 / 无窗口守卫）。

不启动真实窗口：bridge.main 的窗口控制纯函数在无 pywebview 窗口时
返回 None / {"ok": False, "error": "window unavailable"}，可安全单测。
"""
import sys

from bridge import main as bmain


def test_app_env_service_mode_not_windowed():
    """服务/开发形态（未走 run_windowed）：windowed=False，web 端不渲染窗口控件。"""
    bmain._WINDOWED_UI = False
    env = bmain.get_app_env()
    assert env["windowed"] is False
    assert env["frameless"] is False
    assert env["platform"] == sys.platform


def test_app_env_windowed_flag(monkeypatch):
    """run_windowed 置位后 app.env 反映 windowed=True。"""
    monkeypatch.setattr(bmain, "_WINDOWED_UI", True)
    try:
        assert bmain.get_app_env()["windowed"] is True
    finally:
        bmain._WINDOWED_UI = False


def test_window_rect_no_window_returns_none():
    """无 pywebview 窗口（测试环境）：window_rect → None（不抛）。"""
    assert bmain.window_rect() is None


def test_window_move_resize_no_window_guard():
    """无窗口守卫：move/resize/maximize/minimize 返回结构化错误而非异常。"""
    for fn, args in (
        (bmain.move_window, (10, 20)),
        (bmain.resize_window, (1024, 768)),
        (bmain.minimize_window, ()),
    ):
        r = fn(*args)
        assert r["ok"] is False and "error" in r
    r = bmain.toggle_maximize()
    assert r["ok"] is False and "error" in r


def test_clamp_window_size_min():
    """拉伸钳制最小尺寸 960×600（与 min_size 同源）。"""
    assert bmain._clamp_window_size(500, 300) == (960, 600)
    assert bmain._clamp_window_size(960, 600) == (960, 600)
    assert bmain._clamp_window_size(1400, 900) == (1400, 900)
    # 字符串入参（WS 参数可能带噪声）也安全
    assert bmain._clamp_window_size("1400", "900") == (1400, 900)


def test_max_state_default():
    """最大化状态缓存默认值（win32 几何驱动只用 saved 缓存；mac/linux 标志位配对）。"""
    assert bmain._MAX_STATE.get("maximized") in (False, None)
    assert bmain._MAX_STATE.get("saved") is None


def test_is_maximized_geometry():
    """几何判定（v2.10 幂等自愈的核心）：±8 逻辑 px 容差内视为最大化。"""
    target = (0, 0, 1536, 816)
    # 精确命中
    assert bmain._is_maximized_geometry({"x": 0, "y": 0, "width": 1536, "height": 816}, target) is True
    # 容差内（读回抖动 ±7）
    assert bmain._is_maximized_geometry({"x": 3, "y": -5, "width": 1539, "height": 812}, target) is True
    # 容差外（差 9 → 非最大化）
    assert bmain._is_maximized_geometry({"x": 0, "y": 0, "width": 1536, "height": 807}, target) is False
    # 缺省 / None 安全
    assert bmain._is_maximized_geometry(None, target) is False
    assert bmain._is_maximized_geometry({"x": 0, "y": 0, "width": 1536, "height": 816}, None) is False


def test_win_work_areas_lists_monitors():
    """Windows：显示器枚举回调参数正确 → 至少枚举出 1 个 (物理边界, 物理工作区) 元组
    （回归 v2.0.8 回调 3 参 bug）。"""
    import sys
    if sys.platform != "win32":
        return
    mons = bmain._win_work_areas()
    assert len(mons) >= 1, "显示器枚举失败（回调签名回归？）"
    mon, work = mons[0]
    assert len(mon) == 4 and len(work) == 4
    for v in mon + work:
        assert isinstance(v, int)
    assert work[2] > 0 and work[3] > 0
    # 工作区 ⊆ 显示器边界（任务栏可能吃掉一边）
    assert work[2] <= mon[2] + 4 and work[3] <= mon[3] + 4


# ---- v2.0.14 混合 DPI 坐标模型（纯函数单测；mons 为 _monitor_info 的 dict 形式）----
# 双屏合成拓扑：主屏 1920×1080 @125%（work 1920×1020），副屏 1600×900 @100% 物理右接
# 逻辑几何：主屏逻辑宽 = 1920/1.25 = 1536；副屏逻辑左缘 = 1920/1.25 = 1536，逻辑尺寸 1600×900
_MIXED = [
    {"mon": (0, 0, 1920, 1080), "work": (0, 0, 1920, 1020), "primary": True, "scale": 1.25},
    {"mon": (1920, 0, 1600, 900), "work": (1920, 0, 1600, 900), "primary": False, "scale": 1.0},
]


def test_logical_to_physical_mixed_dpi():
    """逻辑→物理：主屏内 ×1.25；副屏内按 副屏自身 scale ×1.0 + 物理原点偏移。"""
    # 主屏：逻辑 (100,100,800,600) → 物理 (125,125,1000,750)
    assert bmain._logical_to_physical(100, 100, 800, 600, _MIXED) == (125, 125, 1000, 750)
    # 副屏：逻辑 x=2000（副屏逻辑左缘 1536 起）→ 物理 1920 + (2000-1536)×1.0 = 2384
    assert bmain._logical_to_physical(2000, 100, 400, 300, _MIXED) == (2384, 100, 400, 300)


def test_physical_to_logical_mixed_dpi():
    """物理→逻辑（GetWindowRect 回读换算）：副屏物理 (2384,100) → 逻辑 (2000,100)。"""
    assert bmain._physical_to_logical(2384, 100, 400, 300, _MIXED) == (2000, 100, 400, 300)
    assert bmain._physical_to_logical(125, 125, 1000, 750, _MIXED) == (100, 100, 800, 600)  # 主屏对称


def test_mixed_dpi_roundtrip():
    """逻辑→物理→逻辑 往返恒等（拖拽/边缘缩放不漂移的数学保证）。"""
    for x, y, w, h in [(100, 100, 800, 600), (2000, 100, 400, 300),
                       (1400, 50, 1200, 700), (3100, 200, 500, 400)]:
        px, py, pw, ph = bmain._logical_to_physical(x, y, w, h, _MIXED)
        assert bmain._physical_to_logical(px, py, pw, ph, _MIXED) == (x, y, w, h), (x, y, w, h)


def test_span_window_anchor_top_left_monitor():
    """跨屏窗口（逻辑 1400 起宽 1200 → 越过副屏逻辑左缘 1536）：锚定左上角所在主屏 scale。"""
    m = bmain._pick_logical_monitor(1400, 50, 1200, 700, _MIXED, _MIXED[0]["scale"])
    assert m is not None and m.get("primary") is True


def test_single_monitor_degrades_to_scale_multiply():
    """单屏退化：L=T=0 → 逻辑×scale=物理（与 v2.0.10 旧行为一致，不回退）。"""
    mons = [{"mon": (0, 0, 1920, 1080), "work": (0, 0, 1920, 1020), "primary": True, "scale": 1.25}]
    assert bmain._logical_to_physical(100, 100, 800, 600, mons) == (125, 125, 1000, 750)
    assert bmain._physical_to_logical(125, 125, 1000, 750, mons) == (100, 100, 800, 600)


def test_no_monitor_info_identity_fallback():
    """枚举失败（mons=[]）→ 恒等映射（不抛异常，单屏 100% 时精确）。"""
    assert bmain._logical_to_physical(100, 100, 800, 600, []) == (100, 100, 800, 600)
    assert bmain._physical_to_logical(100, 100, 800, 600, []) == (100, 100, 800, 600)


def test_maximize_target_mixed_dpi():
    """副屏/主屏工作区 → 逻辑最大化目标（主屏任务栏遮挡 60px：1020/1.25=816）。"""
    wl, wt, ww, wh = _MIXED[1]["work"]
    assert bmain._physical_to_logical(wl, wt, ww, wh, _MIXED) == (1536, 0, 1600, 900)
    wl, wt, ww, wh = _MIXED[0]["work"]
    assert bmain._physical_to_logical(wl, wt, ww, wh, _MIXED) == (0, 0, 1536, 816)


def test_move_no_settle_is_fast(monkeypatch):
    """v2.0.16：连续 move（settle=False）不串行等 120ms —— 10 笔拖动流 <300ms 完成；
    settle=True（最大化/还原等一次性状态变更）仍保留 120ms 落定。
    v2.0.17：流式路径不再调 ShowWindow（每帧 ShowWindow 强制重绘 → 拉伸闪烁）；
    settle 路径保留 ShowWindow（清残留 showCmd）。"""
    import ctypes
    import time
    u32 = ctypes.windll.user32
    calls: list = []
    show_calls: list = []

    def fake_swp(h, _none, x, y, w, hgt, _flags):
        calls.append((x, y, w, hgt))
        return 1

    monkeypatch.setattr(u32, "SetWindowPos", fake_swp)
    monkeypatch.setattr(u32, "ShowWindow", lambda h, n: show_calls.append((h, n)) or 1)

    class FakeW:
        class _N:
            Handle = 12345
        native = _N()

    w = FakeW()
    monkeypatch.setattr(bmain, "_get_window_phys", lambda _w: (500, 500, 1600, 1000))
    monkeypatch.setattr(bmain, "_monitor_info_safe", lambda: [])  # 恒等换算

    t0 = time.perf_counter()
    for i in range(10):
        bmain._set_window_geometry_phys(w, 500 + i, 500 + i, 1600, 1000,
                                        keep_size=True, settle=False)
    dt_fast = time.perf_counter() - t0
    assert len(calls) == 10, f"10 笔 SetWindowPos 应全部发出（无吞包），实际 {len(calls)}"
    assert dt_fast < 0.3, f"无落定 10 笔应 <0.3s（120ms 串行仍在？），实际 {dt_fast:.2f}s"
    assert len(show_calls) == 0, "流式（settle=False）路径不应调 ShowWindow（每帧重绘→闪烁）"

    t1 = time.perf_counter()
    bmain._set_window_geometry_phys(w, 0, 0, 1600, 1000, settle=True)
    # 0.12s sleep 在 Windows 上可因计时器分辨率提前 ~1 tick 唤醒 → 阈值放宽到 0.08s
    # （仍能区分「有落定」与无落定的 <0.3s/10 笔 快路径）
    assert time.perf_counter() - t1 >= 0.08, "settle=True 路径应仍含 120ms 落定（≥0.08s 实测下限）"
    assert len(show_calls) == 1, "settle=True 路径应保留 ShowWindow（清残留 showCmd）"


def test_set_window_background_no_window():
    """v2.0.17：window.set_background 无窗口守卫（服务形态/测试环境 → 不抛）。"""
    r = bmain.set_window_background(30, 31, 36)
    assert r.get("ok") is False and "error" in r
    bad = bmain.set_window_background(300, 0, 0)
    assert bad.get("ok") is False, "rgb 越界应拒绝"
