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


def test_app_env_includes_version():
    """v2.0.18：app.env 新增 version 字段（单一来源 update_service.APP_VERSION；前端品牌区展示）。"""
    from bridge.update_service import APP_VERSION
    env = bmain.get_app_env()
    assert env["version"] == APP_VERSION
    assert APP_VERSION == "2.2.3"  # 锚定单一来源常量值（随当前发行版本更新）


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


def test_pick_work_area_for_rect_stays_on_second_monitor():
    """v2.2.3 双屏最大化回归：窗口在副屏 → 工作区必须取副屏，不能回退主屏。
    同一坐标空间（GetWindowRect 与 EnumDisplayMonitors 原生值）选屏，不再逻辑↔物理回推。"""
    # 副屏 (1920,0,1600,900) 内的窗口
    assert bmain._pick_work_area_for_rect((2384, 100, 1000, 700), _MIXED) == (1920, 0, 1600, 900)
    # 主屏窗口
    assert bmain._pick_work_area_for_rect((125, 125, 1000, 750), _MIXED) == (0, 0, 1920, 1020)
    # 左上角越界（跨屏拖拽）但中心在副屏 → 仍选副屏
    assert bmain._pick_work_area_for_rect((1500, 100, 1200, 700), _MIXED) == (1920, 0, 1600, 900)
    # 无显示器信息 → None（调用方走原生 MonitorFromWindow / 报错守卫）
    assert bmain._pick_work_area_for_rect((100, 100, 800, 600), []) is None


def test_rects_near_and_restore_geometry():
    """最大化几何判定 / 还原目标（80% 居中 + 最小尺寸）纯函数。"""
    assert bmain._rects_near((1920, 0, 1600, 900), (1924, 2, 1595, 903)) is True
    assert bmain._rects_near((0, 0, 1536, 816), (1920, 0, 1600, 900)) is False
    # 副屏 1600×900 @100%：80% = 1280×720（>= 960×600）
    x, y, w, h = bmain._restore_geometry_for_work((1920, 0, 1600, 900), [])
    assert (w, h) == (1280, 720)
    assert (x, y) == (1920 + 160, 90)
    # 小屏（1280×720）：高度 80%=576 < 最小 600 → 抬到 600
    _, _, w, h = bmain._restore_geometry_for_work((0, 0, 1280, 720), [])
    assert (w, h) == (1024, 600)


def test_move_no_settle_is_fast(monkeypatch):
    """v2.0.16：连续 move（settle=False）不串行等 120ms —— 10 笔拖动流 <300ms 完成；
    settle=True（最大化/还原等一次性状态变更）仍保留 120ms 落定。
    v2.0.17：流式路径不再调 ShowWindow（每帧 ShowWindow 强制重绘 → 拉伸闪烁）；
    settle 路径保留 ShowWindow（清残留 showCmd）。
    v2.0.18：流式 SetWindowPos 的 SWP_SHOWWINDOW（0x40）位随 settle 移除（0x14）；
    settle 路径保留 0x54（一次性路径行为不回退）。"""
    import ctypes
    import time
    u32 = ctypes.windll.user32
    calls: list = []
    show_calls: list = []

    def fake_swp(h, _none, x, y, w, hgt, _flags):
        calls.append((x, y, w, hgt, _flags))
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
    # v2.0.18：流式 SetWindowPos 亦不携带 SWP_SHOWWINDOW（0x40 每帧强制 show 语义 = 重绘闪烁根因之一）
    assert all(c[4] == 0x14 for c in calls), "流式路径 SetWindowPos flags 应为 NOZORDER|NOACTIVATE（0x04|0x10=0x14），不得含 0x40"

    t1 = time.perf_counter()
    bmain._set_window_geometry_phys(w, 0, 0, 1600, 1000, settle=True)
    # 0.12s sleep 在 Windows 上可因计时器分辨率提前 ~1 tick 唤醒 → 阈值放宽到 0.08s
    # （仍能区分「有落定」与无落定的 <0.3s/10 笔 快路径）
    assert time.perf_counter() - t1 >= 0.08, "settle=True 路径应仍含 120ms 落定（≥0.08s 实测下限）"
    assert len(show_calls) == 1, "settle=True 路径应保留 ShowWindow（清残留 showCmd）"
    assert calls[-1][4] == 0x54, "settle=True 路径 SetWindowPos 保留 SWP_SHOWWINDOW（0x04|0x40|0x10，清残留 showCmd 双保险）"


def test_set_window_rect_noop_only_when_geometry_identical(monkeypatch):
    """v2.0.20：set_rect 流式路径只有「几何完全一致」才 no-op（防拖拽空帧重入 Win32）。
    v2.0.18 判据只看尺寸——固定尺寸模式下尺寸恒等，会把纯位置移动永远判成 no-op
    （窗口拖不动），因此位置也必须参与比较。"""
    import sys
    import ctypes
    if sys.platform != "win32":
        return
    calls: list = []
    u32 = ctypes.windll.user32

    def fake_swp(_h, _none, x, y, w, h, _flags):
        calls.append((x, y, w, h))
        return 1

    class FakeW:
        class _N:
            Handle = 999
        native = _N()

    w = FakeW()
    monkeypatch.setattr(bmain, "_active_window", lambda: w)
    monkeypatch.setattr(bmain, "_monitor_info_cached", lambda: [])  # 恒等换算（单屏 100%）
    monkeypatch.setattr(bmain, "_get_window_phys", lambda _ww: (0, 0, 1280, 800))
    monkeypatch.setattr(u32, "SetWindowPos", fake_swp)

    r1 = bmain.set_window_rect(0, 0, 1280, 800)
    assert r1["ok"] is True and r1.get("noop") is True, f"几何一致应 no-op，实际 {r1}"
    assert calls == [], "no-op 路径不应触 SetWindowPos"

    # 同尺寸不同 x（纯位置移动）：必须真正提交，否则固定尺寸的窗口永远拖不动
    r1b = bmain.set_window_rect(5, 0, 1280, 800)
    assert r1b["ok"] is True and not r1b.get("noop"), f"位置变化不应被判为 no-op，实际 {r1b}"
    assert calls == [(5, 0, 1280, 800)], f"位置变化应恰好一笔 SetWindowPos，实际 {calls}"

    # 尺寸变化（目标 1400 vs 当前 1280）→ 正常原子提交
    monkeypatch.setattr(bmain, "_active_window", lambda: FakeW())
    r2 = bmain.set_window_rect(0, 0, 1400, 800)
    assert r2["ok"] is True and not r2.get("noop"), f"尺寸变化应提交，实际 {r2}"
    assert calls == [(5, 0, 1280, 800), (0, 0, 1400, 800)], f"应逐笔提交，实际 {calls}"


def test_set_window_rect_no_window_guard(monkeypatch):
    """v2.0.18：无窗口守卫：_active_window → None → 结构化错误（在触 Win32 前返回），
    no-op/流式路径不误触（服务形态/测试环境安全，不抛）。"""
    import sys
    import ctypes
    if sys.platform != "win32":
        return
    calls: list = []
    u32 = ctypes.windll.user32
    monkeypatch.setattr(u32, "SetWindowPos", lambda *_a, **_k: calls.append(_a) or 1)
    monkeypatch.setattr(bmain, "_active_window", lambda: None)
    r = bmain.set_window_rect(0, 0, 1280, 800)
    assert r["ok"] is False and r["error"] == "window unavailable", r
    assert calls == [], "无窗口守卫应在触 Win32 前返回（流式/no-op 路径不得误触 SetWindowPos）"


def test_monitor_info_cached_ttl_reuse(monkeypatch):
    """v2.0.18：_monitor_info_cached 在 30s TTL 内命中（拖拽流免每帧 EnumDisplayMonitors+
    GetDpiForMonitor 开销——闪烁/掉帧根因 b）；TTL 过期后重走 _monitor_info_safe 现枚举。
    非 Windows/枚举失败时 _monitor_info_safe 返回 []（主屏 scale 直乘降级），缓存同样成立。"""
    hits: list = []
    monkeypatch.setattr(bmain, "_monitor_info_safe", lambda: hits.append(1) or [])
    t = [1000.0]
    monkeypatch.setattr(bmain.time, "monotonic", lambda: t[0])
    try:
        a = bmain._monitor_info_cached()
        b = bmain._monitor_info_cached()
        assert a is b and len(hits) == 1, "TTL 内命中应返回同一 list（调用方只读），仅枚举一次"
        t[0] += 29.9
        c = bmain._monitor_info_cached()
        assert c is a and len(hits) == 1, "TTL（30s）内仍应命中缓存"
        t[0] += 0.2
        d = bmain._monitor_info_cached()
        assert d is not a and len(hits) == 2, "TTL 过期应重新现枚举"
    finally:
        bmain._MONITOR_CACHE = None


def test_set_window_background_no_window():
    """v2.0.17：window.set_background 无窗口守卫（服务形态/测试环境 → 不抛）。"""
    r = bmain.set_window_background(30, 31, 36)
    assert r.get("ok") is False and "error" in r
    bad = bmain.set_window_background(300, 0, 0)
    assert bad.get("ok") is False, "rgb 越界应拒绝"


# ---- v2.0.20：窗口尺寸固定（主屏工作区 80%，不可拖拽拉伸）----
# 前端 AppShell 的 onEdgeResizeStart / edgeRect 已随「禁止拉伸」移除，
# 原 v2.0.18 的 _edge_geometry 镜像对拍用例一并退役（公式已不存在，保留会误导）。

def test_fixed_window_geometry_ratio_and_center(monkeypatch):
    """固定几何 = 主屏工作区 80% 且居中（逻辑像素；1080p + 40px 任务栏 → 1536×832）。"""
    mons = [{"mon": (0, 0, 1920, 1080), "work": (0, 0, 1920, 1040), "primary": True, "scale": 1.0}]
    monkeypatch.setattr(bmain, "_monitor_info_safe", lambda: mons)
    assert bmain._fixed_window_geometry() == (192, 104, 1536, 832)


def test_fixed_window_geometry_hi_dpi(monkeypatch):
    """150% 缩放：工作区物理 2880×1560 ÷1.5 → 逻辑 1920×1040，80% 仍为 1536×832（DPI 不放大窗口）。"""
    mons = [{"mon": (0, 0, 2880, 1620), "work": (0, 0, 2880, 1560), "primary": True, "scale": 1.5}]
    monkeypatch.setattr(bmain, "_monitor_info_safe", lambda: mons)
    assert bmain._fixed_window_geometry() == (192, 104, 1536, 832)


def test_fixed_window_geometry_fallback(monkeypatch):
    """显示器枚举失败：回退 1280×800（≈1600×1000 屏的 80%），不留 0 尺寸。"""
    monkeypatch.setattr(bmain, "_monitor_info_safe", lambda: [])
    assert bmain._fixed_window_geometry() == (0, 0, 1280, 800)


def test_clamp_window_size_keeps_min_floor(monkeypatch):
    """v2.2.1：可缩放模式 —— 尺寸不再被钳死，但不得小于最小宽高 960×600。

    v2.0.20 的「固定尺寸」语义已下线（用户要求像 Windows 应用一样可拖边/拖角拉伸，
    但要有最小值，不能无限拉小）。"""
    monkeypatch.setattr(bmain, "_FIXED_WINDOW_SIZE", (1536, 832))
    assert bmain._clamp_window_size(500, 300) == (960, 600)
    assert bmain._clamp_window_size(3000, 2000) == (3000, 2000)


def test_clamp_window_size_exact_min_boundary(monkeypatch):
    """恰好等于最小值时原样返回（不 +1、不越界）。"""
    monkeypatch.setattr(bmain, "_FIXED_WINDOW_SIZE", None)
    assert bmain._clamp_window_size(960, 600) == (960, 600)
    assert bmain._clamp_window_size(959, 599) == (960, 600)
    assert bmain._clamp_window_size(1400, 900) == (1400, 900)


# ---- v2.2.1：可缩放窗口的门禁（前端手柄 → window.set_rect → 后端钳制）----

def test_clamp_window_size_allows_resize_upward():
    """v2.2.1：允许放大到任意尺寸（不再被固定值钳死），这是「恢复可缩放」的核心语义。"""
    assert bmain._clamp_window_size(2400, 1600) == (2400, 1600)
    assert bmain._clamp_window_size(3840, 2160) == (3840, 2160)


def test_clamp_window_size_blocks_shrink_below_min():
    """v2.2.1：不能无限拉小 —— 小于最小尺寸时钳到 960×600（用户明确要求）。"""
    assert bmain._clamp_window_size(100, 100) == (960, 600)
    assert bmain._clamp_window_size(959, 600) == (960, 600)
    assert bmain._clamp_window_size(960, 599) == (960, 600)
    # 单轴越界只钳该轴，另一轴保持
    assert bmain._clamp_window_size(500, 900) == (960, 900)
    assert bmain._clamp_window_size(1400, 300) == (1400, 600)


def test_window_min_size_matches_create_window_min_size():
    """后端最小尺寸常量与 create_window(min_size=...) 必须一致，
    否则「后端允许缩小但 WinForms MinimumSize 卡住」会出现拉伸回弹抖动。"""
    import inspect
    src = inspect.getsource(bmain.run_windowed)
    assert f"min_size=(_WINDOW_MIN_W, _WINDOW_MIN_H)" in src
    assert f"resizable=True" in src
    # 固定尺寸模式已下线：不应再出现 min_size=(fw, fh)
    assert "min_size=(fw, fh)" not in src


# ---- v2.0.19：拖拽重绘挂起 / 钩子兜底 / 背景色兜底（纯逻辑门禁）----

def test_hwnd_key_int_and_c_void_p(monkeypatch):
    """ctypes 回调 hwnd 可能是 int 或 c_void_p，统一取整数键（转发器查表用）。"""
    import ctypes
    assert bmain._hwnd_key(12345) == 12345
    assert bmain._hwnd_key(ctypes.c_void_p(0x1E240)) == 0x1E240
    assert bmain._hwnd_key(None) == 0


def test_colorref_byte_order():
    """0xRRGGBB → COLORREF 0x00BBGGRR（低字节在前），GCLP_HBRBACKGROUND 兜底钉字节序。"""
    assert bmain._colorref(0x1E1F24) == 0x241F1E
    assert bmain._colorref(0xF4F6F8) == 0xF8F6F4
    assert bmain._colorref(0x000000) == 0
    assert bmain._colorref(0xFFFFFF) == 0xFFFFFF


def test_drag_begin_end_no_window_guard():
    """无窗口（服务形态/测试环境）：drag_begin 返回结构化错误，drag_end no-op 不抛。"""
    monkeypatch_target = bmain._active_window
    bmain._active_window = lambda: None
    try:
        r = bmain.drag_begin()
        assert r.get("ok") is False and "error" in r
        e = bmain.drag_end()
        assert e.get("ok") is True and e.get("noop") is True
    finally:
        bmain._active_window = monkeypatch_target


def test_apply_class_background_non_win32_guard(monkeypatch):
    """非 win32 平台：背景色兜底返回结构化错误（不抛、不误调 GDI）。"""
    monkeypatch.setattr(bmain.sys, "platform", "linux")
    try:
        r = bmain._apply_class_background(1, 0x1E1F24)
        assert r.get("ok") is False and r.get("error") == "win32 only"
    finally:
        monkeypatch.undo()


def test_set_window_background_subclass_missing_falls_back(monkeypatch):
    """钩子未装（_SUBCLASS_PROCS 空）：set_window_background 走 GCLP 兜底而非报「subclass not installed」。"""
    called: list = []
    fake_win = type("_W", (), {"native": None})()
    monkeypatch.setattr(bmain, "_active_window", lambda: fake_win)
    monkeypatch.setattr(bmain, "_handle_int", lambda _w: 999)
    monkeypatch.setattr(bmain, "_SUBCLASS_PROCS", {}, raising=False)
    monkeypatch.setattr(bmain, "_apply_class_background", lambda h, rgb: called.append((h, rgb)) or {"ok": True, "applied": "class-brush"})
    r = bmain.set_window_background(30, 31, 36)
    assert called == [(999, 0x1E1F24)], (called, r)
    assert r.get("ok") is True and r.get("applied") == "class-brush"


def test_drag_redraw_state_defaults():
    """拖拽重绘状态默认未激活（进程启动 / 无拖拽时）。"""
    assert bmain._DRAG_REDRAW["active"] is False
    assert bmain._DRAG_REDRAW["hwnd"] == 0


# ---- v2.1.1：单实例守卫 / WebView2 持久化 profile（启动性能改造）----
import os  # noqa: E402  （追加段局部使用）


def test_webview_storage_path_versioned_and_created(monkeypatch, tmp_path):
    """持久化目录 = <root>/data/webview2-<版本>：带版本后缀 → 升级后自动换新 profile。"""
    monkeypatch.setattr("bridge.menu_service.project_root", lambda: tmp_path)
    p = bmain._webview_storage_path()
    assert p is not None
    assert os.path.basename(p) == f"webview2-{bmain.APP_VERSION}"
    assert os.path.isdir(p)


def test_webview_storage_path_cleans_old_versions(monkeypatch, tmp_path):
    """旧版本 profile 目录启动时清理（避免磁盘无限堆积），当前版本保留。"""
    monkeypatch.setattr("bridge.menu_service.project_root", lambda: tmp_path)
    old = tmp_path / "data" / "webview2-0.0.1"
    old.mkdir(parents=True)
    (old / "junk.bin").write_bytes(b"x" * 64)
    p = bmain._webview_storage_path()
    assert not old.exists(), "旧版本 profile 目录应被清理"
    assert p and os.path.isdir(p)


def test_webview_storage_path_unwritable_returns_none(monkeypatch, tmp_path):
    """目录建不出来（只读安装位置）：返回 None 让调用方退回私有模式，绝不抛异常挡启动。"""
    monkeypatch.setattr("bridge.menu_service.project_root", lambda: tmp_path)
    (tmp_path / "data").write_text("not a directory")  # data 是文件 → mkdir 失败
    assert bmain._webview_storage_path() is None


def test_acquire_single_instance_non_windows(monkeypatch):
    """非 Windows：守卫直接放行（不因平台分支挡住启动）。"""
    monkeypatch.setattr(bmain.sys, "platform", "linux")
    assert bmain._acquire_single_instance() is True


def test_wake_existing_window_non_windows(monkeypatch):
    """非 Windows：唤回窗口返回 False（不触 Win32）。"""
    monkeypatch.setattr(bmain.sys, "platform", "linux")
    assert bmain._wake_existing_window() is False


def test_single_instance_second_acquire_blocked(monkeypatch):
    """同一互斥量名二次获取 → ERROR_ALREADY_EXISTS → 判定「已有实例」。
    用独立名字（含 pid），避免与本机正在运行的真实实例撞名导致首次获取就失败。"""
    if sys.platform != "win32":
        return
    monkeypatch.setattr(bmain, "_SINGLE_INSTANCE_NAME", f"Local\\DaybreakToolbox.Test.{os.getpid()}")
    monkeypatch.setattr(bmain, "_wake_existing_window", lambda: False)
    monkeypatch.setattr(bmain, "_SINGLE_INSTANCE_MUTEX", None)
    assert bmain._acquire_single_instance() is True
    assert bmain._SINGLE_INSTANCE_MUTEX, "首次获取后必须持句柄引用（防 GC 释放互斥量）"
    assert bmain._acquire_single_instance() is False
