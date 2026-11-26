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
    """最大化状态机默认值（未最大化、无保存几何；几何由 toggle_maximize 自行记忆）。"""
    assert bmain._MAX_STATE["maximized"] is False
    assert bmain._MAX_STATE["saved"] is None


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
