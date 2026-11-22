# -*- coding: utf-8 -*-
"""本地桌面工具骨架 —— 只为标准库，可直接改成自己的工具。

跑起来:
    python app.py            桌面窗口（没有 pywebview 就自动开浏览器）
    python app.py --browser  强制浏览器模式

已有的东西:
    · 单实例检测 + 端口重试（8770 起往上试 10 个）
    · 数据目录容器化（可用 MYAPP_DATA_ROOT 覆盖）
    · 统一的 JSON 响应形状 {"ok": true/false, ...}
    · 数值清洗 num()，避免 NaN / None 一路传到下游
    · 配置原子写（临时文件 + os.replace）
    · 前端错误上报 POST /api/log
扩展方式: 搜 "在这里扩展"，按同样的形状加路由即可。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_ID = "myapp"
APP_VER = "0.1.0"
APP_DIR = Path(__file__).resolve().parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))   # 打包后资源在 _MEIPASS
UI_FILE = RES_DIR / "ui" / "index.html"
PORT_FROM, PORT_TRIES = 8770, 10


# ------------------------------------------------------------------ 数据目录
def detect_data_root() -> Path:
    env = os.environ.get("MYAPP_DATA_ROOT")
    if env:
        return Path(env)
    for drive in ("E:", "D:"):
        if Path(drive + "\\").exists():
            return Path(drive + "\\MyAppData")
    return Path(os.path.expanduser("~")) / "Pictures" / "MyAppData"


DATA_ROOT = detect_data_root()
CFG_FILE = DATA_ROOT / "config.json"
LOG_FILE = DATA_ROOT / "app.log"
for _d in (DATA_ROOT,):
    _d.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{__import__('time').strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ 配置
def default_cfg() -> dict:
    return {"items_dir": str(DATA_ROOT / "items"), "theme": "light"}


def load_cfg() -> dict:
    try:
        return {**default_cfg(), **json.loads(CFG_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return default_cfg()


def save_cfg(cfg: dict) -> None:
    tmp = CFG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    os.replace(tmp, CFG_FILE)      # 原子替换，断电也不会留半截文件


def num(v, default, lo=None, hi=None):
    """把前端来的任何东西变成确定的数：None / "" / NaN / "abc" 都回默认值。"""
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return default
    except (TypeError, ValueError):
        return default
    if lo is not None and f < lo:
        return lo
    if hi is not None and f > hi:
        return hi
    return f


# ------------------------------------------------------------------ 业务逻辑
def list_items() -> list[dict]:
    """骨架示例：列出一个目录里的文件。换成你自己的数据源。"""
    d = Path(load_cfg()["items_dir"])
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file():
            st = f.stat()
            out.append({"name": f.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return out[:200]


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_ID}/{APP_VER}"

    def log_message(self, fmt, *args):     # 静音默认访问日志
        pass

    # ---- 响应助手
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400) -> None:
        self._json({"ok": False, "error": msg}, code)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ---- 路由
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        path, qs = u.path, urllib.parse.parse_qs(u.query)
        try:
            if path in ("/", "/index.html"):
                if not UI_FILE.is_file():
                    return self._err("界面文件缺失: ui/index.html", 500)
                return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")

            if path == "/api/status":
                return self._json({"ok": True, "app": APP_ID, "ver": APP_VER,
                                   "dataRoot": str(DATA_ROOT),
                                   "count": len(list_items())})

            if path == "/api/items":
                return self._json({"ok": True, "items": list_items()})

            if path.startswith("/ui/"):
                base = (RES_DIR / "ui").resolve()
                fp = (base / path[4:]).resolve()
                try:
                    fp.relative_to(base)
                except ValueError:
                    return self._err("非法路径", 403)
                if not fp.is_file():
                    return self._err("文件不存在", 404)
                ct = {".css": "text/css; charset=utf-8",
                      ".js": "application/javascript; charset=utf-8",
                      ".png": "image/png", ".jpg": "image/jpeg",
                      ".svg": "image/svg+xml"}.get(fp.suffix.lower(),
                                                   "application/octet-stream")
                return self._send(200, fp.read_bytes(), ct)

            return self._err("未找到", 404)
        except Exception as e:
            log(f"GET {self.path} 失败: {e}\n{traceback.format_exc()}")
            return self._err(str(e), 500)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        body = self._body()
        try:
            if path == "/api/save":
                cfg = load_cfg()
                cfg["theme"] = "dark" if body.get("theme") == "dark" else "light"
                save_cfg(cfg)
                return self._json({"ok": True, "cfg": cfg})

            if path == "/api/open-folder":
                os.startfile(str(DATA_ROOT))       # 仅 Windows
                return self._json({"ok": True})

            if path == "/api/log":                 # 前端错误上报
                log(f"前端上报：{str(body.get('msg'))[:500]}")
                return self._json({"ok": True})

            # 在这里扩展：加新接口照上面的形状抄

            return self._err("未找到", 404)
        except Exception as e:
            log(f"POST {path} 失败: {e}\n{traceback.format_exc()}")
            return self._err(str(e), 500)


# ------------------------------------------------------------------ 启动
def already_running(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_server() -> tuple[ThreadingHTTPServer | None, int]:
    host = "127.0.0.1"      # 只监听本机；要让局域网能访问再改成 0.0.0.0
    for p in range(PORT_FROM, PORT_FROM + PORT_TRIES):
        try:
            return ThreadingHTTPServer((host, p), Handler), p
        except OSError:
            continue
    return None, 0


def set_dpi_aware() -> None:
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def open_window(url: str) -> bool:
    """有 pywebview 就开原生窗口，没有返回 False 让调用方退化成浏览器。"""
    try:
        import webview
        webview.create_window(f"{APP_ID} {APP_VER}", url, width=1280, height=860)
        webview.start()
        return True
    except Exception as e:
        log(f"窗口模式不可用（{e}）")
        return False


def main() -> None:
    browser_only = "--browser" in sys.argv
    if already_running(PORT_FROM) and not browser_only:
        url = f"http://127.0.0.1:{PORT_FROM}/"
        log(f"已在运行：{url}")
        webbrowser.open(url)
        return

    server, port = start_server()
    if server is None:
        log("没有可用端口")
        return
    url = f"http://127.0.0.1:{port}/"
    log(f"已启动：{url}  （数据目录 {DATA_ROOT}）")

    if browser_only:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return

    threading.Thread(target=server.serve_forever, daemon=True).start()
    set_dpi_aware()
    if open_window(url):
        return
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"启动失败: {e}\n{traceback.format_exc()}")
        raise
