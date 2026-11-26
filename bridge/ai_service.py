"""AI service：包 ai_config.chat_once（配置驱动、每次读盘 → 无需重启即时生效）。

设计（Phase 3.4 → 配置驱动升级）：
  - 不再依赖 Chat_AI.ai_main / fun 的模块导入期缓存（那会导致「新增模型需重启」）；
    直接走 ai_config.chat_once，每次请求实时读取 config/ai.json，
    用户新增/修改模型与 API 后**立即生效**，无需重启。
  - 支持 5 个内置 + 任意自定义模型（kind: openai/zhipu/ollama）。
  - 阻塞 I/O 在 daemon 线程里跑，不卡调用方。
  - 按 session 维护历史（最近 20 轮），1:1 复刻旧版 global_history 语义。

事件：
  ai.result { session, msg_id, provider, text, ok }
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, List

from . import ai_config as _ai_config  # 相对导入（bridge 包内；worker 线程共用同一模块对象）

# 历史轮数上限的兜底默认；实际值每次请求从 ai_config.history_rounds() 动态读取（改配置即时生效）
_HISTORY_LIMIT = 20  # 轮（每轮 user+assistant 两条），仅作 history_rounds() 读失败时的兜底
_MAX_SESSIONS = 50   # 会话键上限（v2.0.12：托盘常驻数天，按插入序淘汰最旧会话防无界增长）


class AiService:
    def __init__(self, broadcast: Callable[[str, dict], None]):
        self._broadcast = broadcast
        self._hist: Dict[str, List[dict]] = {}
        self._lock = threading.Lock()

    def _prune_sessions_locked(self) -> None:
        """超出会话上限时淘汰最旧键（dict 保插入序；需持 self._lock 调用）。"""
        excess = len(self._hist) - _MAX_SESSIONS
        if excess <= 0:
            return
        for k in list(self._hist.keys())[:excess]:
            self._hist.pop(k, None)

    def _history(self, session: str) -> List[dict]:
        with self._lock:
            h = list(self._hist.get(session, []))
            # 读时也按当前轮数裁剪（用户可能调低历史轮数，内存里旧历史随之失效）
            try:
                limit = _ai_config.history_rounds()
            except Exception:
                limit = _HISTORY_LIMIT
            if len(h) > limit * 2:
                h = h[-limit * 2:]
            return h

    def _append(self, session: str, user: str, assistant: str) -> None:
        with self._lock:
            if session in self._hist:
                del self._hist[session]  # 刷新 LRU 位置（复用最旧会话 → 变最新，不被淘汰）
            h = self._hist.setdefault(session, [])
            h.append({"role": "user", "content": user})
            h.append({"role": "assistant", "content": assistant})
            # 动态历史轮数：改「历史轮数」下拉后立即改变裁剪上限（每次 append 读盘）
            try:
                limit = _ai_config.history_rounds()
            except Exception:
                limit = _HISTORY_LIMIT
            if len(h) > limit * 2:
                del h[: len(h) - limit * 2]
            self._prune_sessions_locked()

    def clear(self, session: str) -> None:
        """会话清空（对应旧版「清空」按钮 / 重开会话）。"""
        with self._lock:
            self._hist.pop(session, None)

    def send(self, session: str, provider: str, text: str, msg_id: str = "") -> None:
        """后台调用 chat_once（配置驱动），结果广播 ai.result。text 空则直接回 ok=False。"""
        text = (text or "").strip()
        if not text:
            self._broadcast("ai.result", {"session": session, "msg_id": msg_id,
                                          "provider": provider, "text": "", "ok": False})
            return

        def _worker():
            try:
                res = _ai_config.chat_once(text, provider,
                                           history=self._history(session),
                                           temperature=0.3, timeout=60)
                ok = bool(res.get("ok"))
                content = str(res.get("text", ""))
                # 历史：仅成功时记 user+assistant（与旧版一致：失败不记历史）
                if ok:
                    self._append(session, text, content)
                self._broadcast("ai.result", {"session": session, "msg_id": msg_id,
                                               "provider": provider,
                                               "text": content, "ok": ok})
            except Exception as e:
                self._broadcast("ai.result", {"session": session, "msg_id": msg_id,
                                               "provider": provider,
                                               "text": f"AI 请求出错：{e}", "ok": False})

        threading.Thread(target=_worker, daemon=True).start()
