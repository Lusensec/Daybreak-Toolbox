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
    assert APP_VERSION == "2.0.18"  # 锚定单一来源常量值（随当前发行版本更新）


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


def test_set_window_rect_noop_when_size_unchanged(monkeypatch):
    """v2.0.18：set_rect 流式路径（settle=False）目标物理尺寸与当前物理尺寸一致 → no-op，
    不触 SetWindowPos（防拖拽流无变化空帧重入 Win32）；尺寸变化 → 正常原子提交。
    位置不入 no-op 判定：_logical_to_physical 对 x/y 的换算值与物理读回的 cur[0]/cur[1]
    在恒等（100% 屏）下严格相等；混合 DPI 下按尺寸判据已覆盖「无尺寸变化的空帧」这一
    主要空转来源（位置抖动在 60fps 流里每帧必变，no-op 判定意义有限）。"""
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
    assert r1["ok"] is True and r1.get("noop") is True, f"同尺寸应 no-op，实际 {r1}"
    assert calls == [], "no-op 路径不应触 SetWindowPos"

    # 同尺寸不同 x（位置变化）：位置不入 no-op 判定（cur[2]==pw 仍成立）→ 仍 no-op（见 docstring）
    r1b = bmain.set_window_rect(5, 0, 1280, 800)
    assert r1b.get("noop") is True and calls == [], "同尺寸位置变化应仍 no-op"

    # 尺寸变化（目标 1400 vs 当前 1280）：no-op 判据 cur[2]==pw 不成立 → 恰好一笔原子提交
    monkeypatch.setattr(bmain, "_active_window", lambda: FakeW())
    r2 = bmain.set_window_rect(0, 0, 1400, 800)
    assert r2["ok"] is True and not r2.get("noop"), f"尺寸变化应提交，实际 {r2}"
    assert calls == [(0, 0, 1400, 800)], f"应恰好一笔 SetWindowPos（物理 1400×800），实际 {calls}"


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


# ---- v2.0.18：tl/tr 斜向拉伸几何（前端 EdgeZone 客户端镜像的纯函数对拍）----
# 对拍目标：web/src/components/AppShell.tsx onEdgeResizeStart（L210-L229，v2.0.18 已评审 PASS）。
# 以下 4 个用例门禁的是 Python 侧镜像公式（_edge_geometry）的回归钉——不 import TS，无新代码也绿
# （有意设计：前端公式由评审 + 本镜像钉双保险）；对照断言由 test_edge_zone_invariance_vs_orthogonal_edges
# 承担（「角落 = 正交边缘合成」，与 left/right/bl/br 既有语义自洽）。
# 前端 AppShell.onEdgeResizeStart 的公式（与后端 _clamp_window_size 同源钳制；lead 复核 v2.0.18 修正底缘锚定）：
#   tl：w=max(MIN, ow-dx), x=ox+(ow-w); h=max(MIN, oh-dy), y=oy+(oh-h)  （右下锚定：右缘+底缘固定）
#   tr：w=max(MIN, ow+dx), x=ox;        h=max(MIN, oh-dy), y=oy+(oh-h)  （左下锚定：左缘+底缘固定）
#   （未触发最小高钳制时 y=oy+(oh-h) 恒等于 y=oy+dy，行为不变）
_EDGE_MIN_W, _EDGE_MIN_H = 960, 600


def _edge_geometry(zone, ox, oy, ow, oh, dx, dy):
    """镜像 web/src/components/AppShell.tsx onMove 的 zone→几何公式（纯函数，可测）。
    tl：宽随左缘右移缩小（w=max(MIN,ow-dx), x=ox+(ow-w)），高随顶缘下移缩小（h=oh-dy），
    右下锚定（右缘+底缘固定）。tr：宽随右缘右移增大（w=ow+dx, x=ox），高随顶缘下移缩小，
    左下锚定（左缘+底缘固定）。最小高钳制后 y 按钳后 h 重锚底缘：y=oy+(oh-h)
    （lead 复核 v2.0.18：与 left 边 x=ox+(ow-w) 右缘锚定对称；未钳制时 y=oy+dy 不变）。"""
    w, h, x, y = ow, oh, ox, oy
    if zone in ("right", "br"):
        w = ow + dx
    if zone in ("bottom", "bl"):
        h = oh + dy
    if zone in ("left", "bl", "tl"):
        w = max(_EDGE_MIN_W, ow - dx)
        x = ox + (ow - w)
    if zone == "tr":
        w = ow + dx
    if zone in ("tl", "tr"):
        h = oh - dy
        y = oy + dy
    wf = max(_EDGE_MIN_W, w)
    hf = max(_EDGE_MIN_H, h)
    if zone in ("tl", "tr"):
        y = oy + (oh - hf)  # 底缘锚定：最小高钳制触发后顶缘重锚（未钳制时恒等于 oy+dy）
    return {"x": x, "y": y, "width": wf, "height": hf}


def test_edge_tl_geometry():
    """左上角拉伸（tl：右下固定——右缘+底缘不动）：右移 dx / 下移 dy → 宽缩小、高缩小、左上角右移下移。"""
    g = _edge_geometry("tl", 100, 100, 1400, 900, 40, 30)
    assert g == {"x": 140, "y": 130, "width": 1360, "height": 870}
    # 左缘继续右移越过最小宽 → 钳制 960，x 停在 ox+(ow-960)=100+440=540（钳制后停止漂移）
    g = _edge_geometry("tl", 100, 100, 1400, 900, 460, 30)
    assert g["width"] == 960 and g["x"] == 540
    # 底缘锚定（lead 复核 v2.0.18）：顶缘下移越过最小高 → 钳制 600，顶缘 y 重锚 oy+(oh-600)=400
    #（底缘停在 oy+oh=1000，不再随光标下滑；旧缺陷 y=oy+dy=430）
    g = _edge_geometry("tl", 100, 100, 1400, 900, 40, 330)
    assert g["height"] == 600 and g["y"] == 400


def test_edge_tr_geometry():
    """右上角拉伸（tr：左下固定——左缘+底缘不动）：右移 dx → 宽增大；下移 dy → 高缩小、上缘下移。"""
    g = _edge_geometry("tr", 100, 100, 1400, 900, 40, 30)
    assert g == {"x": 100, "y": 130, "width": 1440, "height": 870}
    # 反向拖动（dx 为负 / dy 为负 = 向左/向上拖）：宽/高被最小值钳制，左下锚点固定
    #（底缘锚定：顶缘 y 重锚 oy+(oh-600)=400；旧缺陷 y=oy+dy=430）
    g = _edge_geometry("tr", 100, 100, 1400, 900, -500, 330)
    assert g == {"x": 100, "y": 400, "width": 960, "height": 600}


def test_edge_corner_bottom_anchor_boundary():
    """lead 复核 v2.0.18：tl/tr 最小高钳制边界用例——dx=0、dy 使 oh-dy < 600 →
    h=600 且 y=oy+(oh-600)（底缘锚定；而非 y=oy+dy 把整个窗口带下滑）；
    未触边界（dy 小）时 y=oy+dy 保持旧行为。"""
    # tl（右下固定：底缘 oy+oh=1000、右缘 ox+ow=1500 不动）
    g = _edge_geometry("tl", 100, 100, 1400, 900, 0, 310)
    assert g == {"x": 100, "y": 400, "width": 1400, "height": 600}
    # tr 对称（左下固定：左缘 x=ox=100 不动）
    g = _edge_geometry("tr", 100, 100, 1400, 900, 0, 310)
    assert g == {"x": 100, "y": 400, "width": 1400, "height": 600}
    # 未触最小高：顶缘 y=oy+dy，与旧公式一致（钳制未触发 → 无行为变化）
    assert _edge_geometry("tl", 100, 100, 1400, 900, 0, 100) == {"x": 100, "y": 200, "width": 1400, "height": 800}
    assert _edge_geometry("tr", 100, 100, 1400, 900, 0, 100) == {"x": 100, "y": 200, "width": 1400, "height": 800}


def test_edge_zone_invariance_vs_orthogonal_edges():
    """斜角区 = 同侧两条正交边缘组合（tl = left + 顶缘分量，tr = right + 顶缘分量），
    与逐边公式结果一致——保证「角落=边缘合成」的不变量（与 left/right/bl/br 既有语义自洽）。
    顶缘分量为 h=max(MIN, oh-dy)（顶缘下移变矮，与 bottom 的 oh+dy 符号相反）。"""
    for ox, oy, ow, oh, dx, dy in [(100, 100, 1400, 900, 40, 30),
                                   (0, 0, 960, 600, -200, -200),  # 已贴最小值的反向拖
                                   (0, 0, 960, 600, 0, 330)]:     # 顶缘下移越过最小高
        for zone in ("tl", "tr"):
            g = _edge_geometry(zone, ox, oy, ow, oh, dx, dy)
            # 宽分量与 left/right 正缘同公式（tr：dx>0 同 right 变宽，dx<0 被最小宽钳制）
            ref_w = _edge_geometry("left" if zone == "tl" else "right", ox, oy, ow, oh, dx, 0)["width"]
            # 高分量 = 顶缘分量（与 bottom 区符号相反）
            ref_h = max(_EDGE_MIN_H, oh - dy)
            assert g["width"] == ref_w, (zone, g, ref_w)
            assert g["height"] == ref_h, (zone, g, ref_h)
