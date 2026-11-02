"""SSH 终端 service：config/ssh_hosts.json 主机表 + 每别名一个常驻 paramiko 会话。

设计（对齐「工具箱设置 → 终端设置」标签页 与 导航条 SSH 主机下拉框）：
  - 主机表 config/ssh_hosts.json：
        [ {"alias": "srv-a", "host": "192.168.1.10", "port": 22,
           "username": "root", "password": "***"}, ... ]
      保存前做整表校验（alias 非空/无空格/唯一，host/username 非空，port 合法），
      原子写（临时文件 + os.replace）。
  - 会话：每个 alias 至多一个常驻 SSHClient（connect 幂等复用；close 即断开）。
      命令模型与本地终端一致 —— 逐条 exec_command（非交互 PTY），
      有界输出（尾部 256KB / 4000 行）+ 超时终止。

错误码：
  SSH_HOSTS_INVALID   主机表校验失败
  SSH_HOSTS_CORRUPT   文件损坏
  SSH_HOST_NOT_FOUND  别名不存在
  SSH_CONNECT_FAILED  连接/认证失败（含 paramiko 未安装）
  SSH_SESSION_LOST    会话已断（远端断开/超时）——前端应重连重试
"""
from __future__ import annotations

import atexit
import json
import os
import re
import socket
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional

try:
    import paramiko
    from paramiko.ssh_exception import SSHException as _ParamikoSSHException
except ImportError:  # 依赖缺失时优雅降级：配置管理仍可用，连接时报错提示安装
    paramiko = None
    _ParamikoSSHException = Exception  # type: ignore

# 项目根（bridge/ssh_service.py → 上一级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "config" / "ssh_hosts.json"

_MAX_OUT_BYTES = 256 * 1024
_MAX_OUT_LINES = 4000
_DEFAULT_TIMEOUT = 60
_CONNECT_TIMEOUT = 15

# 别名：字母/数字/_/-/.（防空白、防路径注入、防与 tool 槽位「__」约定混淆）
_ALIAS_RE = re.compile(r"^[\w.\-]+$")


class SSHServiceError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def set_root(root) -> None:
    """覆写项目根（测试用临时目录，避免污染真实 config/ssh_hosts.json）。"""
    global _PROJECT_ROOT, _CONFIG_FILE
    _PROJECT_ROOT = Path(root)
    _CONFIG_FILE = _PROJECT_ROOT / "config" / "ssh_hosts.json"


# ---- 原子写（与 shortcut_service 同款） ----
def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".ssh_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _bound(text: str) -> tuple[str, bool]:
    """有界化输出（与 shell_service 同规格：超限时保留尾部）。"""
    t = text or ""
    truncated = False
    if len(t.encode("utf-8", "ignore")) > _MAX_OUT_BYTES:
        t = t.encode("utf-8", "ignore")[-_MAX_OUT_BYTES:].decode("utf-8", "ignore")
        truncated = True
    lines = t.splitlines()
    if len(lines) > _MAX_OUT_LINES:
        t = "\n".join(lines[-_MAX_OUT_LINES:])
        truncated = True
    return t, truncated


# ---- 主机表 CRUD ----
def normalize_hosts(hosts) -> List[dict]:
    """整表校验 + 规范化（缺省 port=22、password=""）。非法即抛 SSH_HOSTS_INVALID。"""
    if not isinstance(hosts, list):
        raise SSHServiceError("SSH_HOSTS_INVALID", "hosts 必须是数组")
    out: List[dict] = []
    seen: set = set()
    for i, h in enumerate(hosts):
        if not isinstance(h, dict):
            raise SSHServiceError("SSH_HOSTS_INVALID", f"第 {i + 1} 项不是对象")
        alias = str(h.get("alias", "")).strip()
        host = str(h.get("host", "")).strip()
        username = str(h.get("username", "")).strip()
        password = str(h.get("password", ""))
        port = h.get("port")
        try:
            port = int(port) if port not in (None, "") else 22
        except (TypeError, ValueError):
            raise SSHServiceError("SSH_HOSTS_INVALID", f"第 {i + 1} 项端口非法：{port}")
        if not alias:
            raise SSHServiceError("SSH_HOSTS_INVALID", f"第 {i + 1} 项缺少别名")
        if not _ALIAS_RE.match(alias):
            raise SSHServiceError("SSH_HOSTS_INVALID",
                                  f"别名「{alias}」只能含 字母/数字/_/./-")
        if "__" in alias:
            raise SSHServiceError("SSH_HOSTS_INVALID",
                                  f"别名「{alias}」不能含双下划线（__ 为系统分隔符）")
        if alias in seen:
            raise SSHServiceError("SSH_HOSTS_INVALID", f"别名重复：{alias}")
        if not host:
            raise SSHServiceError("SSH_HOSTS_INVALID", f"别名「{alias}」缺少地址")
        if not username:
            raise SSHServiceError("SSH_HOSTS_INVALID", f"别名「{alias}」缺少用户名")
        if not 1 <= port <= 65535:
            raise SSHServiceError("SSH_HOSTS_INVALID", f"别名「{alias}」端口 {port} 超出 1-65535")
        seen.add(alias)
        out.append({"alias": alias, "host": host, "port": port,
                    "username": username, "password": password})
    return out


def get_hosts() -> dict:
    """全量主机表（文件缺失 → 空表；损坏 → SSH_HOSTS_CORRUPT）。"""
    if not _CONFIG_FILE.exists():
        return {"hosts": []}
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise SSHServiceError("SSH_HOSTS_CORRUPT", "config/ssh_hosts.json 已损坏，请删除后重新保存")
    return {"hosts": normalize_hosts(data)}


def save_hosts(hosts) -> dict:
    """整表覆盖保存（前端每次发全量列表；即时生效并广播 ssh.hosts.changed）。"""
    data = normalize_hosts(hosts)
    _atomic_write(_CONFIG_FILE, data)
    return {"ok": True, "hosts": data}


def _find_host(alias: str) -> dict:
    for h in get_hosts()["hosts"]:
        if h["alias"] == alias:
            return h
    raise SSHServiceError("SSH_HOST_NOT_FOUND", f"SSH 主机「{alias}」不存在（请先在 终端设置 中保存）")


# ---- 常驻会话（每 alias 一个 paramiko.SSHClient） ----
_sessions: Dict[str, object] = {}
_guard = threading.Lock()


def _alive(client) -> bool:
    try:
        t = client.get_transport()
        return t is not None and t.is_active()
    except Exception:
        return False


def connect(alias: str) -> dict:
    """建连（幂等：已有存活会话直接复用）。失败抛 SSH_CONNECT_FAILED。"""
    alias = str(alias or "").strip()
    if not alias:
        raise SSHServiceError("SSH_HOST_NOT_FOUND", "缺少别名")
    with _guard:
        c = _sessions.get(alias)
        if c is not None and _alive(c):
            h = _find_host(alias)
            return {"ok": True, "alias": alias, "user": h["username"],
                    "host": f"{h['host']}:{h['port']}", "reused": True}
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
            _sessions.pop(alias, None)

    h = _find_host(alias)  # 先查表（无依赖，离线也可给准确错误码）
    if paramiko is None:
        raise SSHServiceError("SSH_CONNECT_FAILED", "paramiko 未安装（python -m pip install paramiko）")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        # 密码为空时允许回退到本机密钥（look_for_keys=True），仍无方法 → paramiko 报认证错误
        client.connect(
            hostname=h["host"], port=h["port"],
            username=h["username"], password=h["password"] or None,
            timeout=_CONNECT_TIMEOUT, banner_timeout=_CONNECT_TIMEOUT, auth_timeout=_CONNECT_TIMEOUT,
            allow_agent=False, look_for_keys=True,
        )
    except Exception as e:
        try:
            client.close()
        except Exception:
            pass
        raise SSHServiceError("SSH_CONNECT_FAILED", f"连接 {h['username']}@{h['host']}:{h['port']} 失败：{e}")
    with _guard:
        old = _sessions.get(alias)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        _sessions[alias] = client
    return {"ok": True, "alias": alias, "user": h["username"],
            "host": f"{h['host']}:{h['port']}", "reused": False}


def _get_session(alias: str):
    c = _sessions.get(alias)
    if c is None or not _alive(c):
        connect(alias)  # 自动重建
        c = _sessions.get(alias)
    return c


def _drop(alias: str, reason: str = "") -> None:
    with _guard:
        c = _sessions.pop(alias, None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass


def run(alias: str, command: str, timeout: Optional[int] = None) -> dict:
    """在远端执行一条命令（与本地终端同款命令块模型）。会话断了自动重连一次。"""
    alias = str(alias or "").strip()
    command = str(command or "").strip()
    to = int(timeout) if (timeout and str(timeout).isdigit()) else _DEFAULT_TIMEOUT
    c = _get_session(alias)

    timed_out = False
    try:
        _stdin, stdout, stderr = c.exec_command(command, timeout=to)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
    except (socket.timeout, TimeoutError):
        # 远端命令超时（通道仍在）：与本地终端一致 → 终止标记，不判会话丢失
        return {"ok": False, "output": f"[超时 {to}s] 远端命令已终止：{command}\n",
                "exit": -1, "truncated": False, "alias": alias, "timed_out": True}
    except Exception as e:
        # 会话级失败（远端断开 / 认证失效 / 通道关闭）：丢弃会话，由前端经 ssh.closed 感知
        _drop(alias, str(e))
        raise SSHServiceError("SSH_SESSION_LOST", f"与「{alias}」的会话已断开：{e}")

    out, trunc = _bound(out + (("\n" + err) if err else ""))
    return {"ok": code == 0, "output": out, "exit": code, "truncated": trunc,
            "alias": alias, "timed_out": False}


def close(alias: str) -> dict:
    _drop(alias)
    return {"ok": True, "alias": alias}


def status() -> dict:
    """存活会话的别名列表（前端刷新后恢复「已连接」指示用）。"""
    with _guard:
        out = [a for a, c in list(_sessions.items()) if _alive(c)]
        for dead in [a for a in list(_sessions) if a not in out]:
            _sessions.pop(dead, None)
    return {"active": out}


def _cleanup_all() -> None:
    with _guard:
        for c in _sessions.values():
            try:
                c.close()
            except Exception:
                pass
        _sessions.clear()


atexit.register(_cleanup_all)
