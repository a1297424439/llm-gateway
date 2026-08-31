@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo  LLM 智能调度网关 - Windows 打包
echo ============================================
python -m pip install -r requirements.txt || goto :err
python -m pip install pyinstaller pywebview || goto :err
python -m PyInstaller --noconfirm --clean --onefile --name llm-gateway ^
  --add-data "web;web" ^
  --collect-all uvicorn ^
  --collect-all webview ^
  --collect-all pythonnet ^
  --collect-all pystray ^
  --collect-all pillow ^
  --hidden-import clr ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import webview.platforms.winforms ^
  main.py || goto :err
echo.
echo 打包完成: dist\llm-gateway.exe
pause
exit /b 0
:err
echo 打包失败，请检查上方报错信息。
pause
exit /b 1
