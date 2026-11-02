"""翻译 service：包 fanyi.py（百度翻译，阻塞 HTTP → worker 线程），结果走广播。

设计原则：
  - transport-agnostic：只依赖一个 broadcast(event, payload) 回调，
    由 bridge 接到 WS；app.py 旧版可接到 Text.insert。
  - 阻塞 I/O 在 daemon 线程里跑，不卡调用方。
  - 1:1 复刻 fanyi.py.translate_text 行为（含"首字符自动定方向"与"凭证缺失返回提示"）。

事件（与 docs 方案 E11/E12 对齐）：
  translate.result { req_id, text, ok }      正常译文 / 友好提示
  translate.error  { req_id, message }       未捕获异常（网络/依赖缺失）
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

# fanyi.py 在凭证缺失时返回的提示前缀（用于 ok 判定，1:1 复刻旧行为）
_OK_PREFIXES = ("未配置", "Error", "翻译出错")


class TranslateService:
    def __init__(self, broadcast: Callable[[str, dict], None]):
        self._broadcast = broadcast

    def run(self, req_id: str, text: str, from_lang: str = "auto", to_lang: str = "auto") -> None:
        """后台翻译。text 空则直接回 result(ok=False)。
        from_lang/to_lang 仅为显式语义；fanyi.translate_text 内部按首字符定方向，
        此处 1:1 透传，保持与旧版一致。"""
        text = (text or "").strip()
        if not text:
            self._broadcast("translate.result",
                            {"req_id": req_id, "text": "", "ok": False})
            return

        def _worker():
            try:
                # 延迟 import：避免凭证缺失/依赖缺失在 service 构造期炸
                import fanyi
                result = fanyi.translate_text(text, from_lang=from_lang, to_lang=to_lang)
                ok = not any(str(result).startswith(p) for p in _OK_PREFIXES)
                self._broadcast("translate.result",
                                {"req_id": req_id, "text": str(result), "ok": ok})
            except Exception as e:  # 网络 / requests 缺失 / 响应格式变化
                self._broadcast("translate.error",
                                {"req_id": req_id, "message": f"翻译出错：{e}"})

        threading.Thread(target=_worker, daemon=True).start()
