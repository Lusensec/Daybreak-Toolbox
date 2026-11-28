"""工具执行 service：Web 端在本机执行 5 种启动方式（新数据模型版）。

数据源（Phase 4）：config/config.json 的 菜单→导航→工具 结构（旧 tools.txt 已退役）。

相对路径新规则：
  工具箱根目录 / <菜单名> / <导航名> / <工具路径>
  （菜单/导航名即目录段，缺目录逐级创建）

语义（对齐旧版 fun.create_command_function，去掉 首页 index==1 特判）：
  - 直接打开 / 命令行打开 / 文件夹打开：解析目标后 subprocess 执行
  - 链接打开：Windows start msedge <url> / Linux xdg-open
  - 下载链接：未下载 → 下载到 <根>/<菜单>/<导航>/<工具名称>/<文件名>（目录逐级建），
              成功后回写 工具路径 为 <工具名称>/<文件名>（相对 菜单/导航 目录）
  置灰（active）：路径（绝对/相对解析后/已下载）不存在 → 按钮禁用。
"""
from __future__ import annotations

import os
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .menu_service import (load_config, get_menu_entry, update_tool_path,
                           home_tools, MenuError, RUN_TYPES, project_root)

# 项目根取自 menu_service（单一真相源：set_root 同时约束 工具读写 与 路径解析）

# RUN_TYPES 以 menu_service 为唯一真相源（顶部 import）；本模块不再重复定义


def _root() -> Path:
    return project_root()


class ToolError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _find_tool(menu: str, name: str) -> tuple[dict, str]:
    """按工具名跨该菜单全部导航查找 → (工具, 所属导航名)。"""
    entry = get_menu_entry(menu)
    for nav, tools in (entry.get("navigation_bar_name") or {}).items():
        for t in tools:
            if t.get("工具名称") == name:
                return t, str(nav)
    raise ToolError("TOOL_NOT_FOUND", f"工具 {name} 不存在")


def _resolve(tool: dict, menu: str, nav: str) -> tuple[int, str]:
    """返回 (path_kind, resolved_path)：
    1 绝对 / 2 相对（菜单/导航目录树下）/ 3 未下载链接 / 4 已下载（本地文件）。"""
    tool_path = str(tool.get("工具路径", ""))
    run_type = str(tool.get("启动方式", ""))

    if run_type == "下载链接":
        if "http" in tool_path:
            return 3, tool_path          # 未下载：仍是 URL
        return 4, tool_path             # 已下载：本地相对（菜单/导航目录）

    if os.path.isabs(tool_path):
        return 1, tool_path
    # 相对路径 → <根>/<菜单>/<导航>/<工具路径>（Windows 统一分隔符）
    resolved = _root() / menu / nav / Path(tool_path).as_posix().replace("/", os.sep)
    return 2, str(resolved)


def tool_active(tool: dict, menu: str, nav: str) -> bool:
    """路径不存在 → 置灰（链接类恒 active）。"""
    if "http" in str(tool.get("工具路径", "")):
        return True
    kind, resolved = _resolve(tool, menu, nav)
    if kind in (3, 4):
        # 已下载的本地文件：按 菜单/导航 目录树解析后查存在性
        return kind == 3 or os.path.exists(
            str(_root() / menu / nav / str(tool.get("工具路径", "")).replace("/", os.sep)))
    return os.path.exists(resolved)


def _tool_folder_target(tool: dict, menu: str, nav: str) -> tuple[str, str]:
    """v2.2.5「打开所在文件夹」：解析工具 → (选中目标, 要打开的目录)。
    - 链接类 / 未下载 → ToolError
    - 文件 → 选中该文件、打开其父目录；目录 → 打开目录本身
    纯解析函数（不弹资源管理器），可单测。"""
    path = str(tool.get("工具路径", ""))
    if "http" in path:
        raise ToolError("TOOL_NO_FOLDER", "链接类工具没有本地文件夹")
    kind, _resolved = _resolve(tool, menu, nav)
    if kind == 3:
        raise ToolError("TOOL_NO_FOLDER", "安装包尚未下载，没有本地文件夹")
    # kind 2（相对路径）/ kind 4（已下载回写的相对路径）都要拼 菜单/导航 目录树；
    # kind 1 绝对路径直接用（_resolve 对绝对路径原样返回）
    if kind == 1:
        target = path
    else:
        target = str(_root() / menu / nav / Path(path).as_posix().replace("/", os.sep))
    if not target or not os.path.exists(target):
        raise ToolError("TOOL_FOLDER_MISSING", f"路径不存在：{target or path}")
    if os.path.isdir(target):
        return target, target
    parent = os.path.dirname(os.path.abspath(target)) or target
    return target, parent


def open_tool_folder(menu: str, name: str) -> dict:
    """在系统资源管理器中打开工具所在文件夹（文件则定位选中）。"""
    tool, nav = _find_tool(menu, name)
    select, open_dir = _tool_folder_target(tool, menu, nav)
    import sys as _sys
    if _sys.platform == "win32":
        if os.path.isdir(select):
            os.startfile(select)  # noqa: S606 —— 目录打开
        else:
            # explorer /select 定位到文件（注意 /select, 后必须直接跟路径，无空格）
            subprocess.Popen(["explorer", f"/select,{select}"])
    elif _sys.platform == "darwin":
        subprocess.Popen(["open", open_dir])
    else:
        subprocess.Popen(["xdg-open", open_dir])
    return {"ok": True, "folder": open_dir, "selected": select}


def home_tools_detailed() -> list[dict]:
    """首页固定工具卡（v2.2.5）：pin 列表 + 每条的展示信息（菜单/导航/启动方式/置灰）。"""
    out = []
    for pin in home_tools():
        try:
            tool, nav = _find_tool(str(pin["menu"]), str(pin["name"]))
        except ToolError:
            continue  # home_tools 刚剪枝过，这里理论不可达；防御性跳过
        m = str(pin["menu"])
        out.append({
            "menu": m, "name": str(pin["name"]), "nav": nav,
            "启动方式": str(tool.get("启动方式", "")),
            "工具路径": str(tool.get("工具路径", "")),
            "active": tool_active(tool, m, nav),
        })
    return out


def run_tool(menu: str, name: str) -> dict:
    """执行工具，返回 {ok, message, run_type}。异常统一 ToolError → 前端 toast。"""
    tool, nav = _find_tool(menu, name)
    run_type = str(tool.get("启动方式", ""))
    if run_type not in RUN_TYPES:
        raise ToolError("INTERNAL", f"未知启动方式 {run_type}")
    kind, resolved = _resolve(tool, menu, nav)

    # ---- 下载链接（未下载）：逐级建目录 + 下载 + 回写 工具路径 ----
    if kind == 3:
        url = str(tool.get("工具路径", ""))
        local_dir = _root() / menu / nav / name
        local_dir.mkdir(parents=True, exist_ok=True)
        fname = os.path.basename(urlparse(url).path) or "download"
        local_file = local_dir / fname
        try:
            with urllib.request.urlopen(url, timeout=120) as resp, \
                    open(local_file, "wb") as out:
                # 1MB 分块流式写盘（v2.0.12：旧版 resp.read() 全量入内存，
                # 几百 MB 的工具会顶起等量内存峰值）
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
        except Exception as e:
            # 失败清理残留部分文件（避免下次误判已下载）
            try:
                if local_file.exists():
                    local_file.unlink()
            except OSError:
                pass
            raise ToolError("TOOL_DOWNLOAD_FAIL", f"下载失败：{e}")
        # 回写 config：工具路径 → <工具名称>/<basename>（相对 菜单/导航 目录）
        update_tool_path(menu, name, f"{name}/{fname}")
        return {"ok": True, "run_type": run_type,
                "message": f"已下载到 {local_file}，如需命令行使用请在「工具管理」修改该工具启动命令"}

    if kind == 4:
        # 已下载的本地工具：在 菜单/导航 目录树下解析
        local = _root() / menu / nav / str(tool.get("工具路径", "")).replace("/", os.sep)
        return _run_local(tool, run_type, str(local), menu, nav)

    return _run_local(tool, run_type, resolved, menu, nav)


def _run_local(tool: dict, run_type: str, target: str, menu: str, nav: str) -> dict:
    """直接打开 / 命令行打开 / 文件夹打开 / 链接打开（Windows 分支与旧版一致）。"""
    is_win = os.name == "nt"
    command = str(tool.get("工具命令", ""))

    if run_type == "文件夹打开":
        try:
            Path(target).mkdir(parents=True, exist_ok=True)  # 缺目录逐级创建
            if is_win:
                subprocess.Popen(f'explorer "{target}"')
            else:
                subprocess.Popen(["xdg-open", target])
            return {"ok": True, "run_type": run_type, "message": f"已打开文件夹：{target}"}
        except Exception as e:
            raise ToolError("TOOL_RUN_FAIL", f"文件夹打开失败：{e}")

    if run_type == "命令行打开":
        try:
            if " " not in command:
                p = target
                subprocess.Popen(p)
            else:
                cmd = command.replace("*", target)
                workdir = str(Path(target).parent or ".")
                if is_win:
                    line = f'start cmd /k "cd \\"{workdir}\\" && {cmd}"'
                    subprocess.Popen(line, shell=True)
                else:
                    subprocess.Popen(["bash", "-c", f'cd "{workdir}" && {cmd}'])
            return {"ok": True, "run_type": run_type, "message": "命令已在终端启动"}
        except Exception as e:
            raise ToolError("TOOL_RUN_FAIL", f"命令行启动失败：{e}")

    if run_type == "直接打开":
        try:
            subprocess.Popen(target)
            return {"ok": True, "run_type": run_type, "message": f"已启动：{os.path.basename(target)}"}
        except Exception as e:
            raise ToolError("TOOL_RUN_FAIL", f"直接启动失败：{e}")

    # 链接打开（URL）
    url = target if "http" in target else str(tool.get("工具路径", ""))
    try:
        if is_win:
            # start "" 显式空窗口标题 + URL 加引号：含空格/特殊字符的 URL 不会被 start 误解析
            # （旧写法 start msedge {url} 对含空格 URL 会丢参；非法 URL 不含裸引号，引号配对安全）
            subprocess.Popen(f'start "" msedge "{url}" & exit', shell=True)
        else:
            subprocess.Popen(["xdg-open", url])
        return {"ok": True, "run_type": run_type, "message": f"已打开链接：{url}"}
    except Exception as e:
        raise ToolError("TOOL_RUN_FAIL", f"链接打开失败：{e}")


def tool_grid(menu: str, nav: str) -> dict:
    """按导航栏取工具：新结构下 导航键 即 工具归属（旧版 首页 index==1 特判消失，
    首页只是普通导航键）。菜单不存在 → MenuError(MENU_NOT_FOUND) 由 handler 转 BridgeError。"""
    entry = get_menu_entry(menu)  # 菜单不存在抛 MENU_NOT_FOUND
    tools = (entry.get("navigation_bar_name") or {}).get(nav, []) or []
    out = []
    for t in tools:
        out.append({
            **{k: t.get(k, "") for k in ("工具名称", "工具路径", "启动方式", "工具命令")},
            "工具使用": nav,   # 前端展示用：归属导航（新结构中由键位体现，显式回带）
            "active": tool_active(t, menu, nav),
        })
    return {"menu": menu, "nav": nav, "tools": out}
