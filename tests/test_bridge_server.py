"""tests/test_bridge_server.py：桥接服务层（v2.1.4 stdlib HTTP + SSE）回归。

覆盖：
  - BridgeBus：注册 / 同步调用 / 未知命令 / 业务错误传播 / 事件广播到订阅队列
  - HTTP 层：/api/ping、/api/token、/api/rpc（token 鉴权 + ack/err 信封）
  - 静态托管：index.html + SPA 兜底（未知前端路由回 index.html）

背景：v2.1.4 把 FastAPI + uvicorn + WebSocket 整套换成标准库实现，这层协议必须锁住，
      否则前端 sendCommand 会在无真机打包的情况下静默崩掉。
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bridge.server import BridgeBus, BridgeError, make_server, serve_in_thread

TOKEN = "t0ken-for-test"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# --------------------------------------------------------------------------- bus

def test_bus_registers_and_calls_handler():
    bus = BridgeBus()

    async def handler(payload, _ws):
        return {"got": payload.get("x")}

    bus.register("t.echo", handler)
    assert bus.call("t.echo", {"x": 1}) == {"got": 1}


def test_bus_unknown_command_raises_not_found():
    bus = BridgeBus()
    with pytest.raises(BridgeError) as ei:
        bus.call("nope.not.here", {})
    assert ei.value.code == "NOT_FOUND"


def test_bus_propagates_business_error():
    bus = BridgeBus()

    async def boom(_p, _ws):
        raise BridgeError("MENU_NOT_FOUND", "菜单不存在")

    bus.register("t.boom", boom)
    with pytest.raises(BridgeError) as ei:
        bus.call("t.boom", {})
    assert ei.value.code == "MENU_NOT_FOUND"


def test_bus_broadcast_reaches_subscribers():
    import asyncio

    bus = BridgeBus()
    q = bus.subscribe()
    asyncio.run(bus.broadcast("menu.changed", {"menus": []}))
    frame = q.get_nowait()
    assert frame["type"] == "menu.changed"
    assert frame["payload"] == {"menus": []}
    bus.unsubscribe(q)
    asyncio.run(bus.broadcast("menu.changed", {"menus": [1]}))
    assert q.qsize() == 0  # 退订后不再收到


# --------------------------------------------------------------------------- http

@pytest.fixture()
def server(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")

    bus = BridgeBus()

    async def echo(payload, _ws):
        return {"echo": payload}

    async def fail(_p, _ws):
        raise BridgeError("MENU_NOT_FOUND", "菜单不存在")

    bus.register("echo", echo)
    bus.register("t.fail", fail)

    port = _free_port()
    srv = make_server(dist, port, bus, lambda: TOKEN, lambda t: t == TOKEN)
    serve_in_thread(srv)
    _server_bus[:] = [bus]  # 供 SSE 用例跨 fixture 触发广播
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()


def _rpc(base: str, cmd: str, payload: dict, token: str | None = TOKEN):
    body = json.dumps({"v": 1, "id": "t1", "type": cmd, "payload": payload}).encode()
    req = urllib.request.Request(f"{base}/api/rpc", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Bridge-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def test_http_ping_and_token(server: str):
    with urllib.request.urlopen(f"{server}/api/ping", timeout=5) as r:
        assert json.loads(r.read().decode())["ok"] is True
    with urllib.request.urlopen(f"{server}/api/token", timeout=5) as r:
        assert json.loads(r.read().decode())["token"] == TOKEN


def test_http_rpc_ack_envelope(server: str):
    status, body = _rpc(server, "echo", {"msg": "hi"})
    assert status == 200
    assert body["id"] == "t1" and body["type"] == "ack"
    assert body["payload"]["echo"]["msg"] == "hi"


def test_http_rpc_requires_token(server: str):
    status, _ = _rpc(server, "echo", {}, token=None)
    assert status == 401
    status, _ = _rpc(server, "echo", {}, token="wrong")
    assert status == 401


def test_http_rpc_business_error_is_err_envelope(server: str):
    status, body = _rpc(server, "t.fail", {})
    assert status == 200
    assert body["type"] == "err" and body["payload"]["code"] == "MENU_NOT_FOUND"


def test_http_rpc_unknown_command(server: str):
    status, body = _rpc(server, "no.such", {})
    assert status == 200
    assert body["payload"]["code"] == "NOT_FOUND"


def test_static_assets_and_spa_fallback(server: str):
    with urllib.request.urlopen(f"{server}/", timeout=5) as r:
        assert b"shell" in r.read()
        assert r.headers.get("Cache-Control") == "no-cache"
    # 带内容哈希的 assets 走长缓存
    with urllib.request.urlopen(f"{server}/assets/app-abc123.js", timeout=5) as r:
        assert "immutable" in (r.headers.get("Cache-Control") or "")
    # SPA 兜底：前端路由（不存在于磁盘）回 index.html
    with urllib.request.urlopen(f"{server}/tools/whatever", timeout=5) as r:
        assert b"shell" in r.read()


def test_static_blocks_path_traversal(server: str):
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(f"{server}/../bridge/main.py", timeout=5)
    assert ei.value.code in (400, 404)


def test_sse_stream_pushes_broadcast(server: str):
    """SSE 长连接：订阅后 broadcast 的帧应以 `data: {...}` 送达。"""
    got: list[dict] = []
    ready = threading.Event()

    def reader() -> None:
        req = urllib.request.Request(f"{server}/api/events?token={TOKEN}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            ready.set()
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    got.append(json.loads(line[6:]))
                    return

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    assert ready.wait(5), "SSE 未建立"

    # 通过 RPC 触发一次广播（echo handler 不广播，这里直接拿 bus 引用）
    # → 用 /api/rpc 无副作用：改从 bus 侧触发（同一 server 实例）
    srv_bus = _server_bus[0]
    import asyncio

    asyncio.run(srv_bus.broadcast("menu.changed", {"n": 1}))
    t.join(5)
    assert got and got[0]["type"] == "menu.changed" and got[0]["payload"] == {"n": 1}


_server_bus: list[BridgeBus] = []
