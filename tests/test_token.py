"""bridge/token.py 单测：密钥文件惰性生成/迁移/原子写/并发读改写（set_root 无关，monkeypatch 模块级路径隔离）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bridge.token as token_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """把 3 个文件路径指到临时目录（旧文件不存在 → 迁移分支为 no-op），并清空 token 缓存。"""
    monkeypatch.setattr(token_mod, "_SECRETS_FILE", tmp_path / "config" / "bridge_secrets.json")
    monkeypatch.setattr(token_mod, "_LEGACY_TOKEN_FILE", tmp_path / "config" / "bridge_token.json")
    monkeypatch.setattr(token_mod, "_LEGACY_BAIDU_PY", tmp_path / "config" / "baidu.py")
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


def test_baidu_roundtrip_preserves_token():
    tok = token_mod.get_token()
    r = token_mod.set_baidu("appid-x", "secret-y")
    assert r["ok"] and r["secret_key_configured"] is True
    assert token_mod.get_baidu() == {"app_id": "appid-x", "secret_key": "secret-y"}
    data = json.loads(token_mod._SECRETS_FILE.read_text(encoding="utf-8"))
    assert data["token"] == tok  # token 字段保留
    # 清空 secret（app_id 保留）
    r2 = token_mod.set_baidu("appid-x", "")
    assert r2["secret_key_configured"] is False
    assert token_mod.get_baidu() == {"app_id": "appid-x", "secret_key": ""}


def test_baidu_concurrent_read_modify_write_no_crash():
    """并发 get/set_baidu（读-改-写有锁 + 原子写）：无异常、无撕裂 JSON。"""
    import threading
    errors: list = []

    def worker(i: int) -> None:
        try:
            for j in range(20):
                token_mod.set_baidu(f"app-{i}-{j}", f"sec-{i}-{j}")
                token_mod.get_baidu()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    # 最终文件必须是合法 JSON（原子写保证）
    json.loads(token_mod._SECRETS_FILE.read_text(encoding="utf-8"))
