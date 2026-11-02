"""WebSocket 事件总线：连接注册表 + 请求-响应匹配 + 广播 + 帧上限。

前端协议信封（与 docs/React_TS_UI_重构方案.md §4.1 对齐）：
  请求  {"v":1,"id":"<uuid>","type":"<cmd>","payload":{...}}
  响应  {"v":1,"id":"<uuid>","type":"ack|err","payload":{...}}
  事件  {"v":1,"type":"<event>","payload":{...}}          （无 id）
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastapi import WebSocket

MAX_FRAME_BYTES = 512 * 1024  # 512KB 帧上限

# 错误码
E_TOKEN_INVALID = "TOKEN_INVALID"
E_FRAME_TOO_LARGE = "WS_FRAME_TOO_LARGE"
E_INTERNAL = "INTERNAL"
E_NOT_FOUND = "NOT_FOUND"


@dataclass
class WsBus:
    """WS 事件总线。

    职责：
    - 连接注册表（多客户端并存）
    - 请求-响应：按 id 匹配 ack/err
    - broadcast(event, payload)：向所有已认证客户端推事件
    - 帧上限：超过 MAX_FRAME_BYTES 拒收
    """
    token: str = ""
    _handlers: Dict[str, Any] = field(default_factory=dict)  # type -> async handler
    _clients: Dict[WebSocket, bool] = field(default_factory=dict)  # ws -> authenticated

    # ---- 命令注册 ----
    def register(self, type_name: str, handler) -> None:
        """handler(payload, ws) -> 返回 dict 作为 ack payload；抛 BridgeError 作为 err。"""
        self._handlers[type_name] = handler

    # ---- 广播 ----
    async def broadcast(self, event: str, payload: dict) -> None:
        frame = {"v": 1, "type": event, "payload": payload}
        text = json.dumps(frame, ensure_ascii=False)
        for ws in list(self._clients.keys()):
            try:
                await ws.send_text(text)
            except Exception:
                # 发送失败 → 移除连接（由 receive 循环的 disconnect 兜底）
                self._clients.pop(ws, None)

    async def send_to(self, ws: WebSocket, event: str, payload: dict) -> None:
        frame = {"v": 1, "type": event, "payload": payload}
        await ws.send_text(json.dumps(frame, ensure_ascii=False))

    # ---- 入站消息处理 ----
    async def handle_inbound(self, ws: WebSocket, raw: str) -> None:
        if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
            await self._reply(ws, str(uuid.uuid4()), "err", {"code": E_FRAME_TOO_LARGE})
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._reply(ws, str(uuid.uuid4()), "err", {"code": E_INTERNAL, "message": "bad json"})
            return

        req_id = msg.get("id")
        mtype = msg.get("type", "")
        payload = msg.get("payload") or {}

        handler = self._handlers.get(mtype)
        if handler is None:
            await self._reply(ws, req_id, "err", {"code": E_NOT_FOUND, "message": f"unknown type {mtype}"})
            return
        try:
            result = await handler(payload, ws)
            await self._reply(ws, req_id, "ack", result if isinstance(result, dict) else {})
        except BridgeError as e:
            await self._reply(ws, req_id, "err", {"code": e.code, "message": e.message})
        except Exception as e:  # noqa: BLE001
            await self._reply(ws, req_id, "err", {"code": E_INTERNAL, "message": str(e)})

    async def _reply(self, ws: WebSocket, req_id: Optional[str], mtype: str, payload: dict) -> None:
        frame: Dict[str, Any] = {"v": 1, "type": mtype, "payload": payload}
        if req_id is not None:
            frame["id"] = req_id
        try:
            await ws.send_text(json.dumps(frame, ensure_ascii=False))
        except Exception:
            self._clients.pop(ws, None)


class BridgeError(Exception):
    """业务层错误，携带错误码，被 ws.bus 捕获后映射为 err 响应。"""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
