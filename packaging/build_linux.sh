#!/usr/bin/env bash
# 破晓·工具箱 —— Linux 自编译脚本（产物 DaybreakToolbox 单文件可执行）
# 依赖：Python 3.10+、Node 18+、pnpm 11、zip；
#       运行环境需系统 GTK 库（托盘/悬浮球仅 Windows 生效，Linux 为纯服务 + 浏览器访问）
# 用法：仓库根目录执行  bash packaging/build_linux.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 1/4 前端构建 (vite → web/dist)"
( cd web && pnpm install --frozen-lockfile && pnpm build )

echo "==> 2/4 安装依赖 + PyInstaller"
python3 -m pip install -r requirements.txt
python3 -m pip install "setuptools<81" pyinstaller

echo "==> 3/4 PyInstaller 打包（onefile）"
rm -rf build dist DaybreakToolbox.spec
python3 -m PyInstaller --name DaybreakToolbox --noconfirm \
  --onefile \
  --exclude-module keyring --exclude-module pywebview \
  --add-data "web/dist:dist" --add-data "config:config" \
  run_bridge.py

echo "==> 4/4 压缩"
VER=$(sed -n 's/.*APP_VERSION = "\([0-9.]*\)".*/\1/p' bridge/update_service.py | head -1)
[ -n "$VER" ] || VER="local"
cd dist
zip "../Daybreak-Toolbox-v${VER}-linux-x64.zip" DaybreakToolbox
cd ..
ls -la dist
echo "完成：dist/DaybreakToolbox（运行 ./DaybreakToolbox，浏览器打开 http://127.0.0.1:8765/）"
