"""快捷键设置 service：config/shortcuts.json 的 槽位(slot) → 组合键(combo) 扁平表。

设计（对齐「工具箱设置 → 快捷键设置」标签页）：
  - 单文件 config/shortcuts.json：
        { "panel": "Ctrl+Space",
          "dyn:Windows红队工具箱": "Ctrl+1",
          "fix:首页": "Ctrl+Alt+1",
          "nav:1": "Ctrl+Shift+1",
          "tool:Windows红队工具箱__主机端口扫描": "Ctrl+Shift+P" }
  - 槽位键固定前缀体系（默认组合由前端按当前菜单顺序生成，后端只做纯存储）：
      panel           回到面板（首页）
      dyn:<菜单名>    第 N 个用户动态菜单栏
      fix:<菜单名>    第 N 个系统固定菜单栏
      nav:<n>         当前菜单栏下第 n 个导航项（n=1..9，1=首页）
      tool:<菜单>__<工具>  工具快捷键（工具名菜单内唯一）
  - 组合串规范化格式：Ctrl[+Alt][+Shift]+<Key>
      * 必须含 Ctrl（避免与中文输入法/普通输入冲突）
      * Key ∈ A-Z / 0-9 / F1-F12 / Space
      * 空串 = 该槽位快捷键显式停用（区别于「未设置→用默认」）
  - 原子写：临时文件 + os.replace，防截断。

错误码：SHORTCUT_INVALID（槽位/组合键非法）/ SHORTCUT_CORRUPT（文件损坏）/ INTERNAL
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

# 项目根（bridge/shortcut_service.py → 上一级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "config" / "shortcuts.json"

# 槽位键：panel / dyn:x / fix:x / nav:数字 / tool:菜单__工具
_SLOT_RE = re.compile(r"^(panel|dyn:.+|fix:.+|nav:[0-9]+|tool:.+)$")
# 组合串：Ctrl[+Alt][+Shift]+(F1-F12 | 单字母 | 数字 | Space)
_COMBO_RE = re.compile(
    r"^Ctrl(\+Alt)?(\+Shift)?\+(F([1-9]|1[0-2])|[A-Z]|[0-9]|Space)$")


class ShortcutError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def set_root(root) -> None:
    """覆写项目根（测试用临时目录，避免污染真实 config/shortcuts.json）。"""
    global _PROJECT_ROOT, _CONFIG_FILE
    _PROJECT_ROOT = Path(root)
    _CONFIG_FILE = _PROJECT_ROOT / "config" / "shortcuts.json"


def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".shortcut_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _load_raw() -> dict:
    """读盘原始 dict；文件缺失 → 空表（首次使用时由 set 创建）。"""
    if not _CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ShortcutError("SHORTCUT_CORRUPT", "config/shortcuts.json 已损坏，请删除后重新设置")
    return data if isinstance(data, dict) else {}


def validate_shortcuts(shortcuts) -> None:
    """整表校验：键必须合法槽位，值必须是 空串（停用）或 合法组合串。"""
    if not isinstance(shortcuts, dict):
        raise ShortcutError("SHORTCUT_INVALID", "shortcuts 必须是 槽位→组合 的对象")
    for k, v in shortcuts.items():
        if not _SLOT_RE.match(str(k)):
            raise ShortcutError("SHORTCUT_INVALID", f"非法槽位键：{k}")
        v = str(v)
        if v and not _COMBO_RE.match(v):
            raise ShortcutError("SHORTCUT_INVALID", f"非法组合键：{v}（须 Ctrl[+Alt][+Shift]+字母/数字/F键/空格）")


def get_shortcuts() -> dict:
    """全量返回 {shortcuts: {slot: combo}}（文件缺失 → 空表，前端按默认渲染）。"""
    data = _load_raw()
    validate_shortcuts(data)  # 容忍手工编辑：脏数据直接报错，前端刷新回退
    return {"shortcuts": data}


def set_shortcuts(shortcuts: dict) -> dict:
    """整表覆盖保存（前端每次发全量 map；即时生效并广播 shortcut.changed）。
    必须显式传 dict —— None / 缺字段一律拒绝，避免误清空全表。"""
    if not isinstance(shortcuts, dict):
        raise ShortcutError("SHORTCUT_INVALID", "shortcuts 必须是 槽位→组合 的对象")
    shortcuts = {str(k): str(v) for k, v in shortcuts.items()}
    validate_shortcuts(shortcuts)
    _atomic_write(_CONFIG_FILE, shortcuts)
    return {"ok": True, "shortcuts": shortcuts}
