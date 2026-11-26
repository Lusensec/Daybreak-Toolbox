"""tests/test_run_bridge_log.py：v2.0.11 日志轻量优化 —— _LogStream 行缓冲/滚动通道。"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_bridge  # noqa: E402


def test_log_stream_splits_lines_and_skips_blank():
    """_LogStream：按行切分、跨 write 续行、空行不记。"""
    logger = logging.getLogger("test.logstream")
    logger.setLevel(logging.INFO)
    recs: list[str] = []
    h = logging.Handler()
    h.emit = lambda r: recs.append(r.getMessage())  # type: ignore[method-override]
    logger.addHandler(h)
    logger.propagate = False

    stream = run_bridge._LogStream(io, logger)
    assert stream.write("line1\n") == 6
    assert stream.write("line2") == 5      # 无换行 → 暂存缓冲
    assert stream.write("\nline3") == 6    # 续行完成 + 新一行
    assert stream.write("\n") == 1          # 空行
    assert stream.write("line4\n\n") == 7  # 行尾 + 中间空行
    assert recs == ["line1", "line2", "line3", "line4"], recs


def test_log_stream_flush_noop():
    stream = run_bridge._LogStream(io, logging.getLogger("test.logstream2"))
    assert stream.flush() is None


def test_bootstrap_idempotent_handler_guard():
    """_bootstrap_frozen_state 非 frozen 态直接返回（不触碰日志系统）。"""
    # 非 frozen 环境（sys._MEIPASS 不存在）→ 无操作、无异常
    run_bridge._bootstrap_frozen_state()
