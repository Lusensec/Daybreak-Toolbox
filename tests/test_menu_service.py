"""menu service 单测（新数据模型：工具全部存 config/config.json，set_root 隔离）。

覆盖：
  - 菜单栏 增（无需 工具文件夹路径）/删/重排/重命名 + 重名/特殊字符 校验
  - 导航栏（config 内 导航键）增/删(连同工具)/重排/重命名
  - 工具 存于 菜单→导航 结构：增（5 种启动方式 + 全菜单唯一 + 归属导航必须存在）/删/列(带 nav)
  - 显隐参数（menu_visible / __fixed_menu_visible__）
  - 一次性迁移器（旧 menu_path + nav list + tools.txt → 新结构；丢弃 工具使用 为空的工具；
    相对路径绝对化；删旧文件；.bak 备份；幂等）
  - 相对路径 目录链自动创建（<根>/<菜单>/<导航>/<工具路径>）

运行：python tests\\test_menu_service.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bridge.menu_service as ms  # noqa: E402


class MenuServiceTest(unittest.TestCase):
    """新模型基础 CRUD（config 内 菜单→导航→工具）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        ms.set_root(self.root)
        # 预置一个**新结构**菜单（导航为 dict，无 menu_path）
        cfg_dir = os.path.join(self.root, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"Windows红队工具箱": {
                "menu_color": "#ff0000",
                "menu_visible": 1,
                "navigation_bar_name": {"首页": [], "资产收集": []},
            }}, f, ensure_ascii=False, indent=4)

    def tearDown(self):
        self._tmp.cleanup()

    # ---- 读 ----
    def test_list_menus(self):
        menus = ms.list_menus()
        self.assertEqual(len(menus), 1)
        m = menus[0]
        self.assertEqual(m["name"], "Windows红队工具箱")
        self.assertEqual(m["navigation_bar_name"], ["首页", "资产收集"])
        self.assertEqual(m["tool_count"], 0)
        self.assertEqual(m["menu_visible"], 1)

    def test_empty_config_returns_empty(self):
        empty = tempfile.TemporaryDirectory()
        try:
            ms.set_root(empty.name)
            self.assertEqual(ms.list_menus(), [])
            self.assertEqual(ms.load_config(), {})
        finally:
            ms.set_root(self.root)

    # ---- 菜单 CRUD（无需 工具文件夹路径）----
    def test_add_menu_no_path(self):
        ms.add_menu("新菜单", "#123456")
        menus = {m["name"]: m for m in ms.list_menus()}
        self.assertEqual(menus["新菜单"]["menu_path"], "")  # 不再有工具文件夹
        self.assertEqual(menus["新菜单"]["navigation_bar_name"], ["首页"])
        self.assertEqual(menus["新菜单"]["menu_visible"], 1)
        # 未创建任何目录
        self.assertFalse(os.path.exists(os.path.join(self.root, "新菜单")))

    def test_add_menu_default_color(self):
        ms.add_menu("无色菜单", "")
        menus = {m["name"]: m for m in ms.list_menus()}
        self.assertEqual(menus["无色菜单"]["menu_color"], "#2980b9")

    def test_add_menu_duplicate_name(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_menu("Windows红队工具箱", "#000000")
        self.assertEqual(cm.exception.code, "MENU_NAME_EXISTS")

    def test_add_menu_bad_chars(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_menu("新 名", "#1")
        self.assertEqual(cm.exception.code, "INTERNAL")

    def test_delete_menu_removes_all_tools(self):
        ms.add_tool("t1", "t1.exe", "Windows红队工具箱", "首页", "直接打开")
        ms.delete_menu("Windows红队工具箱")
        self.assertEqual(ms.list_menus(), [])

    def test_delete_menu_missing(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.delete_menu("幽灵")
        self.assertEqual(cm.exception.code, "MENU_NOT_FOUND")

    def test_reorder_menus(self):
        ms.add_menu("菜单A", "#1")
        ms.add_menu("菜单B", "#2")
        ms.reorder_menus(["菜单B", "菜单A", "Windows红队工具箱"])
        self.assertEqual(
            [m["name"] for m in ms.list_menus()], ["菜单B", "菜单A", "Windows红队工具箱"])

    def test_reorder_menus_preserves_reserved_keys(self):
        ms.set_fixed_visible("首页", False)
        ms.reorder_menus(["Windows红队工具箱"])
        self.assertEqual(ms.list_fixed_visible().get("首页"), 0)

    def test_rename_menu(self):
        ms.rename_menu("Windows红队工具箱", "新菜单名")
        self.assertEqual([m["name"] for m in ms.list_menus()], ["新菜单名"])

    def test_rename_menu_exists(self):
        # 相同名：无操作、不报错
        ms.rename_menu("Windows红队工具箱", "Windows红队工具箱")
        self.assertEqual([m["name"] for m in ms.list_menus()], ["Windows红队工具箱"])
        # 重名到已存在 → 报错
        ms.add_menu("菜单B", "#3")
        with self.assertRaises(ms.MenuError) as cm:
            ms.rename_menu("Windows红队工具箱", "菜单B")
        self.assertEqual(cm.exception.code, "MENU_NAME_EXISTS")

    # ---- 导航栏 CRUD ----
    def test_add_nav(self):
        ms.add_nav("Windows红队工具箱", "扫描")
        self.assertEqual(
            ms.list_menus()[0]["navigation_bar_name"], ["首页", "资产收集", "扫描"])

    def test_add_nav_exists(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_nav("Windows红队工具箱", "首页")
        self.assertEqual(cm.exception.code, "NAV_NAME_EXISTS")

    def test_add_nav_bad_menu(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_nav("幽灵", "x")
        self.assertEqual(cm.exception.code, "MENU_NOT_FOUND")

    def test_delete_nav_removes_tools(self):
        ms.add_tool("t1", "t1.exe", "Windows红队工具箱", "资产收集", "直接打开")
        ms.add_tool("t2", "t2.exe", "Windows红队工具箱", "资产收集", "直接打开")
        r = ms.delete_nav("Windows红队工具箱", "资产收集")
        self.assertEqual(r["removed_tools"], 2)
        self.assertEqual(ms.list_menus()[0]["tool_count"], 0)

    def test_rename_nav_moves_tools(self):
        ms.add_tool("t1", "t1.exe", "Windows红队工具箱", "资产收集", "直接打开")
        ms.rename_nav("Windows红队工具箱", "资产收集", "流量分析")
        cfg = ms.load_config()
        self.assertEqual(
            cfg["Windows红队工具箱"]["navigation_bar_name"]["流量分析"][0]["工具名称"], "t1")

    def test_rename_nav_exists(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.rename_nav("Windows红队工具箱", "资产收集", "首页")
        self.assertEqual(cm.exception.code, "NAV_NAME_EXISTS")

    # ---- 工具 CRUD（config 内 菜单→导航→工具）----
    def test_add_tool_and_list_with_nav(self):
        r = ms.add_tool("t1", "t1.exe", "Windows红队工具箱", "首页", "直接打开")
        self.assertEqual(r["nav"], "首页")
        tools = ms.list_tools("Windows红队工具箱")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["nav"], "首页")
        self.assertNotIn("工具分类", tools[0])
        self.assertNotIn("工具使用", tools[0])

    def test_add_tool_creates_dir_chain(self):
        ms.add_tool("t1", "test/t1.exe", "Windows红队工具箱", "资产收集", "直接打开")
        self.assertTrue(os.path.isdir(
            os.path.join(self.root, "Windows红队工具箱", "资产收集", "test")))

    def test_add_tool_folder_open_creates_target_dir(self):
        ms.add_tool("myfolder", "mydir", "Windows红队工具箱", "首页", "文件夹打开")
        self.assertTrue(os.path.isdir(
            os.path.join(self.root, "Windows红队工具箱", "首页", "mydir")))

    def test_add_tool_requires_existing_nav(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_tool("t", "t.exe", "Windows红队工具箱", "不存在的导航", "直接打开")
        self.assertEqual(cm.exception.code, "NAV_NAME_EXISTS")

    def test_add_tool_name_unique_across_navs(self):
        ms.add_tool("t1", "a.exe", "Windows红队工具箱", "首页", "直接打开")
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_tool("t1", "b.exe", "Windows红队工具箱", "资产收集", "直接打开")
        self.assertEqual(cm.exception.code, "TOOL_NAME_EXISTS")

    def test_add_tool_cmdline_needs_star(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_tool("t", "t.exe", "Windows红队工具箱", "首页", "命令行打开", "python t.exe")
        self.assertEqual(cm.exception.code, "INTERNAL")

    def test_add_tool_link_needs_http(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.add_tool("t", "ftp://x", "Windows红队工具箱", "首页", "链接打开")
        self.assertEqual(cm.exception.code, "INTERNAL")

    def test_add_tool_download_no_dir_create(self):
        # 下载链接：不建本地目录，路径保持 URL
        r = ms.add_tool("dl", "https://x.y/dl.exe", "Windows红队工具箱", "首页", "下载链接")
        self.assertEqual(r["工具路径"], "https://x.y/dl.exe")

    def test_delete_tool(self):
        ms.add_tool("t1", "t1.exe", "Windows红队工具箱", "首页", "直接打开")
        ms.delete_tool("Windows红队工具箱", "t1")
        self.assertEqual(ms.list_tools("Windows红队工具箱"), [])

    def test_delete_tool_missing(self):
        with self.assertRaises(ms.MenuError) as cm:
            ms.delete_tool("Windows红队工具箱", "幽灵")
        self.assertEqual(cm.exception.code, "TOOL_NOT_FOUND")

    def test_update_tool_path(self):
        ms.add_tool("t1", "https://x.y/t1.zip", "Windows红队工具箱", "首页", "下载链接")
        ms.update_tool_path("Windows红队工具箱", "t1", "t1/t1.zip")
        self.assertEqual(ms.list_tools("Windows红队工具箱")[0]["工具路径"], "t1/t1.zip")

    # ---- 显隐（菜单栏展示：1 显示 / 0 隐藏）----
    def test_set_visible(self):
        ms.set_visible("Windows红队工具箱", False)
        self.assertEqual([m["menu_visible"] for m in ms.list_menus()], [0])
        ms.set_visible("Windows红队工具箱", True)
        self.assertEqual([m["menu_visible"] for m in ms.list_menus()], [1])

    def test_set_fixed_visible(self):
        ms.set_fixed_visible("首页", False)
        self.assertEqual(ms.list_fixed_visible().get("首页"), 0)
        # 显隐表对任意名称都可写（v2.1.3：固定功能面板已移除，只剩「首页」实际参与渲染）
        ms.set_fixed_visible("任意名称", True)
        self.assertEqual(ms.list_fixed_visible().get("任意名称"), 1)
        # 保留键不影响菜单列表
        self.assertEqual([m["name"] for m in ms.list_menus()], ["Windows红队工具箱"])


class MigrationTest(unittest.TestCase):
    """旧结构（menu_path + nav list + tools.txt）→ 新结构 的一次性迁移。"""

    def _write_old_config(self, tools_txt_lines):
        cfg_dir = os.path.join(self.root, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"旧菜单": {
                "menu_path": "mp",
                "menu_color": "#f00",
                "navigation_bar_name": ["首页", "资产收集"],
            }}, f, ensure_ascii=False, indent=4)
        os.makedirs(os.path.join(self.root, "mp"), exist_ok=True)
        with open(os.path.join(self.root, "mp", "tools.txt"), "w", encoding="utf-8") as f:
            for line in tools_txt_lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        ms.set_root(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_migrate_distributes_and_absolutizes(self):
        self._write_old_config([
            {"工具名称": "a", "工具路径": "test/a.exe", "工具分类": "旧菜单",
             "工具使用": "资产收集", "启动方式": "直接打开", "工具命令": ""},
            {"工具名称": "b", "工具路径": "b.exe", "工具分类": "旧菜单",
             "工具使用": "", "启动方式": "直接打开", "工具命令": ""},   # 使用 为空 → 丢弃
            {"工具名称": "c", "工具路径": "https://x.y/dl.exe", "工具分类": "旧菜单",
             "工具使用": "首页", "启动方式": "下载链接", "工具命令": ""},
        ])
        cfg = ms.load_config()  # 触发迁移
        m = cfg["旧菜单"]
        self.assertEqual(list(m["navigation_bar_name"].keys()), ["首页", "资产收集"])
        # 资产收集：a（相对路径绝对化，指向原 mp 位置，文件不搬动）
        a = m["navigation_bar_name"]["资产收集"][0]
        self.assertEqual(a["工具名称"], "a")
        self.assertTrue(os.path.isabs(a["工具路径"]))
        self.assertIn("mp", a["工具路径"].replace("\\", "/"))
        # 首页：c（下载链接保留 URL）
        self.assertEqual(m["navigation_bar_name"]["首页"][0]["工具名称"], "c")
        # b（使用 为空）被丢弃
        self.assertNotIn("b", [t["工具名称"] for n in m["navigation_bar_name"].values() for t in n])
        # 旧 tools.txt 已删除
        self.assertFalse(os.path.exists(os.path.join(self.root, "mp", "tools.txt")))
        # 备份已生成
        self.assertTrue(os.path.exists(os.path.join(self.root, "config", "config.json.bak")))

    def test_migrate_idempotent(self):
        import copy
        self._write_old_config([
            {"工具名称": "a", "工具路径": "a.exe", "工具分类": "旧菜单",
             "工具使用": "资产收集", "启动方式": "直接打开", "工具命令": ""},
        ])
        first = ms.load_config()
        snap = copy.deepcopy(first)
        second = ms.load_config()
        self.assertEqual(first, second)
        self.assertEqual(snap, second)

    def test_no_migration_on_new_structure(self):
        cfg_dir = os.path.join(self.root, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"M": {"menu_color": "#1", "menu_visible": 1,
                             "navigation_bar_name": {"首页": []}}}, f, ensure_ascii=False)
        cfg = ms.load_config()
        # 新结构不生成 .bak
        self.assertFalse(os.path.exists(os.path.join(self.root, "config", "config.json.bak")))
        self.assertIn("M", cfg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
