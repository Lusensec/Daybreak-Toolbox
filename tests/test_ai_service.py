"""ai service 单测（配置驱动版：mock bridge.ai_config.chat_once，纯确定性）。

覆盖：
  1. 空文本 → 同步广播 result(ok=False, text="")，不起线程
  2. 正常 → chat_once 返回 ok=True，text 原样，广播 ai.result(ok=True)，历史追加
  3. 失败 → chat_once 返回 ok=False，广播 ai.result(ok=False)，历史不追加
  4. 异常 → chat_once 抛异常，ok=False + 错误信息
  5. 会话历史：同一 session 连续两次成功，第二次请求把第一次的 user/assistant 传入
  6. clear_session：清空后历史为空
  7. 自定义模型（如 "111"）也能走同一链路（provider 透传给 chat_once）

运行：python -m pytest tests/test_ai_service.py
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bridge.ai_service as ai_service  # noqa: E402
import bridge.ai_config as ai_config  # noqa: E402


class Collect:
    def __init__(self):
        self.events = []
        self._ev = threading.Event()

    def __call__(self, event, payload):
        self.events.append((event, payload))
        self._ev.set()

    def wait(self, timeout=5.0):
        return self._ev.wait(timeout)

    def results(self):
        return [p for e, p in self.events if e == "ai.result"]


def _set_chat_once(fn):
    original = ai_config.chat_once
    ai_config.chat_once = fn
    # ai_service 引用同一模块对象的属性，改 ai_config.chat_once 即生效
    return lambda: setattr(ai_config, "chat_once", original)


class TestAiService(unittest.TestCase):

    def test_empty_text_sync_result(self):
        c = Collect()
        svc = ai_service.AiService(c)
        svc.send("s1", "kimi_ai", "   ")
        self.assertTrue(c.events)
        event, payload = c.events[0]
        self.assertEqual(event, "ai.result")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["text"], "")
        self.assertEqual(payload["session"], "s1")

    def test_session_keys_bounded(self):
        """v2.0.12：会话键上限 50（插入序淘汰最旧）——托盘常驻数天内存有界。"""
        svc = ai_service.AiService(lambda *a: None)
        for i in range(60):
            svc._append(f"sess-{i}", "u", "a")
        self.assertEqual(len(svc._hist), 50)
        # 最旧 10 个（sess-0..9）被淘汰，保留 sess-10..59
        self.assertNotIn("sess-0", svc._hist)
        self.assertNotIn("sess-9", svc._hist)
        self.assertIn("sess-10", svc._hist)
        self.assertIn("sess-59", svc._hist)

    def test_session_prune_keeps_recent_on_reuse(self):
        """复用旧会话键后其位置更新（插入序语义），不被误淘汰。"""
        svc = ai_service.AiService(lambda *a: None)
        for i in range(51):
            svc._hist.setdefault(f"s{i}", [])
        self.assertEqual(len(svc._hist), 51)
        # 再给最旧的 s0 追加一轮 → 它成为最新，淘汰的应是 s1
        svc._append("s0", "u", "a")
        self.assertEqual(len(svc._hist), 50)
        self.assertIn("s0", svc._hist)
        self.assertNotIn("s1", svc._hist)

    def test_normal_appends_history(self):
        restore = _set_chat_once(lambda msg, model, **kw:
                                 {"ok": True, "text": "你好，我是Kimi", "kind": "openai", "label": "Kimi"})
        try:
            c = Collect()
            svc = ai_service.AiService(c)
            svc.send("s1", "kimi_ai", "你好", msg_id="m1")
            self.assertTrue(c.wait(5))
            r = c.results()[0]
            self.assertTrue(r["ok"])
            self.assertEqual(r["msg_id"], "m1")
            self.assertIn("Kimi", r["text"])
            # 历史已追加 user+assistant
            self.assertEqual(svc._history("s1"),
                             [{"role": "user", "content": "你好"},
                              {"role": "assistant", "content": "你好，我是Kimi"}])
        finally:
            restore()

    def test_custom_model_passes_provider(self):
        seen = {}

        def fake(msg, model, **kw):
            seen["model"] = model
            return {"ok": True, "text": "hi", "kind": "openai", "label": model}

        restore = _set_chat_once(fake)
        try:
            c = Collect()
            svc = ai_service.AiService(c)
            svc.send("s1", "111", "hi")
            self.assertTrue(c.wait(5))
            self.assertEqual(seen["model"], "111")   # 自定义模型名透传给 chat_once
            self.assertTrue(c.results()[0]["ok"])
        finally:
            restore()

    def test_failure_no_history(self):
        restore = _set_chat_once(lambda msg, model, **kw:
                                 {"ok": False, "text": "[111] 调用失败：Missing credentials",
                                  "kind": "openai", "label": "111"})
        try:
            c = Collect()
            svc = ai_service.AiService(c)
            svc.send("s1", "111", "hi")
            self.assertTrue(c.wait(5))
            r = c.results()[0]
            self.assertFalse(r["ok"])
            self.assertIn("Missing credentials", r["text"])
            self.assertEqual(svc._history("s1"), [])   # 失败不记历史
        finally:
            restore()

    def test_history_carried_into_next_request(self):
        calls = []
        import time

        def fake(msg, model, history=None, **kw):
            calls.append(list(history or []))
            return {"ok": True, "text": "答" + msg, "kind": "openai", "label": model}

        restore = _set_chat_once(fake)
        try:
            c = Collect()
            svc = ai_service.AiService(c)
            # 第一次：worker1 启动时历史为空；成功后 _append 进 第一问/答第一问
            svc.send("sX", "kimi_ai", "第一问")
            # 等 worker1 把这一轮写入内部历史（此时才发第二次，保证 worker2 读到）
            deadline = time.time() + 5
            while len(svc._hist.get("sX", [])) < 2 and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(svc._hist["sX"]), 2)
            # 第二次：worker2 读取历史 → 携带第一轮
            svc.send("sX", "kimi_ai", "第二问")
            deadline = time.time() + 5
            while len(calls) < 2 and time.time() < deadline:
                time.sleep(0.01)
            # 第二次调用应携带第一次的 user/assistant 历史
            self.assertEqual(calls[0], [])
            self.assertEqual(calls[1],
                             [{"role": "user", "content": "第一问"},
                              {"role": "assistant", "content": "答第一问"}])
        finally:
            restore()

    def test_clear_session(self):
        restore = _set_chat_once(lambda msg, model, **kw:
                                 {"ok": True, "text": "a", "kind": "openai", "label": "x"})
        try:
            c = Collect()
            svc = ai_service.AiService(c)
            svc.send("sZ", "kimi_ai", "x")
            self.assertTrue(c.wait(5))
            self.assertEqual(len(svc._history("sZ")), 2)
            svc.clear("sZ")
            self.assertEqual(svc._history("sZ"), [])
        finally:
            restore()

    def test_exception(self):
        def _boom(msg, model, **kw):
            raise RuntimeError("api timeout")
        restore = _set_chat_once(_boom)
        try:
            c = Collect()
            svc = ai_service.AiService(c)
            svc.send("s2", "deepseek_api", "x")
            self.assertTrue(c.wait(5))
            r = c.results()[0]
            self.assertFalse(r["ok"])
            self.assertIn("api timeout", r["text"])
        finally:
            restore()

    def test_dynamic_history_trim_on_read(self):
        """历史轮数动态裁剪：读盘 history_rounds() 决定上限。设 10 轮后 12 轮历史被裁到 24 条。"""
        restore = _set_chat_once(lambda msg, model, **kw:
                                 {"ok": True, "text": "a", "kind": "openai", "label": "x"})
        import tempfile, json
        import bridge.ai_config as ac
        tmp = tempfile.TemporaryDirectory()
        try:
            ac.set_root(tmp.name)
            ac.set_ai_history(10)  # 限制 10 轮
            c = Collect()
            svc = ai_service.AiService(c)
            # 制造 12 轮（24 条）历史：手工塞入（绕过 chat_once 裁剪），验证读取时裁剪
            for i in range(12):
                svc._hist.setdefault("sd", []).extend(
                    [{"role": "user", "content": f"u{i}"},
                     {"role": "assistant", "content": f"a{i}"}])
            h = svc._history("sd")
            self.assertEqual(len(h), 20)         # 10 轮 * 2
            self.assertEqual(h[0]["content"], "u2")  # 保留最新 10 轮（u2..u11）
        finally:
            ac.set_root(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
            tmp.cleanup()
            restore()


if __name__ == "__main__":
    unittest.main(verbosity=2)
