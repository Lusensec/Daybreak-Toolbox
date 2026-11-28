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
APP_VERSION = "2.2.3"

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
    "v2.2.3":
"""
侧栏、窗口与双屏体验修正：
1、左侧菜单栏移除小型下拉箭头：整行菜单按钮即展开/收缩开关——点击展开其下导航栏并上架到顶栏，再次点击即收缩（不跳页）
2、最大化状态下按住顶栏空白区拖动：先还原到全屏前尺寸再跟随鼠标移动（光标横向位置保持不变），单击不会误还原
3、修复双屏最大化跑屏：目标显示器由 MonitorFromWindow 直接读取窗口当前所在屏工作区，副屏最大化留在副屏
4、app.env / window.get_rect 附带几何驱动的最大化状态，页面重载后顶栏图标与拖拽行为仍准确
5、README 补充工具管理「启动方式下拉」实景截图并同步交互说明
6、Windows 安装包排除运行时生成的 WebView2 缓存 data\\ 与 daybreak.log，避免把验证机状态打进发行包
""",
    "v2.2.2":
"""
顶栏与侧栏交互优化：
1、顶栏菜单栏按钮悬停时在右侧浮现「×」，点击即把该菜单栏移回左侧导航栏（等价于右键「移到左侧栏」，不必再右键）
2、左侧菜单导航栏与右侧内容区的滚动条滑块全部隐藏 —— 滚轮 / 触控板滚动照常，不再有多余的竖条占位
3、顶栏展开后的导航栏行下沉到内容区顶部（左侧导航栏右侧），不再横跨整窗压住侧栏上方；同时压缩高度（40px → 32px），按钮间距同步收紧
""",
    "v2.2.1":
"""
窗口交互与清理优化：
1、顶栏中部空白区（菜单按钮右侧 → 窗口控件之间）新增拖动垫片，按住即可拖动窗口；菜单按钮之间的缝隙仍不可拖，避免误拖
2、左侧菜单导航栏右边缘可左右拖动拉伸宽度（180~480px，宽度持久化保存）
3、窗口恢复 Windows 原生式缩放：左/右/下三条边 + 四个角均可拖动拉伸，保留最小尺寸 960×600（不再拉成固定大小）
4、取消右上角「工具箱设置」按钮 —— 左下角侧栏「管理菜单」已是同一入口，顶栏只留原生窗口控件
5、清理旧版本打包产物与构建缓存，释放约 1.2GB 磁盘占用
""",
    "v2.2.0":
"""
界面结构改版：左侧导航栏 + 顶栏按需上架（顶栏回归清爽）：
1、新增左侧导航栏：全部自定义菜单栏常驻左侧（文件夹式），点箭头可展开/收缩该菜单下的导航栏列表；整栏可一键收起为图标条（状态本地保存，刷新保持）
2、顶栏默认只保留「首页」——用户菜单默认不再挤在顶栏，需要时从左侧点一下"上架"
3、点左侧的菜单栏或任一导航栏 → 该菜单自动回归到顶栏并展开其导航行，同时打开对应工具画布；顶栏按钮上加图钉标记表示已上架，右键可「移到左侧栏」收回
4、工具管理里添加工具成功后自动收起设置弹框、刷新左侧/顶栏导航，并直接跳到该「菜单 / 导航」的工具画布（不用再手动点一遍）
5、左侧栏底部「管理菜单」直达工具箱设置的菜单栏管理页
""",
    "v2.1.4":
"""
拖拽根因修复 + 桥接服务架构瘦身（去掉整套 Web 框架，安装包再小一圈）：
1、修复「在界面任意位置按住鼠标滑动就把整个窗口带走」的真正根因：无边框窗口下 pywebview 默认开启 easy_drag，会向页面注入一段全局 mousedown 拖窗脚本——任何位置按下都是拖窗口，且它的 mousemove 监听在 mouseup 丢失时会残留。现已关闭（easy_drag=False），窗口只由顶栏拖动；顺带恢复内容区文本可选中（此前 pywebview 默关注入全局 user-select:none，输入框外一律无法框选）
2、桥接服务从 FastAPI + uvicorn + WebSocket 换成标准库实现（ThreadingHTTPServer + SSE）：命令走 POST /api/rpc，事件（菜单/设置/快捷键变更）走 GET /api/events，协议信封不变，前端调用点零改动
3、随之移除 fastapi / starlette / uvicorn / websockets 及其传递依赖（pydantic、pydantic-core、anyio、sniffio、watchfiles、httptools、h11、click、uvloop）——服务端第三方依赖归零，冷启动少一段 uvicorn 初始化
4、端口、token 鉴权、静态托管 + SPA 兜底行为保持不变；新增 /api/ping 轻量健康检查供托盘与冒烟脚本使用
""",
    "v2.1.3":
"""
功能瘦身：移除系统固定菜单栏及其全部内置面板，工具箱回归「可配置菜单 + 一键启动本机工具」：
1、删除五个固定功能面板：AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记（页面、路由、子窗口内容、首页与托盘入口一并移除），顶栏固定菜单只剩「首页」
2、工具箱设置同步精简：移除 AI模型设置 / 翻译设置 / 终端设置 三个页签
3、后端删除 ai_service / ai_config / translate_service / codec_service / shell_service / ssh_service 及 fanyi.py / encryption.py，WebSocket 命令 66 → 39 条
4、依赖收敛：移除 openai / requests / beautifulsoup4 / zhipuai / paramiko，安装包进一步变小
5、快捷键槽位去掉「固定菜单栏」分组（回到面板 / 动态菜单 / 导航 / 工具 不受影响）
""",
    "v2.1.2":
"""
顶栏拖拽修复 + 安装包瘦身（体积 67.6MB → 54.6MB，约 −19%）：
1、修复「在主内容区（如临时笔记）滑动鼠标就把整个窗口带走」：顶栏拖拽的全局监听器此前只在 mouseup 里拆除，一旦 mouseup 丢失（窗口外松手 / pointercancel / 失焦 / 切后台）就会永久残留，之后在笔记区任何滑动都被算作「继续拖窗口」。现在拆除逻辑幂等化，并补 pointercancel / blur / visibilitychange 兜底，且移动时检测到左键已松开立即拆除
2、顶栏拖拽热区收窄：菜单按钮行与右侧控件行整块不再参与窗口拖动（此前按钮之间的 flex 间隙也放行，想点菜单常点进缝里变成拖窗口），仅品牌区与真空白可拖
3、安装包瘦身：移除 dashscope / chardet / pycryptodome 三个零引用依赖，排除 Pillow 用不到的 AVIF、FreeType、WebP 编解码插件（12.8MB → 2.8MB），logo 由 1024px 压到 128px（2.0MB → 55KB）
4、修复 SSH 终端在官方安装包中不可用：paramiko 此前从未进入依赖清单，打包后静默降级为「未安装」；已补入并验证打包完整
""",
    "v2.1.1":
"""
启动性能优化（双击到界面可用 5.0s → 约 3.0s，同机实测）：
1、打包方式 onefile → onedir：去掉每次启动把 394 个文件 / 63MB 解压到 %TEMP% 的开销（实测独占 3.0s，且每个文件都要过杀软实时扫描）；顺带不再残留 _MEI 临时目录、进程数减半（无 bootloader 父进程）
2、WebView2 改用持久化 profile（data/webview2-<版本>）：不再每次启动重建临时缓存目录（减少数百个缓存文件写入与扫描）；目录带版本后缀，升级自动换新，避免旧 index.html 缓存导致界面不更新。注：对启动耗时本身贡献很小（~0.03s，噪声级），剩余 1.2s 主要是 WebView2 环境/浏览器进程创建，非缓存可比
3、新增单实例守卫（命名互斥量）：重复双击不再起第二个完整实例（约 1.4s 内退出），而是唤回已有窗口并置前
4、安装包与 zip 分发包随产物改为目录结构：安装包递归安装 _internal/，zip 解压得到单一文件夹（README 在内）
""",
    "v2.1.0":
"""
窗口形态定版（合并 2.0.19 + 2.0.20 全部成果）：
1、窗口尺寸固定为主屏工作区的 80% 并居中，取消边缘/角落拖拽拉伸（resizable=False + 尺寸钳制双保险），仅保留 最大化/还原 与关闭；顶栏拖动移动、双击最大化保留
2、修复点击左上角品牌区黑屏/白屏（2.0.19 回归）：WM_SETREDRAW 挂起只作用于顶层窗体、单击（位移 < 3px）不发任何窗口命令、禁止 logo 图片原生拖拽（其会吞掉 mouseup 导致重绘永不恢复）
3、顶栏信息精简：移除底部「就绪 · 破晓·工具箱 / 已连接」整行，连接状态移到顶栏版本号右侧（在线/重连中/连接中/未连接 + 图标），主内容区多出 28px
4、版本号改为椭圆胶囊样式（强调色浅底 + 同色系文字）
5、Windows 边框拖拽闪烁根治：拖拽期间挂起重绘、收尾一次性刷新 + 3s 看门狗；打包版 SetWindowSubclass 失败自动走 SetWindowLongPtrW 兜底（关闭后最小化 / 背景色同步 / MinimumSize 归一化在 exe 真正生效）；钩子全失败时 SetClassLongPtrW 类画刷兜底露底色；前端几何按实测 RTT 自适应节流
""",
    "v2.0.20":
"""
窗口形态与顶栏信息精简：
1、窗口尺寸固定为主屏工作区的 80% 并居中，取消边缘/角落拖拽拉伸（后端 resizable=False + 尺寸钳制双保险），仅保留 最大化/还原 与关闭
2、修复点击左上角品牌区黑屏/白屏：v2.0.19 的 WM_SETREDRAW 挂起会冻死 WebView2 合成，现改为只挂起顶层窗体、单击（位移<3px）不发任何窗口命令，并禁止 logo 图片原生拖拽（其会吞掉 mouseup）
3、移除底部状态栏（「就绪 · 破晓·工具箱」/ 已连接），连接状态移到顶栏品牌区版本号右侧（在线/重连中/连接中/未连接 + 图标）
4、版本号改为椭圆胶囊样式（单一强调色浅底 + 同色系文字），品牌区两行结构：标题 / 版本号 + 连接状态
""",
    "v2.0.19":
"""
Windows 边框拖拽拉伸闪烁根治：
1、拖拽/拉伸开始时挂起窗口及 WebView2 子窗口重绘（WM_SETREDRAW），结束时补发最终几何再一次性整体刷新，消除「外框已变、内容未合成」的露底闪烁；附带 3s 看门狗，页面崩溃/WS 断线也不会让窗口永久冻结
2、frozen（打包 exe）下 Win32 消息钩子失败修复：SetWindowSubclass 静默失败时自动改走 SetWindowLongPtrW(GWLP_WNDPROC) 兜底，关闭后最小化 / 背景色同步 / MinimumSize 归一化在打包版真正生效
3、背景色兜底不依赖钩子：钩子两条路径都失败时改 SetClassLongPtrW(GCLP_HBRBACKGROUND) 设置窗口类画刷，露底条仍与主题同色（不再白闪）
4、前端拖拽按实测 RTT 自适应节流（RTT>16ms 降频给 WebView2 留合成时间），onMove/onUp 共用同一几何公式，收尾补发最终位置保证窗口精确停在光标处
""",
    "v2.0.18":
"""
窗口体验三项优化：
1、顶栏左上/右上角新增 14×14 斜向拉伸区（紧贴顶栏正下方；hover 斜纹提示，与下缘角落同构；仅窗口形态渲染角落手柄）
2、拖拽拉伸闪烁根因修复：显示器信息 30s 缓存（免每帧枚举）、几何不变帧 no-op 免 Win32 重入、MinimumSize 按窗口显示器缩放等比归一（消除 >100% 缩放回跳）、流式 SetWindowPos 去 SWP_SHOWWINDOW
3、顶栏品牌区展示版本号（单一来源 update_service.APP_VERSION 经 app.env 下发；不可用/旧桥接不渲染）
""",
    "v2.0.17":
"""
Windows 安装/卸载界面中文化 + 修复下边框拉伸闪烁晃动：
1、安装程序（win-setup.exe）向导与卸载对话框改为简体中文（Inno 官方中文语言文件入库，单一语言无选择页）
2、修复下边框上压缩时的窗口闪烁晃动：
  - 流式几何应用（顶栏拖拽/边缘拉伸）不再每帧 ShowWindow（消除 60fps 重绘闪动）
  - 窗体背景色随主题同步（拉伸时 WebView2 渲染间隙露出的条带与页面同色，白闪不可见）
  - 拖拽/拉伸流「至多一笔在途」背压（慢 RTT 下平滑合并而非成批追帧）
  - 已知限制：Alt+F4/任务栏X 的「关闭后进入最小化」拦截本版本未生效（frozen 环境 Win32 子类待攻关），
    此两条路径保持旧语义（关窗=退出）；顶栏 X 按钮的关闭后最小化正常
""",
    "v2.0.16":
"""
修复拖动主窗口延迟与左右晃动：
1、顶栏拖拽 / 边缘拉伸的窗口几何应用不再串行等待 120ms 落定（旧版每笔 move/resize 等 120ms → 拖动被限速到 ~8Hz 明显滞后；滞后引发的补偿振荡即「左右晃动」；同时拖拽流堵满命令队列导致其他命令如 tool.grid 排队超时（界面「加载失败: cmd tool.grid timeout」））
2、直接 Win32 SetWindowPos 为同步调用，连发安全无吞包，拖拽恢复 60fps 跟手；120ms 落定仅保留给 最大化/还原 等一次性状态变更
""",
    "v2.0.15":
"""
新增「关闭后进入最小化」通用设置：
1、工具箱设置 → 通用设置 → 窗口：新增「关闭后进入最小化」开关（config/settings.json 持久化，切换即时生效无需重启）
2、开启后：顶栏关闭（×）/ Alt+F4 → 窗口最小化并驻留托盘（进程不退出），可经托盘菜单「打开…」唤回；托盘「退出破晓工具箱」始终为真正退出
3、托盘「打开…」菜单项优先唤回已有窗口（最小化驻留态），无窗口时回退浏览器打开（旧行为）
4、X 按钮提示随设置动态显示（关闭=退出 / 最小化到托盘）
""",
    "v2.0.14":
"""
性能与多屏优化：
1、混合 DPI 多屏修复：窗口移动/最大化/边缘拉伸改 per-monitor scale 精确坐标模型（主屏基准虚拟桌面），不同缩放比例的双屏之间拖窗口不再漂移（v2.0.10 已知限制的根治）；move/resize 一并改原子 SetWindowPos
2、托盘启动全后台化：pystray/Pillow 导入与图标渲染不再占主线程，窗口启动提速 0.2–0.5s
3、启动计时：各阶段耗时（bootstrap/uvicorn/窗口）打 [perf] 行进日志，为后续启动优化建立数据基线
4、CI 增加测试门禁：全量 pytest + 前端构建先行，5 个平台构建 job 依赖其通过
""",
    "v2.0.13":
"""
全面清理：移除已退役的旧版功能痕迹
1、删除过时的《React_TS_UI 重构方案》设计文档（描述的旧 tkinter 架构与 C2 协议已随 v2.0.0 架构重构退役）
2、更新记录面板移除 v1.x 旧版条目（ tkinter 单体时期的发布记录），现仅保留 v2.0.x 及以后
3、.gitignore 清除旧运行时产物规则残留
（功能本身早已在 v2.0.0 架构重构中移除，本版清理的是文档/记录残留）
""",
    "v2.0.12":
"""
轻量优化与稳健性修复（行为不变）：
1、临时笔记行号槽改增量更新（旧版每次击键全量重建全部行号 DOM，长笔记卡顿）—— 行数/主题/字号变化才重建，光标移动仅 O(1) 交换高亮
2、下载链接改 1MB 分块流式写盘（旧版整文件读入内存再写，几百 MB 工具顶等量内存峰值）；失败自动清理残留部分文件
3、AI 会话键上限 50（LRU 淘汰）—— 托盘常驻数天内存有界
4、桥接 10s 未就绪时窗口模式不再开空白窗口（降级浏览器 + 明确日志）；服务模式补告警
""",
    "v2.0.11":
"""
轻量优化（内存/CPU/磁盘卫生，行为不变）：
1、daybreak.log 改滚动日志（单文件 ≤5MB、留 2 份备份，磁盘占用封顶 ~15MB）——托盘常驻跑数天不再无限增长；stdout/stderr 统一经 logging 落轮转文件
2、WS 总线每连接待处理命令设上限（512，超出拒收回 WS_QUEUE_FULL）——异常客户端/慢命令堆积时内存有界
3、WS 帧上限校验快路径（普通小帧免 utf-8 编码分配，降 CPU 微开销）
""",
    "v2.0.10":
"""
1、最大化/还原改为几何驱动（幂等自愈）：不再依赖状态标志——页面重载、任务栏最小化往返、最大化中手动改大小后，按钮依旧可靠（v2.0.9 起第二次点击失效的根因）
2、最小化按钮图标修正为「—」（原斜箭图标易误认为放大）；最大化=⤢、还原=叠方
3、窗口边缘全向拉伸：左/右/下边缘任意位置 + 左下/右下角均可拖动调整大小（原仅右下角）；最大化中拖边缘自动还原后拉伸；最小 960×600 双保险钳制
""",
    "v2.0.9":
"""
1、Windows 安装程序（Inno Setup）：Release 新增 win-setup.exe 资产，安装时可自选路径（默认 %LOCALAPPDATA%\\DaybreakToolbox 免管理员），含 开始菜单/桌面快捷方式、卸载项、装后可选立即运行；原 zip 绿色版保留
2、顶栏右侧新增 最小化 按钮（-），窗口控件序 最小化/最大化·还原/关闭
3、修复 v2.0.8 最大化卡死 bug：第二/三次点击最大化无效果（显示器枚举回调参数错位致工作区计算恒失败 + 原生/手动状态失步）；现最大化走原生状态转换 + 工作区钳制、还原走原生 restore，多次切换稳定
4、移除顶栏主题切换按钮：主题统一在「工具箱设置 → 通用设置 → 外观」配置，顶栏 Logo 自动跟随深浅色
""",
    "v2.0.8":
"""
1、无边框窗口形态：移除 exe 原生标题栏（全平台窗口形态统一），窗口观感回归 web 自定义顶栏
2、顶栏右侧（主题切换右边）新增 最大化/还原 + 关闭 X 按钮：X 关闭整个应用（与托盘「退出破晓工具箱」同义）
3、顶栏品牌区/栏间隙 按住拖动可移动窗口、双击最大化（模拟原生标题栏行为）；右下角小三角可拉伸缩放窗口（最小 960×600）
4、新增 WS 命令：app.env（窗口形态探测）/ app.quit（退出进程）/ window.get_rect / window.move / window.resize / window.maximize（Windows 手动工作区版最大化，避开无边框盖任务栏）
5、浏览器 / 服务形态顶栏保持原样（不渲染窗口控件）
""",
    "v2.0.7":
"""
1、移除悬浮球功能：原生 Win32 置顶球、ball.get_state / ball.set_topmost / ball.set_hidden 命令与 ball.state 事件、设置页「悬浮球」开关（置顶/隐藏）、全局快捷键 ball:show（显隐切换）、托盘「显示悬浮球」项、config/ball_pos.json 位置持久化全部移除
2、快捷键旧数据自动迁移：旧版本 config/shortcuts.json 中的 ball:show / ball:hide 条目在读取时静默丢弃，无需手工清理
3、设置「其他设置」标签页（仅含悬浮球）一并移除；界面与托盘回归纯工具箱形态
""",
    "v2.0.6":
"""
1、悬浮球统一为「全局球」：屏幕上的悬浮球只保留 bridge 进程运行的原生置顶球一颗（可拖动到屏幕任意位置、位置记忆、跟随系统深浅色主题、左键聚焦主应用窗口）
2、球外观换回用户选定的「完整 Logo 徽标」（深色系统用藏青徽标、浅色系统用米白徽标；v2.0.5 的简化球图标降为兜底）
3、移除页内 web 悬浮球及其快捷面板（页面/工具快启/子窗口）：应用窗口内不再有第二颗球，避免双球混淆
4、左键聚焦增强：球窗口加 WS_EX_NOACTIVATE 不再抢占焦点，点球即把主窗口拉到前台（前台锁下多次重试 + 最小化/还原破锁），焦点不会停在球上
5、设置页「悬浮球」开关与全局快捷键 ball:show 语义收敛为控制这一颗全局球
""",
    "v2.0.5":
"""
1、悬浮球改造：全新简化球图标（藏青 / 米白双主题，大号交叉工具、无小齿轮）；球体自动跟随 Windows 系统深浅色主题切换
2、悬浮球左键：窗口形态下改为聚焦 / 还原主应用窗口（服务形态仍开浏览器），不再多开浏览器界面
3、修复悬浮球右键菜单闪烁 / 状态错乱：多条触发路径统一收敛为单一 400ms 去抖 toggle
4、修复悬浮球拖拽卡顿：改为直接移动 + 表面重提交（不再逐次重建窗口），抓取区扩大（点球边缘也能抓起）
5、修复悬浮球拖到右下角越屏 + 重启后位置弹回默认位：拖拽钳制按窗口全宽修正，启动越界钳制改为保留用户位置，拖拽中周期落盘
6、说明：v2.0.4 起 exe 已内置「破晓」图标（已验证嵌入）；若资源管理器中仍显示旧的默认图标，为 Windows 图标缓存所致——换一个新文件夹解压（或清理图标缓存 / 重启资源管理器）即可显示新图标
""",
    "v2.0.4":
"""
1、Windows 图标修复：exe 文件图标 / 窗口标题栏 / 任务栏 / 资源管理器均换成「破晓」系统 Logo（此前为 Python 打包默认图像）
2、浅色模式 Logo 统一：顶栏左上角 Logo 与浏览器标签 favicon 在浅色主题下改用浅色 Logo（深色主题沿用深色 Logo，与悬浮球一致）
3、修复打包版悬浮球 / 托盘在 zip 目录运行时显示手绘兜底图标的问题：改为读取内置真 Logo
""",
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
}


def get_update_record_content() -> dict:
    """返回 {版本号: 说明文本}（Web 更新记录标签页数据源）。"""
    return _VERSIONS
