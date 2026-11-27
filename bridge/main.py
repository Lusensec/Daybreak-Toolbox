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

# ---- v2.0.14 启动计时：各阶段耗时（ms）打 [perf] 行进 daybreak.log（启动优化的数据基线）----
_PERF_T0 = time.perf_counter()


def _perf(stage: str) -> None:
    print(f"[perf] {stage} {int((time.perf_counter() - _PERF_T0) * 1000)}ms")


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

    # ---- 通用设置（v2.0.15 config/settings.json：close_to_tray 等前后端共享偏好）----
    from . import settings_service as _settings_mod

    async def _settings_get(_p, _ws):
        return await asyncio.to_thread(_settings_mod.get_all)

    async def _settings_set(p, _ws):
        try:
            r = await asyncio.to_thread(_settings_mod.set, p)
        except _settings_mod.SettingsError as e:
            raise BridgeError(e.code, e.message)
        await _bus.broadcast("settings.changed", r)  # 多客户端同步（第二 webview/浏览器端同显）
        return {"ok": True, **r}

    _bus.register("settings.get", _settings_get)
    _bus.register("settings.set", _settings_set)

    # ---- 应用形态 / 自定义窗口控件（v2.0.8 无边框窗口：web 顶栏驱动 移动/最大化/拉伸/关闭）----
    async def _app_env(_p, _ws):
        return get_app_env()

    async def _app_quit(_p, _ws):
        # v2.0.15：「关闭后进入最小化」开启时 quit_app 最小化驻留托盘并返回 ack（不终止进程）；
        # 否则进程终止（本 handler 不返回）
        return await asyncio.to_thread(quit_app)

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

    async def _window_set_background(p, _ws):
        return await asyncio.to_thread(set_window_background, int(p.get("r", 0)), int(p.get("g", 0)), int(p.get("b", 0)))

    async def _window_drag_begin(_p, _ws):
        return await asyncio.to_thread(drag_begin)

    async def _window_drag_end(_p, _ws):
        return await asyncio.to_thread(drag_end)

    _bus.register("app.env", _app_env)
    _bus.register("app.quit", _app_quit)
    _bus.register("window.get_rect", _window_get_rect)
    _bus.register("window.move", _window_move)
    _bus.register("window.resize", _window_resize)
    _bus.register("window.maximize", _window_maximize)
    _bus.register("window.minimize", _window_minimize)
    _bus.register("window.set_rect", _window_set_rect)
    _bus.register("window.set_background", _window_set_background)
    _bus.register("window.drag_begin", _window_drag_begin)
    _bus.register("window.drag_end", _window_drag_end)

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

    app = FastAPI(title="Daybreak Toolbox Bridge", version="2.1.1", lifespan=_lifespan)
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
# v2.0.20：窗口尺寸固定为主屏工作区的 80%（用户要求：不可拖拽拉伸，仅保留 最大化/还原）。
# _FIXED_WINDOW_SIZE 由 run_windowed 启动时写入（逻辑像素），此后所有 resize/set_rect 都钳到该值。
_WINDOW_SIZE_RATIO = 0.8
_FIXED_WINDOW_SIZE: "tuple[int, int] | None" = None



def get_app_env() -> dict:
    """进程运行形态（web 端据此决定渲染 关闭X/最大化/拖移/拉伸 控件；非窗口形态不渲染）。
    v2.0.18：新增 version（单一来源 update_service.APP_VERSION；web 品牌区展示，取不到不渲染）。"""
    return {"windowed": _WINDOWED_UI, "frameless": _WINDOWED_UI, "platform": sys.platform,
            "version": APP_VERSION}


def _active_window():
    """当前 pywebview 主窗口（非窗口形态 / 窗口未创建 → None）。"""
    try:
        import webview as _webview
        return _webview.windows[0] if _webview.windows else None
    except Exception:
        return None


def window_rect() -> Optional[dict]:
    """窗口位置/尺寸（逻辑像素，主屏基准虚拟桌面；v2.0.14 按 per-monitor scale 精确换算——
    窗口在副屏/混合缩放时不再漂移）。不可用返回 None。web 端以此基准驱动 move/resize。"""
    w = _active_window()
    if w is None:
        return None
    try:
        phys = _get_window_phys(w)
        if phys:
            lx, ly, lw, lh = _physical_to_logical(*phys, _monitor_info_safe())
            return {"x": lx, "y": ly, "width": lw, "height": lh}
        return {"x": int(w.x), "y": int(w.y), "width": int(w.width), "height": int(w.height)}
    except Exception:
        return None


def move_window(x: int, y: int) -> dict:
    """移动窗口（v2.0.14：单次原子 SetWindowPos，位置走 per-monitor 逻辑→物理换算，
    尺寸保持当前物理值不变；替代旧 pywebview w.move 两步路径）。"""
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    try:
        mons = _monitor_info_safe()
        px, py, _pw, _ph = _logical_to_physical(int(x), int(y), 0, 0, mons)
        # v2.0.16：顶栏拖拽流（60fps 连发）不串行等 120ms —— 同步 SetWindowPos 连发安全，
        # 落定延时留给一次性状态变更（settle 默认 True 的调用方）
        _set_window_geometry_phys(w, px, py, 0, 0, keep_size=True, settle=False)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _clamp_window_size(width, height) -> "tuple[int, int]":
    """尺寸钳制（纯函数可测）。
    v2.0.20：固定尺寸模式（_FIXED_WINDOW_SIZE 已由 run_windowed 写入）下恒返回 80% 工作区尺寸
    —— 窗口不可拖拽拉伸；最大化/还原走 _set_window_geometry（不经本函数）不受影响。
    固定值未初始化（服务形态 / 单测）时保持旧的最小尺寸钳制语义。"""
    if _FIXED_WINDOW_SIZE:
        return _FIXED_WINDOW_SIZE
    return max(int(width), _WINDOW_MIN_W), max(int(height), _WINDOW_MIN_H)


def resize_window(width, height) -> dict:
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    cw, ch = _clamp_window_size(width, height)
    try:
        # v2.0.14：原子 SetWindowPos（旧 pywebview w.resize 两步路径的快连发隐患一并消除）；
        # 位置保持当前物理值，逻辑尺寸 × 当前所在显示器 scale 换算
        mons = _monitor_info_safe()
        phys = _get_window_phys(w) or (0, 0, int(cw), int(ch))
        s_anchor = _monitor_scale_at(phys[0], phys[1], mons)
        _set_window_geometry_phys(w, phys[0], phys[1], int(round(cw * s_anchor)), int(round(ch * s_anchor)))
        return {"ok": True, "width": cw, "height": ch}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_MAX_STATE = {"maximized": False, "saved": None}


def _monitor_info() -> "list[dict]":
    """各显示器信息（v2.0.14 混合 DPI 修复）：{mon:物理边界, work:物理工作区, primary:bool, scale:自身缩放}。

    Per-Monitor-DPI aware 进程里 EnumDisplayMonitors/GetMonitorInfoW 返回物理坐标；
    每屏 scale 用 GetDpiForMonitor（MMD 精确值），任何环节失败回退窗口 GetDpiForWindow。"""
    import ctypes
    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_uint32)]

    raw: "list[tuple[object, tuple, tuple, bool]]" = []

    def cb(hMon, _hdc, _lprc, _dw):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hMon, ctypes.byref(mi))
        mon = (mi.rcMonitor.left, mi.rcMonitor.top,
               mi.rcMonitor.right - mi.rcMonitor.left, mi.rcMonitor.bottom - mi.rcMonitor.top)
        work = (mi.rcWork.left, mi.rcWork.top,
                mi.rcWork.right - mi.rcWork.left, mi.rcWork.bottom - mi.rcWork.top)
        raw.append((hMon, mon, work, bool(mi.dwFlags & 1)))
        return True

    _cb_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    user32.EnumDisplayMonitors(None, None, _cb_type(cb), None)

    fallback = _window_dpi_scale()  # 窗口 scale 作兜底（主屏单屏常见 1.0/1.25）
    out: "list[dict]" = []
    for hMon, mon, work, is_primary in raw:
        out.append({"mon": mon, "work": work, "primary": is_primary,
                    "scale": _monitor_scale(hMon, fallback)})
    return out


def _monitor_info_safe() -> "list[dict]":
    """_monitor_info 的异常安全版（非 Windows / 枚举失败 → []，调用方走降级路径）。"""
    try:
        return _monitor_info()
    except Exception:
        return []


def _fixed_window_geometry() -> "tuple[int, int, int, int]":
    """v2.0.20：固定窗口几何（逻辑像素，x, y, w, h）——主屏工作区的 80%，水平/垂直居中。
    不依赖窗口已创建（create_window 前置调用）；枚举失败回退 1280×800（≈1600×1000 屏的 80%）。
    纯计算、无副作用（可单测）。"""
    mons = _monitor_info_safe()
    if mons:
        pick = next((m for m in mons if m.get("primary")), mons[0])
        wl, wt, ww, wh = pick["work"]
        try:
            lx, ly, lw, lh = _physical_to_logical(wl, wt, ww, wh, mons)
        except Exception:  # 换算异常：按物理值直接用（单屏 100% 缩放下二者等价）
            lx, ly, lw, lh = int(wl), int(wt), int(ww), int(wh)
        fw = max(1, int(round(lw * _WINDOW_SIZE_RATIO)))
        fh = max(1, int(round(lh * _WINDOW_SIZE_RATIO)))
        return (int(lx) + (int(lw) - fw) // 2, int(ly) + (int(lh) - fh) // 2, fw, fh)
    return (0, 0, 1280, 800)



#: v2.0.18：_monitor_info 结果缓存（TTL 30s）——拖拽流每帧 _monitor_info（EnumDisplayMonitors
#: + GetDpiForMonitor）开销可观且结果低频变化（显示器插拔/缩放变更 <30s），缓存续缓拖拽流
#: 的 CPU/GC 压力；_monitor_info_cached 命中即返回同一 list（调用方只读，不共享可变引用）。
_MONITOR_CACHE: "tuple[float, list] | None" = None
_MONITOR_TTL = 30.0


def _monitor_info_cached() -> "list[dict]":
    """_monitor_info_safe 的带 TTL 缓存版（流式路径 set_window_rect 用；一次性状态变更仍走
    _monitor_info_safe 现枚举，保证 maximize/restore 读到真实工作区）。"""
    global _MONITOR_CACHE
    now = time.monotonic()
    if _MONITOR_CACHE and now - _MONITOR_CACHE[0] < _MONITOR_TTL:
        return _MONITOR_CACHE[1]
    info = _monitor_info_safe()
    _MONITOR_CACHE = (now, info)
    return info


def _monitor_scale(hMon, fallback: float = 1.0) -> float:
    """单显示器 scale（GetDpiForMonitor / 96；Win10+ 有，异常/不支持回退 fallback）。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        dpi = ctypes.c_uint32()
        r = user32.GetDpiForMonitor(hMon, 0, ctypes.byref(dpi), None)  # MDT_EFFECTIVEDPI = 0
        if r == 0 and dpi.value >= 96:
            return dpi.value / 96.0
    except Exception:
        pass
    return float(fallback)


def _win_work_areas() -> "list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]":
    """各显示器 (物理边界, 物理工作区)。兼容旧调用/单测契约（tuple 形式）。"""
    return [(m["mon"], m["work"]) for m in _monitor_info_safe()]


# ---- v2.0.14 混合 DPI 坐标模型（纯函数，可单测；mons 为 _monitor_info 输出）----
# 模型（Windows 真实行为）：逻辑虚拟桌面以主屏物理原点为 (0,0)；
# 显示器 m 的逻辑位置 = (L_m/s_p, T_m/s_p)（s_p = 主屏 scale，位置按主屏比例映射），
# 逻辑尺寸 = (W_m/s_m, H_m/s_m)（自身 scale）。窗口尺寸按其左上角所在显示器的 scale 换算。

def _pick_logical_monitor(x, y, w, h, mons, sp) -> "dict | None":
    """逻辑左上角（退化：中心 → 主屏）落在哪个显示器。纯函数。"""
    pts = [(x, y)]
    if w and h:
        pts.append((x + w / 2.0, y + h / 2.0))
    for px, py in pts:
        for m in mons:
            L, T, W, H = m["mon"]
            s = float(m.get("scale") or sp) or 1.0
            ll, lt = L / sp, T / sp
            if ll <= px < ll + W / s and lt <= py < lt + H / s:
                return m
    return next((m for m in mons if m.get("primary")), None)


def _pick_physical_monitor(px, py, pw, ph, mons) -> "dict | None":
    """物理左上角（退化：中心 → 主屏）落在哪个显示器。纯函数。"""
    pts = [(px, py)]
    if pw and ph:
        pts.append((px + pw / 2.0, py + ph / 2.0))
    for cx, cy in pts:
        for m in mons:
            L, T, W, H = m["mon"]
            if L <= cx < L + W and T <= cy < T + H:
                return m
    return next((m for m in mons if m.get("primary")), None)


def _logical_to_physical(x, y, w, h, mons) -> "tuple[int, int, int, int]":
    """逻辑坐标（浏览器 screenX/screenY 同空间，主屏基准）→ 目标显示器物理坐标（SetWindowPos 入参）。
    锚点 = 逻辑左上角所在显示器：phys = L + (x − L/s_p) × s_m。无显示器信息 → 按主屏 scale 直乘（单屏退化）。"""
    if not mons:
        return int(round(x)), int(round(y)), int(round(w)), int(round(h))
    primary = next((m for m in mons if m.get("primary")), mons[0])
    sp = float(primary.get("scale") or 1.0) or 1.0
    target = _pick_logical_monitor(x, y, w, h, mons, sp)
    if target is None:
        s = sp
        return (int(round(x * s)), int(round(y * s)), int(round(w * s)), int(round(h * s)))
    L, T, W, H = target["mon"]
    s = float(target.get("scale") or sp) or 1.0
    return (int(round(L + (x - L / sp) * s)),
            int(round(T + (y - T / sp) * s)),
            int(round(w * s)),
            int(round(h * s)))


def _physical_to_logical(px, py, pw, ph, mons) -> "tuple[int, int, int, int]":
    """窗口物理矩形（GetWindowRect）→ 逻辑坐标（_logical_to_physical 的逆；window_rect / 最大化判定用）。
    无显示器信息 → 主屏 scale 直除（单屏退化 = 旧行为）。"""
    if not mons:
        return int(round(px)), int(round(py)), int(round(pw)), int(round(ph))
    primary = next((m for m in mons if m.get("primary")), mons[0])
    sp = float(primary.get("scale") or 1.0) or 1.0
    target = _pick_physical_monitor(px, py, pw, ph, mons)
    if target is None:
        s = sp
        return (int(round(px / s)), int(round(py / s)), int(round(pw / s)), int(round(ph / s)))
    L, T, W, H = target["mon"]
    s = float(target.get("scale") or sp) or 1.0
    return (int(round(L / sp + (px - L) / s)),
            int(round(T / sp + (py - T) / s)),
            int(round(pw / s)),
            int(round(ph / s)))


def _get_window_phys(w) -> "tuple[int, int, int, int] | None":
    """窗口物理矩形（GetWindowRect；失败 None）。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        class _R(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]

        rc = _R()
        if not user32.GetWindowRect(_handle_int(w), ctypes.byref(rc)):
            return None
        return (rc.l, rc.t, rc.r - rc.l, rc.b - rc.t)
    except Exception:
        return None


def _monitor_scale_at(px, py, mons) -> float:
    """物理点 (px, py) 所在显示器 scale（回退主屏 → 1.0）。"""
    m = _pick_physical_monitor(px, py, 0, 0, mons) or next((x for x in mons if x.get("primary")), None)
    return float(m.get("scale") or 1.0) if m else 1.0


import threading as _threading

_geo_lock = _threading.Lock()


def _set_window_geometry_phys(w, px, py, pw, ph, keep_size: bool = False,
                              settle: bool = True) -> None:
    """单次原子 SetWindowPos（**物理**入参；位置+大小一次提交）。
    为什么不用 pywebview 的 w.move()+w.resize() 两步：
    - 两步跨线程 .NET Invoke 快速连发时，WinForms UI 线程未消化完上一笔 WM_MOVE/WM_SIZE，
      第二笔被丢弃/半应用（v2.0.10 冒烟实测：快连点还原不生效，慢速则正常）；
    - 后端 resize 内部读 Location 决定固定点，跨线程读到旧值会把窗口钉回错误位置。
    串行锁保证原子性；ShowWindow(Normal) 清残留 showCmd（仅 settle=True 一次性路径——
    流式路径 60fps 每笔 ShowWindow 会强制重绘触发闪烁，v2.0.17 移除）。
    v2.0.18：SetWindowPos 的 SWP_SHOWWINDOW（0x40）位同样仅 settle=True 携带
    （流式每笔强制 show 语义 = 每帧重绘压力，与 ShowWindow(Normal) 同因）。
    keep_size=True 时忽略 pw/ph，保持窗口当前物理尺寸（move 用）。
    settle（v2.0.16）：120ms 落定延时 —— 仅「一次性状态变更」（最大化/还原/单条 resize）需要，
    给 WebView2 布局留消化时间；**连续拖拽流**（顶栏 move / 边缘 set_rect，60fps）置 False：
    直接 SetWindowPos 是同步 Win32 调用（非 .NET Invoke），连发无吞包，120ms 串行会把拖动
    限速到 8Hz（明显滞后）并堵满 FIFO 队列（其他命令如 tool.grid 排队超时）。"""
    import ctypes
    import time
    with _geo_lock:
        user32 = ctypes.windll.user32
        handle = _handle_int(w)
        if keep_size:
            cur = _get_window_phys(w)
            pw, ph = (cur[2], cur[3]) if cur else (int(pw), int(ph))
        # 0x04 NOZORDER | 0x40 SHOWWINDOW | 0x10 NOACTIVATE。
        # v2.0.18：SHOWWINDOW 仅一次性（settle=True）路径携带——流式 60fps 每笔强制 show 语义
        # 触发重绘是拉伸闪烁根因之一（与 v2.0.17 去每帧 ShowWindow(Normal) 同因）；
        # settle 路径保留（清残留 showCmd + 其后显式 ShowWindow(Normal) 双保险）。
        flags = 0x04 | (0x40 if settle else 0) | 0x10
        user32.SetWindowPos(handle, None, int(px), int(py), int(pw), int(ph), flags)
        if settle:
            user32.ShowWindow(handle, 1)  # SW_SHOWNORMAL：清残留 Maximized/Minimized 状态
            time.sleep(0.12)  # 让 UI 线程消化 WM_MOVE/WM_SIZE，下一笔才不会被吞


def _set_window_geometry(w, x, y, ww, hh, settle: bool = True) -> None:
    """**逻辑**入参（web 端 screenX/screenY 同空间，主屏基准）的窗口几何应用：
    v2.0.14 经 per-monitor scale 模型换算成物理后原子提交（混合 DPI 跨屏不再漂移；
    无显示器信息时退化为单屏主 scale 直乘 = 旧行为）。settle 见 _set_window_geometry_phys。"""
    mons = _monitor_info_safe()
    px, py, pw, ph = _logical_to_physical(x, y, ww, hh, mons)
    _set_window_geometry_phys(w, px, py, pw, ph, settle=settle)


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
    """窗口所在显示器工作区的**逻辑**目标（v2.0.14：per-monitor scale 精确换算；
    旧版 物理÷窗口scale 在混合 DPI 下漂移）。**永不返回 None**：
    枚举失败时回退主屏全屏（GetSystemMetrics 物理值 → 主屏 scale 换算）。Windows 路径不使用
    原生 w.maximize()（无边框原生最大化 → showCmd=Maximized，其后紧跟的手动 SetWindowPos
    会被 Windows 忽略 = v2.0.9「第二次点击不响应」的根因）。"""
    mons = _monitor_info_safe()
    w = _active_window()
    if mons:
        phys = _get_window_phys(w) if w is not None else None
        pick = _pick_physical_monitor(*phys, mons) if phys else next((m for m in mons if m.get("primary")), mons[0])
        wl, wt, ww, wh = pick["work"]
        return _physical_to_logical(wl, wt, ww, wh, mons)
    # 兜底：主屏全屏（物理值 → 逻辑）
    import ctypes
    user32 = ctypes.windll.user32
    sw = user32.GetSystemMetrics(0)  # SM_CXSCREEN（主屏物理宽）
    sh = user32.GetSystemMetrics(1)  # SM_CYSCREEN（主屏物理高）
    sp = float(next((m.get("scale") for m in mons if m.get("primary")), 1.0)) or 1.0
    return (0, 0, int(round(sw / sp)), int(round(sh / sp)))


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
                # 处于最大化 → 还原（saved 缺失回退固定 80% 工作区居中——v2.0.20 窗口尺寸固定）
                x, y, ww, hh = _MAX_STATE.get("saved") or _fixed_window_geometry()
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
    两步分开快连发会被 UI 线程吞一笔）。尺寸走 _clamp_window_size（与 window.resize 同源）。
    v2.0.18：拖拽流（settle=False）几何逐像素不变时直接 no-op（不触 Win32 重入）；
    流式路径用 _monitor_info_cached 避免每帧 EnumDisplayMonitors+GetDpiForMonitor。"""
    w_win = _active_window()
    if w_win is None:
        return {"ok": False, "error": "window unavailable"}
    try:
        cw, ch = _clamp_window_size(w, h)
        # v2.0.16：边缘拖拽流（连续 set_rect）不串行等 120ms（同上：同步 SetWindowPos 连发安全）
        mons = _monitor_info_cached()
        px, py, pw, ph = _logical_to_physical(int(x), int(y), cw, ch, mons)
        cur = _get_window_phys(w_win)
        if cur and cur[0] == px and cur[1] == py and cur[2] == pw and cur[3] == ph:
            # 无变化 no-op：几何完全一致才不触 Win32（v2.0.20：固定尺寸下尺寸恒等，
            # 若只比尺寸会把「纯位置变化」误判为 no-op —— 位置也必须参与比较）
            return {"ok": True, "x": int(x), "y": int(y), "width": cw, "height": ch, "noop": True}
        _set_window_geometry_phys(w_win, px, py, pw, ph, settle=False)
        # v2.0.19：每笔拉伸帧刷新看门狗时间戳（正常拖拽永不触发 3s 超时）
        if _DRAG_REDRAW["active"]:
            _DRAG_REDRAW["last"] = time.monotonic()
        return {"ok": True, "x": int(x), "y": int(y), "width": cw, "height": ch}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---- v2.0.19：拖拽期间挂起 WM_SETREDRAW，消除「几何已变 / WebView2 内容未合成」的露底闪烁 ----
# SetWindowPos 是同步 Win32 调用（外框瞬间变化），而 WebView2 内容合成是异步的；
# 快速拉伸时新暴露的条带先画窗体背景、下一帧才被内容覆盖 → 肉眼可见闪烁。
# 拖拽开始时 SendMessageTimeout(WM_SETREDRAW,0) 挂起绘制（含子窗口），结束时恢复并整体刷新。
_DRAG_REDRAW: dict = {"hwnd": 0, "active": False, "last": 0.0,
                      "lock": _threading.Lock(), "watchdog": None}


def _drag_watchdog(hwnd: int, token: object) -> None:
    """兜底看门狗：drag_end 丢失（页面崩溃/WS 断线/鼠标在窗口外释放）时强制恢复重绘，
    避免窗口永久「冻结」在 WM_SETREDRAW=0。3s 无新活动（正常拖拽每帧 set_rect 刷新）即脱手。"""
    import time as _t
    while True:
        _t.sleep(0.5)
        with _DRAG_REDRAW["lock"]:
            if not _DRAG_REDRAW["active"] or _DRAG_REDRAW["hwnd"] != hwnd:
                return
            if _t.monotonic() - _DRAG_REDRAW["last"] > 3.0:
                _DRAG_REDRAW["active"] = False
                _DRAG_REDRAW["watchdog"] = None
                force = True
            else:
                force = False
        if force:
            print("[bridge] 拖拽重绘看门狗超时：自动恢复 WM_SETREDRAW")
            _apply_drag_redraw(hwnd, False)
            return


def _apply_drag_redraw(hwnd: int, suspend: bool) -> dict:
    """对窗口发送 WM_SETREDRAW；恢复时整体失效重绘。
    SendMessageTimeout 带 1s 上限，避免 UI 线程忙时 worker 永久阻塞。
    v2.0.20：**只处理顶层窗体，不再遍历子窗口**——WebView2 宿主窗口被 WM_SETREDRAW=0
    冻结合成后，恢复时可能整片空白（v2.0.19 实测「点击左上角黑/白屏」的直接原因）。
    顶层挂起只影响窗体背景绘制，露底条带仍由 GCLP_HBRBACKGROUND 兜底同色。"""
    if sys.platform != "win32":
        return {"ok": False, "error": "win32 only"}
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        WM_SETREDRAW = 0x000B
        RDW_INVALIDATE, RDW_ALLCHILDREN, RDW_ERASE, RDW_FRAME = 0x0001, 0x0080, 0x0004, 0x0400
        SMTO_ABORTIFHUNG = 0x0002
        user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                               wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                               ctypes.c_void_p]
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t

        user32.SendMessageTimeoutW(wintypes.HWND(int(hwnd)), WM_SETREDRAW,
                                   0 if suspend else 1, 0, SMTO_ABORTIFHUNG, 1000, None)
        if not suspend:
            user32.RedrawWindow(wintypes.HWND(int(hwnd)), None, None,
                                RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_ERASE | RDW_FRAME)
        return {"ok": True, "suspend": suspend, "windows": 1}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def drag_begin() -> dict:
    """拖拽流开始：挂起重绘 + 启动看门狗（重复调用只刷新活动时间戳）。"""
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    hwnd = _handle_int(w)
    with _DRAG_REDRAW["lock"]:
        first = not _DRAG_REDRAW["active"]
        if first:
            r = _apply_drag_redraw(hwnd, True)
            if not r.get("ok"):
                return r
            _DRAG_REDRAW["hwnd"] = hwnd
            _DRAG_REDRAW["active"] = True
            _DRAG_REDRAW["watchdog"] = _threading.Thread(
                target=_drag_watchdog, args=(hwnd, object()), daemon=True, name="drag-redraw-watch")
            _DRAG_REDRAW["watchdog"].start()
        _DRAG_REDRAW["last"] = time.monotonic()
    return {"ok": True, "active": True}


def drag_end() -> dict:
    """拖拽流结束：恢复重绘 + 停看门狗（未拖拽时 no-op，便于 mouseup 无条件调用）。"""
    with _DRAG_REDRAW["lock"]:
        if not _DRAG_REDRAW["active"]:
            return {"ok": True, "noop": True}
        hwnd = _DRAG_REDRAW["hwnd"]
        _DRAG_REDRAW["active"] = False
        _DRAG_REDRAW["watchdog"] = None
    return _apply_drag_redraw(hwnd, False)


def minimize_window() -> dict:
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    try:
        w.minimize()  # 原生最小化（winforms 后端 Invoke 线程 marshaling；任务栏图标可还原/关闭兜底）
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Win32 子类过程引用表（handle → 过程对象；必须持引用防 GC 回收，回收后回调野指针崩）
_SUBCLASS_PROCS: "dict[int, object]" = {}
# 子类回调（UI 线程）应用的 .NET 值：handle → {"bg": 预计算的 Color 对象, "min_applied": bool}
# （.NET 值在 worker 线程预计算——静态 FromArgb 调用安全；属性写只能发生在 UI 线程，
#  跨线程写 WinForms 属性即使关了检查也会死锁全进程，v2.0.17 实测）
_SUBCLASS_NET_VALUES: "dict[int, dict]" = {}

# v2.0.19：comctl32.SetWindowSubclass 在 PyInstaller frozen 环境静默失败（ICC 已初始化、
# GetLastError=0，实测 v2.0.17 记录）→ 增加 GWLP_WNDPROC 兜底。两者都把回调注册到
# _SUBCLASS_PROCS（供背景色/MinimumSize 归一化判定「钩子已装」），但转发路径不同：
#   comctl32 → DefSubclassProc；GWLP_WNDPROC → CallWindowProcW(原始 WndProc)。
_SUBCLASS_FORWARD: "dict[int, object]" = {}
_ORIGINAL_WNDPROC: "dict[int, int]" = {}


def _hwnd_key(hwnd) -> int:
    """ctypes 回调里的 hwnd 可能是 int 或 c_void_p（依 argtypes 而定），统一取整数键。"""
    if isinstance(hwnd, int):
        return hwnd
    return int(getattr(hwnd, "value", 0) or 0)


def _install_closing_hook() -> None:
    """v2.0.15/17/19：Win32 消息钩子统一处理：
    - WM_CLOSE / WM_SYSCOMMAND(SC_CLOSE)：「关闭后进入最小化」开启 → 吞掉并最小化驻留托盘；
      关闭 → 放行（旧语义：窗口销毁 → 退出进程）。事件时读盘判定（改设置即时生效）。
    - WM_USER+100（wParam=0xRRGGBB）/ WM_USER+101：在 **UI 线程** 应用窗体 BackColor /
      MinimumSize（worker 线程只 PostMessage 异步触发——跨线程直接写
      WinForms 属性会死锁全进程，v2.0.17 冒烟实测：uvicorn accept 停摆、全线程 0 CPU）。
    安装路径（v2.0.19 修复 frozen 下 SetWindowSubclass 静默失败）：
      1) comctl32.SetWindowSubclass（需 exe 携带 comctl32 v6 manifest——已嵌入）
      2) 失败 → SetWindowLongPtrW(GWLP_WNDPROC) 直接替换 WndProc（不依赖 comctl32 v6）
    两条路径共用同一回调；未接管消息分别经 DefSubclassProc / CallWindowProcW 转发原生链。
    best-effort：两条都失败仅记日志（关闭=退出旧语义，背景色走 GCLP_HBRBACKGROUND 兜底）。"""
    w = _active_window()
    if w is None or sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        h = wintypes.HWND(_handle_int(w))
        WM_CLOSE, WM_SYSCOMMAND, SC_CLOSE = 0x0010, 0x0112, 0xF050
        WMU_BG, WMU_MINSIZE = 0x0400 + 100, 0x0400 + 101

        hkey = _handle_int(w)

        def _apply_bg(rgb: int):
            """UI 线程回调内：应用 .NET BackColor（异常仅记日志，绝不跨线程 Invoke）。"""
            try:
                wf = _wf_types()
                if wf is None:
                    return
                r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
                i32 = wf.Int32
                form = _active_window().native if _active_window() else None
                if form is None:
                    return
                form.BackColor = wf.Color.FromArgb(i32(r), i32(g), i32(b))
                vals = _SUBCLASS_NET_VALUES.get(hkey)
                if vals is not None and not vals.get("bg_logged"):
                    vals["bg_logged"] = True
                    print(f"[bridge] UI 线程应用 BackColor 完成 rgb=0x{r:02X}{g:02X}{b:02X}")
            except Exception as ex:
                print(f"[bridge] UI 线程应用 BackColor 失败（跳过）：{ex}")

        def _apply_min_size():
            """UI 线程回调内：MinimumSize 归一化——逻辑 960×600 按窗口所在显示器 scale 换算为
            物理像素（v2.0.18：旧版写死 960×600 物理，>100% 缩放下物理最小值 < 逻辑最小值 →
            WinForms 回跳引发拉伸间隙抖动；现按 GetDpiForWindow 等比放大，钳制语义与
            _clamp_window_size 同源；100% 屏 scale=1.0 → 旧行为）。"""
            try:
                vals = _SUBCLASS_NET_VALUES.get(hkey)
                if not vals or vals.get("min_applied"):
                    return
                wf = _wf_types()
                form = _active_window().native if _active_window() else None
                if wf is None or form is None:
                    return
                i32 = wf.Int32
                scale = _window_dpi_scale()
                # v2.0.20：固定尺寸模式下 MinimumSize = 固定尺寸（窗口既不能缩小也不能拖拉伸；
                # 最大化/还原走 Win32 SetWindowPos 不受 MinimumSize 限制），非固定模式维持 960×600
                base_w, base_h = _FIXED_WINDOW_SIZE or (_WINDOW_MIN_W, _WINDOW_MIN_H)
                mw = int(round(base_w * scale))
                mh = int(round(base_h * scale))
                form.MinimumSize = wf.Size(i32(mw), i32(mh))
                vals["min_applied"] = True
                print(f"[bridge] WinForms 属性归一化完成（UI 线程：MinimumSize={mw}×{mh} 物理 = 逻辑 {base_w}×{base_h} @ {scale:g}x）")
            except Exception as ex:
                print(f"[bridge] UI 线程应用 MinimumSize 失败（跳过）：{ex}")

        def _proc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_CLOSE or (msg == WM_SYSCOMMAND and (wparam & 0xFFF0) == SC_CLOSE):
                    from . import settings_service
                    if settings_service.get_all().get("close_to_tray") and _active_window() is not None:
                        _active_window().minimize()
                        print("[bridge] 系统关窗拦截（Alt+F4/任务栏X）：关闭后进入最小化已开启 → 驻留托盘")
                        return 0
                elif msg == WMU_BG:
                    _apply_bg(wparam & 0xFFFFFF)
                    return 0
                elif msg == WMU_MINSIZE:
                    _apply_min_size()
                    return 0
            except Exception as ex:
                print(f"[bridge] closing hook 异常，放行：{ex}")
            # 未接管消息 → 按实际安装路径转发原生链（v2.0.19）
            fwd = _SUBCLASS_FORWARD.get(_hwnd_key(hwnd))
            if fwd is not None:
                if fwd[0] == "wndproc":
                    return fwd[1].CallWindowProcW(fwd[2], hwnd, msg, wparam, lparam)
                return fwd[1].DefSubclassProc(hwnd, msg, wparam, lparam)
            return 0

        proc_ref = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM)(_proc)
        method = ""

        # 路径 1：comctl32.SetWindowSubclass（v2.0.17 原方案）
        try:
            comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)

            # SetWindowSubclass 前置（Vista+ ICC_CLASSINIT；需 comctl32 v6 manifest）
            class _INITCOMMONCONTROLSEX(ctypes.Structure):
                _fields_ = [("dwSize", ctypes.c_uint32), ("dwICC", ctypes.c_uint32)]

            icc = _INITCOMMONCONTROLSEX()
            icc.dwSize = ctypes.sizeof(_INITCOMMONCONTROLSEX)
            icc.dwICC = 0x0080
            comctl32.InitCommonControlsEx(ctypes.byref(icc))
            comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
            comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
            comctl32.SetWindowSubclass.restype = ctypes.c_int
            if comctl32.SetWindowSubclass(h, proc_ref, 1, 0):
                _SUBCLASS_FORWARD[hkey] = ("comctl32", comctl32)
                method = "comctl32.SetWindowSubclass"
            else:
                print(f"[bridge] SetWindowSubclass 返回 0（err={ctypes.get_last_error()}），改走 GWLP_WNDPROC 兜底")
        except Exception as ex:
            print(f"[bridge] SetWindowSubclass 不可用（{ex}），改走 GWLP_WNDPROC 兜底")

        # 路径 2：SetWindowLongPtrW(GWLP_WNDPROC) —— 不依赖 comctl32 v6，frozen 环境可用
        if not method:
            try:
                GWLP_WNDPROC = -4
                set_wndproc = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
                set_wndproc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
                set_wndproc.restype = ctypes.c_ssize_t
                proc_ptr = ctypes.cast(proc_ref, ctypes.c_void_p).value
                original = set_wndproc(h, GWLP_WNDPROC, ctypes.c_ssize_t(proc_ptr))
                if not original:
                    raise RuntimeError(f"SetWindowLongPtrW 失败 err={ctypes.get_last_error()}")
                user32.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                                   wintypes.WPARAM, wintypes.LPARAM]
                user32.CallWindowProcW.restype = ctypes.c_ssize_t
                _ORIGINAL_WNDPROC[hkey] = int(original)
                _SUBCLASS_FORWARD[hkey] = ("wndproc", user32, int(original))
                method = "SetWindowLongPtrW(GWLP_WNDPROC)"
            except Exception as ex:
                print(f"[bridge] GWLP_WNDPROC 兜底安装失败：{ex}")

        if not method:
            print("[bridge] 窗口消息钩子两条路径均失败（关闭=退出旧语义；背景色走 GCLP_HBRBACKGROUND 兜底）")
            return

        _SUBCLASS_PROCS[hkey] = proc_ref  # 持引用（防 GC 回收后回调野指针）
        _SUBCLASS_NET_VALUES[hkey] = {"min_applied": False, "bg_logged": False}
        print(f"[bridge] 窗口消息钩子安装成功（{method}；关闭/背景色/MinimumSize 均生效）")
    except Exception as e:
        print(f"[bridge] 窗口消息钩子安装失败（关闭=退出 旧语义保持）：{e}")


def _colorref(rgb: int) -> int:
    """0xRRGGBB → Win32 COLORREF 0x00BBGGRR（低字节在前）；纯函数可测。"""
    r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
    return r | (g << 8) | (b << 16)


def _apply_class_background(hwnd: int, rgb: int) -> dict:
    """v2.0.19：GCLP_HBRBACKGROUND 兜底——直接改窗口类背景画刷（Win32 层，跨线程安全），
    即使消息钩子完全装不上，WebView2 渲染间隙露出的条带也是主题同色而非白底。"""
    if sys.platform != "win32":
        return {"ok": False, "error": "win32 only"}
    try:
        import ctypes
        from ctypes import wintypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        GCLP_HBRBACKGROUND = -10
        r, g, b = (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF
        colorref = _colorref(int(rgb))
        gdi32.CreateSolidColorBrush.argtypes = [wintypes.DWORD]
        gdi32.CreateSolidColorBrush.restype = ctypes.c_void_p
        brush = gdi32.CreateSolidColorBrush(colorref)
        if not brush:
            return {"ok": False, "error": "CreateSolidColorBrush failed"}
        # 旧 brush 泄漏量有界：仅在主题切换时新建（浅/深两个），进程退出系统回收
        user32.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetClassLongPtrW.restype = ctypes.c_ulonglong
        user32.SetClassLongPtrW(wintypes.HWND(int(hwnd)), GCLP_HBRBACKGROUND, ctypes.c_ssize_t(brush))
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        user32.InvalidateRect(wintypes.HWND(int(hwnd)), None, True)  # 擦除背景 → 用新 brush 重画
        return {"ok": True, "rgb": [r, g, b], "applied": "class-brush"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _post_winforms_normalize(w) -> None:
    """v2.0.17/19：向子类（UI 线程）投递归一化消息：默认主题背景色 + MinimumSize 960×600 物理。
    v2.0.19：子类未安装时不再跳过背景色——改走 GCLP_HBRBACKGROUND 兜底（露底同色）。"""
    h = _handle_int(w)
    if h not in _SUBCLASS_PROCS:
        print("[bridge] 子类未安装，背景色走 GCLP_HBRBACKGROUND 兜底（MinimumSize 跳过）")
        _apply_class_background(h, 0x1E1F24)  # 默认主题 dark bg
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.PostMessageW(wintypes.HWND(h), 0x0400 + 100, 0x1E1F24, 0)  # 默认主题 dark bg
    user32.PostMessageW(wintypes.HWND(h), 0x0400 + 101, 0, 0)


def set_window_background(r, g, b) -> dict:
    """v2.0.17/19：web 端主题解析后同步窗体背景色。
    钩子已装 → worker 线程只 PostMessage，.NET 属性写由 UI 线程回调执行（跨线程直写死锁）；
    钩子未装 → GCLP_HBRBACKGROUND 兜底（Win32 层改类背景刷，跨线程安全）。"""
    w = _active_window()
    if w is None:
        return {"ok": False, "error": "window unavailable"}
    if not (0 <= int(r) <= 255 and 0 <= int(g) <= 255 and 0 <= int(b) <= 255):
        return {"ok": False, "error": "rgb out of range"}
    h = _handle_int(w)
    if h not in _SUBCLASS_PROCS:
        return _apply_class_background(h, (int(r) << 16) | (int(g) << 8) | int(b))
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.PostMessageW(wintypes.HWND(h), 0x0400 + 100,
                         (int(r) << 16) | (int(g) << 8) | int(b), 0)
    return {"ok": True, "rgb": [int(r), int(g), int(b)], "applied": "async(ui-thread)"}


def _restore_window() -> bool:
    """v2.0.15 托盘「打开…」菜单项：已有窗口 → 还原显示并前置（最小化驻留态唤回）；
    无窗口（服务形态）→ 返回 False，托盘退回 webbrowser 打开浏览器页（旧行为）。"""
    w = _active_window()
    if w is None:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            user32 = ctypes.windll.user32
            h = _handle_int(w)
            user32.ShowWindow(h, 9)  # SW_RESTORE
            user32.SetForegroundWindow(h)
        else:
            w.restore()
        return True
    except Exception as e:
        print(f"[bridge] 窗口唤回失败：{e}")
        return False


def _wf_types():
    """v2.0.17：pywebview winforms 后端的 .NET 类型对象（Color/Size/Int32/Control）。
    统一从此处取（不写 `from System... import`——frozen 环境 pythonnet 导入钩子可能未激活）；
    不可用（非 win32/未建窗）→ None。"""
    try:
        import webview.platforms.winforms as _wf
        return _wf
    except Exception:
        return None


def _install_window_hooks_once() -> None:
    """v2.0.17：后台轮询等 pywebview 构建完窗体（w.native 非空——它在 webview.start() 建
    Form 时才赋值，create_window 后立刻装钩子会拿到 None）→ 安装 Closing 钩子 + WinForms
    属性归一化。超时 30s 放弃（退回旧语义，不影响窗口本体）。"""
    import time

    def _worker() -> None:
        for _ in range(60):
            w = _active_window()
            if w is not None and getattr(w, "native", None) is not None:
                _install_closing_hook()
                _post_winforms_normalize(w)  # 钩子成功才投递；失败则保持现状（不劣于无归一化）
                return
            time.sleep(0.5)
        print("[bridge] 窗体 native 未就绪（放弃 关闭钩子/WinForms 归一化，行为退回旧语义）")

    _threading.Thread(target=_worker, daemon=True, name="win-hooks").start()


def resolve_close_action(close_to_tray: bool, has_window: bool) -> str:
    """关闭（app.quit / Alt+F4）动作判定（v2.0.15「关闭后进入最小化」；纯函数可测）：
    开启且窗口存在 → minimize（驻留托盘）；否则 quit（退出全进程，旧语义）。"""
    return "minimize" if (close_to_tray and has_window) else "quit"


def quit_app() -> dict:
    """关闭应用程序（web 顶栏 X；Alt+F4 经 Closing 钩子走同一判定）。
    v2.0.15：「关闭后进入最小化」开启且窗口存在 → 最小化驻留托盘（可经托盘菜单唤回）；
    否则终止全进程（与托盘「退出破晓工具箱」同语义；daemon 线程随进程消失）。"""
    from . import settings_service
    w = _active_window()
    try:
        close_to_tray = bool(settings_service.get_all().get("close_to_tray"))
    except Exception:
        close_to_tray = False
    if resolve_close_action(close_to_tray, w is not None) == "minimize":
        try:
            w.minimize()
            print("[bridge] 关闭→最小化（驻留托盘；托盘菜单可重新打开）")
            return {"ok": True, "minimized": True, "quit": False}
        except Exception as e:
            print(f"[bridge] 最小化失败，退回退出进程：{e}")
    print("[bridge] app.quit requested; exiting process")
    os._exit(0)


# ---- v2.1.1：单实例守卫 / WebView2 持久化缓存 ----
_SINGLE_INSTANCE_MUTEX = None  # 持引用：进程存活期间互斥量必须保持打开
_SINGLE_INSTANCE_NAME = "Local\\DaybreakToolbox.SingleInstance"  # Local\ = 每登录会话一个（单测可替换）


def _wake_existing_window() -> bool:
    """唤回已运行实例的窗口（还原最小化 + 置前）；找不到窗口返回 False。
    窗口标题与 create_window 同源（「破晓·工具箱」）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        hwnd = user32.FindWindowW(None, "破晓·工具箱")
        if not hwnd:
            return False
        user32.ShowWindow(wintypes.HWND(hwnd), 9)  # SW_RESTORE
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
        return True
    except Exception as e:
        print(f"[bridge] 唤回已有窗口失败：{e}")
        return False


def _acquire_single_instance() -> bool:
    """命名互斥量单实例守卫（Local\\ 命名空间 = 每登录会话一个）。
    True = 本进程唯一，继续启动；False = 已有实例在跑（已尽力唤回其窗口），调用方应退出。
    非 Windows / 任何异常一律返回 True —— 守卫自身出问题绝不能把用户挡在门外。"""
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        h = kernel32.CreateMutexW(None, True, _SINGLE_INSTANCE_NAME)
        if not h:
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            _wake_existing_window()
            return False
        _SINGLE_INSTANCE_MUTEX = h
        return True
    except Exception as e:
        print(f"[bridge] 单实例检查跳过（{e}）→ 按常规启动")
        return True


def _webview_storage_path() -> "str | None":
    """v2.1.1：WebView2 持久化 profile 目录。

    pywebview 默认 private_mode=True → cache_dir 取 tempfile 随机目录，每次冷启动都重建
    JS 编译/GPU 缓存（实测 WebView2 初始化 ~1.2s）。持久化目录可复用缓存缩短该段。
    目录带应用版本后缀：升级后自动换新 profile，避免旧 index.html 被缓存导致界面不更新；
    旧版本目录 best-effort 清理。
    返回 None = 目录不可用（只读安装位置等）→ 调用方退回私有模式，行为与旧版一致。
    """
    try:
        import shutil
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent / "data"
        else:
            from .menu_service import project_root as _pr
            base = Path(_pr()) / "data"
        name = f"webview2-{APP_VERSION}"
        target = base / name
        target.mkdir(parents=True, exist_ok=True)
        for old in base.glob("webview2-*"):
            if old.is_dir() and old.name != name:
                shutil.rmtree(old, ignore_errors=True)
        return str(target)
    except Exception as e:
        print(f"[bridge] WebView2 持久化目录不可用（{e}）→ 退回私有模式")
        return None


def run_windowed(port: Optional[int] = None) -> None:
    """打包窗口模式（方案 A）：主线程跑 pywebview 原生窗口（Windows=WebView2 / macOS=WKWebView /
    Linux=WebKitGTK），加载同源桥接 UI；uvicorn / 托盘均为 daemon 后台线程。
    v2.0.8 起无边框（frameless）：原生标题栏移除，窗口操作（移动/最大化/拉伸/关闭）由 web 顶栏驱动。

    - 关闭窗口 → 退出全进程（与托盘「退出破晓工具箱」同语义；想服务常驻请用 --service）
    - 窗口引擎不可用（无 WebView2 / 无显示环境等）→ 降级「服务 + 默认浏览器」并保持进程存活
    """
    global _current_port, _WINDOWED_UI, _FIXED_WINDOW_SIZE
    import threading as _threading

    from .menu_service import project_root as _project_root

    _perf("windowed.entry")
    # v2.1.1：单实例守卫——必须在起 uvicorn / 托盘之前判定（避免第二个实例抢端口、
    # 多出托盘图标；也省掉重复启动的整段开销）。唤回成功即退出本进程。
    if not _acquire_single_instance():
        print("[bridge] 检测到已运行实例 → 已唤回其窗口，本进程退出（单实例守卫）")
        os._exit(0)
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
    _perf("windowed.uvicorn_ready" if server.started else "windowed.uvicorn_degraded")
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
    start_tray(port, root=_pr, restore_fn=_restore_window)  # v2.0.15：托盘「打开…」优先唤回窗口

    try:
        import webview
        _perf("windowed.before_window")  # 距 uvicorn ready 的间隔 ≈ build_app + 托盘线程化后的准备开销
        # v2.0.20：固定尺寸 = 主屏工作区 80%（居中）；resizable=False 去掉 WS_THICKFRAME，
        # 系统层面也无法拖边拉伸，仅保留 最大化/还原（后端几何驱动，见 toggle_maximize）。
        fx, fy, fw, fh = _fixed_window_geometry()
        _FIXED_WINDOW_SIZE = (fw, fh)
        print(f"[bridge] 固定窗口 {fw}×{fh} @({fx},{fy})（主屏工作区 80%；禁止拖拽拉伸，仅最大化/还原）")
        webview.create_window("破晓·工具箱", url, x=fx, y=fy, width=fw, height=fh,
                              resizable=False, min_size=(fw, fh), frameless=True)
        _perf("windowed.window_created")
        _install_window_hooks_once()  # v2.0.17：后台等窗体就绪 → Alt+F4 钩子 + WinForms 属性归一化
        # v2.1.1：持久化 WebView2 profile（复用 JS/GPU 缓存）；目录不可用时退回私有模式
        _storage = _webview_storage_path()
        if _storage:
            print(f"[bridge] WebView2 持久化缓存: {_storage}")
        webview.start(private_mode=not _storage, storage_path=_storage)  # 阻塞：主线程消息循环
    except Exception as e:
        print(f"[bridge] 窗口模式不可用（{type(e).__name__}: {e}）；降级服务模式，用默认浏览器打开界面")
        _fallback_browser(port, url)
        _threading.Event().wait()  # 服务模式：保持进程存活（uvicorn/托盘为 daemon 线程）
        return

    # 窗口关闭 → 退出全进程（与托盘「退出」同语义；「关闭后进入最小化」开启时 X/Alt+F4 走
    # 最小化不会到这里；到这里说明窗口被系统销毁且钩子未生效 → 提示常驻服务形态）
    print("[bridge] 窗口已关闭，退出进程（想服务常驻请用 --service 参数启动；或开启 通用设置→关闭后进入最小化）")
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
    _perf("service.entry")
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
        _perf("service.uvicorn_degraded")
        print(f"[bridge] 警告：桥接服务 10s 内未就绪（should_exit={server.should_exit}）；"
              f"进程/托盘保持，界面暂不可用")
    else:
        _perf("service.uvicorn_ready")
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
