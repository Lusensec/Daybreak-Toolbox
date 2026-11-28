"""破晓·工具箱 —— 内置桥接服务（v2.1.4：stdlib HTTP + SSE，不再依赖 FastAPI/uvicorn/WebSocket）。

为什么换掉 FastAPI + uvicorn + websockets：
  功能面瘦身后（v2.1.3 删掉 5 个面板）桥接只剩 ~39 条本机命令，仍是「单进程、单客户端、
  127.0.0.1、请求-响应 + 少量事件推送」的极简模型。为这点负载常驻一整套 ASGI 栈代价过高：
  fastapi/starlette/pydantic(+core)/uvicorn/websockets/anyio/watchfiles/httptools/h11/click
  在安装包内合计约 12–14MB，且启动时多出 uvicorn 初始化 + 端口就绪轮询。
  改用标准库后：零第三方依赖、冷启动更快、体积直接省下这一整块。

协议（保持与旧 WS 一致的信封，前端几乎零改动）：
  POST /api/rpc        {"id","type","payload"}  → {"v":1,"id","type":"ack|err","payload":{...}}
  GET  /api/events     SSE 长连接，每帧 "data: {<事件信封>}\\n\\n"（含心跳注释行保活）
  GET  /api/token      同源取 token（本地桌面应用，供前端 X-Bridge-Token 使用）
  GET  /api/ping       自检
  GET  /*              web/dist 静态资源 + SPA 兜底（未知路径回 index.html 交给 react-router）

线程模型：
  ThreadingHTTPServer（每请求一线程，daemon_threads）
    ├─ /api/rpc → BridgeBus.call()：run_coroutine_threadsafe 到常驻 asyncio loop 线程，
    │             同步等待结果（handler 内部 IO 走 asyncio.to_thread，不占 loop）
    └─ /api/events → 每连接一个 queue.Queue，broadcast() 只做 put_nowait（不阻塞）
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

MAX_BODY_BYTES = 8 * 1024 * 1024  # 请求体上限（工具网格/菜单树等大对象留足余量）
CALL_TIMEOUT_S = 600.0            # 单条命令兜底超时（前端另有自己的预算，这里只防线程永久挂住）
SSE_HEARTBEAT_S = 15.0            # SSE 心跳（防中间层/浏览器判定空闲断连）

# 错误码（与旧 ws.py 保持一致，前端已有映射文案）
E_TOKEN_INVALID = "TOKEN_INVALID"
E_FRAME_TOO_LARGE = "FRAME_TOO_LARGE"
E_INTERNAL = "INTERNAL"
E_NOT_FOUND = "NOT_FOUND"
E_BUSY = "BRIDGE_BUSY"

# 高频/长事务窗口几何命令：不参与串行锁（顶栏拖拽 60fps 连发，排队会让拖动变卡；
# 浮动窗口创建/拖动会阻塞到用户松手，绝不能占住全局写锁）
UNTETHERED_COMMANDS = frozenset({
    "window.move", "window.get_rect", "window.maximize", "window.minimize",
    "window.set_background", "window.drag",
    "float.create", "float.move", "float.maximize", "float.drag_begin", "float.resize", "float.focus",
    "browser.attach_float", "browser.set_float_rect",
})


class BridgeError(Exception):
    """业务层错误，携带错误码，由 server 层映射为 err 响应。"""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class BridgeBus:
    """命令注册表 + 事件广播（进程内单例，由 main.py 持有）。"""

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._subs: "set[queue.Queue]" = set()
        self._subs_lock = threading.Lock()
        # 写操作（菜单/设置/快捷键）串行化：旧架构靠「单连接 FIFO」天然串行，
        # 换 HTTP 后每请求独立线程，必须显式加锁否则 config.json 并发写会互相覆盖。
        self._serial = threading.RLock()

    # ---- 注册 / 生命周期 ----
    def register(self, type_name: str, handler: Callable) -> None:
        """handler(payload, _ws) -> dict（async）。第二参数为兼容旧签名保留，恒为 None。"""
        self._handlers[type_name] = handler

    def has(self, type_name: str) -> bool:
        return type_name in self._handlers

    def start_loop(self) -> None:
        """起常驻 asyncio loop 线程（handler 全是 async，需要事件循环跑 to_thread）。"""
        if self._loop_thread is not None and self._loop_thread.is_alive():
            return
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run, name="bridge-loop", daemon=True)
        t.start()
        self._loop = loop
        self._loop_thread = t

    # ---- 请求-响应（同步，供 HTTP 线程调用）----
    def call(self, type_name: str, payload: dict, timeout: float = CALL_TIMEOUT_S) -> dict:
        handler = self._handlers.get(type_name)
        if handler is None:
            raise BridgeError(E_NOT_FOUND, f"unknown type {type_name}")
        self.start_loop()
        coro = handler(payload if isinstance(payload, dict) else {}, None)
        if type_name in UNTETHERED_COMMANDS:
            return self._await(coro, timeout)
        with self._serial:
            return self._await(coro, timeout)

    def _await(self, coro, timeout: float) -> dict:
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]
        try:
            result = fut.result(timeout)
        except TimeoutError:
            fut.cancel()
            raise BridgeError(E_INTERNAL, f"command timeout after {timeout:.0f}s")
        return result if isinstance(result, dict) else {}

    # ---- 事件广播（SSE）----
    def subscribe(self) -> "queue.Queue":
        q: "queue.Queue" = queue.Queue(maxsize=256)
        with self._subs_lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: "queue.Queue") -> None:
        with self._subs_lock:
            self._subs.discard(q)

    async def broadcast(self, event: str, payload: dict) -> None:
        self.emit(event, payload)

    def emit(self, event: str, payload: dict) -> None:
        """同步广播（线程安全）：供 UI 线程回调（如浮动窗口关闭）直接调用，
        无需回到 asyncio loop 里 await。"""
        frame = {"v": 1, "type": event, "payload": payload}
        with self._subs_lock:
            targets = list(self._subs)
        for q in targets:
            try:
                q.put_nowait(frame)
            except queue.Full:
                # 慢客户端（或已断开）→ 丢弃该帧，绝不阻塞调用方
                pass


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "DaybreakBridge/2.1.4"
    protocol_version = "HTTP/1.1"

    # 由 factory 注入
    bus: BridgeBus = None        # type: ignore[assignment]
    dist: Optional[Path] = None
    token_getter: Callable[[], str] = staticmethod(lambda: "")
    token_check: Callable[[str], bool] = staticmethod(lambda _t: False)

    # ---- 日志：静音（避免每个请求一行 stderr 污染 daybreak.log）----
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    # ---- 通用响应 ----
    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        # dev（vite 5173 → 8765）跨源需要；仅监听 127.0.0.1，无外部可达面
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _authed(self) -> bool:
        tok = self.headers.get("X-Bridge-Token") or self._query_token() or ""
        return bool(tok) and self.token_check(tok)

    def _query_token(self) -> str:
        qs = urlparse(self.path).query
        for part in qs.split("&"):
            if part.startswith("token="):
                return part[6:]
        return ""

    # ---- OPTIONS（dev 预检）----
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- RPC ----
    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/rpc":
            self._send_json({"ok": False, "code": E_NOT_FOUND}, status=404)
            return
        if not self._authed():
            self._send_json({"v": 1, "type": "err", "payload": {"code": E_TOKEN_INVALID}}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json({"v": 1, "type": "err",
                             "payload": {"code": E_FRAME_TOO_LARGE}}, status=413)
            return
        raw = self.rfile.read(length)
        try:
            msg = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"v": 1, "type": "err", "payload": {"code": E_INTERNAL, "message": "bad json"}},
                            status=400)
            return
        req_id = msg.get("id") or str(uuid.uuid4())
        mtype = str(msg.get("type") or "")
        payload = msg.get("payload") or {}
        try:
            result = self.bus.call(mtype, payload)
            self._send_json({"v": 1, "id": req_id, "type": "ack", "payload": result})
        except BridgeError as e:
            self._send_json({"v": 1, "id": req_id, "type": "err",
                             "payload": {"code": e.code, "message": e.message}})
        except Exception as e:  # noqa: BLE001 —— 任何 handler 异常都回结构化错误
            self._send_json({"v": 1, "id": req_id, "type": "err",
                             "payload": {"code": E_INTERNAL, "message": str(e)}})

    # ---- 事件流（SSE）----
    def _serve_events(self) -> None:
        if not self._authed():
            self._send_json({"ok": False, "code": E_TOKEN_INVALID}, status=401)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.bus.subscribe()
        try:
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            while True:
                try:
                    frame = q.get(timeout=SSE_HEARTBEAT_S)
                    data = json.dumps(frame, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.bus.unsubscribe(q)

    # ---- GET ----
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/events":
            self._serve_events()
            return
        if path == "/api/ping":
            self._send_json({"ok": True})
            return
        if path == "/api/token":
            self._send_json({"token": self.token_getter()})
            return
        if path.startswith("/api/"):
            self._send_json({"ok": False, "code": E_NOT_FOUND}, status=404)
            return
        self._serve_static(path)

    def _serve_static(self, path: str) -> None:
        dist = self.dist
        if dist is None:
            self._send_json({"ok": False, "message": "web/dist not found"}, status=404)
            return
        rel = path.lstrip("/") or "index.html"
        target = (dist / rel).resolve()
        try:
            target.relative_to(dist.resolve())  # 防目录穿越
        except ValueError:
            self._send_json({"ok": False, "code": E_NOT_FOUND}, status=404)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            target = dist / "index.html"  # SPA 兜底（/tools/xxx 等前端路由）
        if not target.is_file():
            self._send_json({"ok": False, "message": "index.html missing"}, status=404)
            return

        ctype = self._guess_type(target)
        try:
            body = target.read_bytes()
        except OSError:
            self._send_json({"ok": False, "message": "read error"}, status=500)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 资源名带内容哈希 → 长缓存；index.html 必须每次校验（否则升级后仍跑旧壳）
        if "/assets/" in path:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _guess_type(path: Path) -> str:
        import mimetypes

        ctype, _ = mimetypes.guess_type(str(path))
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        return ctype


def make_server(dist: Optional[Path], port: int, bus: BridgeBus,
                token_getter: Callable[[], str],
                token_check: Callable[[str], bool]) -> ThreadingHTTPServer:
    """构建并返回（未启动的）HTTP 服务；调用方负责 serve_forever 线程。"""

    class Handler(_Handler):
        pass

    Handler.bus = bus
    Handler.dist = dist
    Handler.token_getter = staticmethod(token_getter)
    Handler.token_check = staticmethod(token_check)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    return srv


def serve_in_thread(srv: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=srv.serve_forever, name="bridge-http", daemon=True)
    t.start()
    return t


def wait_ready(port: int, timeout: float = 5.0) -> bool:
    """轮询 /api/ping 确认服务已就绪（替代旧版 uvicorn server.started 判定）。"""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.02)
    return False
