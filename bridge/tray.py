"""桌面托盘图标（Windows）：常驻任务栏，右键菜单快速打开工具箱。

设计取舍：
  - 用 pystray（原生托盘）+ Pillow 程序化生成图标，不依赖 ico 资源文件；
  - v2.1.3：系统固定功能面板（AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记）已移除，
    托盘菜单只保留「打开首页」与「退出」；
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
]


def _make_icon_image(root: "object" = None):
    """托盘图标：优先系统 logo（web/public/logo.png → 48px），缺失时回退程序化日出渐变。"""
    from PIL import Image, ImageDraw

    # 1) 真 logo
    cands = []
    if root is not None:
        cands += [Path(root) / rel for rel in ("web/public/logo.png", "web/dist/logo.png")]
    # frozen（打包 exe）：web 资产在 _MEIPASS/dist/（add-data web/dist;dist）
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / "dist" / "logo.png")
    for p in cands:
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


def start_tray(port: int, root: Path | None = None,
               restore_fn: "Callable[[], bool] | None" = None) -> bool:
    """启动托盘（v2.0.14：pystray 导入/图标渲染/消息循环全在 daemon 线程，主线程零阻塞）。
    返回是否已发起；失败仅记日志，不抛。
    root：项目根（托盘图标取系统 logo；None 走手绘兜底）。
    restore_fn（v2.0.15）：「打开…」菜单项先尝试唤回已有窗口（返回 True = 已处理）；
    None / 返回 False → 旧行为 webbrowser.open（服务形态无窗口）。"""
    if os.environ.get("DAYBREAK_NO_TRAY") == "1":
        log.info("tray disabled by DAYBREAK_NO_TRAY=1")
        return False
    if sys.platform != "win32":
        log.info("tray only on Windows, skip")
        return False

    def _tray_main() -> None:
        try:
            import pystray
            from pystray import Menu, MenuItem
        except Exception as e:  # 依赖缺失（干净环境/CI）
            log.warning("tray skipped: pystray unavailable (%s)", e)
            return
        try:
            image = _make_icon_image(root)
        except Exception as e:
            log.warning("tray skipped: icon render failed (%s)", e)
            return
        try:
            # 注意：pystray 用 co_argcount 校验 action，lambda 带默认参数会算成 3 参被拒 → 用 def 闭包
            def _make_page(label: str, path: str) -> "MenuItem":
                def action(icon, item):
                    # v2.0.15：优先唤回已有窗口（最小化驻留态）；无窗口才开浏览器
                    try:
                        if restore_fn is not None and restore_fn() is True:
                            return
                    except Exception:
                        pass
                    _open_url(port, path)

                return MenuItem(label, action)

            def _exit(icon, item):
                os._exit(0)  # 托盘/桥全进程退出（daemon 线程随进程消失，状态已落盘）

            items = [_make_page(l, p) for l, p in _TRAY_PAGES]
            items.append(MenuItem("退出破晓工具箱", _exit))
            menu = Menu(*items)
            icon = pystray.Icon("daybreak-toolbox", image, "破晓·工具箱", menu)
            icon.run()  # 阻塞（Windows 消息循环）；本线程为 daemon，进程退出自动消失
        except Exception as e:
            log.warning("tray loop ended: %s", e)

    threading.Thread(target=_tray_main, name="daybreak-tray", daemon=True).start()
    log.info("tray starting in background (daybreak-toolbox @ 127.0.0.1:%d)", port)
    return True
