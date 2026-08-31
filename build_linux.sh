#!/usr/bin/env bash
# LLM 智能调度网关 - Linux 打包脚本
# 桌面窗口模式需要系统 WebKitGTK（Debian/Ubuntu: sudo apt install libwebkit2gtk-4.1-dev）；
# 缺失时程序会自动回退到浏览器打开面板，不影响使用。
set -e
cd "$(dirname "$0")"
echo "============================================"
echo " LLM 智能调度网关 - Linux 打包"
echo "============================================"
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller pywebview
python3 -m PyInstaller --noconfirm --clean --onefile --name llm-gateway \
  --add-data "web:web" \
  --collect-all uvicorn \
  --collect-all webview \
  --collect-all pystray \
  --collect-all pillow \
  --hidden-import webview.platforms.gtk \
  main.py
echo ""
echo "打包完成: dist/llm-gateway"
