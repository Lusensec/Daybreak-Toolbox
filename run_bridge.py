"""破晓·工具箱 —— 可执行程序入口（PyInstaller 打包用；开发态直接 `python -m bridge.main`）。

与 `python -m bridge.main` 的差异：
  - 顶层绝对导入（PyInstaller 脚本入口不支持包内相对导入）；
  - 打包态（sys.frozen）启动前，把内置的 config/ 默认配置种子复制到 exe 同目录
    （首次运行生成用户可写配置；已存在的文件一律不覆盖，保留用户数据）。

打包（Windows 示例，在项目根执行，需先 `pnpm build` 出 web/dist）：
  pyinstaller --onefile --noconsole --name DaybreakToolbox ^
      --add-data "web/dist;dist" --add-data "config;config" run_bridge.py
产物 dist/DaybreakToolbox.exe 与同目录 dist/ 静态文件由程序自解析（bridge/main.py）。
"""
from __future__ import annotations

import os
import shutil
import sys


def _bootstrap_frozen_state() -> None:
    """frozen 态：把 _MEIPASS 内置 config 缺项复制到 exe 同目录（可写状态区），
    并把 stdout/stderr 落盘到 exe 旁 daybreak.log（无 console 版唯一的诊断通道）。"""
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
    # 日志：exe 旁 daybreak.log（追加）；console 版保留原句柄，双写
    log_path = os.path.join(exe_dir, "daybreak.log")
    log_f = open(log_path, "a", encoding="utf-8", buffering=1)
    # logging（bridge 各模块 log）也落同一文件，便于窗口形态诊断
    import logging
    _root = logging.getLogger()
    if not any(getattr(h, "stream", None) is log_f for h in _root.handlers):
        _h = logging.StreamHandler(log_f)
        _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        _root.addHandler(_h)
        _root.setLevel(logging.INFO)
    for name in ("stdout", "stderr"):
        cur = getattr(sys, name, None)
        if getattr(sys, "frozen", False):
            if cur is None:
                setattr(sys, name, log_f)
            else:  # console 版：双写
                import io

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

                setattr(sys, name, _Dup(cur, log_f))
    print(f"[daybreak] frozen root={exe_dir} log={log_path}")


def main() -> None:
    _bootstrap_frozen_state()
    try:
        from bridge.main import main as _bridge_main
        _bridge_main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
