"""本地终端 service：Web 端「显式化」旧版隐藏的 create_local_cmd（app.py L1073）。

设计：
  - 会话化：每个前端 session 维护一个 cwd（逻辑路径），`cd` 在会话内持久；
    子命令在会话 cwd 下执行（subprocess cwd=），跨会话互不影响。
  - 终端类型：每个会话可选底层 shell（cmd / PowerShell / pwsh，按系统 PATH 探测可用性）；
    cmd 走 shell=True（默认，与旧版一致，启动 ~50ms）；
    PowerShell / pwsh 走**常驻进程**（首次用时 spawn 一次，stdin 喂命令，哨兵行读退出码，
    避免 5.1 每次 ~3s 的运行时冷启动；超时/崩溃/切类型 → kill 后下次自动重生）。
  - 内置命令（1:1 复刻旧版 execute_command 语义，不依赖底层 shell）：
      cd <path> / cd       改会话 cwd（abspath + normpath 解析，校验目录存在）
      ls                   列会话 cwd（目录行尾加 /）
      pwd                  打印会话 cwd
      clear / exit         前端清屏（返回 clear 标记，不打印）
      其它                 按会话选定 shell 有界执行（timeout 默认 60s）
  - 有界：输出截断到最后 N 行 / M 字节（防大输出拖垮前端）。
  - 补全：complete(session, prefix) 返回会话 cwd 下匹配前缀的条目（≤50）。

错误码：SHELL_NOT_FOUND / INTERNAL（cwd 异常）
仅 127.0.0.1 桥接 → 本机执行，属工具箱本征能力（非对外暴露）。
"""
from __future__ import annotations

import atexit
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

_MAX_OUT_BYTES = 256 * 1024
_MAX_OUT_LINES = 4000
_DEFAULT_TIMEOUT = 60
_MAX_COMPLETE = 50

# 可选终端类型（模块导入时按系统 PATH 探测一次；cmd 恒可用作兜底）
_SHELL_EXES = (("cmd", "cmd.exe"), ("powershell", "powershell.exe"), ("pwsh", "pwsh.exe"))
SHELLS_AVAILABLE = [n for n, exe in _SHELL_EXES if shutil.which(exe)] or ["cmd"]


def _bound(text: str) -> tuple[str, bool]:
    """有界化输出：超字节/行数时保留尾部（终端关心最新输出），标记 truncated。"""
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


class ShellSession:
    """按 session_id 维护 cwd（默认项目根）与底层 shell 选择（默认 cmd）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cwd: Dict[str, str] = {}
        self._shell: Dict[str, str] = {}
        self._default = os.getcwd()

    def cwd(self, session: str) -> str:
        with self._lock:
            return self._cwd.get(session or "local", self._default)

    def set_cwd(self, session: str, path: str) -> None:
        with self._lock:
            self._cwd[session or "local"] = path

    def shell(self, session: str) -> str:
        with self._lock:
            s = self._shell.get(session or "local", "cmd")
            return s if s in SHELLS_AVAILABLE else "cmd"

    def set_shell(self, session: str, shell: str) -> None:
        with self._lock:
            self._shell[session or "local"] = shell


_sessions = ShellSession()


# ---- PowerShell / pwsh 常驻进程（消除 5.1 每次 ~3s 冷启动；cmd 太便宜保持逐条执行）----

class _PsProc:
    """常驻 PowerShell 进程：stdin 逐条喂脚本，后台线程泵 stdout 行，
    脚本尾部追加唯一哨兵行（token + $LASTEXITCODE）→ 精确取退出码并分界输出。

    命令经 self.lock 串行化（同时只跑一条）；超时 → 整进程 kill（命令随之终止），
    下次执行时由 _ps_get 自动重生。"""

    def __init__(self, shell: str, cwd: str) -> None:
        self.shell = shell
        self.exe = "powershell" if shell == "powershell" else "pwsh"
        self.token = "DBRKPS" + secrets.token_hex(6)
        self.lock = threading.Lock()
        self.lines: "queue.Queue[str]" = queue.Queue()
        self._dead = False
        try:
            self.proc = subprocess.Popen(
                [self.exe, "-NoProfile", "-NonInteractive", "-Command", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=cwd,
            )
        except Exception:
            self._dead = True
            self.proc = None
            return
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc is not None
        try:
            for line in self.proc.stdout:
                self.lines.put(line.rstrip("\r\n"))
        except Exception:
            pass
        finally:
            self._dead = True

    def alive(self) -> bool:
        return (not self._dead) and self.proc is not None and self.proc.poll() is None

    def kill(self) -> None:
        self._dead = True
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass

    def drain_stale(self) -> None:
        """冲刷前一条（被 kill 的）命令的残留输出，防止串进下一条命令。"""
        while True:
            try:
                self.lines.get_nowait()
            except queue.Empty:
                return

    def exec(self, command: str, cwd: str, timeout: int) -> Tuple[str, int, bool]:
        """喂一条命令（自动 Set-Location 到会话 cwd）。返回 (output, exit, timed_out)。"""
        if self.proc is None or not self.alive():
            return "", -1, False  # spawn 失败：调用方 kill + 重生重试
        self.drain_stale()
        quoted = cwd.replace("'", "''")
        script = (
            f"Set-Location -LiteralPath '{quoted}' 2>$null\n"
            f"{command}\n"
            f"Write-Output ('{self.token}' + $LASTEXITCODE)\n"
        )
        try:
            self.proc.stdin.write(script)
            self.proc.stdin.flush()
        except Exception:
            return "", 1, False  # 进程已死：调用方 kill + 重生重试

        out_lines: list = []
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "\n".join(out_lines), -1, True
            try:
                line = self.lines.get(timeout=min(0.5, remaining))
            except queue.Empty:
                # 短轮询等哨兵；进程已自行退出（命令带 exit）→ 立即继承其退出码
                rc = self.proc.poll()
                if rc is not None:
                    return "\n".join(out_lines), rc or 0, False
                continue
            if line.startswith(self.token):
                tail = line[len(self.token):].strip()
                try:
                    code = int(tail) if tail else 0
                except ValueError:
                    code = 0
                return "\n".join(out_lines), code, False
            out_lines.append(line)
            # 进程自行退出（命令里带 exit N / 关机类命令）：哨兵行不会再来 →
            # 抽干剩余缓冲行，直接继承进程退出码
            if self.proc.poll() is not None:
                while True:
                    try:
                        out_lines.append(self.lines.get_nowait())
                    except queue.Empty:
                        break
                return "\n".join(out_lines), self.proc.returncode or 0, False


_ps_procs: Dict[str, _PsProc] = {}
_ps_guard = threading.Lock()


def _ps_get(session: str, shell: str, cwd: str) -> _PsProc:
    """取本会话的常驻 PS 进程；类型不符/已死 → kill 旧进程并重生（cwd 同步最新值）。"""
    with _ps_guard:
        p = _ps_procs.get(session)
        if p is not None and p.alive() and p.shell == shell:
            return p
        if p is not None:
            p.kill()
        p = _PsProc(shell, cwd)
        if not p.alive():
            # spawn 失败（exe 不在等）：返回死实例，调用方按错误处理
            _ps_procs[session] = p
            return p
        _ps_procs[session] = p
        return p


def _ps_run(session: str, command: str, shell: str, cwd: str, timeout: int) -> Tuple[str, int, bool]:
    """常驻执行；超时 → kill 并重生重试；进程自行退出（命令带 exit）→ 直接采用其退出码。"""
    p = _ps_get(session, shell, cwd)
    out, code, timed_out = p.exec(command, cwd, timeout)
    if not timed_out and p.alive():
        return out, code, False
    if not timed_out and code != -1:
        # 进程已自行退出且拿到真实退出码（如命令里写了 exit 7）：不重试，进程留着由下次 _ps_get 重生
        return out, code, False
    # 超时 / 崩溃（哨兵缺失）：kill 旧进程，重生后重试一次
    p.kill()
    p2 = _ps_get(session, shell, cwd)
    out2, code2, timed_out2 = p2.exec(command, cwd, timeout)
    if not p2.alive() and code2 != -1:
        return out2, code2, False  # 重试后再次自行退出（exit 类命令）
    p2.kill()
    return out2, code2, timed_out2


def _cleanup_ps() -> None:
    with _ps_guard:
        for p in _ps_procs.values():
            p.kill()
        _ps_procs.clear()


atexit.register(_cleanup_ps)


def _resolve_cwd(session: str, target: str) -> Optional[str]:
    """把相对/绝对路径解析为会话内的绝对目录；不存在/非目录返回 None。"""
    base = _sessions.cwd(session)
    if not target:
        return base  # 裸 cd → 当前目录（旧版 cd 无参数不改；这里保持一致=不变）
    p = target.replace("/", os.sep)
    if not os.path.isabs(p):
        p = os.path.join(base, p)
    p = os.path.normpath(p)
    if os.path.isdir(p):
        return p
    return None


def run(session: str, command: str, timeout: Optional[int] = None) -> dict:
    """执行一条命令，返回 {ok, output, exit, cwd, clear, truncated}。"""
    command = (command or "").strip()
    session = session or "local"
    cwd = _sessions.cwd(session)

    # 内置命令（1:1 旧版 execute_command）
    parts = command.split(None, 1)
    verb = _norm(parts[0]) if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    if verb in ("cd", "ls", "pwd", "clear", "exit"):
        if verb == "cd":
            new = _resolve_cwd(session, rest)
            if new is None:
                return {"ok": False, "output": f"目录 {rest} 不存在或不是目录\n",
                        "exit": 1, "cwd": cwd, "clear": False, "truncated": False}
            _sessions.set_cwd(session, new)
            return {"ok": True, "output": "", "exit": 0, "cwd": new, "clear": False, "truncated": False}
        if verb == "ls":
            try:
                entries = sorted(os.listdir(cwd), key=str.lower)
                out = "".join(
                    (e + ("/" if os.path.isdir(os.path.join(cwd, e)) else "") + "\n")
                    for e in entries
                )
                out, trunc = _bound(out)
                return {"ok": True, "output": out, "exit": 0, "cwd": cwd, "clear": False, "truncated": trunc}
            except PermissionError:
                return {"ok": False, "output": "无权限读取该目录内容\n", "exit": 1,
                        "cwd": cwd, "clear": False, "truncated": False}
        if verb == "pwd":
            return {"ok": True, "output": cwd + "\n", "exit": 0, "cwd": cwd, "clear": False, "truncated": False}
        # clear / exit：前端据此清屏（旧版 exit=清屏而非退出程序）
        return {"ok": True, "output": "", "exit": 0, "cwd": cwd, "clear": True, "truncated": False}

    # 其它 → 按会话选定 shell 本机执行（有界 + 超时）
    to = int(timeout) if (timeout and str(timeout).isdigit()) else _DEFAULT_TIMEOUT
    shell_kind = _sessions.shell(session)
    if shell_kind in ("powershell", "pwsh"):
        # 常驻进程：消除每次冷启动（PS 5.1 ~3s / pwsh ~0.7s → 复用后接近 0）
        out, code, timed_out = _ps_run(session, command, shell_kind, cwd, to)
        if timed_out:
            return {"ok": False, "output": f"[超时 {to}s] 命令已终止：{command}\n",
                    "exit": -1, "cwd": cwd, "clear": False, "truncated": False}
        out_b, trunc = _bound(out)
        return {"ok": code == 0, "output": out_b, "exit": code,
                "cwd": cwd, "clear": False, "truncated": trunc}
    try:
        r = subprocess.run(command, shell=True, cwd=cwd, capture_output=True,
                           text=True, timeout=to)
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": f"[超时 {to}s] 命令已终止：{command}\n",
                "exit": -1, "cwd": cwd, "clear": False, "truncated": False}
    except Exception as e:  # 非法命令 / 无 shell 等
        return {"ok": False, "output": f"错误：{e}\n", "exit": -1, "cwd": cwd, "clear": False, "truncated": False}

    out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    out, trunc = _bound(out)
    return {"ok": r.returncode == 0, "output": out, "exit": r.returncode,
            "cwd": cwd, "clear": False, "truncated": trunc}


def shells(session: str) -> dict:
    """本会话可用终端类型（按系统 PATH 探测一次）+ 当前选定 shell。"""
    return {"ok": True, "available": list(SHELLS_AVAILABLE), "current": _sessions.shell(session)}


def set_shell(session: str, shell: str) -> dict:
    """切换本会话底层 shell（仅允许 SHELLS_AVAILABLE 内的值；非法 → 拒绝并保持原值）。
    切到 PS 类型时**立即后台预热**常驻进程（消除首条命令的 ~3s 冷启动感知）。"""
    if shell not in SHELLS_AVAILABLE:
        return {"ok": False, "current": _sessions.shell(session)}
    _sessions.set_shell(session, shell)
    if shell == "cmd":
        # 切回 cmd 时回收常驻 PS 进程（避免白白挂着一个 powershell）
        with _ps_guard:
            p = _ps_procs.pop(session, None)
            if p is not None:
                p.kill()
        return {"ok": True, "current": shell}
    # 预热：spawn 常驻进程（Popen 本身很快；PS 的 ~3s 就绪等待发生在后台，
    # 用户此时输入的命令会暂存 stdin 管道缓冲，进程就绪后照常执行）
    with _ps_guard:
        old = _ps_procs.get(session)
        if old is not None:
            old.kill()
        try:
            _ps_procs[session] = _PsProc(shell, _sessions.cwd(session))
        except Exception:
            pass  # spawn 失败 → 下次命令时 _ps_get 自动再试
    return {"ok": True, "current": shell}


def complete(session: str, prefix: str, start: int = 0, limit: int = _MAX_COMPLETE) -> dict:
    """会话 cwd 下匹配前缀的条目（文件名/目录名），供 Tab 补全。"""
    prefix = (prefix or "")
    cwd = _sessions.cwd(session or "local")
    try:
        entries = sorted(os.listdir(cwd), key=str.lower)
    except Exception:
        return {"ok": False, "items": [], "cwd": cwd}
    items = [e for e in entries if e.startswith(prefix)][:limit]
    return {"ok": True, "items": items, "cwd": cwd}


def reset(session: str) -> dict:
    """重置会话 cwd 回默认（项目根）。"""
    _sessions.set_cwd(session, _sessions._default)
    return {"ok": True, "cwd": _sessions._default}


def _norm(w: str) -> str:
    return w.lower()
