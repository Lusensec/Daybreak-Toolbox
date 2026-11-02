"""tests/test_shell_service.py：本地终端 service（会话化 cwd + 内置命令 + 有界执行）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge import shell_service  # noqa: E402


def test_builtin_ls_pwd():
    r = shell_service.run("t1", "pwd")
    assert r["ok"] and r["cwd"] and r["output"].strip() == r["cwd"]


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
