"""入口：python main.py [--browser] [--no-ui]

默认行为：启动网关并弹出一个原生桌面窗口承载管理面板（Windows 用系统自带
WebView2 渲染）。点窗口 ✕ 时弹出确认框：隐藏到托盘 / 退出程序（可记住选择）。
托盘图标双击/左键 = 重新打开面板。
  --browser   不弹桌面窗口，直接在默认浏览器打开面板
  --no-ui     无界面服务模式：托盘图标常驻（双击打开面板，右键退出）

首次启动自动生成随机监听端口与随机 API Key（与历史不重复）。
Python 3.9+，Windows / Linux / macOS 通用。
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _wait_started(srv, timeout: float = 25.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if getattr(srv, "started", False):
            return True
        time.sleep(0.1)
    return False


def _tray_image():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=16, fill=(10, 110, 255))
    for i, y in enumerate((20, 32, 44)):
        d.line([(16, y), (46 - i * 8, y)], fill="white", width=5)
    return img


def _ask_close_native(window, srv, tray_icon) -> str:
    """✕ 确认框（无边框圆角卡片）：返回 "hide" / "quit" / None(取消)。"""
    import clr
    import System.Windows.Forms as WinForms
    import System.Drawing as Drawing
    import System.Drawing.Drawing2D as Drawing2D

    BLUE = Drawing.Color.FromArgb(0, 122, 255)
    RED = Drawing.Color.FromArgb(255, 59, 48)
    result = {"action": None, "remember": False}

    form = WinForms.Form()
    form.Text = "关闭窗口"
    # FormBorderStyle 的 None 值不能直接写 .None（关键字），用 getattr 取
    form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
    form.StartPosition = WinForms.FormStartPosition.CenterParent
    form.TopMost = True
    form.ClientSize = Drawing.Size(360, 224)
    form.BackColor = Drawing.Color.White

    def _round(w, h, radius=16):
        path = Drawing2D.GraphicsPath()
        path.AddArc(0, 0, radius * 2, radius * 2, 180, 90)
        path.AddArc(w - radius * 2, 0, radius * 2, radius * 2, 270, 90)
        path.AddArc(w - radius * 2, h - radius * 2, radius * 2, radius * 2, 0, 90)
        path.AddArc(0, h - radius * 2, radius * 2, radius * 2, 90, 90)
        path.CloseFigure()
        form.Region = Drawing.Region(path)

    title = WinForms.Label()
    title.Text = "关闭窗口"
    title.Font = Drawing.Font("Segoe UI", 12.0, Drawing.FontStyle.Bold)
    title.ForeColor = Drawing.Color.FromArgb(28, 28, 30)
    title.SetBounds(0, 18, 360, 28)
    title.TextAlign = Drawing.ContentAlignment.MiddleCenter

    msg = WinForms.Label()
    msg.Text = "要退出调度中枢，还是最小化到托盘继续服务？\n（Hermes 等客户端只有在程序运行时才能连接）"
    msg.Font = Drawing.Font("Segoe UI", 9.5)
    msg.ForeColor = Drawing.Color.FromArgb(110, 110, 115)
    msg.SetBounds(24, 52, 312, 46)

    chk = WinForms.CheckBox()
    chk.Text = "记住我的选择，今后点 ✕ 不再询问"
    chk.Font = Drawing.Font("Segoe UI", 9.0)
    chk.ForeColor = Drawing.Color.FromArgb(110, 110, 115)
    chk.SetBounds(24, 104, 312, 24)

    btn_hide = WinForms.Button()
    btn_hide.Text = "隐藏到托盘（服务继续运行）"
    btn_hide.Font = Drawing.Font("Segoe UI", 9.75, Drawing.FontStyle.Bold)
    btn_hide.BackColor = BLUE
    btn_hide.ForeColor = Drawing.Color.White
    btn_hide.FlatStyle = WinForms.FlatStyle.Flat
    btn_hide.FlatAppearance.BorderSize = 0
    btn_hide.Cursor = WinForms.Cursors.Hand
    btn_hide.SetBounds(24, 138, 312, 38)

    btn_quit = WinForms.Button()
    btn_quit.Text = "退出程序"
    btn_quit.Font = Drawing.Font("Segoe UI", 9.75)
    btn_quit.BackColor = Drawing.Color.White
    btn_quit.ForeColor = RED
    btn_quit.FlatStyle = WinForms.FlatStyle.Flat
    btn_quit.FlatAppearance.BorderSize = 0
    btn_quit.Cursor = WinForms.Cursors.Hand
    btn_quit.SetBounds(24, 184, 312, 38)

    def _on_hide(s, e):
        result["action"] = "hide"
        result["remember"] = chk.Checked
        form.Close()

    def _on_quit(s, e):
        result["action"] = "quit"
        result["remember"] = chk.Checked
        form.Close()

    btn_hide.Click += _on_hide
    btn_quit.Click += _on_quit
    form.Controls.Add(title)
    form.Controls.Add(msg)
    form.Controls.Add(chk)
    form.Controls.Add(btn_hide)
    form.Controls.Add(btn_quit)
    _round(360, 224, 16)
    form.ShowDialog()   # 原生模态：阻塞确认框，必然可点

    act = result["action"]
    if act and result["remember"]:
        try:
            from app import config as cfgmod
            cfgmod.cfg()["server"]["close_action"] = act
            cfgmod.save()
        except Exception:
            pass
    if act == "hide":
        try:
            window.hide()
        except Exception:
            pass
    elif act == "quit":
        srv.should_exit = True
        try:
            if tray_icon:
                tray_icon.stop()
        except Exception:
            pass
    return act


def main() -> None:
    multiprocessing.freeze_support()

    # 无控制台窗口（PyInstaller console=False）下 sys.stdout/stderr 为 None，
    # uvicorn 初始化日志会调用 isatty() 崩溃，这里兜底重定向到 devnull。
    if sys.stdout is None or sys.stderr is None:
        try:
            _dn = open(os.devnull, "w", encoding="utf-8")
            if sys.stdout is None:
                sys.stdout = _dn
            if sys.stderr is None:
                sys.stderr = _dn
        except Exception:
            pass

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="LLM 智能调度网关")
    ap.add_argument("--browser", action="store_true", help="不弹桌面窗口，直接用默认浏览器打开面板")
    ap.add_argument("--no-ui", action="store_true", help="无界面服务模式：托盘图标常驻（右键退出）")
    args = ap.parse_args()

    # 本地回环流量不走路由代理（用户可能配置了 HTTP(S)_PROXY 访问国际渠道）
    for var in ("NO_PROXY", "no_proxy"):
        cur = os.environ.get(var, "")
        parts = [x for x in cur.split(",") if x.strip()]
        for need in ("127.0.0.1", "localhost"):
            if need not in parts:
                parts.append(need)
        os.environ[var] = ",".join(parts)

    from app import config as cfgmod
    cfg = cfgmod.load()

    # 重启/新进程启动后，新配置已实际生效，清除「待重启」横幅标记
    if cfg.pop("_pending_restart", None):
        cfgmod.save()

    host = cfg["server"].get("host") or "127.0.0.1"
    port = int(cfg["server"].get("port") or 0)
    if not port:
        port = cfgmod.random_free_port(host)
        cfg["server"]["port"] = port
        cfgmod.save()

    # 重启场景：旧进程可能仍短暂占用端口，最多等待 10 秒
    deadline = time.time() + 10
    while not _port_free(host, port) and time.time() < deadline:
        time.sleep(0.4)
    if not _port_free(host, port):
        newp = cfgmod.random_free_port(host)
        print(f"[!] 端口 {port} 被占用，自动改用随机新端口 {newp}")
        cfg["server"]["port"] = newp
        port = newp
        cfgmod.save()

    import uvicorn
    from app import server

    key = cfg["server"]["key"]
    line = "=" * 62
    print(line)
    print("  LLM 智能调度网关 已启动")
    print(f"  管理面板 : http://127.0.0.1:{port}/")
    print(f"  接口地址 : http://127.0.0.1:{port}/v1  (OpenAI 兼容)")
    print(f"  API Key  : {key}")
    print("  停止服务 : 关闭窗口 / 托盘右键退出 / Ctrl+C")
    print(line)

    url = f"http://127.0.0.1:{port}/"
    # 无窗口模式下 uvicorn 默认日志格式化器会探测 tty（isatty），即使上面
    # 已重定向 stdout，仍可能在极端时序下拿到 None；直接禁用其日志配置。
    _log_cfg = dict(uvicorn.config.LOGGING_CONFIG)
    _log_cfg["formatters"] = {
        "default": {"()": "uvicorn.logging.DefaultFormatter", "fmt": "%(levelprefix)s %(message)s", "use_colors": False},
        "access": {"()": "uvicorn.logging.AccessFormatter", "fmt": '%(client_addr)s - "%(request_line)s" %(status_code)s', "use_colors": False},
    }
    conf = uvicorn.Config(server.app, host=host, port=port, log_level="warning", access_log=False, log_config=_log_cfg)

    # ---- 无界面模式：托盘图标常驻，服务跑后台线程 ----
    if args.no_ui:
        srv = uvicorn.Server(conf)
        th = threading.Thread(target=srv.run, daemon=True)
        th.start()
        if not _wait_started(srv):
            print("[!] 服务启动失败，请检查端口占用")
            return

        def _open_panel(*_):
            webbrowser.open(url)

        def _quit_tray(icon, item=None):
            srv.should_exit = True
            try:
                icon.stop()
            except Exception:
                pass

        try:
            import pystray
            menu = pystray.Menu(
                pystray.MenuItem("打开管理面板", _open_panel, default=True),
                pystray.MenuItem("退出", _quit_tray),
            )
            icon = pystray.Icon("llm-gateway", _tray_image(),
                                f"LLM 智能调度网关 · {url}", menu)
            print("[i] 已最小化到系统托盘（右下角图标，右键可退出）")
            icon.run()
        except Exception as e:
            print(f"[!] 系统托盘不可用（{e}）。面板: {url} ，按 Ctrl+C 停止。")
            try:
                webbrowser.open(url)
            except Exception:
                pass
            try:
                while th.is_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
        srv.should_exit = True
        return

    # ---- 浏览器模式 ----
    if args.browser:
        srv = uvicorn.Server(conf)
        th = threading.Thread(target=srv.run, daemon=True)
        th.start()
        if not _wait_started(srv):
            print("[!] 服务启动失败，请检查端口占用")
            return
        webbrowser.open(url)
        print("[i] 已在默认浏览器打开管理面板。Ctrl+C 停止服务。")
        try:
            while th.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            srv.should_exit = True
        return

    # ---- 桌面窗口模式（默认）：服务后台线程 + 原生窗口 + 托盘 ----
    srv = uvicorn.Server(conf)
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    if not _wait_started(srv):
        print("[!] 服务启动失败，请检查端口占用")
        return

    import webview

    exiting = {"v": False}
    ui = {"tray_ok": False, "icon": None}
    window = webview.create_window("LLM 智能调度网关", url, width=1180, height=800,
                                   min_size=(960, 640), background_color="#0a0a0c")

    def _show_window(*_):
        try:
            window.show()
            window.restore()
        except Exception:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def _quit_app(*_):
        exiting["v"] = True
        srv.should_exit = True
        try:
            if ui["icon"]:
                ui["icon"].stop()
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            pass

    def _on_closing():
        # 点 ✕：按用户保存的行为执行；未保存过则弹原生确认框
        # pywebview 语义：closing 处理器返回 False = 取消关闭
        if exiting["v"]:
            return True
        if not ui["tray_ok"]:
            return True            # 无托盘：隐藏不可用，正常退出
        action = (cfg.get("server") or {}).get("close_action") or ""
        if action == "quit":
            srv.should_exit = True
            return True
        if action == "hide":
            try:
                window.hide()
                return False
            except Exception:
                return True
        # 未设置：取消本次关闭，弹原生确认框（隐藏到托盘 / 退出程序 + 记住选择）
        _ask_close_native(window, srv, ui["icon"])
        return False   # 取消关闭，窗口保留

    window.events.closing += _on_closing

    # 托盘图标（独立线程，不阻塞窗口）
    try:
        from pystray import Icon, Menu, MenuItem

        menu = Menu(
            MenuItem("显示主窗口", lambda ic, it: _show_window(), default=True),
            MenuItem("打开管理面板（浏览器）", lambda ic, it: webbrowser.open(url)),
            Menu.SEPARATOR,
            MenuItem("退出", lambda ic, it: _quit_app(ic)),
        )
        icon = Icon("llm-gateway", _tray_image(), f"LLM 智能调度网关 · {url}", menu)
        icon.run_detached()
        ui["tray_ok"] = True
        ui["icon"] = icon
        print("[i] 托盘图标已启用：双击/左键 = 显示主窗口，右键 = 菜单；点窗口 ✕ 默认隐藏到托盘")
    except Exception as e:
        print(f"[!] 托盘不可用（{e}）：点窗口 ✕ 将直接退出服务")

    # 注入给 /api/window/*（前端确认框的隐藏/退出）
    server.window_ref = window
    server.srv_ref = srv
    server.tray_ref = ui["icon"] if ui["tray_ok"] else None

    webview.start()
    srv.should_exit = True
    try:
        if ui["icon"]:
            ui["icon"].stop()
    except Exception:
        pass


if __name__ == "__main__":
    main()
