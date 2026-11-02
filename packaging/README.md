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
    --exclude-module keyring --exclude-module pywebview \
    --add-data "web/dist;dist" --add-data "config;config" \
    run_bridge.py
```

- 排除项说明：`keyring`/`pywebview` 为未使用依赖（分析阶段体积与风险）；如装有多余的
  ML 依赖（torch/transformers 等）建议一并 `--exclude-module`，避免分析阶段耗时过长。
- 本机若装有安全代理软件，分析阶段长时间读文件可能被误杀：减小分析图（更多 exclude）可规避。

## 运行行为（打包版）

- 首次启动在 **exe 同目录** 生成 `config/`（菜单配置 / 悬浮球位置 / 更新仓库配置）与 `daybreak.log`（诊断日志）。
- 升级覆盖 exe 不会丢失 config/（已存在文件不覆盖）。
- 启动后浏览器打开 http://127.0.0.1:8765/（端口被占用时自动 +1，日志中打印实际端口）。
- Windows 托盘右键「退出破晓工具箱」结束进程；悬浮球菜单「关闭小球」仅停球。
