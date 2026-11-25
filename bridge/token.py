"""桥接密钥统一管理。

单一文件 config/bridge_secrets.json 同时存放（本地敏感信息，必须 gitignore，永不分发）：
  {
    "token":  "<32 字节 hex，桥接鉴权>",
    "baidu":  { "app_id": "...", "secret_key": "..." }   # 百度翻译凭证（可缺省）
  }

设计：
  - 启动时若无 token 则生成并写盘（0600，Windows 忽略权限）；存在则读取。
  - 迁移（一次性，惰性）：
      * config/bridge_token.json（旧 token 单文件）→ 并入本文件的 token 字段；
      * config/baidu.py（旧 Python 常量模块）→ 正则解析后并入 baidu 字段。
    迁移完成后旧文件可安全删除（本模块不再读它们，baidu.py 仅作为迁移来源）。
  - 该文件必须加入 .gitignore。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from pathlib import Path

# 项目根目录（bridge/ 的同级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SECRETS_FILE = _PROJECT_ROOT / "config" / "bridge_secrets.json"
_LEGACY_TOKEN_FILE = _PROJECT_ROOT / "config" / "bridge_token.json"
_LEGACY_BAIDU_PY = _PROJECT_ROOT / "config" / "baidu.py"

_TOKEN = {"value": ""}
# 密钥文件读改写锁：跨连接并发（translate.get_creds / set_creds 等 handler + 翻译 worker）
# 下保证「读-改-写」不互相吃到写了一半的文件
_IO_LOCK = threading.Lock()


def _write_secrets(data: dict) -> None:
    """原子写（临时文件 + os.replace，与 shortcut/ssh/menu 配置同款）：
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


def _parse_legacy_baidu_py() -> dict | None:
    """正则解析旧 config/baidu.py 的两个常量（不 import，避免副作用）；无则 None。"""
    try:
        src = _LEGACY_BAIDU_PY.read_text(encoding="utf-8")
        app_m = re.search(r'BAIDU_FANYI_APP_ID\s*=\s*["\']([^"\']*)["\']', src)
        sec_m = re.search(r'BAIDU_FANYI_SECRET_KEY\s*=\s*["\']([^"\']*)["\']', src)
        app = (app_m.group(1).strip() if app_m else "")
        sec = (sec_m.group(1).strip() if sec_m else "")
        if app or sec:
            return {"app_id": app, "secret_key": sec}
    except Exception:
        pass
    return None


def _migrate_legacy(data: dict) -> dict:
    """把旧 bridge_token.json / baidu.py 的内容并入 data（就地），返回 data。"""
    changed = False
    if not str(data.get("token", "")).strip():
        try:
            legacy = json.loads(_LEGACY_TOKEN_FILE.read_text(encoding="utf-8"))
            t = str(legacy.get("token", "")).strip()
            if t:
                data["token"] = t
                changed = True
        except Exception:
            pass
    if not data.get("baidu"):
        b = _parse_legacy_baidu_py()
        if b:
            data["baidu"] = b
            changed = True
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
        # 旧文件内容（token / baidu）已并入内存但未落盘 → 持久化；token 已存在且 baidu 齐则不重写
        if not had_token or not data.get("baidu"):
            _write_secrets(data)
        _TOKEN["value"] = token
    return token


def validate(token: str | None) -> bool:
    """校验客户端提供的 token（WS query / REST Bearer）。"""
    expected = get_token()
    if not token:
        return False
    return secrets.compare_digest(str(token), expected)


# ---- 百度翻译凭证（与 bridge token 同文件存放）----

def get_baidu() -> dict:
    """返回 baidu 凭证 {app_id, secret_key}（未配置返回空 dict；惰性迁移旧 baidu.py）。"""
    with _IO_LOCK:
        data = _read_secrets()
        if not data.get("baidu") and _parse_legacy_baidu_py():
            data = _migrate_legacy(data)  # 并入旧 baidu 凭证，保留文件已有的 token
            _write_secrets(data)
        b = data.get("baidu") or {}
        return {"app_id": str(b.get("app_id", "")).strip(),
                "secret_key": str(b.get("secret_key", "")).strip()}


def set_baidu(app_id: str, secret_key: str) -> dict:
    """写入/更新 baidu 凭证（保留 token 字段；空值允许=清除该项）。"""
    get_token()  # 确保统一文件已建立（含 token 与旧文件迁移）
    with _IO_LOCK:
        data = _read_secrets()
        data["baidu"] = {"app_id": (app_id or "").strip(),
                          "secret_key": (secret_key or "").strip()}
        _write_secrets(data)
    return {"ok": True, "app_id": data["baidu"]["app_id"],
            "secret_key_configured": bool(data["baidu"]["secret_key"])}
