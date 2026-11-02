"""乱码修复 service：包 encryption.utf8_decode（外部 ASP 服务，阻塞 HTTP → worker 线程）。

与翻译同模式：阻塞 I/O 在 daemon 线程里跑，结果经 broadcast 回调回前端。
事件：codec.recover { text }
"""
from __future__ import annotations

import threading
from typing import Callable


class CodecService:
    def __init__(self, broadcast: Callable[[str, dict], None]):
        self._broadcast = broadcast

    def recover(self, text: str) -> None:
        """后台乱码修复。text 空则直接回空。"""
        text = (text or "").strip()
        if not text:
            self._broadcast("codec.recover", {"text": ""})
            return

        def _worker():
            try:
                import encryption  # 延迟 import（避免在 service 构造期拉起 requests/bs4）
                result = encryption.utf8_decode(text)
                self._broadcast("codec.recover", {"text": str(result)})
            except Exception as e:  # 网络 / 服务不可用 / 响应格式变化
                self._broadcast("codec.recover",
                                {"text": f"乱码修复出错：{e}"})

        threading.Thread(target=_worker, daemon=True).start()
