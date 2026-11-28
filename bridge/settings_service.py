"""通用设置 service：config/settings.json（桥接侧前后端共享的用户偏好，原子写）。

当前键：
  close_to_tray  「关闭后进入最小化」——开启时 顶栏关闭(X) / Alt+F4 → 窗口最小化并驻留托盘
                 （进程常驻，托盘菜单可重新唤回），而非退出进程。默认 False（关闭=退出，旧语义）。

设计对齐 shortcut_service / menu_service：
  - 相对项目根（frozen → exe 旁；开发 → 仓库根），set_root 供测试隔离
  - 原子写（临时文件 + os.replace），损坏/缺失 → 默认值（不抛）
  - 读无缓存：文件极小（<200B），每次读盘保证多进程/多端改动能即时看到
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

# 项目根（bridge/settings_service.py → 上一级；frozen → exe 旁）
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SETTINGS_PATH = _PROJECT_ROOT / "config" / "settings.json"

# 默认值（新增键在此扩展）
_DEFAULTS: Dict[str, Any] = {
    "close_to_tray": False,
}


def set_root(root) -> None:
    """覆写项目根（测试用临时目录，避免污染真实 config/）。"""
    global _PROJECT_ROOT, _SETTINGS_PATH
    _PROJECT_ROOT = Path(root)
    _SETTINGS_PATH = _PROJECT_ROOT / "config" / "settings.json"


class SettingsError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _raw() -> dict:
    """读盘（缺失/损坏 → {}；调用方叠加默认值）。"""
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_all() -> dict:
    """全部设置（叠加默认值；文件缺失 = 全默认）。"""
    out = dict(_DEFAULTS)
    out.update(_raw())
    return out


def _coerce(key: str, value: Any) -> Any:
    """按默认值类型做轻量校验（bool 键只接受真实 bool，拒绝字符串 "false" 类噪声）。"""
    if key not in _DEFAULTS:
        raise SettingsError("SETTINGS_KEY_INVALID", f"未知设置项 {key}")
    default = _DEFAULTS[key]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise SettingsError("SETTINGS_INVALID", f"设置项 {key} 需要布尔值")
        return value
    return value


def set(patch: dict) -> dict:
    """读-改-写（原子）；未知键/类型错抛 SettingsError。返回写入后的全量。"""
    if not isinstance(patch, dict) or not patch:
        raise SettingsError("SETTINGS_INVALID", "payload 必须为非空对象")
    with _write_guard:
        data = dict(_DEFAULTS)
        data.update(_raw())
        for k, v in patch.items():
            data[k] = _coerce(str(k), v)
        _atomic_write(_SETTINGS_PATH, data)
        return data


# 读-改-写串行锁（跨连接并发 settings.set 不互吃写一半的文件）
_write_guard = threading.Lock()
