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


def test_invalid_slot_key_rejected():
    with pytest.raises(ShortcutError) as ei:
        set_shortcuts({"foo:bar": "Ctrl+1"})
    assert ei.value.code == "SHORTCUT_INVALID"


def test_invalid_combo_rejected():
    for bad in ("A", "Ctrl", "Shift+K", "Alt+1", "Ctrl+Alt+Shift+Meta",
                "ctrl+1", "Ctrl+ctrl+A", "Ctrl+F13", "Ctrl+!"):
        with pytest.raises(ShortcutError):
            set_shortcuts({"panel": bad})
    # 空串（显式停用）合法
    assert set_shortcuts({"panel": ""})["ok"] is True


def test_valid_combo_variants_accepted():
    for good in ("Ctrl+Space", "Ctrl+1", "Ctrl+Alt+K", "Ctrl+Shift+9",
                 "Ctrl+Alt+Shift+F5", "Ctrl+A"):
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
