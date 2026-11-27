"""破晓·工具箱 —— 可执行程序入口（PyInstaller 打包用；开发态直接 `python -m bridge.main`）。

与 `python -m bridge.main` 的差异：
  - 顶层绝对导入（PyInstaller 脚本入口不支持包内相对导入）；
  - 打包态（sys.frozen）启动前，把内置的 config/ 默认配置种子复制到 exe 同目录
    （首次运行生成用户可写配置；已存在的文件一律不覆盖，保留用户数据）。

打包（Windows 示例，在项目根执行，需先 `pnpm build` 出 web/dist）：
  pyinstaller --onedir --noconsole --name DaybreakToolbox ^
      --add-data "web/dist;dist" --add-data "config;config" run_bridge.py
产物 dist/DaybreakToolbox/DaybreakToolbox.exe（onedir：运行时不再自解压，启动比 onefile 快 ~3s；
静态文件在 dist/DaybreakToolbox/_internal/dist，由程序经 sys._MEIPASS 自解析）。
"""
from __future__ import annotations

import os
import shutil
import sys
import time as _time

# v2.0.14 启动计时 T0：frozen 进程里第一行执行的 Python（模块导入前）
_BOOT_T0 = _time.perf_counter()


def _LogStream(io, logger):
    """stdout/stderr → 滚动日志文件（经 logging 通道，与 RotatingFileHandler 同一份轮转策略；
    无 console 版唯一的诊断通道由此落盘。按行切分，空行不记。"""
    import logging as _logging

    class _S(io.TextIOBase):
        def __init__(self, log):
            super().__init__()
            self._log = log
            self._buf = ""

        def write(self, s):
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._log.info("%s", line)
            return len(s)

        def flush(self):
            pass

    return _S(logger)


def _bootstrap_frozen_state() -> None:
    """frozen 态：把 _MEIPASS 内置 config 缺项复制到 exe 同目录（可写状态区），
    并把 stdout/stderr 经 logging 落盘到 exe 旁 daybreak.log（**滚动 5MB×2 备份**——
    托盘常驻应用跑数天不再无限增长；旧版裸 append 句柄轮转后仍写旧文件，故统一走 logging）。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    src = os.path.join(meipass, "config")
    if os.path.isdir(src):
        dst = os.path.join(exe_dir, "config")
        os.makedirs(dst, exist_ok=True)
        for name in ("config.json", "update.json"):
            src_f = os.path.join(src, name)
            dst_f = os.path.join(dst, name)
            if os.path.isfile(src_f) and not os.path.exists(dst_f):
                shutil.copyfile(src_f, dst_f)
    # 日志：exe 旁 daybreak.log（滚动：单文件 ≤5MB，保留 2 份备份 → 磁盘占用封顶 ~15MB）
    import logging
    from logging.handlers import RotatingFileHandler
    log_path = os.path.join(exe_dir, "daybreak.log")
    _root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == log_path
               for h in _root.handlers):
        _rfh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=2,
                                   encoding="utf-8")
        _rfh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        _root.addHandler(_rfh)
        _root.setLevel(logging.INFO)
    _console_log = logging.getLogger("daybreak.console")  # print/traceback 走同一滚动文件
    import io
    for name in ("stdout", "stderr"):
        cur = getattr(sys, name, None)
        if cur is None:
            # 无 console（--noconsole）：直接接滚动日志
            setattr(sys, name, _LogStream(io, _console_log))
        else:
            # console 版：双写（真 console + 滚动日志）
            class _Dup(io.TextIOBase):
                def __init__(self, a, b):
                    self._a, self._b = a, b

                def write(self, s):
                    try:
                        self._a.write(s)
                    except Exception:
                        pass
                    try:
                        self._b.write(s)
                    except Exception:
                        pass

                def flush(self):
                    for x in (self._a, self._b):
                        try:
                            x.flush()
                        except Exception:
                            pass

            setattr(sys, name, _Dup(cur, _LogStream(io, _console_log)))
    print(f"[daybreak] frozen root={exe_dir} log={log_path} (rotating 5MB x2)")


def main() -> None:
    _bootstrap_frozen_state()
    print(f"[perf] bootstrap {int((_time.perf_counter() - _BOOT_T0) * 1000)}ms "
          f"(frozen 解压 + config 种子 + 日志初始化)")
    try:
        from bridge.main import main as _bridge_main
        _bridge_main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
