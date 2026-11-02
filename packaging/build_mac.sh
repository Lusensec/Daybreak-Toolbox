#!/usr/bin/env bash
# 破晓·工具箱 —— macOS 自编译脚本（arm64 / x86_64 均可；产物 DaybreakToolbox.app）
# 依赖：Python 3.10+（建议 brew 的 3.10/3.11）、Node 18+、pnpm 11
# 用法：仓库根目录执行  bash packaging/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 1/4 前端构建 (vite → web/dist)"
( cd web && pnpm install --frozen-lockfile && pnpm build )

echo "==> 2/4 安装依赖 + PyInstaller"
python3 -m pip install -r requirements.txt
python3 -m pip install "setuptools<81" pyinstaller

echo "==> 3/4 PyInstaller 打包（onefile .app）"
rm -rf build dist DaybreakToolbox.spec
python3 -m PyInstaller --name DaybreakToolbox --noconfirm \
  --onefile --windowed \
  --exclude-module keyring --exclude-module pywebview \
  --add-data "web/dist:dist" --add-data "config:config" \
  run_bridge.py

echo "==> 4/4 压缩"
VER=$(sed -n 's/.*APP_VERSION = "\([0-9.]*\)".*/\1/p' ../bridge/update_service.py | head -1)
[ -n "$VER" ] || VER="local"
cd dist
zip -r "../Daybreak-Toolbox-v${VER}-mac-$(uname -m).zip" DaybreakToolbox.app
cd ..
ls -la dist
echo "完成：dist/DaybreakToolbox.app（双击运行；首次 右键→打开 绕过 Gatekeeper）"
