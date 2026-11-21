# -*- coding: utf-8 -*-
"""
壁纸工坊 · 动态壁纸引擎
把画面渲染到桌面图标下面（WorkerW 层），实现视频壁纸 / 特效壁纸。

用法:
    pythonw dynwall.py --video "E:\\Wallpapers\\Dynamic\\xxx.mp4"
    pythonw dynwall.py --scene "E:\\Wallpapers\\Scenes\\xxx.json"
    pythonw dynwall.py --video ... --stop-file "E:\\Wallpapers\\Dynamic\\.stop"
    pythonw dynwall.py --video ... --parent none      # 普通窗口（调试用）
    pythonw dynwall.py --scene ... --max-seconds 6    # 跑 6 秒自动退出（自检用）
退出: 出现 stop 文件 / --max-seconds 到点 / 直接结束进程。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes as w
from pathlib import Path

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import fx  # noqa: E402

# ------------------------------------------------------------------ Win32
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
HINSTANCE = ctypes.c_void_p
HCURSOR = ctypes.c_void_p
HBRUSH = ctypes.c_void_p
HICON = ctypes.c_void_p

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, ctypes.c_uint, WPARAM, LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", w.LPCWSTR),
        ("lpszClassName", w.LPCWSTR),
        ("hIconSm", HICON),
    ]


user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = ctypes.c_ushort
user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.HWND, w.HMENU, HINSTANCE, w.LPVOID]
user32.CreateWindowExW.restype = w.HWND
user32.DefWindowProcW.argtypes = [w.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SetParent.argtypes = [w.HWND, w.HWND]
user32.SetParent.restype = w.HWND
user32.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
user32.FindWindowW.restype = w.HWND
user32.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
user32.FindWindowExW.restype = w.HWND
user32.SendMessageTimeoutW.argtypes = [w.HWND, ctypes.c_uint, WPARAM, LPARAM,
                                       ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = LRESULT
user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [w.HWND, ctypes.c_void_p]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DestroyWindow.argtypes = [w.HWND]
user32.IsWindow.argtypes = [w.HWND]
kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
kernel32.GetModuleHandleW.restype = HINSTANCE

SM_CXSCREEN, SM_CYSCREEN = 0, 1
SW_SHOWNOACTIVATE = 4
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
WM_DESTROY = 0x0002
PM_REMOVE = 0x0001


def log(msg: str) -> None:
    try:
        with open(APP_DIR / "dynwall.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def dpi_aware() -> None:
    """4K 屏 + 200% 缩放时，DPI 不感知会让窗口只有实际像素的一半 —— 必须先声明感知"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ------------------------------------------------------------------ WorkerW
def find_workerw() -> int:
    """让 Progman 生成 WorkerW，返回承载壁纸的窗口句柄"""
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return 0
    result = ctypes.c_size_t(0)
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, ctypes.byref(result))
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 1, 0, 1000, ctypes.byref(result))
    time.sleep(0.35)

    worker = None
    hwnd = 0
    while True:
        hwnd = user32.FindWindowExW(None, hwnd, "WorkerW", None)
        if not hwnd:
            break
        view = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
        if view:
            worker = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            break

    if not worker:
        view = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
        if view:
            worker = user32.FindWindowExW(None, progman, "WorkerW", None)

    if not worker:
        hwnd = 0
        while True:
            hwnd = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if not hwnd:
                break
            if not user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
                worker = hwnd
                break

    log(f"progman={progman} workerw={worker}")
    return worker or progman


# ------------------------------------------------------------------ 主流程
def parse_args(argv: list[str]) -> dict:
    out = {"video": None, "scene": None, "stop_file": None,
           "parent": "worker", "max_seconds": 0}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--video", "--scene", "--stop-file", "--parent", "--max-seconds") and i + 1 < len(argv):
            key = a[2:].replace("-", "_")
            out[key] = argv[i + 1]
            i += 2
        else:
            i += 1
    return out


def load_cfg(args: dict) -> dict:
    if args.get("scene"):
        p = Path(args["scene"])
        cfg = json.loads(p.read_text(encoding="utf-8"))
        cfg.setdefault("bg", {})
        return cfg
    video = args.get("video")
    return {"name": Path(video).stem if video else "video",
            "bg": {"type": "video", "src": video, "motion_speed": 1.0},
            "fx": [], "mouse": {}, "clock": {"on": False}, "text": {"on": False}}


def main() -> int:
    dpi_aware()
    args = parse_args(sys.argv[1:])
    if not args["video"] and not args["scene"]:
        print("缺少 --video 或 --scene", file=sys.stderr)
        return 2
    if args["scene"] and not os.path.isfile(args["scene"]):
        log(f"bad scene: {args['scene']}")
        return 2
    if args["video"] and not os.path.isfile(args["video"]):
        log(f"bad video: {args['video']}")
        return 2

    stop_file = args["stop_file"]
    if stop_file and os.path.exists(stop_file):
        try:
            os.remove(stop_file)
        except Exception:
            pass

    sw, sh = user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)
    log(f"start screen={sw}x{sh} mode={'scene' if args['scene'] else 'video'}")

    hinst = kernel32.GetModuleHandleW(None)
    class_name = "WallpaperStudioDyn"

    @WNDPROC
    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.style = 0
    wc.lpfnWndProc = wndproc
    wc.hInstance = hinst
    wc.hbrBackground = None
    wc.lpszClassName = class_name
    user32.RegisterClassExW(ctypes.byref(wc))

    parent = None
    if args["parent"] == "none":
        style = WS_POPUP | WS_VISIBLE
    else:
        parent = find_workerw()
        style = WS_CHILD | WS_VISIBLE

    hwnd = user32.CreateWindowExW(0, class_name, "WallpaperStudio",
                                  style, 0, 0, sw, sh,
                                  parent, None, hinst, None)
    if not hwnd:
        log(f"CreateWindow failed err={ctypes.get_last_error()}")
        return 3

    user32.SetWindowPos(hwnd, w.HWND(0 if parent else -1), 0, 0, sw, sh,
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

    hdc = user32.GetDC(hwnd)
    if not hdc:
        log("GetDC failed")
        return 4

    cfg = load_cfg(args)
    try:
        renderer = fx.Renderer(hdc, sw, sh, cfg, log)
        renderer.start()
    except Exception as e:
        log(f"初始化失败: {e}")
        user32.ReleaseDC(hwnd, hdc)
        return 5

    is_video = isinstance(renderer.bg, fx.VideoBg)
    max_seconds = float(args.get("max_seconds") or 0)
    msg = w.MSG()
    frames = 0
    t0 = time.time()
    last = t0
    running = True
    target = 1.0 / 30.0
    try:
        while running:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if stop_file and os.path.exists(stop_file):
                log("stop file found")
                break
            if not user32.IsWindow(hwnd):
                log("window gone")
                break
            if max_seconds and time.time() - t0 >= max_seconds:
                log("max seconds reached")
                break

            now = time.time()
            dt = min(0.12, now - last)
            last = now
            if not renderer.frame(dt):
                break
            frames += 1

            if not is_video:
                # 图片/纯色背景没有解码器限速，自己控节奏
                rest = target - (time.time() - now)
                if rest > 0:
                    time.sleep(rest)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log(f"loop error: {e}")
    finally:
        try:
            renderer.close()
        except Exception:
            pass
        user32.ReleaseDC(hwnd, hdc)
        if user32.IsWindow(hwnd):
            user32.DestroyWindow(hwnd)
        dt = max(0.001, time.time() - t0)
        log(f"exit frames={frames} fps={frames / dt:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
