"""shortcut_service 单元测试：组合键校验 / 槽位键校验 / 原子读写 / 损坏恢复。"""
import json

import pytest

from bridge import shortcut_service
from bridge.shortcut_service import (ShortcutError, get_shortcuts,
                                    set_shortcuts, set_root)


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    set_root(tmp_path)
    yield


def test_get_missing_file_returns_empty():
    assert get_shortcuts() == {"shortcuts": {}}


def test_set_and_get_roundtrip():
    data = {"panel": "Ctrl+Space", "dyn:红队": "Ctrl+1", "fix:首页": "Ctrl+Alt+1",
            "nav:1": "Ctrl+Shift+1", "tool:红队__扫描器": "Ctrl+Shift+P", "dyn:蓝队": ""}
    r = set_shortcuts(data)
    assert r["ok"] is True
    assert r["shortcuts"] == data
    assert get_shortcuts()["shortcuts"] == data
    # 落盘文件内容一致
    ondisk = json.loads(shortcut_service._CONFIG_FILE.read_text(encoding="utf-8"))
    assert ondisk == data


def test_ball_slot_keys_removed():
    # v2.0.7 起悬浮球功能移除：ball:* 槽位不再合法（set 拒绝）
    for bad in ("ball:show", "ball:hide", "ball:xxx", "ball"):
        with pytest.raises(ShortcutError) as ei:
            set_shortcuts({bad: "Ctrl+1"})
        assert ei.value.code == "SHORTCUT_INVALID"


def test_legacy_ball_entries_dropped_on_load():
    # 旧版本落盘的 ball:* 条目读取时静默丢弃（老用户无需手工清理）
    target = shortcut_service._CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "panel": "Ctrl+Space",
        "ball:show": "Ctrl+Shift+X",
        "ball:hide": "",
    }), encoding="utf-8")
    r = get_shortcuts()["shortcuts"]
    assert "ball:show" not in r and "ball:hide" not in r
    assert r["panel"] == "Ctrl+Space"
    # 下次整表保存后 ball 条目自然消失
    set_shortcuts(r)
    ondisk = json.loads(target.read_text(encoding="utf-8"))
    assert "ball:show" not in ondisk and "ball:hide" not in ondisk


def test_invalid_slot_key_rejected():
    with pytest.raises(ShortcutError) as ei:
        set_shortcuts({"foo:bar": "Ctrl+1"})
    assert ei.value.code == "SHORTCUT_INVALID"


def test_invalid_combo_rejected():
    # 纯修饰键 / 顺序错误 / 小写 / 非法键 / 不支持的键 仍拒绝
    for bad in ("Ctrl", "Alt", "Shift", "Ctrl+Alt", "Ctrl+", "ctrl+1",
                "Ctrl+ctrl+A", "Ctrl+F13", "Ctrl+!", "Shift+Ctrl+K", "F13", "A B"):
        with pytest.raises(ShortcutError):
            set_shortcuts({"panel": bad})
    # 空串（显式停用）合法
    assert set_shortcuts({"panel": ""})["ok"] is True


def test_valid_combo_variants_accepted():
    # 任意键或组合（Ctrl 非必须；修饰键顺序固定 Ctrl<Alt<Shift）
    for good in ("Ctrl+Space", "Ctrl+1", "Ctrl+Alt+K", "Ctrl+Shift+9",
                 "Ctrl+Alt+Shift+F5", "Ctrl+A",
                 "K", "F5", "Space", "1", "Shift+K", "Alt+1", "Alt+Shift+P"):
        assert set_shortcuts({"panel": good})["ok"] is True


def test_corrupt_file_rejected_on_get():
    target = shortcut_service._CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(ShortcutError) as ei:
        get_shortcuts()
    assert ei.value.code == "SHORTCUT_CORRUPT"


def test_set_non_dict_rejected():
    with pytest.raises(ShortcutError):
        set_shortcuts(None)
