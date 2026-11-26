"""破晓·工具箱 —— 桥接服务（FastAPI + uvicorn，仅 127.0.0.1）。

目标态（docs/React_TS_UI_重构方案.md §3）：
  Python 单进程内
  ├─ uvicorn (thread) 127.0.0.1:8765
  │   ├─ /ws   WebSocket 事件总线（token 鉴权）
  │   └─ /api  REST（配置 CRUD，token 鉴权）
  └─ 各 service（ai / translate / codec / shell / menu）

本文件为 **Phase 1 骨架**：
  - 端口 8765 起冲突 +1 最多 5 次
  - token 鉴权（WS query ?token= / REST Bearer）
  - /api/ping + /api/echo（自检）
  - /ws + 一条 echo 命令（前端冒烟用）
  - 优雅关停

启动：python -m bridge.main
冒烟：python -m bridge.smoke  （另起进程）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, Query
from fastapi.responses import JSONResponse

from . import token as _token_mod
from .ws import WsBus, BridgeError
from .translate_service import TranslateService
from .ai_service import AiService
from .ai_config import (get_ai_config, set_ai_config, test_ai,
                       add_ai_model, remove_ai_model, AiConfigError,
                       get_ai_history, set_ai_history, set_ai_page)
from .codec_service import CodecService
from .menu_service import (list_menus, add_menu, delete_menu, rename_menu, rename_nav,
                           add_nav, delete_nav,
                          reorder_menus, reorder_navs,
                          set_visible, set_fixed_visible, list_fixed_visible,
                          add_tool, delete_tool, list_tools, changed_snapshot,
                          MenuError)
from .dialog_service import pick_file, pick_folder, DialogError
from .execute_service import run_tool, tool_grid, ToolError
from .update_service import (
    APP_VERSION,
    UpdateError,
    check_update,
    get_repo,
    get_update_record_content,
    save_repo,
)
from .shortcut_service import get_shortcuts, set_shortcuts, ShortcutError
from . import shell_service
from . import ssh_service
from . import token as _token
from .tray import start_tray

# ---- 端口探测（8765..8770）----
_BASE_PORT = 8765
_MAX_RETRY = 5


def find_free_port(base: int = _BASE_PORT, retries: int = _MAX_RETRY) -> int:
    for offset in range(retries):
        port = base + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in {base}..{base + retries - 1}")


# ---- 全局实例 ----
_bus = WsBus()
_translate_service: Optional[TranslateService] = None
_ai_service: Optional[AiService] = None
_codec_service: Optional[CodecService] = None
_bridge_loop: Optional[asyncio.AbstractEventLoop] = None  # 跨线程广播用
_current_port: Optional[int] = None


def _thread_broadcast(event: str, payload: dict) -> None:
    """供阻塞线程（翻译 worker）调用的同步广播桥。
    无事件循环时忽略（测试场景）；否则 run_coroutine_threadsafe 投递到主循环。"""
    if _bridge_loop and _bridge_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(_bus.broadcast(event, payload), _bridge_loop)
        except RuntimeError:
            pass


def _register_builtin_commands() -> None:
    """内置命令（echo / ping），作为前端冒烟路径。"""

    async def echo(payload: dict, _ws) -> dict:
        # 原样回传，便于前端验证请求-响应匹配
        return {"echo": payload, "ts": int(time.time())}

    _bus.register("echo", echo)
    _bus.register("ping", lambda p, w: _ping_handler(p, w))

    async def _ping_handler(payload: dict, _ws) -> dict:
        return {"pong": True}

    # ---- 翻译 handler（translate.run）：service 在 worker 线程跑，结果经 _thread_broadcast 回 WS ----
    global _translate_service
    _translate_service = TranslateService(_thread_broadcast)

    async def _translate_run(payload: dict, _ws) -> dict:
        req_id = str(payload.get("req_id") or uuid.uuid4())
        # 异步受理（service 已在后台线程跑，立即回 ack，结果走事件）
        _translate_service.run(req_id, str(payload.get("text", "")),
                               str(payload.get("from_lang", "auto")),
                               str(payload.get("to_lang", "auto")))
        return {"accepted": True, "req_id": req_id}

    _bus.register("translate.run", _translate_run)

    # ---- 翻译凭证（工具箱设置「翻译设置」）：与 bridge token 同存 config/bridge_secrets.json ----
    async def _translate_get_creds(_p, _ws) -> dict:
        b = _token.get_baidu()
        return {"ok": True,
                "configured": bool(b["app_id"] and b["secret_key"]),
                "app_id": b["app_id"],
                "secret_key_configured": bool(b["secret_key"]),
                # 本机 127.0.0.1 单用户工具：密钥已在 config/bridge_secrets.json 明文落地，
                # 回传给前端供「翻译设置」掩码回显（默认 * 号，小眼睛切换明文）
                "secret_key": b["secret_key"]}

    async def _translate_set_creds(p, _ws) -> dict:
        app_id = str(p.get("app_id", "")).strip()
        sec_new = str(p.get("secret_key", "")).strip()
        if not sec_new:
            # 前端留空 = 保留已存密钥（密钥不回显，表单只能追加/覆盖）
            sec_new = _token.get_baidu()["secret_key"]
        r = _token.set_baidu(app_id, sec_new)
        # 保存后立即重载 fanyi 凭证（无需重启桥接）；fanyi 未 import 则延后到翻译 worker
        try:
            import fanyi
            fanyi.refresh_credentials()
        except Exception:
            pass
        return r

    _bus.register("translate.get_creds", _translate_get_creds)
    _bus.register("translate.set_creds", _translate_set_creds)

    # ---- 乱码修复 handler（codec.recover）：worker 线程跑外部服务，结果走 codec.recover 事件 ----
    global _codec_service
    _codec_service = CodecService(_thread_broadcast)

    async def _codec_recover(payload: dict, _ws) -> dict:
        # 受理即 ack；结果走 codec.recover 事件（worker 线程跑）
        _codec_service.recover(str(payload.get("text", "")))
        return {"accepted": True}

    _bus.register("codec.recover", _codec_recover)

    # ---- AI handler（ai.send / ai.providers）：service 在 worker 线程跑，结果经 _thread_broadcast 回 WS ----
    global _ai_service
    _ai_service = AiService(_thread_broadcast)

    async def _ai_send(payload: dict, _ws) -> dict:
        session = str(payload.get("session") or "s1")
        provider = str(payload.get("provider") or "")
        text = str(payload.get("text", ""))
        msg_id = str(payload.get("msg_id") or uuid.uuid4())
        # 兜底：provider 为空或已不在配置中（如旧默认 kimi_ai 被删除/改名）→
        # 自动切到「当前启用模型（use_page!=0）」，否则取排序后第一个模型，
        # 避免 chat_once 直接报 "AI 模型 xxx 不存在"。
        cfg = get_ai_config()
        if provider not in cfg["config"]:
            provider = next(
                (m for m in cfg["models"]
                 if cfg["config"][m].get("use_page") not in (0, None, "")),
                cfg["models"][0] if cfg["models"] else "",
            )
        # 异步受理（worker 线程跑，结果走 ai.result 事件）
        _ai_service.send(session, provider, text, msg_id)
        return {"accepted": True, "msg_id": msg_id, "provider": provider}

    async def _ai_providers(payload: dict, _ws) -> dict:
        # 实时读盘：内置 + 自定义模型都在列（与 ai.get_config 同一数据源，改配置后即时反映）
        cfg = get_ai_config()
        return {"providers": cfg["models"]}

    async def _ai_clear_session(payload: dict, _ws) -> dict:
        session = str(payload.get("session") or "s1")
        _ai_service.clear(session)
        return {"ok": True, "session": session}

    # ---- AI 模型配置 handler（ai.get_config / ai.set_config）：读写 config/ai.json（models + history 合存） ----
    def _ai_cfg_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except AiConfigError as e:
            raise BridgeError(e.code, e.message)

    async def _ai_get_config(_p, _ws) -> dict:
        return _ai_cfg_call(get_ai_config)

    async def _ai_set_config(p, _ws) -> dict:
        r = _ai_cfg_call(set_ai_config,
                         str(p.get("model", "")),
                         str(p.get("api", "")),
                         int(p.get("page_nums", 1) or 1),
                         p.get("model_two"),
                         str(p.get("alias", "")),
                         str(p.get("base_url", "")),
                         str(p.get("model_id", "")),
                         str(p.get("kind", "")))
        await _bus.broadcast("ai.config_changed", r)
        return r

    async def _ai_add_model(p, _ws) -> dict:
        r = _ai_cfg_call(add_ai_model,
                         str(p.get("model", "")),
                         str(p.get("alias", "")),
                         str(p.get("kind", "openai")))
        await _bus.broadcast("ai.config_changed", r)
        return r

    async def _ai_remove_model(p, _ws) -> dict:
        r = _ai_cfg_call(remove_ai_model, str(p.get("model", "")))
        await _bus.broadcast("ai.config_changed", r)
        return r

    async def _ai_test(p, _ws) -> dict:
        # 真实网络请求：放 worker 线程跑，避免阻塞事件循环
        r = await asyncio.to_thread(
            test_ai,
            str(p.get("model", "")),
            str(p.get("api", "")),
            str(p.get("base_url", "")),
            str(p.get("model_id", "")),
            str(p.get("kind", "")),
            str(p.get("alias", "")),
        )
        return r

    async def _ai_get_history(_p, _ws) -> dict:
        return get_ai_history()

    async def _ai_set_history(p, _ws) -> dict:
        r = _ai_cfg_call(set_ai_history, int(p.get("rounds", 20) or 20))
        await _bus.broadcast("ai.config_changed", r)
        return r

    async def _ai_set_page(p, _ws) -> dict:
        # 保存「分栏数量」：直接持久化 use_page 布局（pane1/pane2），即时重载
        r = _ai_cfg_call(set_ai_page,
                         int(p.get("page_nums", 1) or 1),
                         str(p.get("model_one", "")),
                         str(p.get("model_two", "")))
        await _bus.broadcast("ai.config_changed", r)
        return r

    _bus.register("ai.send", _ai_send)
    _bus.register("ai.providers", _ai_providers)
    _bus.register("ai.clear_session", _ai_clear_session)
    _bus.register("ai.get_config", _ai_get_config)
    _bus.register("ai.set_config", _ai_set_config)
    _bus.register("ai.add_model", _ai_add_model)
    _bus.register("ai.remove_model", _ai_remove_model)
    _bus.register("ai.test", _ai_test)
    _bus.register("ai.get_history", _ai_get_history)
    _bus.register("ai.set_history", _ai_set_history)
    _bus.register("ai.set_page", _ai_set_page)

    # ---- 工具执行 / 网格（本机执行层，新数据模型：config 菜单/导航/工具）----
    def _tool_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (ToolError, MenuError) as e:  # MenuError：菜单被删等（前端据 MENU_NOT_FOUND 提示）
            raise BridgeError(e.code, e.message)

    async def _tool_run(p, _ws) -> dict:
        r = await asyncio.to_thread(_tool_call, run_tool,
                                    str(p.get("menu", "")), str(p.get("name", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return r

    async def _tool_grid(p, _ws) -> dict:
        return _tool_call(tool_grid, str(p.get("menu", "")), str(p.get("nav", "首页")))

    _bus.register("tool.run", _tool_run)
    _bus.register("tool.grid", _tool_grid)

    # ---- 本地终端（旧版隐藏的 create_local_cmd 显式化）：shell.run 同步子进程 → worker 线程 ----
    async def _shell_run(p, _ws) -> dict:
        session = str(p.get("session") or "local")
        command = str(p.get("command", ""))
        timeout = p.get("timeout")
        return await asyncio.to_thread(shell_service.run, session, command, timeout)

    async def _shell_complete(p, _ws) -> dict:
        session = str(p.get("session") or "local")
        prefix = str(p.get("prefix", ""))
        return shell_service.complete(session, prefix)

    async def _shell_reset(p, _ws) -> dict:
        session = str(p.get("session") or "local")
        return shell_service.reset(session)

    async def _shell_shells(p, _ws) -> dict:
        session = str(p.get("session") or "local")
        return shell_service.shells(session)

    async def _shell_set_shell(p, _ws) -> dict:
        session = str(p.get("session") or "local")
        shell = str(p.get("shell", "cmd"))
        return shell_service.set_shell(session, shell)

    _bus.register("shell.run", _shell_run)
    _bus.register("shell.complete", _shell_complete)
    _bus.register("shell.reset", _shell_reset)
    _bus.register("shell.shells", _shell_shells)
    _bus.register("shell.set_shell", _shell_set_shell)

    # ---- 菜单/导航/工具 CRUD（同步文件操作，MenuError → BridgeError）----
    def _menu_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except MenuError as e:
            raise BridgeError(e.code, e.message)

    async def _menu_add(p, _ws):
        # 新模型：菜单栏不再需要 工具文件夹路径（menu_path 参数忽略，只取 名称+颜色+导航）
        _menu_call(add_menu, str(p.get("name", "")), str(p.get("menu_color", "")),
                   p.get("navigation") or None)
        await _bus.broadcast("menu.changed", changed_snapshot())
        return {"ok": True}

    async def _menu_remove(p, _ws):
        _menu_call(delete_menu, str(p.get("name", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return {"ok": True}

    async def _menu_add_nav(p, _ws):
        _menu_call(add_nav, str(p.get("menu", "")), str(p.get("nav", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return {"ok": True}

    async def _menu_remove_nav(p, _ws):
        _menu_call(delete_nav, str(p.get("menu", "")), str(p.get("nav", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return {"ok": True}

    async def _menu_rename(p, _ws):
        # 菜单栏改名（新模型：结构即数据，只改 config 键）
        r = _menu_call(rename_menu, str(p.get("name", "")), str(p.get("new_name", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return r

    async def _menu_rename_nav(p, _ws):
        # 导航栏改名（新模型：重命名 导航键，其工具数组随键移动）
        r = _menu_call(rename_nav, str(p.get("menu", "")), str(p.get("nav", "")),
                       str(p.get("new_name", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return r

    async def _menu_add_tool(p, _ws):
        _menu_call(add_tool, str(p.get("name", "")), str(p.get("path", "")),
                   str(p.get("menu", "")), str(p.get("use", "")),
                   str(p.get("run_type", "直接打开")), str(p.get("command", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return {"ok": True}

    async def _menu_remove_tool(p, _ws):
        _menu_call(delete_tool, str(p.get("menu", "")), str(p.get("name", "")))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return {"ok": True}

    async def _menu_list(p, _ws):
        # menus 带 menu_visible（用户菜单栏显隐）；fixed_visible 为固定菜单栏显隐表
        return {"menus": _menu_call(list_menus), "fixed_visible": _menu_call(list_fixed_visible)}

    async def _menu_list_tools(p, _ws):
        return {"tools": _menu_call(list_tools, str(p.get("menu", "")))}

    async def _menu_reorder(p, _ws) -> dict:
        # 拖拽重排用户菜单栏：order = 全部菜单名的新排列
        order = [str(x) for x in (p.get("order") or [])]
        r = _menu_call(reorder_menus, order)
        await _bus.broadcast("menu.changed", changed_snapshot())
        return r

    async def _menu_reorder_nav(p, _ws) -> dict:
        # 拖拽重排某菜单下的导航栏：order = 该菜单导航名的新排列
        order = [str(x) for x in (p.get("order") or [])]
        r = _menu_call(reorder_navs, str(p.get("menu", "")), order)
        await _bus.broadcast("menu.changed", changed_snapshot())
        return r

    # ---- 菜单栏显隐（菜单栏展示设置 / 固定菜单右键：config.json 参数 1 显示 / 0 隐藏）----
    async def _menu_set_visible(p, _ws):
        r = _menu_call(set_visible, str(p.get("name", "")), bool(p.get("visible", True)))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return r

    async def _menu_set_fixed_visible(p, _ws):
        r = _menu_call(set_fixed_visible, str(p.get("name", "")), bool(p.get("visible", True)))
        await _bus.broadcast("menu.changed", changed_snapshot())
        return r

    _bus.register("menu.set_visible", _menu_set_visible)
    _bus.register("menu.set_fixed_visible", _menu_set_fixed_visible)

    _bus.register("menu.add", _menu_add)
    _bus.register("menu.remove", _menu_remove)
    _bus.register("menu.rename", _menu_rename)
    _bus.register("menu.add_nav", _menu_add_nav)
    _bus.register("menu.remove_nav", _menu_remove_nav)
    _bus.register("menu.rename_nav", _menu_rename_nav)
    _bus.register("menu.add_tool", _menu_add_tool)
    _bus.register("menu.remove_tool", _menu_remove_tool)
    _bus.register("menu.list", _menu_list)
    _bus.register("menu.list_tools", _menu_list_tools)
    _bus.register("menu.reorder", _menu_reorder)
    _bus.register("menu.reorder_nav", _menu_reorder_nav)

    # ---- 原生文件/文件夹选择对话框（Web 端「浏览路径」按钮）----
    # 模态对话框阻塞线程 → to_thread 跑，不卡事件循环；取消返回 {"path": ""}
    async def _dialog_pick_file(p, _ws):
        try:
            path = await asyncio.to_thread(
                pick_file, str(p.get("title") or "选择工具路径"),
                str(p.get("initial_dir") or ""))
        except DialogError as e:
            raise BridgeError(e.code, e.message)
        return {"path": path}

    async def _dialog_pick_folder(p, _ws):
        try:
            path = await asyncio.to_thread(
                pick_folder, str(p.get("title") or "选择工具文件夹"),
                str(p.get("initial_dir") or ""))
        except DialogError as e:
            raise BridgeError(e.code, e.message)
        return {"path": path}

    _bus.register("dialog.pick_file", _dialog_pick_file)
    _bus.register("dialog.pick_folder", _dialog_pick_folder)

    # ---- 更新记录 handler（update.record）：纯 dict，直接返回（数据源 bridge/update_service.py）----
    async def _update_record(p, _ws):
        return {"versions": get_update_record_content()}

    _bus.register("update.record", _update_record)

    # ---- 更新设置（config/update.json 仓库配置 + GitHub latest Release 检查）----
    async def _update_repo_get(p, _ws):
        return {"repo": get_repo(), "local_version": APP_VERSION}

    async def _update_repo_save(p, _ws):
        try:
            repo = save_repo(p.get("repo") or "")
        except UpdateError as e:
            raise BridgeError(e.code, e.message)
        return {"ok": True, "repo": repo}

    async def _update_check(p, _ws):
        try:
            # 仓库回退链在 service 内（入参 → 已存配置 → 内置 DEFAULT_REPO）；前端通常发空入参
            return await asyncio.to_thread(check_update, (p.get("repo") or ""))  # 阻塞 HTTP → worker 线程
        except UpdateError as e:
            raise BridgeError(e.code, e.message)

    _bus.register("update.repo.get", _update_repo_get)
    _bus.register("update.repo.save", _update_repo_save)
    _bus.register("update.check", _update_check)

    # ---- 快捷键设置（config/shortcuts.json 槽位表；整表覆盖保存 + 广播即时生效）----
    async def _shortcut_get(p, _ws):
        try:
            return get_shortcuts()
        except ShortcutError as e:
            raise BridgeError(e.code, e.message)

    async def _shortcut_set(p, _ws):
        try:
            r = set_shortcuts(p.get("shortcuts"))
        except ShortcutError as e:
            raise BridgeError(e.code, e.message)
        await _bus.broadcast("shortcut.changed", {"shortcuts": r["shortcuts"]})
        return r

    _bus.register("shortcut.get", _shortcut_get)
    _bus.register("shortcut.set", _shortcut_set)

    # ---- 应用形态 / 自定义窗口控件（v2.0.8 无边框窗口：web 顶栏驱动 移动/最大化/拉伸/关闭）----
    async def _app_env(_p, _ws):
        return get_app_env()

    async def _app_quit(_p, _ws):
        await asyncio.to_thread(quit_app)  # 不返回（进程终止）

    async def _window_get_rect(_p, _ws):
        return {"rect": await asyncio.to_thread(window_rect)}

    async def _window_move(p, _ws):
        return await asyncio.to_thread(move_window, int(p.get("x", 0)), int(p.get("y", 0)))

    async def _window_resize(p, _ws):
        return await asyncio.to_thread(resize_window, int(p.get("width", 0)), int(p.get("height", 0)))

    async def _window_maximize(_p, _ws):
        return await asyncio.to_thread(toggle_maximize)

    async def _window_minimize(_p, _ws):
        return await asyncio.to_thread(minimize_window)

    async def _window_set_rect(p, _ws):
        return await asyncio.to_thread(set_window_rect, p.get("x", 0), p.get("y", 0), p.get("width", 960), p.get("height", 600))

    _bus.register("app.env", _app_env)
    _bus.register("app.quit", _app_quit)
    _bus.register("window.get_rect", _window_get_rect)
    _bus.register("window.move", _window_move)
    _bus.register("window.resize", _window_resize)
    _bus.register("window.maximize", _window_maximize)
    _bus.register("window.minimize", _window_minimize)
    _bus.register("window.set_rect", _window_set_rect)

    # ---- SSH 终端（config/ssh_hosts.json 主机表 + 常驻 paramiko 会话；会话断开广播 ssh.closed）----
    def _ssh_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ssh_service.SSHServiceError as e:
            raise BridgeError(e.code, e.message)

    async def _ssh_hosts_get(p, _ws):
        try:
            return ssh_service.get_hosts()
        except ssh_service.SSHServiceError as e:
            raise BridgeError(e.code, e.message)

    async def _ssh_hosts_save(p, _ws):
        r = _ssh_call(ssh_service.save_hosts, p.get("hosts"))
        await _bus.broadcast("ssh.hosts.changed", {"hosts": r["hosts"]})
        return r

    async def _ssh_connect(p, _ws):
        # 阻塞网络连接（至多 ~3×15s）→ worker 线程，避免卡死整个 WS 事件循环（同 shell.run 的处理）
        alias = str(p.get("alias", ""))
        try:
            r = await asyncio.to_thread(ssh_service.connect, alias)
        except ssh_service.SSHServiceError as e:
            raise BridgeError(e.code, e.message)
        await _bus.broadcast("ssh.connected", r)
        return r

    async def _ssh_run(p, _ws):
        alias = str(p.get("alias", ""))
        try:
            return await asyncio.to_thread(
                ssh_service.run, alias, str(p.get("command", "")), p.get("timeout"))
        except ssh_service.SSHServiceError as e:
            if e.code == "SSH_SESSION_LOST":
                await _bus.broadcast("ssh.closed", {"alias": alias, "reason": e.message})
            raise BridgeError(e.code, e.message)

    async def _ssh_close(p, _ws):
        alias = str(p.get("alias", ""))
        r = _ssh_call(ssh_service.close, alias)
        await _bus.broadcast("ssh.closed", {"alias": alias})
        return r

    async def _ssh_status(p, _ws):
        return ssh_service.status()

    _bus.register("ssh.hosts.get", _ssh_hosts_get)
    _bus.register("ssh.hosts.save", _ssh_hosts_save)
    _bus.register("ssh.connect", _ssh_connect)
    _bus.register("ssh.run", _ssh_run)
    _bus.register("ssh.close", _ssh_close)
    _bus.register("ssh.status", _ssh_status)


def build_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # uvicorn 事件循环 → 翻译 / AI / 编解码 worker 的跨线程广播依赖它
        # （原 @app.on_event("startup")，FastAPI 已弃用 → lifespan）
        global _bridge_loop
        _bridge_loop = asyncio.get_running_loop()
        yield

    app = FastAPI(title="Daybreak Toolbox Bridge", version="2.0.13", lifespan=_lifespan)
    _token_mod.get_token()  # 确保 token 已生成

    @app.get("/api/ping")
    async def api_ping(authorization: str = Header(default="")):
        tok = _extract_bearer(authorization)
        if not _token_mod.validate(tok):
            return JSONResponse({"ok": False, "code": "TOKEN_INVALID"}, status_code=401)
        return {"ok": True, "token_hint": _token_mod.get_token()[:8] + "…"}

    @app.get("/api/echo")
    async def api_echo(msg: str = Query(default="hello"), authorization: str = Header(default="")):
        if not _token_mod.validate(_extract_bearer(authorization)):
            return JSONResponse({"ok": False, "code": "TOKEN_INVALID"}, status_code=401)
        return {"ok": True, "echo": msg}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, token: str = Query(default="")):
        if not _token_mod.validate(token):
            await ws.accept()
            await ws.send_text(json.dumps({"v": 1, "type": "err",
                                           "payload": {"code": "TOKEN_INVALID"}},
                                          ensure_ascii=False))
            await ws.close(code=4401)
            return

        await ws.accept()
        _bus._clients[ws] = True
        try:
            # 握手确认
            await _bus.send_to(ws, "connected", {"port": _current_port or 0})
            while True:
                raw = await ws.receive_text()
                await _bus.handle_inbound(ws, raw)
        except WebSocketDisconnect:
            pass
        finally:
            _bus._clients.pop(ws, None)
            _bus.detach(ws)  # 停止该连接的 handler FIFO worker（在途任务取消，底层线程自行收尾）

    # ---- /api/token：prod（webview 同源）自动取 token，免去手动粘贴 ----
    @app.get("/api/token")
    async def api_token():
        # 仅 127.0.0.1 可达；同源前端直接 fetch 注入
        return {"token": _token_mod.get_token()}

    # ---- 静态服务（webview 单入口）：/ws + /api + web/dist 同端口 8765 ----
    _dist_dirs = [
        Path(__file__).resolve().parent.parent / "web" / "dist",  # 开发：项目根/web/dist
        Path(__file__).resolve().parent.parent / "dist",         # 打包：exe 旁 dist/
    ]
    _dist = next((d for d in _dist_dirs if d.is_dir()), None)
    if _dist:
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse

        _index = _dist / "index.html"
        _assets = _dist / "assets"

        @app.get("/")
        async def _index_route():
            return FileResponse(_index)

        if _assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

        # SPA 兜底：未注册的 GET（如 /ai、/shell）回 index.html，交给 React Router
        @app.get("/{_full_path:path}", include_in_schema=False)
        async def _spa_fallback(_full_path: str):
            # 已存在的静态文件优先（favicon 等）
            _candidate = _dist / _full_path
            if _candidate.is_file():
                return FileResponse(_candidate)
            return FileResponse(_index)

        print(f"[bridge] 静态服务: {str(_dist)} (webview 单入口)")
    else:
        print("[bridge] 未找到 web/dist（先 pnpm build）；webview 需浏览器打开 127.0.0.1:8765")

    return app


def _extract_bearer(authorization: str) -> Optional[str]:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return authorization.strip()


# ---- 进程内 uvicorn（供 webview / 其他入口复用）----
import uvicorn


def run_blocking(port: Optional[int] = None) -> None:
    """同步启动 uvicorn（阻塞当前线程）。供 webview 主线程调用。
    注意：本模式下主线程被 uvicorn 占用；托盘可用。"""
    global _current_port
    port = port or find_free_port()
    _current_port = port
    app = build_app()
    _register_builtin_commands()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    print(f"[bridge] listening on 127.0.0.1:{port}")
    print(f"[bridge] token: {_token_mod.get_token()}")
    # 桌面托盘（daemon 线程；pystray 缺失 / 非 Windows / DAYBREAK_NO_TRAY=1 时静默跳过）
    start_tray(port)
    server.run()  # 阻塞


def pick_mode(argv: "list[str]") -> str:
    """入口形态（纯函数，可测试）：
    - 打包态（frozen）：默认 "windowed"（pywebview 原生窗口，方案 A）；带 --service 参数 → "service"（服务 + 浏览器旧形态）
    - 开发态（python -m bridge.main）："service"（不弹窗口，避免打扰开发）"""
    if getattr(sys, "frozen", False) and "--service" not in argv:
        return "windowed"
    return "service"


# ---- 自定义窗口控件（v2.0.8 起窗口形态为无边框：web 顶栏驱动 移动/最大化/拉伸/关闭）----
# 坐标约定：pywebview 的 move/resize 与 .x/.y/.width/.height 均为「逻辑像素」
# （WinForms 后端内部乘窗口 DPI scale）；web 端 e.screenX/screenY 同为 DIP，增量直接可用。
_WINDOWED_UI = False  # 模块标志：run_windowed 创建窗口前置 True；app.env 命令返回
_WINDOW_MIN_W, _WINDOW_MIN_H = 960, 600  # 与 run_windowed 的 min_size 同源


def get_app_env() -> dict:
    """进程运行形态（web 端据此决定渲染 关闭X/最大化/拖移/拉伸 控件；非窗口形态不渲染）。"""
    return {"windowed": _WINDOWED_UI, "frameless": _WINDOWED_UI, "platform": sys.platform}


def _active_window():
    """当前 pywebview 主窗口（非窗口形态 / 窗口未创建 → None）。"""
    try:
        import webview as _webview
        return _webview.windows[0] if _webview.windows else None
    except Exception:
        return None


def window_rect() -> Optional[dict]:
    """窗口位置/尺寸（逻辑像素）；不可用返回 None。web 端以此基准驱动 move/resize。"""
    w = _active_window()
    if w is None:
        return None
    try:
        return {"x": int(w.x), "y": int(w.y), "width": int(w.width), "height": int(w.height)}
    except Exception:
        return None


def move_window(x: int, y: int) -> dict:
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    try:
        w.move(int(x), int(y))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _clamp_window_size(width, height) -> "tuple[int, int]":
    """拉伸钳制到最小尺寸（与 min_size 同源）；纯函数可测。"""
    return max(int(width), _WINDOW_MIN_W), max(int(height), _WINDOW_MIN_H)


def resize_window(width, height) -> dict:
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    cw, ch = _clamp_window_size(width, height)
    try:
        w.resize(cw, ch)  # 默认 fix point = 左上角（NORTH|WEST）：右下角手柄放大/缩小
        return {"ok": True, "width": cw, "height": ch}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_MAX_STATE = {"maximized": False, "saved": None}


def _win_work_areas() -> "list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]":
    """各显示器 (物理边界, 物理工作区)。DPI aware 进程里 EnumDisplayMonitors/GetMonitorInfoW
    返回物理坐标；move/resize 入参（pywebview 逻辑）× 窗口 scale = 物理 → 同空间可比。"""
    import ctypes
    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_uint32)]

    mons: "list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]" = []

    def cb(hMon, _hdc, _lprc, _dw):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hMon, ctypes.byref(mi))
        mon = (mi.rcMonitor.left, mi.rcMonitor.top,
               mi.rcMonitor.right - mi.rcMonitor.left, mi.rcMonitor.bottom - mi.rcMonitor.top)
        work = (mi.rcWork.left, mi.rcWork.top,
                mi.rcWork.right - mi.rcWork.left, mi.rcWork.bottom - mi.rcWork.top)
        mons.append((mon, work))
        return True

    _cb_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    user32.EnumDisplayMonitors(None, None, _cb_type(cb), None)
    return mons


import threading as _threading

_geo_lock = _threading.Lock()


def _set_window_geometry(w, x, y, ww, hh) -> None:
    """单次原子 SetWindowPos（位置+大小一次提交）应用窗口几何（move/resize 入参空间，×窗口 scale → 物理）。
    为什么不用 pywebview 的 w.move()+w.resize() 两步：
    - 两步跨线程 SetWindowPos 快速连发时，WinForms UI 线程未消化完上一笔 WM_MOVE/WM_SIZE，
      第二笔被丢弃/半应用（v2.0.10 冒烟实测：快连点还原不生效，慢速则正常）；
    - 后端 resize 内部读 Location 决定固定点，跨线程读到旧值会把窗口钉回错误位置。
    串行锁 + 120ms 落定延时保证 UI 线程消化完再放行下一笔；ShowWindow(Normal) 清残留 showCmd。"""
    with _geo_lock:
        import ctypes
        import time
        user32 = ctypes.windll.user32
        handle = _handle_int(w)
        scale = _window_dpi_scale()
        # SWP_NOZORDER(0x04) | SWP_SHOWWINDOW(0x40) | SWP_NOACTIVATE(0x10)
        user32.SetWindowPos(handle, None, int(x * scale), int(y * scale),
                            int(ww * scale), int(hh * scale), 0x04 | 0x40 | 0x10)
        user32.ShowWindow(handle, 1)  # SW_SHOWNORMAL：清残留 Maximized/Minimized 状态
        time.sleep(0.12)  # 让 UI 线程消化 WM_MOVE/WM_SIZE，下一笔才不会被吞


def _handle_int(w) -> int:
    """WinForms 句柄 → 原生 int。pythonnet 下 Handle 是 .NET IntPtr（须 .ToInt32()；
    Python int() 不能直接解析 .NET 结构体）；非冻结/测试环境裸 int 兜底。"""
    h = w.native.Handle
    return h.ToInt32() if hasattr(h, "ToInt32") else int(h)


def _window_dpi_scale() -> float:
    """窗口所在显示器 scale（GetDpiForWindow/96 —— 与 WinForms 后端 move/resize 换算同源）。
    任何异常回退 1.0（宁可目标略偏，也不允许 None 导致落回原生最大化）。"""
    w = _active_window()
    if w is None:
        return 1.0
    try:
        import ctypes
        dpi = ctypes.windll.user32.GetDpiForWindow(_handle_int(w))
        return (dpi / 96.0) if dpi >= 96 else 1.0
    except Exception:
        return 1.0


def _win_maximize_target():
    """窗口所在显示器工作区（move/resize 入参 = 物理工作区 ÷ 窗口 scale）；**永不返回 None**：
    枚举失败时回退主屏全屏（GetSystemMetrics 物理值 ÷ 1.0）——Windows 路径不使用原生
    w.maximize()（无边框原生最大化 → showCmd=Maximized，其后紧跟的手动 SetWindowPos 会被
    Windows 忽略 = v2.0.9「第二次点击不响应」的根因）。"""
    w = _active_window()
    r = window_rect()
    scale = _window_dpi_scale()
    if w is None or r is None:
        return None
    mons = _win_work_areas()
    if mons:
        # 窗口物理中心 = 回读中心 × 窗口 scale（回读值即 物理÷scale）
        cx_phys = (r["x"] + r["width"] // 2) * scale
        cy_phys = (r["y"] + r["height"] // 2) * scale
        pick = None
        for mon, _work in mons:
            ml, mt, mw, mh = mon
            # ±20% 容差命中（跨屏中心歧义时取先命中者；主屏在前）
            if ml - mw * 0.2 <= cx_phys <= ml + mw * 1.2 and mt - mh * 0.2 <= cy_phys <= mt + mh * 1.2:
                pick = (mon, _work)
                break
        if pick is None:
            pick = mons[0]
        _mon, work = pick
        wl, wt, ww, wh = work
        return (int(wl / scale), int(wt / scale), int(ww / scale), int(wh / scale))
    # 兜底：主屏全屏（GetSystemMetrics 物理值 ÷1.0；主屏 100% 时精确，125% 时略大——可接受）
    import ctypes
    user32 = ctypes.windll.user32
    sw = user32.GetSystemMetrics(0)  # SM_CXSCREEN（主屏物理宽）
    sh = user32.GetSystemMetrics(1)  # SM_CYSCREEN（主屏物理高）
    return (0, 0, sw, sh)


def _is_maximized_geometry(rect, target, tol=8) -> bool:
    """几何判定：当前窗口 rect 是否 ≈ 某显示器工作区目标（move/resize 入参空间，±tol 逻辑 px）。
    纯函数（可单测）。用途：最大化 toggle 不信任标志位——页面重载/任务栏往返/最大化中
    手动改大小都会让标志与真实几何脱节；按几何判定则每次点击幂等自愈。"""
    if not rect or not target:
        return False
    return (abs(rect["x"] - target[0]) <= tol and abs(rect["y"] - target[1]) <= tol
            and abs(rect["width"] - target[2]) <= tol and abs(rect["height"] - target[3]) <= tol)


def toggle_maximize() -> dict:
    """最大化/还原 toggle（几何驱动，幂等自愈）。
    Windows：读当前几何 vs 工作区目标判定 已/未最大化 → 手动 move/resize（WindowState 保持
    Normal，避开无边框原生最大化盖任务栏；_MAX_STATE.saved 仅作「最大化前几何」缓存）。
    无论此前点过几次、是否重载页面/动过任务栏，结果都由真实几何决定，不存在失步卡死态。
    macOS/Linux：原生 maximize()/restore()（无边框下行为正常，保留标志位配对）。
    返回 {"maximized": bool} 供 web 端切换图标。"""
    global _MAX_STATE
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    try:
        if sys.platform == "win32":
            r = window_rect()
            if r is None:
                return {"ok": False, "error": "window unavailable"}
            target = _win_maximize_target()
            if target and _is_maximized_geometry(r, target):
                # 处于最大化 → 还原（saved 缺失回退默认 1280×800 居中语义：0,0 由 WinForms 初始位决定）
                x, y, ww, hh = _MAX_STATE.get("saved") or (0, 0, 1280, 800)
                _set_window_geometry(w, x, y, ww, hh)
                _MAX_STATE = {"saved": None}
                return {"ok": True, "maximized": False}
            # 非最大化 → 最大化（先缓存当前几何供还原）
            _MAX_STATE = {"saved": (r["x"], r["y"], r["width"], r["height"])}
            target = _win_maximize_target()
            if target:
                _set_window_geometry(w, target[0], target[1], target[2], target[3])
            else:  # 窗口不可读（罕见）：保持现状，不切标志
                return {"ok": False, "error": "window unavailable"}
            return {"ok": True, "maximized": True}
        # macOS / Linux：原生最大化/还原（标志位配对；无边框在 cocoa/gtk 下行为正常）
        if _MAX_STATE.get("maximized"):
            w.restore()
            _MAX_STATE = {"maximized": False, "saved": None}
            return {"ok": True, "maximized": False}
        w.maximize()
        _MAX_STATE = {"maximized": True, "saved": None}
        return {"ok": True, "maximized": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def set_window_rect(x, y, w, h) -> dict:
    """窗口几何原子设置（位置+大小一次 SetWindowPos；边缘左缘/左下拖拽用——先挪左上角再改宽，
    两步分开快连发会被 UI 线程吞一笔）。尺寸走 _clamp_window_size（与 window.resize 同源）。"""
    w_win = _active_window()
    if w_win is None:
        return {"ok": False, "error": "window unavailable"}
    try:
        cw, ch = _clamp_window_size(w, h)
        _set_window_geometry(w_win, int(x), int(y), cw, ch)
        return {"ok": True, "x": int(x), "y": int(y), "width": cw, "height": ch}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def minimize_window() -> dict:
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    try:
        w.minimize()  # 原生最小化（winforms 后端 Invoke 线程 marshaling；任务栏图标可还原/关闭兜底）
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def quit_app() -> None:
    """关闭应用程序：终止全进程（与托盘「退出破晓工具箱」同语义；daemon 线程随进程消失）。"""
    print("[bridge] app.quit requested; exiting process")
    os._exit(0)


def run_windowed(port: Optional[int] = None) -> None:
    """打包窗口模式（方案 A）：主线程跑 pywebview 原生窗口（Windows=WebView2 / macOS=WKWebView /
    Linux=WebKitGTK），加载同源桥接 UI；uvicorn / 托盘均为 daemon 后台线程。
    v2.0.8 起无边框（frameless）：原生标题栏移除，窗口操作（移动/最大化/拉伸/关闭）由 web 顶栏驱动。

    - 关闭窗口 → 退出全进程（与托盘「退出破晓工具箱」同语义；想服务常驻请用 --service）
    - 窗口引擎不可用（无 WebView2 / 无显示环境等）→ 降级「服务 + 默认浏览器」并保持进程存活
    """
    global _current_port, _WINDOWED_UI
    import threading as _threading

    from .menu_service import project_root as _project_root

    port = port or find_free_port()
    _current_port = port
    app = build_app()
    _register_builtin_commands()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    srv = _threading.Thread(target=server.run, name="bridge-uvicorn", daemon=True)
    srv.start()
    for _ in range(100):
        if server.should_exit or server.started:
            break
        srv.join(0.1)
    url = f"http://127.0.0.1:{port}/"
    if not server.started:
        # v2.0.12：10s 内桥接未就绪（端口竞态/异常）→ 不继续开空白窗口，降级浏览器模式
        print(f"[bridge] 警告：桥接服务 10s 内未就绪（should_exit={server.should_exit}），"
              f"降级服务模式（浏览器打开）")
        _fallback_browser(port, url)
        _threading.Event().wait()  # 保持进程存活（uvicorn 可能稍后恢复；托盘仍可用）
        return
    print(f"[bridge] listening on 127.0.0.1:{port} (windowed)")
    print(f"[bridge] token: {_token_mod.get_token()}")

    _pr = _project_root()
    _WINDOWED_UI = True  # app.env → web 端渲染 关闭X/最大化/拖移/拉伸 控件
    start_tray(port, root=_pr)

    try:
        import webview
        webview.create_window("破晓·工具箱", url, width=1280, height=800,
                              resizable=True, min_size=(960, 600), frameless=True)
        webview.start()  # 阻塞：主线程窗口消息循环；窗口关闭后返回
    except Exception as e:
        print(f"[bridge] 窗口模式不可用（{type(e).__name__}: {e}）；降级服务模式，用默认浏览器打开界面")
        _fallback_browser(port, url)
        _threading.Event().wait()  # 服务模式：保持进程存活（uvicorn/托盘为 daemon 线程）
        return

    # 窗口关闭 → 退出全进程（与托盘「退出」同语义）
    print("[bridge] 窗口已关闭，退出进程（想服务常驻请用 --service 参数启动）")
    os._exit(0)


def _fallback_browser(port: int, url: str) -> None:
    """窗口/桥接不可用时的兜底：0.5s 后开默认浏览器。"""
    import webbrowser
    import threading as _threading
    try:
        _threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    except Exception:
        pass


def main() -> None:
    """python -m bridge.main —— 直接启动（前台）。
    线程模型：uvicorn 后台线程 + 托盘 daemon 线程。
    打包态默认走窗口模式（run_windowed）；--service / 开发态走本路径。"""
    global _current_port
    import threading as _threading

    from .menu_service import project_root as _project_root

    if pick_mode(sys.argv[1:]) == "windowed":
        run_windowed()
        return

    port = find_free_port()
    _current_port = port
    if not getattr(sys, "frozen", False):
        # 开发态：日志输出到 stderr（bridge 诊断；frozen 态由 run_bootstrap 统一落盘）
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = build_app()
    _register_builtin_commands()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    srv = _threading.Thread(target=server.run, name="bridge-uvicorn", daemon=True)
    srv.start()
    for _ in range(100):
        if server.should_exit:
            break
        if server.started:
            break
        srv.join(0.1)
    if not server.started:
        # v2.0.12：桥接未就绪警告（托盘/进程仍存活，uvicorn 稍后可能恢复；不静默）
        print(f"[bridge] 警告：桥接服务 10s 内未就绪（should_exit={server.should_exit}）；"
              f"进程/托盘保持，界面暂不可用")
    else:
        print(f"[bridge] listening on 127.0.0.1:{port}")
    print(f"[bridge] token: {_token_mod.get_token()}")
    print(f"[bridge] 界面地址 http://127.0.0.1:{port}/ （托盘「打开首页」/ 浏览器手动访问亦可）")

    # 打包版（frozen）启动后自动打开浏览器界面；开发态不弹，避免打扰
    if getattr(sys, "frozen", False):
        import webbrowser as _webbrowser

        def _auto_open() -> None:
            try:
                _webbrowser.open(f"http://127.0.0.1:{port}/")
            except Exception as e:  # headless / 无默认浏览器等
                print(f"[bridge] 自动打开浏览器失败（请手动访问 http://127.0.0.1:{port}/）: {e}")

        _threading.Timer(1.2, _auto_open).start()

    # 服务形态：托盘 + 保活（uvicorn/托盘为 daemon 线程，主线程阻塞等待）
    start_tray(port, root=_project_root())
    _threading.Event().wait()


if __name__ == "__main__":
    main()
