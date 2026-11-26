"""ball：系统主题检测 / 球体图像候选链（纯逻辑部分，monkeypatch 可测）。

覆盖 v2.0.5 新增：
- _system_light_theme：AppsUseLightTheme=1 → 浅色；键缺失（OSError）→ 深色
- _ball_logo_files：浅色优先 ball-light.png（legacy logo.png 兜底在列）；深色同理
"""
import winreg

from bridge import ball


def test_system_light_theme_light(monkeypatch):
    """AppsUseLightTheme=1 → 浅色主题（True）。"""

    class _FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_openkey(h, path):
        assert path == r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        return _FakeKey()

    def fake_query(_k, name):
        assert name in ("AppsUseLightTheme", "ColorsUseLightStyle")
        return (1, winreg.REG_DWORD)

    monkeypatch.setattr(winreg, "OpenKey", fake_openkey)
    monkeypatch.setattr(winreg, "QueryValueEx", fake_query)
    assert ball._system_light_theme() is True


def test_system_light_theme_missing_keys_defaults_dark(monkeypatch):
    """注册表键缺失（OSError）→ 深色（False），不抛异常。"""

    def fake_openkey(h, path):
        raise OSError("key not found")

    monkeypatch.setattr(winreg, "OpenKey", fake_openkey)
    assert ball._system_light_theme() is False


def test_ball_logo_files_theme_order():
    """浅色：ball-light.png 优先，legacy logo.png 兜底在列；深色：ball-dark.png 优先。"""
    from pathlib import Path

    light = [p.name for p in ball._ball_logo_files(Path("C:/x"), True)]
    dark = [p.name for p in ball._ball_logo_files(Path("C:/x"), False)]
    assert light[0] == "ball-light.png"
    assert "logo.png" in light
    assert dark[0] == "ball-dark.png"
    assert "logo.png" in dark
