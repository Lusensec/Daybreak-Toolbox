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
                           MenuError, RUN_TYPES, project_root)

# 项目根取自 menu_service（单一真相源：set_root 同时约束 工具读写 与 路径解析）


def _root() -> Path:
    return project_root()

RUN_TYPES = ["直接打开", "命令行打开", "文件夹打开", "链接打开", "下载链接"]


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
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            local_file.write_bytes(data)
        except Exception as e:
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
            subprocess.Popen(f"start msedge {url} & exit", shell=True)
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
