"""菜单 service：config/config.json 的 CRUD（菜单栏 / 导航栏 / 工具 全量数据源）。

新数据模型（Phase 4，旧 tools.txt 已退役）：
  {
    "Windows红队工具箱": {
      "menu_color": "#ff0000",
      "menu_visible": 1,                    # 菜单栏展示：1 显示 / 0 隐藏
      "navigation_bar_name": {             # 键序 = 导航栏顺序，值 = 该导航下的工具数组
        "首页":       [ {"工具名称","工具路径","启动方式","工具命令"} ],
        "资产收集":   [ ... ]
      }
    }
  }
  - 工具不再写 <menu_path>/tools.txt，全部存 config.json（归属 = 所在的菜单键 + 导航键，
    结构即数据，「工具分类/工具使用」字段不再存在）
  - 菜单栏不再需要 工具文件夹路径（menu_path 字段停止使用）
  - 相对路径语义：工具箱根目录 / <菜单名> / <导航名> / <工具路径>（缺目录逐级创建）

一次性迁移（_maybe_migrate，幂等）：
  检测到旧结构（条目含 menu_path / navigation_bar_name 是 list）→
  先备份 config.json.bak → nav list 转 dict → 旧 tools.txt 按「工具使用」分发
  （「工具使用」为空的工具直接丢弃不展示）→ 旧本地相对路径改写为绝对路径（指向原
  menu_path 位置，文件不搬动）→ 删除旧 tools.txt。回滚 = config.json.bak 覆盖。

固定菜单栏（首页/AI对话/…）显隐表：根级保留键 __fixed_menu_visible__（1 显示 / 0 隐藏）。

错误码：
  MENU_NOT_FOUND / NAV_NAME_EXISTS / MENU_NAME_EXISTS / TOOL_NAME_EXISTS /
  TOOL_NOT_FOUND / INTERNAL
"""
from __future__ import annotations

import json
import os
import sys
import shutil
import tempfile
from pathlib import Path
from typing import Optional

# 项目根（bridge/menu_service.py → 上一级）
if getattr(sys, "frozen", False):  # PyInstaller：可写状态（config/ 等）放 exe 旁
    _PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.json"

# 5 种启动方式（与旧版 add_Tools 的 Combobox 完全一致）
RUN_TYPES = ["直接打开", "命令行打开", "文件夹打开", "链接打开", "下载链接"]
_LINK_TYPES = ("下载链接", "链接打开")
_FIXED_VISIBLE_KEY = "__fixed_menu_visible__"
_CONFIG_BACKUP = "config.json.bak"  # 迁移前自动备份（同目录）


def set_root(root) -> None:
    """覆写项目根（测试用临时目录，避免污染真实 config/）。"""
    global _PROJECT_ROOT, _CONFIG_PATH
    _PROJECT_ROOT = Path(root)
    _CONFIG_PATH = _PROJECT_ROOT / "config" / "config.json"


def project_root() -> Path:
    """当前项目根（execute_service 等跨模块复用，保证 set_root 单一真相源）。"""
    return _PROJECT_ROOT


class MenuError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# ---- 原子写 ----
def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".cfg_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ---- 读 ----
def load_config() -> dict:
    try:
        cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    _maybe_migrate(cfg)
    _maybe_migrate_fixed_rename(cfg)
    return cfg


def _maybe_migrate_fixed_rename(cfg: dict) -> None:
    """一次性改名迁移：固定菜单栏「本地终端」→「终端管理」（显隐表旧键平移，幂等）。"""
    table = cfg.get(_FIXED_VISIBLE_KEY)
    if isinstance(table, dict) and "本地终端" in table and "终端管理" not in table:
        table["终端管理"] = table.pop("本地终端")
        _atomic_write_json(_CONFIG_PATH, cfg)


def _menu_items(cfg: dict) -> list:
    """仅用户菜单栏条目（跳过 __ 开头的保留键，如 __fixed_menu_visible__）。"""
    return [(k, v) for k, v in cfg.items() if not str(k).startswith("__")]


def get_menu_entry(menu_name: str) -> dict:
    """取菜单配置（不存在抛 MENU_NOT_FOUND）。execute_service 等跨模块取数用。"""
    cfg = load_config()
    entry = cfg.get(menu_name)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu_name} 不存在")
    return entry


def _navs(entry: dict) -> dict:
    """菜单的 导航名→工具数组 映射（缺省空 dict）。"""
    v = entry.get("navigation_bar_name")
    return v if isinstance(v, dict) else {}


def _nav_names(entry: dict) -> list:
    return list(_navs(entry).keys())


# ---- 一次性迁移（旧 tools.txt / nav list / menu_path → 新 config 结构）----
def _needs_migration(cfg: dict) -> bool:
    for _, v in _menu_items(cfg):
        if "menu_path" in v:
            return True
        if isinstance(v.get("navigation_bar_name"), list):
            return True
    return False


def _maybe_migrate(cfg: dict) -> None:
    """幂等迁移：仅当检测到旧结构时执行一次（迁移后旧文件已删，不会二次触发）。"""
    if not _needs_migration(cfg):
        return
    # 备份（首次；.bak 已存在则不覆盖，保住可回滚点）
    if _CONFIG_PATH.exists() and not (_CONFIG_PATH.parent / _CONFIG_BACKUP).exists():
        shutil.copy2(_CONFIG_PATH, _CONFIG_PATH.parent / _CONFIG_BACKUP)

    for name, entry in _menu_items(cfg):
        old_path = str(entry.pop("menu_path", "")).strip()
        # nav list → dict（保持原顺序；无 nav 的菜单给默认 首页）
        old_navs = entry.get("navigation_bar_name")
        if isinstance(old_navs, list):
            entry["navigation_bar_name"] = {n: [] for n in old_navs} or {"首页": []}
        entry.setdefault("menu_visible", 1)
        # 旧 tools.txt → 按「工具使用」分发进对应导航（为空的直接丢弃）
        if old_path:
            txt = _PROJECT_ROOT / old_path / "tools.txt"
            if txt.exists():
                new_navs: dict = entry["navigation_bar_name"]
                for line in txt.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        t = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    use = str(t.get("工具使用", "")).strip()
                    if not use:
                        continue  # 「工具使用」为空 → 不展示（新结构无处安放）
                    run_type = str(t.get("启动方式", ""))
                    tpath = str(t.get("工具路径", "")).strip()
                    # 旧本地相对路径（相对 <root>/<menu_path>/，含 已下载下载链接 的本地文件）
                    # → 改写为绝对路径指向原位置（文件不搬动；新下载走新目录树）
                    if "http" not in tpath and not os.path.isabs(tpath) and tpath:
                        tpath = str(_PROJECT_ROOT / old_path / tpath)
                    rec = {
                        "工具名称": str(t.get("工具名称", "")).strip(),
                        "工具路径": tpath,
                        "启动方式": run_type,
                        "工具命令": str(t.get("工具命令", "")),
                    }
                    new_navs.setdefault(use, []).append(rec)
                txt.unlink()  # 旧文件不再保留（数据已入 config，回滚走 .bak）
    _atomic_write_json(_CONFIG_PATH, cfg)


# ---- 菜单栏 CRUD ----
def list_menus() -> list:
    """每个菜单：{ name, menu_color, menu_visible, navigation_bar_name(名序), tool_count }。

    navigation_bar_name 返回**导航名列表**（顺序即 dict 键序）；工具数据在 list_tools。"""
    cfg = load_config()
    out = []
    for name, v in _menu_items(cfg):
        out.append({
            "name": name,
            "menu_path": "",  # 新模型不再有工具文件夹（保留字段以兼容前端类型）
            "menu_color": v.get("menu_color", ""),
            "navigation_bar_name": _nav_names(v),
            "tool_count": sum(len(x) for x in _navs(v).values()),
            "menu_visible": 1 if v.get("menu_visible", 1) else 0,
        })
    return out


def add_menu(name: str, menu_color: str,
             navigation: Optional[list] = None) -> dict:
    """新增菜单栏：**无需 工具文件夹路径**，不创建任何目录。
    新菜单默认 首页 导航（或传入的导航名列表）。"""
    name = (name or "").strip()
    if not name:
        raise MenuError("INTERNAL", "菜单名称不能为空")
    if not menu_color or menu_color == "这里显示选择的颜色":
        menu_color = "#2980b9"  # 旧版未选色时的兜底
    cfg = load_config()
    for existing, _v in _menu_items(cfg):
        if existing == name:
            raise MenuError("MENU_NAME_EXISTS", f"菜单栏 {name} 已存在")
    _check_new_name(name, "菜单栏")
    entry = {
        "menu_color": menu_color,
        "menu_visible": 1,
        "navigation_bar_name": {n: [] for n in (navigation or ["首页"])},
    }
    cfg[name] = entry
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"name": name, "menu_color": menu_color,
            "navigation_bar_name": list(entry["navigation_bar_name"].keys())}


def delete_menu(name: str) -> dict:
    """删除菜单栏（连同其全部工具；不影响其它菜单与固定菜单）。"""
    name = (name or "").strip()
    cfg = load_config()
    if name not in dict(_menu_items(cfg)):
        raise MenuError("MENU_NOT_FOUND", f"菜单 {name} 不存在")
    del cfg[name]
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"deleted": name}


def reorder_menus(order: list) -> dict:
    """拖拽重排用户菜单栏：order 必须是当前全部菜单名的一个排列。
    config.json 是扁平 {菜单名: 配置} dict，Python dict 保持插入顺序 →
    按 order 重建 dict 即持久化新顺序；__ 保留键原样保留。"""
    cfg = load_config()
    names = [k for k, _ in _menu_items(cfg)]
    if sorted([str(x) for x in order]) != sorted(names):
        raise MenuError("MENU_NOT_FOUND", "重排序列与当前菜单不一致，请刷新后重试")
    ordered = {str(x): cfg[str(x)] for x in order}
    preserved = {k: v for k, v in cfg.items() if str(k).startswith("__")}
    _atomic_write_json(_CONFIG_PATH, {**ordered, **preserved})
    return {"order": [str(x) for x in order]}


# ---- 重命名（菜单栏 / 导航栏）----
# 新名禁止空格与路径特殊字符（菜单栏/导航栏名会作为相对路径的目录段）。
_BAD_NAME_CHARS = set(' \t/:*?"<>|\\')


def _check_new_name(new_name: str, label: str) -> None:
    if any(c in _BAD_NAME_CHARS for c in new_name):
        raise MenuError("INTERNAL", f"{label}名称不能包含空格或特殊字符 / : * ? \" < > |")


def rename_menu(name: str, new_name: str) -> dict:
    """菜单栏改名：只改 config 键（结构即数据，无需同步任何字段）。"""
    name = (name or "").strip()
    new_name = (new_name or "").strip()
    cfg = load_config()
    if name not in dict(_menu_items(cfg)):
        raise MenuError("MENU_NOT_FOUND", f"菜单 {name} 不存在")
    if new_name != name:
        if not new_name:
            raise MenuError("INTERNAL", "菜单栏新名称不能为空")
        if new_name in cfg or new_name.startswith("__"):
            raise MenuError("MENU_NAME_EXISTS", f"菜单栏 {new_name} 已存在")
        _check_new_name(new_name, "菜单栏")
        cfg[new_name] = cfg.pop(name)
        _atomic_write_json(_CONFIG_PATH, cfg)
    return {"name": new_name}


def rename_nav(menu_name: str, nav_name: str, new_nav: str) -> dict:
    """导航栏改名：重命名 navigation_bar_name 的键（该键下工具数组随键移动）。"""
    cfg = load_config()
    entry = cfg.get(menu_name)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu_name} 不存在")
    nav_name = (nav_name or "").strip()
    new_nav = (new_nav or "").strip()
    navs = _navs(entry)
    if nav_name not in navs:
        raise MenuError("NAV_NAME_EXISTS", f"导航栏 {nav_name} 不存在")
    if new_nav != nav_name:
        if not new_nav:
            raise MenuError("INTERNAL", "导航栏新名称不能为空")
        if new_nav in navs:
            raise MenuError("NAV_NAME_EXISTS", f"导航栏 {new_nav} 已存在")
        _check_new_name(new_nav, "导航栏")
        moved = navs.pop(nav_name)
        navs[new_nav] = moved
        _atomic_write_json(_CONFIG_PATH, cfg)
    return {"menu": menu_name, "navigation_bar_name": list(navs.keys())}


# ---- 导航栏 CRUD ----
def add_nav(menu_name: str, nav_name: str) -> dict:
    cfg = load_config()
    entry = cfg.get(menu_name)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu_name} 不存在")
    nav_name = (nav_name or "").strip()
    if not nav_name:
        raise MenuError("INTERNAL", "导航栏名称不能为空")
    _check_new_name(nav_name, "导航栏")
    navs = _navs(entry)
    if nav_name in navs:
        raise MenuError("NAV_NAME_EXISTS", f"导航栏 {nav_name} 已存在")
    navs[nav_name] = []
    entry["navigation_bar_name"] = navs
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"menu": menu_name, "navigation_bar_name": list(navs.keys())}


def delete_nav(menu_name: str, nav_name: str) -> dict:
    """删除导航栏：**连同其下工具数组一起删除**（前端已二次确认）。"""
    cfg = load_config()
    entry = cfg.get(menu_name)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu_name} 不存在")
    navs = _navs(entry)
    if nav_name not in navs:
        raise MenuError("NAV_NAME_EXISTS", f"导航栏 {nav_name} 不存在")
    removed = len(navs.pop(nav_name))
    entry["navigation_bar_name"] = navs
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"menu": menu_name, "navigation_bar_name": list(navs.keys()),
            "removed_tools": removed}


def reorder_navs(menu_name: str, order: list) -> dict:
    """拖拽重排某菜单下的导航栏：order 必须是该菜单当前导航名的排列（按新序重建 dict）。"""
    cfg = load_config()
    entry = cfg.get(menu_name)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu_name} 不存在")
    navs = _navs(entry)
    if sorted([str(x) for x in order]) != sorted(list(navs.keys())):
        raise MenuError("NAV_NAME_EXISTS", "重排序列与当前导航栏不一致，请刷新后重试")
    entry["navigation_bar_name"] = {str(x): navs[str(x)] for x in order}
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"menu": menu_name, "navigation_bar_name": [str(x) for x in order]}


# ---- 显隐（菜单栏展示设置：1 显示 / 0 隐藏）----
def set_visible(name: str, visible: bool) -> dict:
    """用户菜单栏显隐：cfg[菜单]["menu_visible"] = 1|0。"""
    name = (name or "").strip()
    cfg = load_config()
    if name not in dict(_menu_items(cfg)):
        raise MenuError("MENU_NOT_FOUND", f"菜单 {name} 不存在")
    cfg[name]["menu_visible"] = 1 if visible else 0
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"name": name, "menu_visible": 1 if visible else 0}


def set_fixed_visible(name: str, visible: bool) -> dict:
    """固定菜单栏（首页/AI对话/…）显隐：cfg[__fixed_menu_visible__][名称] = 1|0。"""
    name = (name or "").strip()
    if not name:
        raise MenuError("INTERNAL", "固定菜单栏名称不能为空")
    cfg = load_config()
    table = cfg.setdefault(_FIXED_VISIBLE_KEY, {})
    table[name] = 1 if visible else 0
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"name": name, "visible": 1 if visible else 0}


def list_fixed_visible() -> dict:
    """固定菜单栏显隐表：{名称: 1|0}，缺省视为 1（显示）。"""
    cfg = load_config()
    raw = cfg.get(_FIXED_VISIBLE_KEY, {})
    return {str(k): (1 if v else 0) for k, v in raw.items()}


# ---- 工具 CRUD（config.json 内 菜单→导航→工具数组）----
def _menu_tools(entry: dict) -> list:
    """展平菜单下全部导航的工具（每条附 nav 字段）。"""
    out = []
    for nav, tools in _navs(entry).items():
        for t in tools:
            out.append({**t, "nav": nav})
    return out


def _resolved_dir(entry_menu: str, nav: str, tool_path: str) -> Path:
    """相对路径解析：工具箱根 / <菜单名> / <导航名> / <工具路径>。"""
    norm = str(tool_path).replace("\\", "/")
    return _PROJECT_ROOT / entry_menu / nav / Path(norm)


def add_tool(name: str, path: str, menu: str, use: str,
             run_type: str, command: str = "") -> dict:
    """新增工具：写入 cfg[菜单].navigation_bar_name[use]。
    - 工具名全菜单唯一（跨导航）
    - use 必须是该菜单已有导航（前端只会传已有导航）
    - 命令行打开需带 * 占位；链接类需 http
    - 非链接类的相对路径：自动逐级创建 <根>/<菜单>/<导航>/<目录段>
    """
    name = (name or "").strip()
    path = (path or "").strip()
    use = (use or "").strip() or "首页"
    if not name:
        raise MenuError("INTERNAL", "工具名称不能为空")
    cfg = load_config()
    entry = cfg.get(menu)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu} 不存在")
    navs = _navs(entry)
    if use not in navs:
        raise MenuError("NAV_NAME_EXISTS", f"导航栏 {use} 不存在（请先新增该导航栏）")
    for t in _menu_tools(entry):
        if t.get("工具名称") == name:
            raise MenuError("TOOL_NAME_EXISTS", f"工具名称 {name} 已存在")
    if run_type not in RUN_TYPES:
        raise MenuError("INTERNAL", f"未知启动方式 {run_type}")
    if run_type == "命令行打开" and "*" not in command:
        raise MenuError("INTERNAL", "命令行打开的启动命令需用 * 占位工具名/路径")
    if run_type in _LINK_TYPES and "http" not in path:
        raise MenuError("INTERNAL", f"{run_type} 的工具路径需是 http(s) 链接")

    # 非链接类的相对路径 → 逐级创建目标目录链（文件夹打开连目标目录本身也建）
    if run_type not in _LINK_TYPES and not os.path.isabs(path) and "http" not in path:
        target = _resolved_dir(menu, use, path)
        (target if run_type == "文件夹打开" else target.parent).mkdir(parents=True, exist_ok=True)

    tool_info = {
        "工具名称": name,
        "工具路径": path,
        "启动方式": run_type,
        "工具命令": command or "",
    }
    navs[use].append(tool_info)
    entry["navigation_bar_name"] = navs
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {**tool_info, "nav": use}


def delete_tool(menu: str, name: str) -> dict:
    """删除工具（跨该菜单全部导航查找）。"""
    name = (name or "").strip()
    cfg = load_config()
    entry = cfg.get(menu)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu} 不存在")
    navs = _navs(entry)
    hit = False
    for nav, tools in navs.items():
        kept = [t for t in tools if t.get("工具名称") != name]
        if len(kept) != len(tools):
            navs[nav] = kept
            hit = True
    if not hit:
        raise MenuError("TOOL_NOT_FOUND", f"工具 {name} 不存在")
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"menu": menu, "deleted": name}


def list_tools(menu: str) -> list:
    """菜单下全部工具（展平，每条带 nav 字段 = 所属导航栏名）。"""
    entry = get_menu_entry(menu)
    return _menu_tools(entry)


def update_tool_path(menu: str, name: str, new_path: str) -> dict:
    """下载成功后把 工具路径 改写为新值（1:1 旧版语义，现写 config）。"""
    new_path = (new_path or "").strip()
    if not new_path:
        raise MenuError("INTERNAL", "新的工具路径不能为空")
    cfg = load_config()
    entry = cfg.get(menu)
    if entry is None:
        raise MenuError("MENU_NOT_FOUND", f"菜单 {menu} 不存在")
    hit = False
    for tools in _navs(entry).values():
        for t in tools:
            if t.get("工具名称") == name:
                t["工具路径"] = new_path
                hit = True
    if not hit:
        raise MenuError("TOOL_NOT_FOUND", f"工具 {name} 不存在")
    _atomic_write_json(_CONFIG_PATH, cfg)
    return {"menu": menu, "name": name, "new_path": new_path}


def changed_snapshot() -> dict:
    """menu.changed 事件 payload：全量菜单（前端据此重建路由）。"""
    return {"menus": list_menus()}
