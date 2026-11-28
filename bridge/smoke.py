"""桥接冒烟脚本：验证 token 鉴权 + /api/ping + /ws echo 全链路。

用法：
  1) 终端 A：python -m bridge.main          （起服务）
  2) 终端 B：python -m bridge.smoke         （自检）

输出 SMOKE_OK 即通过。
"""
from __future__ import annotations

import json
import sys
import urllib.request

# 依赖 websockets 库；未装则退回 stdlib 简易检查
try:
    import websockets  # type: ignore
    HAS_WS = True
except ImportError:
    HAS_WS = False


API_BASE = "http://127.0.0.1:8765"
# 统一密钥文件（bridge token）；兼容旧 bridge_token.json
from bridge import token as _token_mod  # noqa: E402

TOKEN_FILE = _token_mod._SECRETS_FILE


def _load_token() -> str:
    return _token_mod.get_token()


def check_rest() -> None:
    tok = _load_token()
    req = urllib.request.Request(
        f"{API_BASE}/api/ping",
        headers={"Authorization": f"Bearer {tok}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200, f"expected 200, got {resp.status}"
        assert body.get("ok") is True, f"unexpected body {body}"
    print("[smoke] REST /api/ping OK")

    # 错误 token 必须 401
    bad_req = urllib.request.Request(
        f"{API_BASE}/api/ping",
        headers={"Authorization": "Bearer wrong_token"},
    )
    try:
        urllib.request.urlopen(bad_req, timeout=5)
        raise AssertionError("wrong token should be rejected (401)")
    except Exception as e:
        # URLError / HTTPError(401) 都算通过
        print(f"[smoke] REST 401 on bad token OK ({type(e).__name__})")


async def check_ws() -> None:
    import asyncio
    tok = _load_token()
    async with websockets.connect(f"ws://127.0.0.1:8765/ws?token={tok}") as ws:
        # 收 connected 事件
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert first.get("type") == "connected", f"expected connected, got {first}"
        print("[smoke] WS connected OK")

        # 发 echo 请求
        req_id = "smoke-1"
        await ws.send(json.dumps({"v": 1, "id": req_id, "type": "echo",
                                  "payload": {"msg": "hi"}}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp.get("id") == req_id, f"id mismatch: {resp}"
        assert resp.get("type") == "ack", f"expected ack, got {resp}"
        assert resp.get("payload", {}).get("echo", {}).get("msg") == "hi"
        print("[smoke] WS echo OK")


def main() -> None:
    print("[smoke] running…")
    check_rest()
    if HAS_WS:
        import asyncio
        asyncio.run(check_ws())
    else:
        print("[smoke] WS check skipped (websockets 未装；pip install websockets 后补测)")
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
