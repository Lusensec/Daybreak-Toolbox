"""桌面托盘图标（Windows）：常驻任务栏，右键菜单快速打开工具箱各页面。

设计取舍：
  - 用 pystray（原生托盘）+ Pillow 程序化生成图标，不依赖 ico 资源文件；
  - 菜单项 = 5 个固定页面（webbrowser 打开 127.0.0.1:<port>/<path>，SPA 兜底路由由 bridge 静态层处理）；
  - 线程以 daemon 方式跑：bridge 进程退出时托盘自动消失，无孤儿图标；
  - 无 pystray / 非 Windows / DAYBREAK_NO_TRAY=1 → 静默跳过，不影响 bridge 本体。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

log = logging.getLogger("bridge.tray")

# 托盘菜单：（显示名, SPA 路由路径）
_TRAY_PAGES = [
    ("打开首页", "/"),
    ("AI 对话", "/ai"),
    ("终端管理", "/shell"),
    ("编解码", "/codec"),
    ("汉英翻译", "/translate"),
    ("临时笔记", "/note"),
]


def _make_icon_image(root: "object" = None):
    """托盘图标：优先系统 logo（web/public/logo.png → 48px），缺失时回退程序化日出渐变。"""
    from PIL import Image, ImageDraw

    # 1) 真 logo
    if root is not None:
        for rel in ("web/public/logo.png", "web/dist/logo.png"):
            p = Path(root) / rel
            if p.is_file():
                try:
                    im = Image.open(p).convert("RGBA").resize((48, 48), Image.LANCZOS)
                    return im
                except Exception:
                    break

    # 2) 兜底：64×64 破晓图标（深蓝夜 → 橙色地平线的日出渐变 + 白色太阳弧）
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆形背景（深蓝夜）
    d.ellipse([0, 0, size - 1, size - 1], fill=(24, 34, 58, 255))
    # 下半部"地面"暗色压住
    d.rectangle([0, size // 2 + 6, size, size], fill=(16, 22, 38, 255))
    # 橙色太阳（半圆露出地平线）
    sun = (size // 2, size // 2 + 8)
    r = 14
    d.pieslice([sun[0] - r, sun[1] - r, sun[0] + r, sun[1] + r], 180, 360, fill=(245, 166, 35, 255))
    # 地平线
    d.line([4, sun[1], size - 5, sun[1]], fill=(245, 200, 120, 255), width=2)
    return img


def _open_url(port: int, path: str) -> None:
    webbrowser.open(f"http://127.0.0.1:{port}{path}")


def start_tray(port: int, extra_items: list[tuple[str, object]] | None = None, root: Path | None = None) -> bool:
    """启动托盘（daemon 线程）。返回是否成功；失败仅记日志，不抛。
    extra_items：附加菜单项（label, callback），如 ball 的「显示悬浮球」。
    root：项目根（用于托盘图标取系统 logo；None 走手绘兜底）。"""
    if os.environ.get("DAYBREAK_NO_TRAY") == "1":
        log.info("tray disabled by DAYBREAK_NO_TRAY=1")
        return False
    if sys.platform != "win32":
        log.info("tray only on Windows, skip")
        return False
    try:
        import pystray
        from pystray import Menu, MenuItem
    except Exception as e:  # 依赖缺失（干净环境/CI）
        log.warning("tray skipped: pystray unavailable (%s)", e)
        return False

    try:
        image = _make_icon_image(root)
    except Exception as e:
        log.warning("tray skipped: icon render failed (%s)", e)
        return False

    try:
        # 注意：pystray 用 co_argcount 校验 action，lambda 带默认参数会算成 3 参被拒 → 用 def 闭包
        def _make_page(label: str, path: str) -> MenuItem:
            def action(icon, item):
                _open_url(port, path)

            return MenuItem(label, action)

        def _make_extra(label: str, cb) -> MenuItem:
            def action(icon, item):
                cb()

            return MenuItem(label, action)

        def _exit(icon, item):
            os._exit(0)  # 托盘/球/桥全进程退出（daemon 线程随进程消失，状态已落盘）

        items = [_make_page(l, p) for l, p in _TRAY_PAGES]
        items += [_make_extra(l, c) for l, c in (extra_items or [])]
        items.append(MenuItem("退出破晓工具箱", _exit))
        menu = Menu(*items)
        icon = pystray.Icon("daybreak-toolbox", image, "破晓·工具箱", menu)

        def _run() -> None:
            # run() 阻塞（Windows 消息循环）；daemon 线程随进程退出自动消失
            try:
                icon.run()
            except Exception as e:
                log.warning("tray loop ended: %s", e)

        threading.Thread(target=_run, name="daybreak-tray", daemon=True).start()
        log.info("tray started (daybreak-toolbox @ 127.0.0.1:%d)", port)
        return True
    except Exception as e:
        log.warning("tray failed to start: %s", e)
        return False
