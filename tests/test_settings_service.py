"""tests/test_settings_service.py：v2.0.15 通用设置 service（config/settings.json 原子读写）。

覆盖：
  1. 缺文件 → 全默认（close_to_tray=False）
  2. set 合法布尔 → 原子落盘 + 返回全量
  3. set 非布尔 / 未知键 / 空 payload → SettingsError 且不写盘
  4. 损坏 JSON → 读默认（不抛）
  5. 主程序 resolve_close_action 判定（关窗动作纯函数）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from bridge import settings_service  # noqa: E402
from bridge.main import resolve_close_action  # noqa: E402


@pytest.fixture
def iso_root(tmp_path, monkeypatch):
    settings_service.set_root(tmp_path)
    yield tmp_path
    settings_service.set_root(Path(__file__).resolve().parent.parent / "bridge" / "..")


def test_missing_file_defaults(iso_root):
    assert settings_service.get_all() == {"close_to_tray": False}


def test_set_bool_roundtrip(iso_root):
    r = settings_service.set({"close_to_tray": True})
    assert r["close_to_tray"] is True
    assert settings_service.get_all()["close_to_tray"] is True
    # 原子写：文件是合法 JSON
    raw = json.loads((iso_root / "config" / "settings.json").read_text(encoding="utf-8"))
    assert raw["close_to_tray"] is True


def test_set_rejects_invalid(iso_root):
    with pytest.raises(settings_service.SettingsError) as e1:
        settings_service.set({"close_to_tray": "true"})  # 字符串噪声拒绝
    assert e1.value.code == "SETTINGS_INVALID"
    with pytest.raises(settings_service.SettingsError) as e2:
        settings_service.set({"no_such_key": 1})
    assert e2.value.code == "SETTINGS_KEY_INVALID"
    with pytest.raises(settings_service.SettingsError):
        settings_service.set({})
    # 拒绝路径未写盘
    assert not (iso_root / "config" / "settings.json").exists()


def test_corrupt_file_falls_back_to_defaults(iso_root):
    p = iso_root / "config" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert settings_service.get_all() == {"close_to_tray": False}
    # 损坏文件仍可被 set 覆盖修复
    assert settings_service.set({"close_to_tray": True})["close_to_tray"] is True


def test_resolve_close_action_matrix():
    """关窗动作判定（v2.0.15 核心语义）。"""
    assert resolve_close_action(True, True) == "minimize"   # 开启 + 有窗口 → 最小化驻留
    assert resolve_close_action(True, False) == "quit"      # 开启但无窗口（服务形态）→ 退出
    assert resolve_close_action(False, True) == "quit"     # 未开启（默认）→ 退出（旧语义）
    assert resolve_close_action(False, False) == "quit"
