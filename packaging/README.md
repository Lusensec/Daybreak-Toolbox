# 打包说明

## 各平台构建

| 平台 | 方式 | 产物 |
| --- | --- | --- |
| Windows | 本仓库 `dist/DaybreakToolbox*.exe`（Release 附件 `*-win-x64.zip`），或本地 `pyinstaller --onefile --noconsole` 重新构建 | `DaybreakToolbox.exe` |
| macOS | `bash packaging/build_mac.sh`（arm64/x86_64 均可，需本机 Mac） | `DaybreakToolbox.app` |
| Linux | `bash packaging/build_linux.sh`（需 Linux 本机） | `DaybreakToolbox` 可执行文件 |

PyInstaller **不能交叉编译**：macOS 包必须在 macOS 上构建、Linux 包必须在 Linux 上构建
（CI `.github/workflows/release.yml` 在标签推送时于 GitHub 各平台 runner 完成并上传附件）。

## Windows 本地重新构建

```
pnpm build            # 在 web/ 目录（或 pnpm --filter web build）
python -m PyInstaller --onefile --noconsole --name DaybreakToolbox --noconfirm \
    --exclude-module keyring \
    --collect-all pythonnet --collect-all clr_loader --hidden-import clr \
    --icon packaging\daybreak_logo.ico \
    --add-data "web/dist;dist" --add-data "config;config" \
    --add-data "<site-packages>/webview/lib/Microsoft.Web.WebView2.Core.dll;." \
    --add-data "<site-packages>/webview/lib/Microsoft.Web.WebView2.WinForms.dll;." \
    --add-data "<site-packages>/webview/lib/WebBrowserInterop.x64.dll;." \
    --add-data "<site-packages>/webview/lib/runtimes/win-x64/native/WebView2Loader.dll;." \
    run_bridge.py
```

- `--icon`（v2.0.4 起）：图标文件为 `packaging/daybreak_logo.ico`（多尺寸 16-256，源自 `web/public/logo.png`）。
  Logo 更新后重新生成 ico（PIL 一行）：
  `python -c "from PIL import Image; Image.open('web/public/logo.png').convert('RGBA').save('packaging/daybreak_logo.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"`
  该图标同时决定 exe 文件图标、窗口标题栏与任务栏图标（WinForms 窗口默认继承进程 exe 图标）。

- 窗口模式（v2.0.3 起 exe 默认弹原生窗口）依赖 pywebview/pythonnet 与上述 WebView2 interop DLL（onefile 下必须平铺到打包根目录；
  缺任一项时窗口不可用 → 自动降级「服务 + 默认浏览器」，其余功能不受影响）。
- `<site-packages>` 用 `python -c "import webview,os;print(os.path.dirname(webview.__file__))"` 获取（CI 同款逻辑见 release.yml）。

- 排除项说明：`keyring`/`pywebview` 为未使用依赖（分析阶段体积与风险）；如装有多余的
  ML 依赖（torch/transformers 等）建议一并 `--exclude-module`，避免分析阶段耗时过长。
- 本机若装有安全代理软件，分析阶段长时间读文件可能被误杀：减小分析图（更多 exclude）可规避。

## 运行行为（打包版）

- 首次启动在 **exe 同目录** 生成 `config/`（菜单配置 / 悬浮球位置 / 更新仓库配置）与 `daybreak.log`（诊断日志）。
- 升级覆盖 exe 不会丢失 config/（已存在文件不覆盖）。
- 窗口形态（v2.0.3 起默认）：启动后弹出原生应用窗口即完整界面；关闭窗口 = 退出进程。
- 服务模式（`--service` 参数或窗口引擎缺失时自动降级）：无常驻窗口，启动后自动打开默认浏览器访问 http://127.0.0.1:8765/（端口被占用时自动 +1，日志中打印实际端口）。
- Windows 托盘右键「退出破晓工具箱」结束进程；悬浮球菜单「关闭小球」仅停球。
