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
