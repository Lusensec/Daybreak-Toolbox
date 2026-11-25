"""tests/test_ws_bus.py：WS 总线 FIFO 派发（慢 handler 不阻塞读帧）。

回归背景：旧版 handle_inbound 内联 await handler —— 一条 60s 的 shell.run
会阻塞同连接读帧，后续命令全部堆积 → 前端 15s 预算下连环假超时。
新版：帧「校验 + 入队」即返回，handler 由每连接 worker 按到达顺序串行执行。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.ws import BridgeError, WsBus  # noqa: E402


class FakeWs:
    """最小 WebSocket 替身：仅记录发出的帧。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def test_fifo_dispatch_keeps_receive_loop_free():
    """慢 handler 运行中，handle_inbound 对后续帧即时返回（不内联等待）。"""

    async def scenario() -> None:
        bus = WsBus()
        order: list[str] = []

        async def slow(p, _ws):
            await asyncio.sleep(0.2)
            order.append("slow")
            return {"tag": "slow"}

        async def fast(p, _ws):
            order.append("fast")
            return {"tag": "fast"}

        bus.register("slow", slow)
        bus.register("fast", fast)
        ws = FakeWs()

        await bus.handle_inbound(ws, json.dumps({"id": "1", "type": "slow", "payload": {}}))
        await asyncio.sleep(0.01)  # slow 尚未完成
        await bus.handle_inbound(ws, json.dumps({"id": "2", "type": "fast", "payload": {}}))
        # 内联旧版此刻才会阻塞；FIFO 版两条都已入队，handle_inbound 早已返回
        assert "slow" not in order, "handle_inbound 应已返回（slow 仍在 worker 中运行）"
        await asyncio.sleep(0.4)
        assert order == ["slow", "fast"], f"FIFO 顺序错乱: {order}"
        acks = [m for m in ws.sent if m.get("type") == "ack"]
        assert [m.get("id") for m in acks] == ["1", "2"]

    asyncio.run(scenario())


def test_unknown_type_inline_err():
    async def scenario() -> None:
        bus = WsBus()
        ws = FakeWs()
        await bus.handle_inbound(ws, json.dumps({"id": "x", "type": "nope", "payload": {}}))
        assert ws.sent and ws.sent[0]["type"] == "err" and ws.sent[0]["payload"]["code"] == "NOT_FOUND"

    asyncio.run(scenario())


def test_bridge_error_maps_to_err():
    async def scenario() -> None:
        bus = WsBus()

        async def bad(p, _ws):
            raise BridgeError("SHELL_NOT_FOUND", "missing")

        bus.register("bad", bad)
        ws = FakeWs()
        await bus.handle_inbound(ws, json.dumps({"id": "1", "type": "bad", "payload": {}}))
        await asyncio.sleep(0.05)  # worker 处理
        err = [m for m in ws.sent if m.get("type") == "err"]
        assert err and err[0]["payload"]["code"] == "SHELL_NOT_FOUND"

    asyncio.run(scenario())


def test_detach_cancels_worker():
    async def scenario() -> None:
        bus = WsBus()

        async def slow(p, _ws):
            await asyncio.sleep(5)
            return {}

        bus.register("slow", slow)
        ws = FakeWs()
        await bus.handle_inbound(ws, json.dumps({"id": "1", "type": "slow", "payload": {}}))
        bus.detach(ws)  # 连接关闭：worker 取消，队列丢弃
        await asyncio.sleep(0.05)
        w = bus._workers.get(ws)
        assert w is None or w.cancelled()
        assert ws not in bus._queues

    asyncio.run(scenario())
