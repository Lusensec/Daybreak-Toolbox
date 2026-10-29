# 破晓·工具箱 UI 重构方案 —— React + TypeScript

> 状态：**方案阶段（不修改现有代码）**。本文档给出可直接照做的逐步骤实施计划。
> 原则：**C 端（fun.py）、C2 协议（c2_common.py）、服务端（server.py）一律不动**；
> 重构边界 = 仅 A 端 GUI（app.py 的 tkinter 层）与其中可下沉的业务编排。

---

## 0. 文档使用方式

- 每个阶段（Phase）→ 若干步骤（Step），每步给出：**操作 / 涉及文件 / 命令 / 预期结果 / 验收标准**。
- 步骤带勾选框（`- [ ]`），完成一个勾一个；每个 Phase 末尾有"出口检查"，全部通过才进入下一 Phase。
- 估算为单人开发工时（人日），可按团队规模压缩。

---

## 1. 目标与不变约束

| 项 | 内容 |
|---|---|
| 目标 | 将 A 端 tkinter GUI 重构为 **React 18 + TypeScript 5 + Vite** 的 Web UI，Python 侧提供 **WebSocket 桥接服务**，Windows 单包分发 |
| 不变 1 | C2 帧协议：44 字节 AES 加密长度前缀 + payload（`c2_common.py`），**零改动** |
| 不变 2 | C 端植入模板 `fun.py`（Py/Go）零改动；除非 Phase 7 明确选择"进度增强"才需 C 端重新发放 |
| 不变 3 | `server.py` 肉鸡中继服务零改动 |
| 不变 4 | 配置体系沿用 `config/*.json`（菜单/导航/工具/AI/窗口尺寸），Web 端通过桥接 CRUD，不新造数据库 |
| 不变 5 | 安全基线：桥接仅监听 `127.0.0.1` + 随机 token；百度密钥仅存本地 gitignored `config/baidu.py` |

**成功指标（出口）**
1. 功能覆盖：现有 tkinter 端全部功能（C2 连接/命令/刷新/下载、AI 单/双聊、翻译、木马生成、菜单管理、编解码、更新记录、窗口大小、主题切换）100% 可用；
2. C2 回归：`recv_exactly` 帧回环、拆包、对端关闭 3 类用例全过；
3. 性能：面板切换 < 100ms；C2 日志 500 行/秒不卡顿（xterm 默认能扛）；
4. 分发：PyInstaller 单目录包，干净 Windows 10/11 双击即开，无需装 Node/浏览器（WebView2 运行时随系统已存在）。

---

## 2. 现状盘点（重构基线）

### 2.1 模块清单与处置

| 文件 | 职责 | 现状 | 重构处置 |
|---|---|---|---|
| `app.py`（≈2500 行） | A 端 tkinter UI + 业务编排 | 菜单/面板/C2/AI/翻译/生成/配置 全在一个大函数里 | **拆分**：UI 全部移入 React；业务编排下沉为 Python services（`c2_client` / `menu_service` / `ai_service` / `translate_service` / `implant_service`），经桥接暴露 |
| `server.py` | C2 肉鸡中继 | 已稳定 | **不动** |
| `fun.py`（≈1660 行） | C 端植入模板（Py + Go，f-string 双份） | 含本地密钥字面（刻意保留） | **不动**（Phase 7 可选增强除外） |
| `c2_common.py` | `C2_AES_KEY` / `C2_FRAME_HEADER_LEN=44` | 稳定 | **不动**，桥接直接 import |
| `encryption.py` | AES-CBC 加解密 | 稳定 | **不动**，桥接 import |
| `Chat_AI.py` | 多模型 AI 对话（openai/dashscope/zhipu…） | 稳定 | 包一层 `ai_service`（支持流式 token 事件） |
| `fanyi.py` | 百度翻译（blocking requests） | 已线程化 | 包一层 `translate_service` |
| `ui_theme.py` | COLORS/DARK 调色板、字体、ttk 样式、控制台 tag、tooltip、进度条样式 | 稳定 | **转译为前端设计令牌（CSS 变量）**，映射表见附录 A；Python 侧保留给过渡期 |
| `config/*.json` | 菜单/导航/工具/AI/窗口/账号 | 单例缓存 `config_json` | 保留格式；桥接 `menu_service` 提供 CRUD |
| `requirements.txt` | openai/requests/chardet/pycryptodome/bs4/dashscope/zhipuai | — | 新增 `fastapi` `uvicorn[standard]` `webview` |

### 2.2 C2 协议事实（桥接必须原样遵守）

1. **帧结构**：`44B AES 加密长度前缀 + payload`；`recv_exactly` 循环累积、对端关闭抛 `ConnectionError`。
2. **共享 socket 串行化**：`rouji_json_xinxi` 刷新帧与 `#>` 命令帧共用同一 socket → 现有 `CLIENT_SOCKET_LOCK` 语义在桥接内**必须保留**（桥接用一把 asyncio 锁或单 worker 队列实现，杜绝并发 send/recv 交错）。
3. **命令帧**：`{rouji_ID} #> {command}`；`get <path>` 走下载流程。
4. **下载流**（C 端 `send_file_nonblocking`）：C 端先**明文**发 `file_size` → 等对端 `READY` → 裸流 8KB 分块 → 结果帧（`[success]`/`[fail]`/`[finish]` 标记）。*注意：裸流与加密帧共用一条 socket，是既有协议现状，重构期保持原样；总字节数 `file_size` 桥接侧可得 → 可做"确定性进度条"（Phase 7 增强项，需与现有接收实现逐项对齐验证）。*
5. **肉鸡信息刷新**：`rouji_json_xinxi` 周期刷新（5s），结果进 `rouji_xinxi`。

---

## 3. 架构选型（决策与理由）

| 方案 | 说明 | 结论 |
|---|---|---|
| **A. Python 内嵌 WebView + WebSocket 桥（pywebview）** | 单进程：uvicorn 线程起 WS/REST（127.0.0.1）；`pywebview.create_window(url=本地文件/localhost)` 加载构建产物 `dist/` | ✅ **采用** |
| B. Electron | 完整 Chromium + Node，包体 100MB+、双运行时 | ❌ 过重；C 端场景要的是"一个 exe 丢过去就能跑" |
| C. Tauri | Rust 壳 + WebView，包体小 | ❌ 需引入 Rust 工具链；且仍需 Python 侧跑 C2，等于双壳双语言，分发更复杂 |
| D. CustomTkinter（不换 React） | 只换观感 | ❌ 达不到目标；但作为过渡观感层已部分实现（ui_theme） |

**采用 A 的核心理由**
1. 目标用户机器是 Windows，`WebView2` 运行时 Win10/11 自带；`pywebview` 打包后无需 Node。
2. C2 加密/裸流/多主机并发留在 **Python 侧单点持有**（浏览器只做"文本事件渲染"），协议零改动、审计面不变。
3. 开发体验：Vite HMR 秒级；浏览器 DevTools 直接调试 React；xterm.js 终端观感。
4. 可回退：过渡期 tkinter 端（app.py）可并行保留，feature flag 切换，失败随时回滚。

**进程模型（目标态）**

```
┌──────────────────────── 单 exe（PyInstaller）────────────────────────┐
│  Python 主进程                                                       │
│  ├─ uvicorn (thread) 127.0.0.1:8765                                 │
│  │    ├─ /ws   WebSocket 事件总线（token 鉴权）                      │
│  │    └─ /api  REST（配置 CRUD，token 鉴权）                         │
│  ├─ c2_client      连接 server.py；帧收发；C2 命令/刷新/下载          │
│  ├─ ai_service     包 Chat_AI.py（流式 token 事件）                 │
│  ├─ translate_svc  包 fanyi.py（worker 线程）                        │
│  ├─ implant_svc    fun.py 模板渲染（py/pyexe/go/goexe）              │
│  ├─ menu_svc       config/*.json CRUD（菜单/导航/工具/AI/窗口）      │
│  └─ webview 窗口 ← dist/（React SPA 静态资源，本地加载）             │
└──────────────────────────────────────────────────────────────────────┘
```

**重构边界（一句话）**：浏览器**只收文本事件、只发 JSON 命令**；一切 socket/加密/二进制流在 Python 内完成。

---

## 4. 桥接协议设计（WS + REST）

### 4.1 传输与鉴权

| 项 | 规格 |
|---|---|
| 端口 | `8765`；被占用则 +1 重试，最多 5 次（`8765..8770`） |
| 监听 | 仅 `127.0.0.1` |
| 鉴权 | 启动时生成 32 字节 hex `token`，写 `config/bridge_token.json`（**加入 .gitignore**）；WS 以 `?token=` 查询参数传递，REST 以 `Authorization: Bearer` 头 |
| 帧上限 | WS 单消息 ≤ 512KB（C2 日志行已截断，足够） |
| 心跳 | 客户端每 15s 发 `ping`；服务端 30s 无消息断开；客户端断线自动重连（指数退避 1/2/4/8/16/30s 封顶） |
| 通用信封 | `{"v":1,"id":"<uuid>","type":"<event|ack|err>","payload":{...}}`；请求带 `id`，响应 `ack/err` 原样回 `id`；服务端**事件**无 `id` |
| 错误码 | `C2_NOT_CONNECTED` / `TRANSFER_BUSY` / `MENU_NAME_EXISTS` / `AI_NOT_CONFIGURED` / `TOKEN_INVALID` / `WS_FRAME_TOO_LARGE` / `INTERNAL` |

### 4.2 事件目录（server → client，逐项定义）

| # | 事件 | payload 字段 | 触发时机 | 示例 |
|---|---|---|---|---|
| E1 | `c2.connected` | `server_ip, port` | 与 server.py 建连成功 | `{"server_ip":"1.2.3.4","port":443}` |
| E2 | `c2.disconnected` | `reason` | 断连/异常 | `{"reason":"服务端连接已关闭"}` |
| E3 | `c2.hosts` | `hosts:[{id,name,ip,version,online}]` | `rouji_json_xinxi` 每次刷新成功 | 数组全量快照（幂等覆盖） |
| E4 | `c2.log` | `host, level∈{info,cmd,success,warn,error,title}, line` | 每条 C2 输出（对应现 `command_line` 的 tag 体系） | `{"host":"PC-07","level":"cmd","line":"ls /tmp"}` |
| E5 | `c2.transfer.start` | `host, file` | `get` 下载开始 | `{"host":"PC-07","file":"/tmp/a.bin"}` |
| E6 | `c2.transfer.progress` | `host, file, done, total, state∈{running,done,error,interrupted}` | 每收到一个分块帧更新 | `{"host":"PC-07","file":"/tmp/a.bin","done":262144,"total":0,"state":"running"}`（`total=0` 表不确定；Phase 7 增强后填真实值） |
| E7 | `c2.transfer.end` | `host, file, ok` | `[finish]`/异常/失败帧 | `{"host":"PC-07","file":"/tmp/a.bin","ok":true}` |
| E8 | `menu.changed` | `config`（完整 config.json 快照） | 任何菜单/导航/工具/AI 设置 CRUD 成功后 | 前端据此重建路由 |
| E9 | `ai.token` | `session, msg_id, delta, done` | AI 流式响应逐段 | `{"session":"s1","msg_id":"m12","delta":"Hello","done":false}` |
| E10 | `ai.error` | `session, msg_id, message` | AI 请求失败 | — |
| E11 | `translate.result` | `req_id, text, from_lang, to_lang` | 翻译完成 | — |
| E12 | `translate.error` | `req_id, message` | 凭证缺失/网络错误 | `"翻译出错：百度凭证未配置"` |
| E13 | `implant.generated` | `lang∈{py,pyexe,go,goexe}, path, ok` | 生成成功/失败 | — |
| E14 | `status.set` | `text, level∈{muted,success,warn,error}` | 对应现 `set_status()` | `{"text":"正在接收文件…","level":"muted"}` |
| E15 | `theme.sync` | `dark` | 主题状态同步（重启后恢复） | `{"dark":true}` |

### 4.3 命令目录（client → server，逐项定义）

| # | 命令 | payload | 语义（对应现有函数） | 响应 |
|---|---|---|---|---|
| C1 | `c2.connect` | `{server_ip, port}` | `muma_listen_setting` 建连 + 首次刷新 | `ack` → E1 |
| C2 | `c2.disconnect` | `{}` | 断开并清理 socket | `ack` → E2 |
| C3 | `c2.command` | `{host, cmd}` | `_run_c2_command`（`cd/ls/系统命令`），经 C2 锁串行 | `ack`/`err(TRANSFER_BUSY)` |
| C4 | `c2.download` | `{host, path}` | `download_file`（`get` 流程 + 忙守卫） | `ack` → E5/E6/E7 |
| C5 | `ai.send` | `{session, provider, text, stream:true}` | `ai_request_thread`（单/双 AI 各自一个 session） | `ack` → E9* |
| C6 | `translate.run` | `{req_id, text, from_lang, to_lang}` | `on_translate_click`（worker 线程） | `ack` → E11/E12 |
| C7 | `menu.add` | `{kind∈{menu,nav,tool}, name, ...}` | `add_menus`/`add_navigation_bar`/`add_Tools` | `ack` → E8 |
| C8 | `menu.remove` | `{kind, name}` | 对应删除逻辑 | `ack` → E8 |
| C9 | `ai.settings` | `{...ai_ask.json 字段}` | `add_ai_setting` 保存 | `ack` → E8 |
| C10 | `implant.generate` | `{lang∈{py,pyexe,go,goexe}}` | `add_py_muma/add_py_exe_muma/add_go_muma/add_go_exe_muma` | `ack` → E13 |
| C11 | `theme.set` | `{dark}` | `_toggle_dark` 语义（持久化 + 回发 E15） | `ack` |
| C12 | `window.resize` | `{width, height}` | `windowSize_Setting`（写 windowSize.json） | `ack` |
| C13 | `status.set` | `{text, level}` | 主动置状态栏（可选） | `ack` |
| C14 | `ping` | `{}` | 心跳 | `ack` |

> 所有 C3–C10 在 Python 侧均为**显式具名方法**，不提供任何"通用命令执行"入口（安全约束 5）。

### 4.4 重连恢复协议

客户端（重连后）→ 依次发：`menu.get`（REST `GET /api/menu`）→ `c2.hosts.get`（REST 取当前快照）→ `theme.get`；服务端全量回快照，前端状态清零重建。

---

## 5. 组件映射表（tkinter → React）

| 现有（app.py 位置/函数） | React 组件 | 前端文件 | 数据来源 | 备注 |
|---|---|---|---|---|
| C2 命令行 `command_line`（Text + info/success/warn/error/cmd/title tag，≈L2339） | `C2Console` | `src/features/c2/C2Console.tsx` | E4 | **xterm.js**；tag → CSS 类；提示符 `PC-07 #>` 样式保留 |
| 肉鸡信息/列表（`rouji_xinxi` + Treeview） | `HostTree` | `src/features/c2/HostTree.tsx` | E3 | 右键菜单（删除→二次确认，保留 `askokcancel` 语义，改 ConfirmDialog） |
| IP/Port 输入 + 连接按钮（L2382–2394） | `C2ConnectBar` | `src/features/c2/C2ConnectBar.tsx` | C1/C2 | 记忆上次连接值（localStorage + windowSize 同构） |
| 传输进度条（`transfer_progress`，P5 新增） | `TransferProgress` | `src/features/c2/TransferProgress.tsx` | E5/E6/E7 | 现 indeterminate；Phase 7 后可 determinate |
| 单 AI 聊天（`chat_box`，≈L1568） | `AiChat` | `src/features/ai/AiChat.tsx` | C5/E9 | markdown 渲染（react-markdown）+ 流式；发送按钮/Shift+Enter 保留 |
| 双 AI 对比（`left/right_chat_box`，≈L1726/1729） | `AiCompare` | `src/features/ai/AiCompare.tsx` | C5×2/E9 | 左右分栏、同名问题双发 |
| 翻译（`input/output_textbox`，≈L1855/1863） | `TranslatePanel` | `src/features/translate/TranslatePanel.tsx` | C6/E11/E12 | 中↔英方向切换保留 |
| 木马生成 4 按钮（L2396–2406） | `ImplantPanel` | `src/features/implant/ImplantPanel.tsx` | C10/E13 | 4 卡片（py/pyexe/go/goexe），生成路径回显 |
| 菜单/导航/工具管理（`add_menus`/`add_navigation_bar`/`add_Tools`，≈L433/370/218） | `MenuManager` | `src/features/menu/MenuManager.tsx` | C7/C8/E8 | 动态路由由 E8 快照驱动 |
| 本地终端编解码（`local_cmd`，≈L1127） | `CodecPanel` | `src/features/codec/CodecPanel.tsx` | **纯前端**（Web Crypto/base64/xxd 等，不经过桥） | 无网络面，独立最安全 |
| AI 模型设置（`add_ai_setting`） | `AiSettings` | `src/features/ai/AiSettings.tsx` | C9/E8 | |
| 窗口大小（`windowSize_Setting`） | 并入 `AiSettings` 同页 | — | C12 | |
| 更新记录（`update_record_show`，≈L911 弹窗） | `AboutDialog` | `src/components/AboutDialog.tsx` | 静态文案/版本 | |
| 底部状态栏（`status_bar`/`set_status`，≈L61） | `StatusBar` | `src/components/StatusBar.tsx` | E14 + 本地 | 左侧文字 + 右侧 C2 连接徽标 |
| 深色模式（工具箱设置菜单项，L998） | `ThemeToggle` | `src/components/ThemeToggle.tsx` | C11/E15 | CSS 变量切换 + localStorage 持久 |
| tooltip（`make_tooltip`，4 处） | 原生 `title` / 统一 Tooltip 组件 | — | — | 文案沿用 |

**键盘映射（旧 → 新）**

| 旧 | 新 |
|---|---|
| 聊天框 `Shift+Enter` 发送 | 保留：`AiChat` 输入框 `keydown` 拦截 |
| 命令行回车执行 | `C2Console` 输入行 `Enter` → C3/C4 路由（`get ` 前缀 → C4，否则 C3） |
| 面板切换（菜单栏点击） | 路由跳转（`/menu/<name>`、`/nav/<name>`） |

---

## 6. 前端工程与逐阶段实施步骤

> 仓库内新增目录（与 Python 同级 monorepo）：
> ```
> Daybreak-Toolbox/
>   python/            # 现有 .py 迁入（app.py 拆分后逐步瘦身）
>   web/               # React + TS（Vite）
>   packaging/         # 打包脚本与 PyInstaller spec
>   docs/              # 本文档
> ```

### Phase 0 — 脚手架（0.5 人日）

| 步 | 操作 | 命令/文件 | 预期 | 验收 |
|---|---|---|---|---|
| 0.1 | 初始化 Vite React-TS | `cd Daybreak-Toolbox && pnpm create vite web --template react-ts && cd web && pnpm i` | `web/` 脚手架生成 | `pnpm dev` 可打开默认页 |
| 0.2 | 装依赖 | `pnpm i zustand xterm xterm-addon-fit react-markdown lucide-react` | — | `pnpm build` 通过 |
| 0.3 | 设计令牌 | 新建 `web/src/theme/tokens.css` + `tokens.ts`：把附录 A 的 CSS 变量落文件（`:root` 浅色、`[data-theme=dark]` 深色） | 两色板齐全 | 页面挂 `<div class="card">` 在两种主题下目检 |
| 0.4 | 布局壳 | `web/src/components/AppShell.tsx`：顶部菜单 + 左侧导航 + 主内容 + 底部 StatusBar（占位） | 四区渲染 | 窗口缩放不破版（`resize` 200ms 拖拽 3 次无错位） |
| 0.5 | 路由 | `react-router`：静态路由 `/ai` `/translate` `/implant` `/settings`；`/menu/*` 动态路由（Phase 3.9 接 E8） | — | `pnpm build` 通过 |
| 0.6 | 本地联调代理 | `web/vite.config.ts` `devServer.proxy`：`/ws → ws://127.0.0.1:8765`、`/api → http://127.0.0.1:8765` | — | dev 下断点可断到 WS 客户端 |
| **出口** | 壳工程可构建 | `pnpm build` exit 0 | dist 生成 | ✅ |

### Phase 1 — 桥接 MVP（Python 侧，1 人日）

| 步 | 操作 | 文件 | 验收 |
|---|---|---|---|
| 1.1 | 新建 `python/bridge/`：`main.py`（FastAPI + uvicorn，仅 127.0.0.1，端口 8765 起冲突 +1×5）、`token.py`（生成/读取 `config/bridge_token.json`，不存在则生成并写盘；文件加入 `.gitignore`） | `python/bridge/*` | `python -m bridge.main` 启动；`curl http://127.0.0.1:8765/api/ping?token=<t>` 200；错误 token 401 |
| 1.2 | `ws.py`：WS 事件总线——连接注册表、`{id}` 请求-响应匹配表、`broadcast(event, payload)`、512KB 帧上限拒绝 | 同上 | pytest：双客户端互收、超帧拒收、断连清理 |
| 1.3 | **从 app.py 抽取 `c2_client.py`**（**先加测试网，不改语义**）：`connect/recv_result/_run_c2_command/get_rouji_json_xinxi/download_file` 逐字搬移；`CLIENT_SOCKET_LOCK` 换成 `asyncio.Lock` + 单 worker 队列保持"帧串行"不变；把 `command_line.insert` 全部改为 `hub.broadcast("c2.log", ...)` | `python/bridge/c2_client.py` | 帧回环 3 用例（44B 头 + 拆包 + 对端关闭）全过；刷新快照进 E3 |
| 1.4 | `echo` 自检端点 + 冒烟脚本 | `python/bridge/smoke.py` | `python -m bridge.smoke` 输出 `SMOKE_OK` |
| 1.5 | 前端 WS 客户端 `web/src/services/ws.ts`：自动重连（指数退避）、心跳 15s、事件分发到 zustand store | 同上 | 手杀 Python 进程后 1s 内前端显示"重连中"，重启后自动恢复 |
| **出口** | `SMOKE_OK` + pytest 绿 + 前端 DevTools 能看到 echo 事件 | | ✅ |

### Phase 2 — 主题与设计系统（0.5 人日）

| 步 | 操作 | 验收 |
|---|---|---|
| 2.1 | 按附录 A 落地 CSS 变量（含深色）；`ThemeToggle` 切换 `[data-theme]` + `localStorage` 持久 + C11/E15 同步 | 明暗切换所有组件即刻生效，无闪烁（变量在 `:root` 层） |
| 2.2 | 基础组件库（自绘，不引 UI 框架）：`Btn`（accent/hover/disabled 对齐 ui_theme 三态色）、`Card`、`Input`、`ConfirmDialog`（承接删除二次确认语义）、`Tooltip` | 组件目检与现 ui_theme 观感一致 |
| 2.3 | 字体：`--font-ui` 用 system-ui 栈（Windows 下即微软雅黑），`--font-mono` Consolas；高 DPI 不做额外缩放 | 125%/150% 缩放下文字不糊 |
| **出口** | 双主题 × 3 个组件（Btn/Card/Dialog）目检通过 | ✅ |

### Phase 3 — 面板逐个迁移（每个面板：开发 4–8 步 + 验收清单）

> 迁移顺序按"依赖最少 → 最多"：C2 → 翻译 → 生成 → AI → 菜单管理 → 其余。

#### 3.1 C2Console + C2ConnectBar + HostTree + TransferProgress（2 人日）

| 步 | 操作 | 验收 |
|---|---|---|
| 3.1.1 | `C2Console`：xterm 实例（`Terminal + FitAddon`），只读输出 + 底部输入行；E4 按 `level` 上色（`cmd` 亮青、`error` 红、`success` 绿，取 tokens 值） | 连续灌 500 行 < 200ms 无掉帧；`see(END)` 等价自动贴底 |
| 3.1.2 | 输入路由：`Enter` → 解析 `get ` 前缀走 C4，否则 C3；`cd/ls` 结果按 E4 渲染 | 与旧行为一致：`ls` 逐行回显 |
| 3.1.3 | `C2ConnectBar`：IP/Port 表单 + 连接/断开按钮 + 连接徽标（E1/E2） | 断连后徽标变红并禁用命令输入（防 TRANSFER_BUSY） |
| 3.1.4 | `HostTree`：E3 全量快照渲染；右键"删除" → `ConfirmDialog`（保留二次确认语义）→ C8 | 删除前必弹确认 |
| 3.1.5 | `TransferProgress`：E5 出现→显示条 + E6 推进（`total>0` 显示 %，否则不确定动画）+ E7 收起；同时驱动 StatusBar（E14） | 一次完整 `get`：进度条"出现→推进→完成收起"，状态栏三段文案 |
| 3.1.6 | 忙守卫：前端禁用 + 服务端 `TRANSFER_BUSY` 错误码双保险 | 下载中再发 C4 → 弹"传输忙"提示，不排队不串流 |
| **验收** | 真实 server.py + 一个 mock 植入（脚本模拟 C 端回帧）跑通：连接/刷新/命令/下载/删除全流程 | ✅ |

#### 3.2 TranslatePanel（0.5 人日）

| 步 | 操作 | 验收 |
|---|---|---|
| 3.2.1 | 输入/输出双框 + 方向切换（中↔英）+ 翻译按钮；提交 C6；E11 回写输出，E12 显示"翻译出错：…" | 与旧文案一致 |
| 3.2.2 | 未配置凭证时按钮禁用 + Tooltip 提示（`config/baidu.py` 缺失） | — |
| **验收** | 配置好凭证：翻译 200 字文本 < 3s 回显；UI 全程不卡（服务端 worker） | ✅ |

#### 3.3 ImplantPanel（0.5 人日）

| 步 | 操作 | 验收 |
|---|---|---|
| 3.3.1 | 4 卡片（py/pyexe/go/goexe），点击 C10；E13 回显生成路径 + 成功/失败态 | 4 个语种各生成一次 |
| 3.3.2 | 生成中卡片 loading（fun.py 渲染 + pyinstaller 若启用可能数秒） | 并发点 2 个卡：服务端串行队列，第二个排队 |
| **验收** | 生成物与旧 app.py 产物逐字节一致（`hash` 对比，同参数） | ✅ |

#### 3.4 AiChat + AiCompare（1.5 人日）

| 步 | 操作 | 验收 |
|---|---|---|
| 3.4.1 | `AiChat`：消息列表（react-markdown）+ 输入框（Shift+Enter 发送保留）+ 流式：E9 `delta` 增量追加、`done` 收尾 | 打字机效果；断流显示 E10 错误条 |
| 3.4.2 | `AiCompare`：左右双会话（两个 session 并行 C5），同名问题双发，各自流式 | 双栏独立滚动能对齐 |
| 3.4.3 | `AiSettings`：provider/模型/key 表单（C9），key 走 `config/`（沿用 baidu 同款 gitignore 约定，**任何 key 不进 git**） | 保存后 E8 广播；UI 不回显完整 key（掩码） |
| **验收** | 双模型流式并发 10 轮无串帧（msg_id 路由正确） | ✅ |

#### 3.5 MenuManager + 动态路由（1 人日）

| 步 | 操作 | 验收 |
|---|---|---|
| 3.5.1 | `MenuManager`：菜单/导航/工具三类 CRUD（C7/C8），表单校验与旧 `entry_Event` 提示语一致 | 重名报 `MENU_NAME_EXISTS` |
| 3.5.2 | E8 快照 → 动态路由重建（`/menu/<name>` 渲染"工具卡片墙"，卡片=工具项，启动方式枚举 5 种：直接打开/命令行打开/文件夹打开/链接打开/下载链接） | 增删一个导航栏后，刷新页面路由仍在 |
| 3.5.3 | 工具"下载链接"：走本地下载（Python `download_tool` service）+ 进度（E6 复用） | 下载→"下载成功"提示与旧文案一致 |
| **验收** | config.json 双向：Web CRUD 后 `cat config/config.json` 结构不变 | ✅ |

#### 3.6 收尾面板（0.5 人日）

`CodecPanel`（纯前端 base64/hex/xxd/url，Web Crypto，不经过桥）、`AboutDialog`（更新记录）、`StatusBar` 汇总（E14 + C2 徽标 + 主题切换入口并入"工具箱设置"菜单，与现菜单结构一致）。
**验收**：全部面板齐、`pnpm build` 绿。

### Phase 4 — 打包分发（1 人日）

| 步 | 操作 | 验收 |
|---|---|---|
| 4.1 | `pnpm build` → `web/dist`；`packaging/entry.py`：起 uvicorn 线程 → `webview.create_window("破晓·工具箱", "http://127.0.0.1:8765", http_user/token)` → 窗口关闭时优雅关停（WS 广播 E2 → 关 socket → 退出） | 源码态 `python packaging/entry.py` 可用 |
| 4.2 | `packaging/DaybreakToolbox.spec`（PyInstaller onedir）：收 `python/` 全模块 + `dist/` + `config/`（排除 `baidu.py`、`bridge_token.json`）；exe 图标 | 干净 Win11 机：放包即跑，无 Node |
| 4.3 | 一键脚本 `packaging/build.ps1`：`pnpm build` → `pyinstaller` → `Compress-Archive` | 全链路 10 分钟内出包 |
| 4.4 | 冒烟清单（附录 D）逐项过 | ✅ |
| **出口** | 干净机（或虚拟机）冒烟全绿 | 出第一个 RC 包 |

### Phase 5 — 切换与退役（1 人日缓冲 + 2 周观察）

| 步 | 操作 | 验收 |
|---|---|---|
| 5.1 | feature flag：`python run.py --ui=web`（默认旧 tkinter），`--ui=web` 走新壳 | 双模式可切 |
| 5.2 | 2 周并行观察：C2 误报/串帧/进度异常任一出现 → 回滚 flag（旧 UI 原样在） | 观察期零 P0 |
| 5.3 | 归档：`app.py` → `legacy/app.py`（保留一版本周期），`requirements.txt` 加 `fastapi/uvicorn/webview` | git 历史可查 |

### Phase 6 — 前端质量（与 Phase 3 并行）

| 项 | 工具 | 标准 |
|---|---|---|
| 单测 | vitest + testing-library | store/services 覆盖率 ≥ 70%；协议 fixtures 用**录制真实帧**（44B 头 + payload 存 `web/test/fixtures/`，测试 key 与生产 key 隔离） |
| E2E | Playwright | 5 条主路径（连接→命令→下载→AI 双聊→翻译）；mock 植入脚本（Python 模拟 C 端回帧）做服务端 |
| 静态检查 | eslint + prettier + `tsc --noEmit` | CI 全绿 |

---

## 7. 可选增强（需 C 端重新发放，默认不做）

| 项 | 内容 | 前置 | 说明 |
|---|---|---|---|
| 7.1 确定性下载进度 | C 端 `send_file_nonblocking` 已先明文发 `file_size`：桥接 `c2_client` 接收侧记录 `total`，E6 填真实值 | 与现有"裸流共用 socket"实现逐项对齐验证 | 进度条从不确定→确定；**C 端零改动**（size 早已发出） |
| 7.2 HMAC / 密钥轮换 | 帧头加 HMAC 字段 | C 端重新发放 | `c2_common.py` 注释已声明：属破坏性协议变更，不做盲改 |
| 7.3 断线续传 | 下载中断按 offset 续传 | C 端 + 协议双改 | 收益/成本比低，暂不做 |

---

## 8. 风险与缓解（Top 10）

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | 共享 socket 帧交错（刷新帧插进下载流） | 中 | 高 | `c2_client` 单 worker 队列 + asyncio 锁 1:1 复刻 `CLIENT_SOCKET_LOCK`；帧回环测试进 CI |
| R2 | 裸流与加密帧混用导致 `recv` 错位 | 中 | 高 | 迁移前先给 `c2_client` 补"协议级录制回放"测试（Phase 1.3 前插一步） |
| R3 | 中文路径/文件名编码（GBK/UTF-8） | 中 | 中 | 桥接统一 UTF-8；URL/路径 percent-encoding；旧 chardet 逻辑仅在解码输出文本时保留 |
| R4 | WebView2 缺失（老 Win7/8） | 低 | 中 | 启动探测缺失 → 回退浏览器模式（提示打开 127.0.0.1:8765） |
| R5 | 包体被杀软误报（PyInstaller + webview） | 中 | 中 | 代码签名（若可申请证书）；误报库留名 |
| R6 | token 文件泄漏 | 低 | 高 | 权限 0600；启动校验文件指纹；`config/bridge_token.json` 永远 gitignore |
| R7 | 双 UI 并行期行为漂移 | 中 | 中 | Phase 5.2 双周观察 + 一键回滚 flag；关键路径 E2E 固定 |
| R8 | AI 流式串帧（双 AI 并发） | 低 | 中 | E9 带 `session+msg_id` 路由；10 轮并发压测 |
| R9 | 大日志刷屏卡 UI | 低 | 中 | xterm 行上限 5000 环形丢弃 + 后端按 100ms 合批 E4 |
| R10 | 迁移期密钥误入 git（历史教训：百度 key 曾进历史） | 低 | 高 | pre-commit `gitleaks` 钩子；key 一律 `config/` gitignored 文件 |

---

## 9. 里程碑与工时（单人）

| 里程碑 | 内容 | 工时 | 累计 |
|---|---|---|---|
| M0 | Phase 0 脚手架 + 令牌 | 0.5d | 0.5d |
| M1 | Phase 1 桥接 MVP（含 c2_client 抽取 + 回环测试） | 1d | 1.5d |
| M2 | Phase 2 主题系统 | 0.5d | 2d |
| M3 | Phase 3.1 C2 全家桶 | 2d | 4d |
| M4 | Phase 3.2–3.3 翻译 + 生成 | 1d | 5d |
| M5 | Phase 3.4–3.6 AI + 菜单 + 收尾 | 3d | 8d |
| M6 | Phase 4 打包分发 + 冒烟 | 1d | 9d |
| M7 | Phase 5 切换退役（含 2 周观察缓冲 1d） | 1d+观察 | 10d |

**总 ≈ 10 人日 + 2 周观察期。**

---

## 10. 附录

### A. `ui_theme.py` → CSS 变量映射（照抄落地）

```css
:root {
  --bg: #f4f6f8;            /* COLORS.bg */
  --panel: #ffffff;         /* COLORS.panel */
  --border: #d9dde3;        /* COLORS.border */
  --text: #202124;         /* COLORS.text */
  --muted: #5f6368;        /* COLORS.muted */
  --accent: #1a73e8;       /* COLORS.accent */
  --accent-hi: #2b86f5;    /* hover */
  --accent-lo: #b6c5e0;    /* disabled */
  --success: #188038;
  --warn: #f9ab00;
  --error: #d93025;
  --console-bg: #1e1e28;   /* 深色控制台（浅色主题下也保持深色，观感一致） */
  --console-fg: #d4d4d4;
  --cmd-fg: #4fc3f7;
  --out-fg: #d4d4d4;
  --scroll: #cfd8dc;
  --heading-bg: #e8eaed;
  --heading-active: #dde2e8;
  --font-ui: "Microsoft YaHei", system-ui, sans-serif;
  --font-mono: "Consolas", monospace;
}
[data-theme="dark"] {
  --bg: #1e1f24;           /* DARK.bg */
  --panel: #262830;        /* DARK.panel */
  --border: #3a3d46;
  --text: #e6e6e6;
  --muted: #9aa0a6;
  --accent: #4f9cf9;
  --accent-hi: #6cb0ff;
  --accent-lo: #33425a;
  --success: #34a853;
  --warn: #fdd663;
  --error: #f28b82;
  --console-bg: #14151a;
  --console-fg: #e6e6e6;
  --cmd-fg: #82d1ff;
  --out-fg: #e6e6e6;
  --scroll: #44474f;
  --heading-bg: #31343d;
  --heading-active: #3a3d46;
}
```

C2 控制台 tag → CSS 类：`.log-cmd{color:var(--cmd-fg)} .log-error{color:var(--error)} .log-success{color:var(--success)} .log-warn{color:var(--warn)} .log-title{color:var(--accent);font-weight:bold}`（与 `apply_console` 的 tag 定义一一对应）。

### B. 桥接消息全目录（含 JSON 示例）

```jsonc
// 客户端 → 服务端（命令）
{"v":1,"id":"a1","type":"c2.command","payload":{"host":"PC-07","cmd":"ls /tmp"}}
{"v":1,"id":"a2","type":"ai.send","payload":{"session":"s2","provider":"gpt","text":"hi","stream":true}}
// 服务端 → 客户端（事件）
{"v":1,"type":"c2.log","payload":{"host":"PC-07","level":"cmd","line":"ls /tmp"}}
{"v":1,"type":"c2.transfer.progress","payload":{"host":"PC-07","file":"/tmp/a.bin","done":8192,"total":0,"state":"running"}}
// 服务端 → 客户端（响应）
{"v":1,"id":"a1","type":"ack","payload":{}}
{"v":1,"id":"a3","type":"err","payload":{"code":"TRANSFER_BUSY","message":"上一次下载未完成"}}
```

### C. 现有 app.py 函数 → 桥接 API 映射（完整对照）

| 现有函数（app.py） | 桥接 API | 备注 |
|---|---|---|
| `muma_listen_setting` | C1 `c2.connect` | 含首次刷新 |
| `_run_c2_command` | C3 `c2.command` | C2 锁语义保留 |
| `download_file` + `poll_file_data` | C4 `c2.download` | 事件化 E5/E6/E7 |
| `get_rouji_json_xinxi`（5s 自订） | 服务端自动 → E3 | 前端零感知 |
| `delete_server_C`（+二次确认） | C8 `menu.remove`（kind=host） | 确认弹窗移前端 |
| `add_menus / add_navigation_bar / add_Tools` | C7 `menu.add` | E8 广播 |
| `ai_request_thread` ×2 | C5 `ai.send` ×2 session | E9 流式 |
| `on_translate_click` | C6 `translate.run` | E11/E12 |
| `add_py_muma / add_py_exe_muma / add_go_muma / add_go_exe_muma` | C10 `implant.generate` | E13 |
| `add_ai_setting` | C9 `ai.settings` | E8 |
| `windowSize_Setting` | C12 `window.resize` | 写 windowSize.json |
| `update_record_show` | 前端静态 AboutDialog | 文案同源 |
| `_toggle_dark` | C11 `theme.set` | E15 同步 |
| `set_status` | E14 / C13 | 双向 |

### D. 打包冒烟清单（干净机）

- [ ] 解压即跑（无 Python/Node 安装提示）
- [ ] 窗口标题/图标正确，DPI 125%/150% 不糊
- [ ] C2：连接 → 自动刷新主机列表 → `cd`/`ls` → `get` 下载（进度条三段：出现→推进→收起）→ 右键删除二次确认
- [ ] 双 AI 流式并发 10 轮无串帧
- [ ] 翻译成功 + 未配置凭证提示
- [ ] 4 种木马生成产物 hash 与旧版一致
- [ ] 菜单增删 → `config/config.json` 结构不变且重开仍在
- [ ] 深色模式切换 + 重启后保持
- [ ] 杀 Python 进程：前端 1s 内"重连中"；恢复后状态自愈
- [ ] `config/` 下无任何 key 类文件被打进包（`dir` 检查）

---

## 11. 立即行动项（若批准开工）

1. `git checkout -b feat/web-ui`（独立分支，tkinter 端继续在 main 演进的互不阻塞）；
2. 按 Phase 0 → 1 → 2 顺序执行，每 Phase 出口检查通过再合并；
3. Phase 1.3 前先补 `c2_client` 协议录制回放测试（风险 R2）；
4. 任何密钥（AI key / 百度 key / bridge token）只落 `config/` gitignored 文件，提交前 `gitleaks` 必过。
