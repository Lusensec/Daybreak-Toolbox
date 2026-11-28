"""桥接密钥统一管理。

单一文件 config/bridge_secrets.json 存放（本地敏感信息，必须 gitignore，永不分发）：
  {
    "token":  "<32 字节 hex，桥接鉴权>"
  }

设计：
  - 启动时若无 token 则生成并写盘（0600，Windows 忽略权限）；存在则读取。
  - 迁移（一次性，惰性）：config/bridge_token.json（旧 token 单文件）→ 并入本文件的 token 字段；
    迁移完成后旧文件可安全删除。
  - 该文件必须加入 .gitignore。
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from pathlib import Path

# 项目根目录（bridge/ 的同级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SECRETS_FILE = _PROJECT_ROOT / "config" / "bridge_secrets.json"
_LEGACY_TOKEN_FILE = _PROJECT_ROOT / "config" / "bridge_token.json"

_TOKEN = {"value": ""}
# 密钥文件读改写锁：跨连接并发下保证「读-改-写」不互相吃到写了一半的文件
_IO_LOCK = threading.Lock()


def _write_secrets(data: dict) -> None:
    """原子写（临时文件 + os.replace）：
    崩溃/并发不会留下截断的 JSON（截断 → token 误判丢失重新生成 → 全客户端 401 重连）。"""
    _SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(_SECRETS_FILE.parent), prefix=".secrets_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _SECRETS_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    try:
        os.chmod(_SECRETS_FILE, 0o600)
    except OSError:
        # Windows 上 chmod 不强制，忽略
        pass


def _read_secrets() -> dict:
    """读取统一密钥文件；缺失/损坏返回 {}（不抛异常，由调用方决定生成或回退）。"""
    try:
        data = json.loads(_SECRETS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _migrate_legacy(data: dict) -> dict:
    """把旧 bridge_token.json 的 token 并入 data（就地），返回 data。"""
    if not str(data.get("token", "")).strip():
        try:
            legacy = json.loads(_LEGACY_TOKEN_FILE.read_text(encoding="utf-8"))
            t = str(legacy.get("token", "")).strip()
            if t:
                data["token"] = t
        except Exception:
            pass
    return data


def get_token() -> str:
    """返回当前生效的 bridge token（惰性生成 + 旧文件迁移 + 缓存）。"""
    if _TOKEN["value"]:
        return _TOKEN["value"]

    with _IO_LOCK:
        data = _read_secrets()
        had_token = bool(str(data.get("token", "")).strip())
        data = _migrate_legacy(data)
        token = str(data.get("token", "")).strip()
        if not token:
            token = secrets.token_hex(32)
            data["token"] = token
        # 旧文件内容已并入内存但未落盘 → 持久化
        if not had_token:
            _write_secrets(data)
        _TOKEN["value"] = token
    return token


def validate(token: str | None) -> bool:
    """校验客户端提供的 token（WS query / REST Bearer）。"""
    expected = get_token()
    if not token:
        return False
    return secrets.compare_digest(str(token), expected)
