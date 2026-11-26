"""tests/test_shell_service.py：本地终端 service（会话化 cwd + 内置命令 + 有界执行）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge import shell_service  # noqa: E402


def test_builtin_ls_pwd():
    r = shell_service.run("t1", "pwd")
    assert r["ok"] and r["cwd"] and r["output"].strip() == r["cwd"]


def test_ls_table_format():
    """内置 ls：表格输出（Mode/LastWriteTime/Length/Name；目录 d----、文件 -a---）。"""
    r = shell_service.run("t16-ls-table", "ls")
    assert r["ok"], r
    out = r["output"]
    # 表头
    assert "Mode" in out and "LastWriteTime" in out and "Length" in out and "Name" in out
    first = out.splitlines()
    assert "Mode" in first[0] and "----" in first[1]
    # 目录行：d---- 且 Length 列为空；文件行：-a--- 且带字节数（项目根固有项）
    dir_line = next(x for x in first if x.rstrip().endswith("bridge"))
    file_line = next(x for x in first if x.rstrip().endswith("README.md"))
    assert dir_line.lstrip().startswith("d----")
    assert file_line.lstrip().startswith("-a---")
    # 旧行为（目录行尾加 /）不再出现
    assert "bridge/" not in out and "README.md/" not in out


def test_builtin_cd_rels():
    r1 = shell_service.run("t2", "cd tests")
    assert r1["ok"]
    assert r1["cwd"].rstrip("/").endswith("tests")
    # 会话 cwd 持久
    r2 = shell_service.run("t2", "pwd")
    assert r2["cwd"] == r1["cwd"]
    shell_service.reset("t2")


def test_cd_missing_fails():
    r = shell_service.run("t3", "cd definitely_not_a_dir_xyz")
    assert not r["ok"] and r["exit"] == 1
    assert "不存在" in r["output"]


def test_system_command_runs_in_cwd():
    r = shell_service.run("t4", "ls")
    assert r["ok"]
    r2 = shell_service.run("t4", "echo hello")
    assert r2["ok"] and "hello" in r2["output"]


def test_system_command_failure():
    r = shell_service.run("t5", 'python -c "import sys; sys.exit(3)"')
    assert not r["ok"] and r["exit"] == 3


def test_clear_flag():
    assert shell_service.run("t6", "clear")["clear"] is True
    assert shell_service.run("t6", "exit")["clear"] is True


def test_complete_prefix():
    c = shell_service.complete("t7", "te")
    assert c["ok"]
    assert any(x.startswith("te") for x in c["items"])


def test_timeout_guard():
    r = shell_service.run("t8", 'python -c "import time; time.sleep(5)"', timeout=1)
    assert not r["ok"] and "超时" in r["output"]


# ---- PowerShell / pwsh 常驻进程（消除每次冷启动 ~3s）----

def test_persistent_ps_reuse():
    """powershell/pwsh 走常驻进程：第二条命令接近 0 延迟（spawn 仅一次）。"""
    import time

    for kind in filter(lambda k: k in shell_service.SHELLS_AVAILABLE, ("powershell", "pwsh")):
        sess = f"t9-{kind}"
        assert shell_service.set_shell(sess, kind)["ok"]
        t0 = time.perf_counter()
        r1 = shell_service.run(sess, "(1+2)*3", timeout=10)  # 首次：spawn
        first = time.perf_counter() - t0
        t0 = time.perf_counter()
        r2 = shell_service.run(sess, "(1+2)*3", timeout=10)  # 复用
        reuse = time.perf_counter() - t0
        assert r1["ok"] and r1["output"].strip() == "9"
        assert r2["ok"] and r2["output"].strip() == "9"
        assert reuse < 2.0, f"{kind} 复用延迟 {reuse:.2f}s 仍偏高（应无冷启动）"
        assert first < 15, f"{kind} spawn 延迟 {first:.2f}s 异常"


def test_persistent_ps_exit_code():
    """命令自带 exit N → 继承进程退出码（且进程被回收后自动重生）。"""
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t10-ps"
    shell_service.set_shell(sess, "powershell")
    r = shell_service.run(sess, "if (-not (Test-Path /x/zz)) { exit 7 }", timeout=10)
    assert r["exit"] == 7 and not r["ok"]
    # 自退出的常驻进程 → 下条命令自动重生
    r2 = shell_service.run(sess, "1+1", timeout=10)
    assert r2["ok"] and r2["output"].strip() == "2"


def test_ps_native_command_no_replacement_chars():
    """原生命令（ipconfig）经常驻 PS 输出不得出现 U+FFFD。

    回归背景：序言曾把 $OutputEncoding 钉成 UTF-8，而原生 exe 重定向输出按系统
    ANSI 码页写字节（本机 GBK）→ GBK 被当 UTF-8 解码 → 中文网卡名全变 U+FFFD。
    修后 $OutputEncoding = GetSystemEncoding()（系统 ANSI 码页），跨语言系统自适应。"""
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t20-native"
    shell_service.set_shell(sess, "powershell")
    r = shell_service.run(sess, "ipconfig", timeout=45)
    assert r["ok"], r
    assert "\ufffd" not in r["output"], f"原生命令输出出现替换字符：{r['output'][:120]!r}"


def test_persistent_ps_timeout_respawn():
    """超时 kill 常驻进程 → 下条命令重生并继续可用。"""
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t11-ps"
    shell_service.set_shell(sess, "powershell")
    r = shell_service.run(sess, "Start-Sleep 5", timeout=1)
    assert not r["ok"] and "超时" in r["output"]
    r2 = shell_service.run(sess, "1+1", timeout=10)
    assert r2["ok"] and r2["output"].strip() == "2"


def test_set_shell_cmd_reclaims_ps():
    """切回 cmd → 常驻 PS 进程被回收（不白挂）。"""
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t12-ps"
    shell_service.set_shell(sess, "powershell")
    shell_service.run(sess, "1+1", timeout=10)
    assert sess in shell_service._ps_procs
    assert shell_service.set_shell(sess, "cmd")["ok"]
    assert sess not in shell_service._ps_procs


def test_set_shell_prewarm_ps():
    """切到 PS 类型 → 常驻进程立即后台预热（首条命令不再承担 ~3s 冷启动）。"""
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t13-ps"
    shell_service.set_shell(sess, "powershell")
    assert sess in shell_service._ps_procs
    assert shell_service._ps_procs[sess].alive()
    shell_service.set_shell(sess, "cmd")  # 收尾回收


def test_ps_concurrent_exec_serialized():
    """同常驻进程两条命令重叠 → lock 严格串行：后到命令排队等待，输出不串扰。

    回归背景：exec 早期未实际加锁（docstring 声称串行但代码漏掉）——
    前端 15s 假超时后用户重发命令时，两条命令交错写同一 PS 的 stdin，
    互吃哨兵 → 输出错乱 + 连环假超时。"""
    import threading
    import time
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t14-ps"
    shell_service.set_shell(sess, "powershell")

    results: dict = {}
    def worker(tag: str, cmd: str, to: int) -> None:
        results[tag] = shell_service.run(sess, cmd, timeout=to)

    th = threading.Thread(target=worker, args=("slow", "Start-Sleep 3", 12))
    th.start()
    time.sleep(1.0)  # slow 在跑时并发发一条快命令
    t0 = time.perf_counter()
    worker("fast", "1+1", 12)
    fast_wait = time.perf_counter() - t0
    th.join()

    assert results["fast"]["ok"] and results["fast"]["output"].strip() == "2", results["fast"]
    assert results["slow"]["ok"], results["slow"]
    # 快命令被锁排队（slow 还要 ~2s）：等待 ≥1.5s 证明串行而非并发交错
    assert fast_wait >= 1.5, f"快命令未排队（{fast_wait:.2f}s），锁未生效"
    shell_service.set_shell(sess, "cmd")  # 收尾回收


# ---- 编码兜底（cmd/PS 管道字节不定码：UTF-8 输出 vs GBK locale 的历史崩溃源）----

def test_decode_bytes_chain():
    """cmd/PS 泵共用解码链：UTF-8 严格 → locale 严格 → replace（任何字节流不抛）。

    无控制台环境（分离 Popen）下 PS host 管道退回系统码页（中文机 GBK），
    此链路保证有/无控制台两种宿主环境中文都还原正确。"""
    import locale
    f = shell_service._decode_bytes
    assert f("目录".encode("utf-8")) == "目录"          # 真实 UTF-8 输出（本机 cmd dir）
    assert f("bridge .gitignore".encode("ascii")) == "bridge .gitignore"  # 纯 ASCII 原样
    gbk_bytes = "以太网适配器".encode("gbk")
    pref = locale.getpreferredencoding(False).lower()
    if "gbk" in pref or "936" in pref:
        assert f(gbk_bytes) == "以太网适配器"            # GBK locale（中文 dev 机）：locale 档还原
    else:
        # en-US 等非 GBK locale（CI runner）：GBK 字节走 locale/replace 兜底 —— 关键契约是「不抛」
        assert isinstance(f(gbk_bytes), str)
    assert "\ufffd" in f(b"\xff\xfe\xfb")                # 杂字节 → replace 兜底，不抛异常
    assert f(b"") == "" and f(None) == ""


# ---- dir 回归：cmd 下输出不再被吞 / PS 下不再假超时（编码错位的两个症状）----

def test_cmd_dir_output_not_empty():
    """cmd 路径：dir 含中文目录名（本机 UTF-8 管道输出）→ 旧 text=True/GBK 会把 stdout 整个吞掉。"""
    r = shell_service.run("t16-cmd-dir", "dir")
    assert r["ok"], r
    assert r["output"].strip(), "dir 输出为空（编码崩溃吞掉了 stdout）"
    assert "超时" not in r["output"]
    # CRLF 归一（二进制捕获后手动还原旧 text=True 的通用换行行为）
    r2 = shell_service.run("t16-cmd-dir", "echo abc")
    assert "abc" in r2["output"] and "\r" not in r2["output"], r2


def test_ps_dir_no_timeout():
    """PS 常驻：dir 的 UTF-8 表头/列表不再让泵线程崩 → 哨兵必达，无假超时。"""
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t17-ps-dir"
    shell_service.set_shell(sess, "powershell")
    r = shell_service.run(sess, "dir", timeout=25)
    assert "超时" not in r["output"], r
    assert r["ok"], r
    assert r["output"].strip(), "PS dir 输出为空（泵线程死于解码异常）"
    shell_service.set_shell(sess, "cmd")  # 收尾回收


def test_ps_unicode_roundtrip():
    """全链路：中文经 [char] 生成（避免测试源编码歧义）→ 输出侧 UTF-8 写管道 → 读回还原。"""
    if "powershell" not in shell_service.SHELLS_AVAILABLE:
        return
    sess = "t18-ps-unicode"
    shell_service.set_shell(sess, "powershell")
    r = shell_service.run(sess, "[char]0x4F60 + [char]0x597D", timeout=25)
    assert r["ok"], r
    assert "你好" in r["output"], r["output"][:100]
    shell_service.set_shell(sess, "cmd")  # 收尾回收
