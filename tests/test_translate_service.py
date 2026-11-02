"""翻译 service 单测（纯 stdlib unittest，mock fanyi.translate_text 做确定性）。

覆盖三类：
  1. 空文本 → 同步广播 result(ok=False, text="")，不起线程
  2. 凭证缺失 → monkeypatch fanyi.BAIDU_FANYI_APP_ID=None，走"未配置"提示，ok=False
  3. 正常译文 → monkeypatch fanyi.translate_text 返回固定译文，ok=True

运行：python tests\\test_translate_service.py
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fanyi  # noqa: E402
from bridge.translate_service import TranslateService  # noqa: E402


class Collect:
    """线程安全的事件收集器：broadcast(event, payload) → 记录 + 置 Event。"""
    def __init__(self):
        self.events = []
        self._ev = threading.Event()

    def __call__(self, event, payload):
        self.events.append((event, payload))
        self._ev.set()

    def wait(self, timeout=5.0):
        return self._ev.wait(timeout)


def _set_translate(fn):
    """临时替换 fanyi.translate_text，返回恢复函数。"""
    original = fanyi.translate_text
    fanyi.translate_text = fn
    return lambda: setattr(fanyi, "translate_text", original)


class TestTranslateService(unittest.TestCase):

    def test_empty_text_sync_result(self):
        c = Collect()
        svc = TranslateService(c)
        # 空文本：同步广播，立即返回（无需等线程）
        svc.run("r1", "   ")
        self.assertTrue(c.events)
        event, payload = c.events[0]
        self.assertEqual(event, "translate.result")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["text"], "")

    def test_missing_credentials(self):
        # 强制凭证缺失 → 走"未配置"提示分支（真实 fanyi 行为，确定性）
        restore = _set_translate(fanyi.translate_text)
        _id, _secret = fanyi.BAIDU_FANYI_APP_ID, fanyi.BAIDU_FANYI_SECRET_KEY
        fanyi.BAIDU_FANYI_APP_ID = None
        fanyi.BAIDU_FANYI_SECRET_KEY = None
        try:
            c = Collect()
            svc = TranslateService(c)
            svc.run("r2", "hello")
            self.assertTrue(c.wait(5), "翻译线程未广播")
            result = [p for e, p in c.events if e == "translate.result"]
            self.assertTrue(result)
            self.assertFalse(result[0]["ok"])
            self.assertIn("未配置", result[0]["text"])
        finally:
            fanyi.BAIDU_FANYI_APP_ID, fanyi.BAIDU_FANYI_SECRET_KEY = _id, _secret
            restore()

    def test_normal_translation(self):
        # mock 成功返回译文
        restore = _set_translate(lambda text, from_lang="zh", to_lang="en": "Hello")
        try:
            c = Collect()
            svc = TranslateService(c)
            svc.run("r3", "你好")
            self.assertTrue(c.wait(5))
            result = [p for e, p in c.events if e == "translate.result"]
            self.assertTrue(result)
            self.assertTrue(result[0]["ok"])
            self.assertEqual(result[0]["text"], "Hello")
            self.assertEqual(result[0]["req_id"], "r3")
        finally:
            restore()

    def test_network_exception_broadcasts_error(self):
        # mock 抛异常（模拟网络错误）→ translate.error
        def _boom(text, **kw):
            raise RuntimeError("network unreachable")
        restore = _set_translate(_boom)
        try:
            c = Collect()
            svc = TranslateService(c)
            svc.run("r4", "test")
            self.assertTrue(c.wait(5))
            err = [p for e, p in c.events if e == "translate.error"]
            self.assertTrue(err)
            self.assertIn("network unreachable", err[0]["message"])
        finally:
            restore()


if __name__ == "__main__":
    unittest.main(verbosity=2)
