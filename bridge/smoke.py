"""桥接冒烟脚本（v2.1.4：HTTP + SSE 版，对应 bridge/server.py）。

用法：
  1) 终端 A：python -m bridge.main          （起服务，日志里会打印端口）
  2) 终端 B：python -m bridge.smoke         （自检）

输出 SMOKE_OK 即通过。校验项：
  - GET  /api/ping          健康检查（无需 token）
  - GET  /api/token         同源取 token
  - POST /api/rpc  echo     命令通路（带 token）
  - POST /api/rpc  app.env  真实业务命令（窗口形态探测字段）
  - 无 token / 错 token     必须 401
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge import token as _token_mod  # noqa: E402

API_BASE = "http://127.0.0.1:8765"


def _post_rpc(cmd: str, payload: dict, token: str = "") -> tuple[int, dict]:
    body = json.dumps({"v": 1, "id": f"smoke-{cmd}", "type": cmd, "payload": payload}).encode()
    req = urllib.request.Request(f"{API_BASE}/api/rpc", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Bridge-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def check_ping() -> None:
    with urllib.request.urlopen(f"{API_BASE}/api/ping", timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200 and body.get("ok") is True, f"unexpected {body}"
    print("[smoke] GET /api/ping OK")


def check_token() -> str:
    with urllib.request.urlopen(f"{API_BASE}/api/token", timeout=5) as resp:
        tok = json.loads(resp.read().decode("utf-8")).get("token") or ""
    assert tok and _token_mod.validate(tok), "token 与本地密钥文件不一致"
    print("[smoke] GET /api/token OK")
    return tok


def check_auth() -> None:
    status, _ = _post_rpc("echo", {"msg": "x"}, "")
    assert status == 401, f"无 token 应 401，实际 {status}"
    status, _ = _post_rpc("echo", {"msg": "x"}, "wrong")
    assert status == 401, f"错 token 应 401，实际 {status}"
    print("[smoke] token 鉴权（401）OK")


def check_rpc(tok: str) -> None:
    status, body = _post_rpc("echo", {"msg": "hi"}, tok)
    assert status == 200, f"echo expected 200, got {status} {body}"
    assert body.get("type") == "ack", f"expected ack, got {body}"
    assert body.get("payload", {}).get("echo", {}).get("msg") == "hi", f"bad echo {body}"
    print("[smoke] POST /api/rpc echo OK")

    status, body = _post_rpc("app.env", {}, tok)
    assert status == 200 and body.get("type") == "ack", f"app.env failed: {status} {body}"
    assert "version" in body.get("payload", {}), f"app.env missing version: {body}"
    print(f"[smoke] POST /api/rpc app.env OK (v{body['payload']['version']})")

    status, body = _post_rpc("no.such.command", {}, tok)
    assert status == 200 and body.get("type") == "err", f"未知命令应回 err 信封，实际 {status} {body}"
    assert body["payload"]["code"] == "NOT_FOUND", f"unexpected {body}"
    print("[smoke] 未知命令 NOT_FOUND OK")


def main() -> None:
    print("[smoke] running…")
    check_ping()
    tok = check_token()
    check_auth()
    check_rpc(tok)
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
