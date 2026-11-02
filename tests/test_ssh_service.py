"""ssh_service 单元测试：主机表校验 / 原子读写 / 会话生命周期（离线 fake，不发真实连接）。"""
import json
from contextlib import contextmanager

import pytest

from bridge import ssh_service
from bridge.ssh_service import (SSHServiceError, connect, close, get_hosts,
                               run, save_hosts, set_root, status)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    set_root(tmp_path)
    table = {}
    monkeypatch.setattr(ssh_service, "_sessions", table)
    monkeypatch.setattr(ssh_service, "paramiko", None)  # 离线：connect 一律走「未安装」分支
    yield


class _FakeChannel:
    def __init__(self, code):
        self._code = code

    def recv_exit_status(self):
        return self._code


class _FakeStd:
    def __init__(self, data: bytes, channel):
        self._data = data
        self.channel = channel

    def read(self):
        return self._data

    def decode(self, *a, **kw):
        return self._data.decode("utf-8", "replace")


class FakeClient:
    """鸭子类型 paramiko.SSHClient：get_transport/is_active + exec_command。"""

    def __init__(self, out=b"", err=b"", code=0, active=True):
        self.out, self.err, self.code, self.active = out, err, code, active
        self.closed = False
        self.execs = []

    def get_transport(self):
        return self if self.active else None

    def is_active(self):
        return self.active

    def exec_command(self, command, timeout=None):
        self.execs.append(command)
        chan = _FakeChannel(self.code)
        return None, _FakeStd(self.out, chan), _FakeStd(self.err, chan)

    def close(self):
        self.closed = True


def _mk_host_file(tmp_path, hosts):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "ssh_hosts.json").write_text(
        json.dumps(hosts, ensure_ascii=False), encoding="utf-8")


def _host(alias="srv-a"):
    return [{"alias": alias, "host": "10.0.0.5", "username": "root", "password": "p"}]


# ---- 主机表 CRUD ----
def test_get_missing_file_returns_empty():
    assert get_hosts() == {"hosts": []}


def test_save_get_roundtrip_defaults():
    r = save_hosts(_host())
    assert r["hosts"][0]["port"] == 22          # 缺省端口 22
    assert get_hosts()["hosts"] == r["hosts"]
    ondisk = json.loads(ssh_service._CONFIG_FILE.read_text(encoding="utf-8"))
    assert ondisk == r["hosts"]


def test_save_invalid_rejected():
    base = {"alias": "a", "host": "h", "username": "u"}
    for bad in (None, "x",
                [{"alias": "", "host": "h", "username": "u"}],
                [{"alias": "a b", "host": "h", "username": "u"}],
                [{"alias": "a", "host": "", "username": "u"}],
                [{"alias": "a", "host": "h", "username": ""}],
                [dict(base, port=0)],
                [dict(base, port="abc")],
                [base, dict(base)],
                [dict(base, alias="a__b")]):
        with pytest.raises(SSHServiceError) as ei:
            save_hosts(bad)
        assert ei.value.code == "SSH_HOSTS_INVALID"


def test_corrupt_file_rejected():
    ssh_service._CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ssh_service._CONFIG_FILE.write_text("{not json", encoding="utf-8")
    with pytest.raises(SSHServiceError) as ei:
        get_hosts()
    assert ei.value.code == "SSH_HOSTS_CORRUPT"


# ---- 连接 / 执行（fake 会话，不发真实网络） ----
def test_connect_unknown_alias():
    _mk_host_file(ssh_service._CONFIG_FILE.parent.parent, [])
    with pytest.raises(SSHServiceError) as ei:
        connect("ghost")
    assert ei.value.code == "SSH_HOST_NOT_FOUND"


def test_connect_paramiko_missing_reports_connect_failed():
    _mk_host_file(ssh_service._CONFIG_FILE.parent.parent, _host())
    with pytest.raises(SSHServiceError) as ei:
        connect("srv-a")
    assert ei.value.code == "SSH_CONNECT_FAILED"


def test_connect_reuses_alive_session():
    _mk_host_file(ssh_service._CONFIG_FILE.parent.parent, _host())
    fake = FakeClient()
    ssh_service._sessions["srv-a"] = fake
    r = connect("srv-a")
    assert r["reused"] is True and r["host"] == "10.0.0.5:22"


def test_run_with_fake_session():
    _mk_host_file(ssh_service._CONFIG_FILE.parent.parent, _host())
    fake = FakeClient(out=b"hello remote\n", err=b"warn\n", code=0)
    ssh_service._sessions["srv-a"] = fake
    r = run("srv-a", "echo hello remote")
    assert r["ok"] is True and r["exit"] == 0
    assert "hello remote" in r["output"] and "warn" in r["output"]
    assert fake.execs == ["echo hello remote"]


def test_run_nonzero_exit_reported():
    _mk_host_file(ssh_service._CONFIG_FILE.parent.parent, _host())
    fake = FakeClient(out=b"no such file\n", code=127)
    ssh_service._sessions["srv-a"] = fake
    r = run("srv-a", "missing-cmd")
    assert r["ok"] is False and r["exit"] == 127


def test_run_dead_session_reconnect_fails():
    """死会话 → 自动重连；重连失败（paramiko 缺失/无网络）→ SSH_CONNECT_FAILED。"""
    _mk_host_file(ssh_service._CONFIG_FILE.parent.parent, _host())
    ssh_service._sessions["srv-a"] = FakeClient(active=False)
    with pytest.raises(SSHServiceError) as ei:
        run("srv-a", "ls")
    assert ei.value.code == "SSH_CONNECT_FAILED"


def test_run_unknown_alias():
    with pytest.raises(SSHServiceError) as ei:
        run("ghost", "ls")
    assert ei.value.code == "SSH_HOST_NOT_FOUND"


def test_close_pops_session():
    fake = FakeClient()
    ssh_service._sessions["srv-a"] = fake
    close("srv-a")
    assert "srv-a" not in ssh_service._sessions and fake.closed


def test_status_lists_alive_only():
    ssh_service._sessions["a"] = FakeClient(active=True)
    ssh_service._sessions["b"] = FakeClient(active=False)
    assert status() == {"active": ["a"]}
    assert "b" not in ssh_service._sessions  # 死会话顺带清理
