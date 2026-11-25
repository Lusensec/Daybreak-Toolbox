"""更新 service：版本更新记录（原 fun.py get_update_record_content，纯数据已迁出）
+ GitHub 检查更新（本地版本 vs 仓库 latest Release）+ 仓库地址配置（config/update.json）。

旧版 tkinter 代码拆除后，Web「更新记录」标签页由本模块提供数据（update.record 命令）。
新版本发布时在此 dict 追加一条（版本号为 key，内容为多行说明）。
"""
import json
import os
import re
import urllib.error
import urllib.request

#: 应用当前版本（检查更新时与 GitHub latest Release 对比）
APP_VERSION = "2.0.3"

#: 内置默认 GitHub 仓库（检查更新回退值）。前端「更新设置」不再提供仓库配置 UI，
#: 未传/未配置仓库时检查此仓库；与 web 端 SettingsModal 的 UPDATE_REPO 常量保持一致。
DEFAULT_REPO = "Lusensec/Daybreak-Toolbox"

import sys as _sys


def _frozen_root() -> str:
    """PyInstaller 打包：可写状态目录 = exe 所在目录；开发态 = 项目根。"""
    if getattr(_sys, "frozen", False):
        return os.path.dirname(os.path.abspath(_sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_ROOT = _frozen_root()
_UPDATE_FILE = os.path.join(_ROOT, "config", "update.json")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")  # GitHub owner/repo 仅 ASCII；\w 会误放行中文


class UpdateError(Exception):
    """code: UPDATE_REPO_INVALID / UPDATE_CONFIG_CORRUPT / UPDATE_NO_REPO / UPDATE_FETCH_FAILED"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def set_root(root: str) -> None:
    """测试用：把 config/update.json 换到隔离目录。"""
    global _UPDATE_FILE
    _UPDATE_FILE = os.path.join(root, "config", "update.json")


# ---------------------------------------------------------------- 仓库配置

def get_repo() -> str:
    """已配置的 GitHub 仓库（owner/repo）；未配置返回空串。"""
    try:
        with open(_UPDATE_FILE, encoding="utf-8") as f:
            return str((json.load(f) or {}).get("repo") or "")
    except FileNotFoundError:
        return ""
    except (json.JSONDecodeError, OSError):
        raise UpdateError("UPDATE_CONFIG_CORRUPT", "更新配置损坏（config/update.json）")


def save_repo(repo: str) -> str:
    """保存 GitHub 仓库地址（owner/repo；空串 = 清空配置）。"""
    repo = (repo or "").strip()
    if repo and not _REPO_RE.match(repo):
        raise UpdateError("UPDATE_REPO_INVALID", "仓库地址须为 owner/repo 形式（如 myuser/daybreak-toolbox）")
    os.makedirs(os.path.dirname(_UPDATE_FILE), exist_ok=True)
    tmp = _UPDATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"repo": repo}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _UPDATE_FILE)
    return repo


# ---------------------------------------------------------------- 检查更新

def _http_get_json(url: str, timeout: int = 15) -> dict:
    """GET JSON（GitHub API）。抽出来便于测试 monkeypatch。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "daybreak-toolbox-update-check",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _parse_version(v) -> tuple | None:
    """'v1.2.1' / 1.3 → (1,2,1)；解析不出数字返回 None。"""
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(n) for n in nums) if nums else None


def check_update(repo: str) -> dict:
    """对比本地 APP_VERSION 与 GitHub latest Release（阻塞调用，main 里走 to_thread）。

    仓库回退链：入参 repo → 已存配置（config/update.json）→ 内置 DEFAULT_REPO。
    前端「更新设置」已无仓库配置 UI，通常发空入参走 DEFAULT_REPO。"""
    repo = (repo or "").strip() or get_repo().strip() or DEFAULT_REPO
    try:
        data = _http_get_json(f"https://api.github.com/repos/{repo}/releases/latest")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace").lower()
        except Exception:
            pass
        if e.code == 404:
            raise UpdateError("UPDATE_FETCH_FAILED", "仓库不存在 / 私有 / 尚无 Release（在 GitHub 仓库的 Releases 里发布一个后重试）")
        if e.code == 403 and "rate limit" in body:
            raise UpdateError("UPDATE_FETCH_FAILED", "GitHub API 限流（未认证 60 次/小时），稍后再试")
        raise UpdateError("UPDATE_FETCH_FAILED", f"GitHub API 请求失败（HTTP {e.code}）")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError("UPDATE_FETCH_FAILED", f"无法连接 GitHub：{e}")

    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    lv, gv = _parse_version(APP_VERSION), _parse_version(tag)
    if lv is not None and gv is not None:
        has_update = gv > lv
    else:  # 版本号不可解析：不做判断，UI 展示两侧版本由用户自行比较
        has_update = False
    return {
        "ok": True,
        "local_version": APP_VERSION,
        "repo": repo,
        "latest_version": tag,
        "release_name": data.get("name"),
        "release_url": data.get("html_url"),
        "published_at": data.get("published_at"),
        "has_update": has_update,
        "repo_url": f"https://github.com/{repo}",
    }

_VERSIONS = {
    "v2.0.3":
"""
1、新增窗口形态（Windows 打包默认）：双击 exe 直接弹出原生应用窗口（WebView2 渲染，与浏览器界面同款），关闭窗口即退出；托盘 / 悬浮球与窗口共存
2、--service 参数（或窗口引擎不可用时）回退旧形态：常驻服务 + 自动打开默认浏览器，行为同 v2.0.2
3、Windows 包内置 pywebview / pythonnet / WebView2 interop DLL；macOS / Linux 包窗口引擎缺失时自动降级浏览器形态
""",
    "v2.0.2":
"""
1、修复打包版启动后不自动打开浏览器：exe 启动约 1 秒后自动用默认浏览器打开界面地址（开发态不受影响；失败时日志打印手动地址）
2、修复原生悬浮球不可见：位置越界（旧配置 / 换屏 / 默认值越界）时自动钳制到主屏工作区右下角；仓库默认位置改为 (1860, 940)
3、Windows 包内置 pywin32（悬浮球渲染走 win32gui 快速路径）；win32gui 缺失提示只打一次，不再逐帧刷日志
""",
    "v2.0.1":
"""
1、工具箱设置左侧导航拆分：新增「通用设置」（默认打开，深色/浅色/跟随系统主题切换），菜单栏管理、导航栏管理、工具管理各自独立成页（新增行置顶 + 列表管理），工具画布移除「← 返回」
2、子窗口体验：双击标题栏 / ⛶ 按钮全屏（工具箱设置同），修复子窗口被设置弹窗遮挡的层级问题
3、悬浮球新增「页面」组：一键打开 6 个系统页子窗口（首页/AI 对话/终端管理/编解码/汉英翻译/临时笔记）；修复窗口缩小时球坐标越界
4、快捷键支持任意键（可不带 Ctrl，如 K / F5 / 空格或修饰键组合）；悬浮球显示/隐藏合并为单一 toggle 键
5、重命名美化：菜单栏/导航栏重命名改用全局模态对话框（Enter 确定 / Esc 取消），替换原生 prompt；菜单与导航右键新增「添加菜单栏」直达设置
6、终端管理：点击输出区不再抢占输入框焦点，复制结果更顺手
7、性能：页面级懒加载拆分主包（~305KB），移除未使用的 react-markdown 依赖
8、「更新设置」菜单项更名「更新检查」
""",
    "v2.0.0":
"""
1、架构重构：React + TypeScript + Vite 前端 + FastAPI/uvicorn WebSocket 桥（单进程 127.0.0.1:8765），替代旧版 tkinter 单体
2、新增原生悬浮球：圆形 logo 球 + 透明边缘、右键展开/收起菜单、拖拽移动自动保存位置、置顶/隐藏、托盘快捷唤起
3、AI 对话支持多模型管理（OpenAI 兼容 / 智谱 / Ollama / 自定义模型），改配置即时生效无需重启；本地 LLM 路由（Free LLM API）超时加固与错误诊断提示
4、新增 GitHub 更新检查：对比本地版本与仓库 latest Release；更新记录面板
5、新增跨平台打包：Windows 单文件可执行程序；macOS / Linux 由 GitHub Actions 构建并附到 Release
""",
    "v1.2.1":
"""
1、修复工具箱启动报错：菜单栏 highlightthickness 非法取值、按钮不支持原生下拉菜单、内置面板名称映射缺失
2、修复固定面板（AI对话/翻译/编解码/肉鸡/临时笔记）与工具画布布局冲突导致的界面变形
3、全面修复深色模式残留浅色：各面板输入框、按钮、标签、滚动条、命令行均随主题切换重套配色
4、修复浅色模式下肉鸡面板局部发黑问题（命令行区改为跟随面板配色）
5、修复各面板输入框失焦时背景闪回浅色的问题
""",
    "v1.2.0":
"""
1、完美解决【肉鸡面板】文件传输功能
2、增加【肉鸡面板】GO语言支持
""",
    "v1.1.9":
"""
1、增加工具属性展示功能
2、优化【肉鸡面板】文件传输功能
3、目录【肉鸡面板】在文件传输时rouji_json_xinxi请求会导致A端与S端通讯出错
""",
    "v1.1.8":
"""
1、全面修复【肉鸡面板】的bug
2、增加py导出和exe导出功能
""",
    "v1.1.7":
"""
1、完善【肉鸡面板】的文件上传功能
2、优化【肉鸡面板】界面和部分bug
""",
    "v1.1.6":
"""
1、完善【肉鸡面板】的命令行基本功能
2、优化【肉鸡面板】界面和部分bug
""",
    "v1.1.5":
"""
1、优化json格式化'单引号出错的问题
""",
    "v1.1.4":
"""
1、修改全局ctrl+A选择背景颜色
2、修正【临时笔记】ctrl+z回退两次bug
""",
    "v1.1.3":
"""
1、修改【更新记录】的展示位置
2、增加MD5编码功能
""",
    "v1.1.2":
"""
1、全面升级【临时笔记】面板
""",
    "v1.1.1":
"""
1、增加了【更新记录】面板
2、优化了【编解码】面板的按钮位置
""",
}


def get_update_record_content() -> dict:
    """返回 {版本号: 说明文本}（Web 更新记录标签页数据源）。"""
    return _VERSIONS
