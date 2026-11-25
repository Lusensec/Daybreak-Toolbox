"""bridge.main.pick_mode —— 入口形态选择（纯函数；frozen 用 monkeypatch 模拟）。"""
import sys


def test_dev_default_is_service(monkeypatch):
    """开发态（非 frozen）无论参数一律 service：不弹窗口，避免打扰开发。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    from bridge.main import pick_mode
    assert pick_mode([]) == "service"
    assert pick_mode(["--service"]) == "service"


def test_frozen_default_is_windowed(monkeypatch):
    """打包态默认窗口模式（方案 A）。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    from bridge.main import pick_mode
    assert pick_mode([]) == "windowed"


def test_frozen_service_flag(monkeypatch):
    """打包态带 --service → 回退服务模式（v2.0.2 形态）。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    from bridge.main import pick_mode
    assert pick_mode(["--service"]) == "service"
    assert pick_mode(["--other", "--service"]) == "service"
