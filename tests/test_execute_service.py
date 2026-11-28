"""tests/test_execute_service.py：新数据模型下 execute_service 的筛选/路径解析/置灰测试。

隔离：menu_service.set_root(临时目录)（execute_service 复用同一 project_root()），
config.json 直接写成**新结构**（菜单→导航→工具 dict），全部工具用 链接/下载/相对文件 类
（不触发 subprocess），校验 tool_grid 的导航键取数与 相对路径（菜单/导航 目录树）解析。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge import execute_service
from bridge import menu_service


def test_download_streams_chunks_not_full_read(root, monkeypatch):
    """v2.0.12：下载链接改 1MB 分块流式写盘（旧版 resp.read() 全量入内存）；
    分块序列断言 + 回写 config + 文件字节完整。"""
    import io

    cfg_dir = root / "config"
    cfg = json.loads((cfg_dir / "config.json").read_text(encoding="utf-8"))
    cfg["红队"]["navigation_bar_name"]["扫描"].append(
        {"工具名称": "dl", "工具路径": "http://x.com/dl.zip",
         "启动方式": "下载链接", "工具命令": ""})
    (cfg_dir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    payload = b"a" * (3 * 1024 * 1024 + 7)  # 3MB+7：验证跨块切分
    chunks_seen: list[int] = []

    class _FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            chunks_seen.append(n)
            return super().read(n)

    monkeypatch.setattr(execute_service.urllib.request, "urlopen",
                       lambda *a, **k: _FakeResp(payload))
    r = execute_service.run_tool("红队", "dl")
    assert r["ok"] is True
    # 文件完整
    f = root / "红队" / "扫描" / "dl" / "dl.zip"
    assert f.read_bytes() == payload
    # 分块读：全部 1MB 块（非一次性全量 -1）
    assert chunks_seen and all(n == 1024 * 1024 for n in chunks_seen), chunks_seen[:4]
    # 回写 config：工具路径 → dl/dl.zip（相对 菜单/导航 目录）
    cfg2 = json.loads((cfg_dir / "config.json").read_text(encoding="utf-8"))
    dl_tool = next(t for t in cfg2["红队"]["navigation_bar_name"]["扫描"]
                   if t["工具名称"] == "dl")
    assert dl_tool["工具路径"] == "dl/dl.zip"


def test_download_failure_removes_partial_file(root, monkeypatch):
    """v2.0.12：下载失败清理残留部分文件（避免下次误判已下载）。"""
    import io

    cfg_dir = root / "config"
    cfg = json.loads((cfg_dir / "config.json").read_text(encoding="utf-8"))
    cfg["红队"]["navigation_bar_name"]["扫描"].append(
        {"工具名称": "dl2", "工具路径": "http://x.com/dl2.zip",
         "启动方式": "下载链接", "工具命令": ""})
    (cfg_dir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    class _Boom(io.BytesIO):
        def __init__(self):
            super().__init__(b"partial")
            self._n = 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            self._n += 1
            if self._n == 1:
                return super().read(n)
            raise ConnectionError("boom")

    monkeypatch.setattr(execute_service.urllib.request, "urlopen", _Boom)
    with pytest.raises(execute_service.ToolError) as exc:
        execute_service.run_tool("红队", "dl2")
    assert exc.value.code == "TOOL_DOWNLOAD_FAIL"
    # 残留部分文件已清理
    assert not (root / "红队" / "扫描" / "dl2" / "dl2.zip").exists()
    # config 未回写（仍是 URL）
    cfg2 = json.loads((cfg_dir / "config.json").read_text(encoding="utf-8"))
    dl_tool = next(t for t in cfg2["红队"]["navigation_bar_name"]["扫描"]
                   if t["工具名称"] == "dl2")
    assert dl_tool["工具路径"] == "http://x.com/dl2.zip"


@pytest.fixture
def root(tmp_path):
    menu_service.set_root(tmp_path)   # execute_service 复用同一 project_root()
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    # 新结构：导航为 dict（键序即导航栏顺序，值 = 该导航下工具数组）
    cfg = {"红队": {
        "menu_color": "#f00",
        "menu_visible": 1,
        "navigation_bar_name": {
            "首页": [
                {"工具名称": "home1", "工具路径": "http://x.com/h",
                 "启动方式": "链接打开", "工具命令": ""},
            ],
            "扫描": [
                {"工具名称": "scan1", "工具路径": "http://x.com/scan",
                 "启动方式": "链接打开", "工具命令": ""},
                {"工具名称": "rel1", "工具路径": "sub/rel1.exe",
                 "启动方式": "直接打开", "工具命令": ""},
            ],
            "杂项": [],
        },
    }}
    (cfg_dir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    yield tmp_path
    menu_service.set_root(Path(__file__).resolve().parent.parent / "bridge" / "..")


def test_grid_by_nav_key(root):
    """导航键 即 工具归属（旧版 首页 index==1 特判消失）：首页 只取 首页 键下工具。"""
    grid = execute_service.tool_grid("红队", "首页")
    assert [t["工具名称"] for t in grid["tools"]] == ["home1"]


def test_grid_nav_filters(root):
    grid = execute_service.tool_grid("红队", "扫描")
    assert set(t["工具名称"] for t in grid["tools"]) == {"scan1", "rel1"}
    # 每条带 工具使用=该导航名（前端展示用）
    assert all(t["工具使用"] == "扫描" for t in grid["tools"])


def test_grid_empty_nav(root):
    assert execute_service.tool_grid("红队", "杂项")["tools"] == []


def test_http_tools_active(root):
    for t in execute_service.tool_grid("红队", "首页")["tools"]:
        assert t["active"] is True  # 链接类工具恒可用


def test_relative_path_resolves_under_menu_nav(root):
    """相对路径 → <根>/<菜单>/<导航>/<工具路径>；文件不存在 → 置灰。"""
    t = {"工具名称": "rel1", "工具路径": "sub/rel1.exe", "启动方式": "直接打开", "工具命令": ""}
    kind, resolved = execute_service._resolve(t, "红队", "扫描")
    assert kind == 2
    expected = root / "红队" / "扫描" / "sub" / "rel1.exe"
    assert Path(resolved) == expected
    grid = execute_service.tool_grid("红队", "扫描")
    rel = next(x for x in grid["tools"] if x["工具名称"] == "rel1")
    assert rel["active"] is False  # 文件尚未创建 → 置灰


def test_relative_path_active_when_file_exists(root):
    (root / "红队" / "扫描" / "sub").mkdir(parents=True)
    (root / "红队" / "扫描" / "sub" / "rel1.exe").write_text("x")
    grid = execute_service.tool_grid("红队", "扫描")
    rel = next(x for x in grid["tools"] if x["工具名称"] == "rel1")
    assert rel["active"] is True


def test_unknown_menu_raises(root):
    with pytest.raises(menu_service.MenuError) as exc:
        execute_service.tool_grid("no_such", "首页")
    assert exc.value.code == "MENU_NOT_FOUND"


def test_missing_tool_raises(root):
    with pytest.raises(execute_service.ToolError) as exc:
        execute_service.run_tool("红队", "no_such_tool")
    assert exc.value.code == "TOOL_NOT_FOUND"


def test_resolve_download_unloaded_is_kind3(root):
    t = {"工具名称": "d", "工具路径": "http://x.com/d.zip", "启动方式": "下载链接", "工具命令": ""}
    kind, resolved = execute_service._resolve(t, "红队", "首页")
    assert kind == 3 and resolved == "http://x.com/d.zip"


def test_resolve_download_loaded_is_kind4(root):
    # 已下载：工具路径 为 相对 菜单/导航 目录的本地路径
    t = {"工具名称": "d", "工具路径": "d/d.zip", "启动方式": "下载链接", "工具命令": ""}
    kind, resolved = execute_service._resolve(t, "红队", "首页")
    assert kind == 4


# ---- v2.2.5：打开所在文件夹（_tool_folder_target 纯解析）----

def test_folder_target_link_rejected(root):
    """链接类工具没有本地文件夹 → TOOL_NO_FOLDER。"""
    from bridge.execute_service import ToolError
    tool = {"工具名称": "home1", "工具路径": "http://x.com/h", "启动方式": "链接打开", "工具命令": ""}
    with pytest.raises(ToolError) as cm:
        execute_service._tool_folder_target(tool, "红队", "首页")
    assert cm.value.code == "TOOL_NO_FOLDER"


def test_folder_target_relative_file_selects_parent(root):
    """相对路径文件：选中该文件、打开其父目录（菜单/导航 目录树解析）。"""
    f = root / "红队" / "扫描" / "sub" / "rel1.exe"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
    tool = {"工具名称": "rel1", "工具路径": "sub/rel1.exe", "启动方式": "直接打开", "工具命令": ""}
    select, open_dir = execute_service._tool_folder_target(tool, "红队", "扫描")
    assert Path(select) == f
    assert Path(open_dir) == f.parent


def test_folder_target_dir_opens_itself(root):
    """文件夹打开类工具：目标目录即打开目录。"""
    d = root / "红队" / "扫描" / "toolkit"
    d.mkdir(parents=True, exist_ok=True)
    tool = {"工具名称": "kit", "工具路径": "toolkit", "启动方式": "文件夹打开", "工具命令": ""}
    select, open_dir = execute_service._tool_folder_target(tool, "红队", "扫描")
    assert Path(select) == d and Path(open_dir) == d


def test_folder_target_missing(root):
    """路径不存在 → TOOL_FOLDER_MISSING。"""
    from bridge.execute_service import ToolError
    tool = {"工具名称": "ghost", "工具路径": "no/such.exe", "启动方式": "直接打开", "工具命令": ""}
    with pytest.raises(ToolError) as cm:
        execute_service._tool_folder_target(tool, "红队", "扫描")
    assert cm.value.code == "TOOL_FOLDER_MISSING"
