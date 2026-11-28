"""bridge/token.py 单测：密钥文件惰性生成/迁移/原子写/并发读改写。

v2.1.3：翻译功能移除后百度凭证段（get_baidu/set_baidu）已删除，对应测试一并移除。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bridge.token as token_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """把密钥文件路径指到临时目录（旧文件不存在 → 迁移分支为 no-op），并清空 token 缓存。"""
    monkeypatch.setattr(token_mod, "_SECRETS_FILE", tmp_path / "config" / "bridge_secrets.json")
    monkeypatch.setattr(token_mod, "_LEGACY_TOKEN_FILE", tmp_path / "config" / "bridge_token.json")
    token_mod._TOKEN["value"] = ""
    yield


def test_token_generated_hex64_and_validated():
    t = token_mod.get_token()
    assert len(t) == 64 and all(c in "0123456789abcdef" for c in t)
    assert token_mod.validate(t) is True
    assert token_mod.validate("") is False
    assert token_mod.validate("wrong") is False
    # 缓存内稳定
    assert token_mod.get_token() == t


def test_token_persisted_across_cache_clear():
    t1 = token_mod.get_token()
    token_mod._TOKEN["value"] = ""  # 模拟进程重启（内存缓存丢失）
    t2 = token_mod.get_token()
    assert t1 == t2  # 从文件读回，不重新生成
    data = json.loads(token_mod._SECRETS_FILE.read_text(encoding="utf-8"))
    assert data["token"] == t1


def test_corrupt_secrets_file_recovers_without_crash():
    token_mod._SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    token_mod._SECRETS_FILE.write_text("{broken json", encoding="utf-8")
    t = token_mod.get_token()  # 读失败 → {} → 重新生成，不抛
    assert len(t) == 64
    # 文件被原子写回为合法 JSON
    json.loads(token_mod._SECRETS_FILE.read_text(encoding="utf-8"))


def test_legacy_token_file_migrated():
    """旧 config/bridge_token.json 的 token 惰性并入统一密钥文件。"""
    legacy = token_mod._LEGACY_TOKEN_FILE
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"token": "legacy-token-abc"}), encoding="utf-8")
    assert token_mod.get_token() == "legacy-token-abc"
    data = json.loads(token_mod._SECRETS_FILE.read_text(encoding="utf-8"))
    assert data["token"] == "legacy-token-abc"
