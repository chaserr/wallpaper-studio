# -*- coding: utf-8 -*-
"""
壁纸工坊 · 特效层引擎（fx）

纯 ctypes + GDI 实现，零第三方依赖。负责把「背景 + 粒子特效 + 鼠标互动 + 时钟文字」
合成到一块窗口 DC 上，由 dynwall.py 负责窗口与消息循环。

设计要点：
  * 粒子不是逐像素算的（Python 太慢），而是预渲染成带 alpha 的小位图（sprite），
    每帧用 msimg32.AlphaBlend 贴上去，几百个粒子也能跑满 30fps。
  * 背景支持：视频（ffmpeg 解码）、图片（ffmpeg 解一帧 + 预缩放 + 缓慢推拉）、纯色。
  * 互动：鼠标跟随光晕、点击涟漪（只在点桌面时触发，点别的窗口不会乱放）。
"""
from __future__ import annotations

import ctypes
import math
import os
import random
import re
import subprocess
import time
from ctypes import wintypes as w

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
msimg32 = ctypes.WinDLL("msimg32")

c_int = ctypes.c_int
c_uint = ctypes.c_uint
AC_SRC_OVER, AC_SRC_ALPHA = 0, 1
SRCCOPY = 0x00CC0020
HALFTONE, COLORONCOLOR = 4, 3
DIB_RGB_COLORS = 0
TRANSPARENT = 1


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", _BMIH), ("bmiColors", ctypes.c_uint32 * 3)]


class _BLENDFUNC(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


gdi32.CreateDIBSection.argtypes = [w.HDC, ctypes.POINTER(_BMI), ctypes.c_uint,
                                   ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
gdi32.CreateDIBSection.restype = w.HBITMAP
gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.StretchBlt.argtypes = [w.HDC, c_int, c_int, c_int, c_int,
                             w.HDC, c_int, c_int, c_int, c_int, w.DWORD]
gdi32.StretchBlt.restype = w.BOOL
gdi32.StretchDIBits.argtypes = [w.HDC, c_int, c_int, c_int, c_int, c_int, c_int,
                                c_int, c_int, ctypes.c_void_p, ctypes.POINTER(_BMI),
                                ctypes.c_uint, w.DWORD]
gdi32.StretchDIBits.restype = c_int
gdi32.BitBlt.argtypes = [w.HDC, c_int, c_int, c_int, c_int,
                         w.HDC, c_int, c_int, w.DWORD]
gdi32.BitBlt.restype = w.BOOL
gdi32.SetStretchBltMode.argtypes = [w.HDC, c_int]
gdi32.SetBrushOrgEx.argtypes = [w.HDC, c_int, c_int, ctypes.c_void_p]
gdi32.CreateSolidBrush.argtypes = [w.COLORREF]
gdi32.CreateSolidBrush.restype = w.HBRUSH
gdi32.CreateFontW.argtypes = [c_int, c_int, c_int, c_int, c_int, w.DWORD, w.DWORD, w.DWORD,
                              w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR]
gdi32.CreateFontW.restype = w.HFONT
gdi32.SetTextColor.argtypes = [w.HDC, w.COLORREF]
gdi32.SetBkMode.argtypes = [w.HDC, c_int]
user32.FillRect.argtypes = [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH]
user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = w.HDC
user32.DrawTextW.argtypes = [w.HDC, w.LPCWSTR, c_int, ctypes.POINTER(w.RECT), c_uint]
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.WindowFromPoint.argtypes = [w.POINT]
user32.WindowFromPoint.restype = w.HWND
user32.GetParent.argtypes = [w.HWND]
user32.GetParent.restype = w.HWND
user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c_int]
user32.GetAsyncKeyState.argtypes = [c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
msimg32.AlphaBlend.argtypes = [w.HDC, c_int, c_int, c_int, c_int,
                               w.HDC, c_int, c_int, c_int, c_int, _BLENDFUNC]
msimg32.AlphaBlend.restype = w.BOOL

VK_LBUTTON = 0x01
DESKTOP_CLASSES = ("SysListView32", "SHELLDLL_DefView", "WorkerW", "Progman")


def _bmi(width: int, height: int) -> _BMI:
    b = _BMI()
    b.bmiHeader.biSize = ctypes.sizeof(_BMIH)
    b.bmiHeader.biWidth = width
    b.bmiHeader.biHeight = -height          # 负数 = 自上而下，与 BGRA 缓冲一致
    b.bmiHeader.biPlanes = 1
    b.bmiHeader.biBitCount = 32
    b.bmiHeader.biCompression = 0           # BI_RGB
    return b


# ------------------------------------------------------------------ 位图
class Bitmap:
    """一块 32 位 BGRA、alpha 预乘的 DIB，可被 AlphaBlend 当贴图用"""

    __slots__ = ("w", "h", "hbm", "hdc", "ptr", "own_dc")

    def __init__(self, hdc: int, width: int, height: int):
        self.w, self.h = int(width), int(height)
        bmi = _bmi(self.w, self.h)
        ptr = ctypes.c_void_p()
        self.hbm = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                          ctypes.byref(ptr), None, 0)
        self.hdc = gdi32.CreateCompatibleDC(hdc)
        gdi32.SelectObject(self.hdc, self.hbm)
        self.ptr = ptr
        self.own_dc = True

    def fill(self, b: int, g: int, r: int, a: int = 255) -> None:
        buf = bytes((b, g, r, a)) * (self.w * self.h)
        ctypes.memmove(self.ptr, buf, len(buf))

    def write(self, buf: bytes | bytearray) -> None:
        ctypes.memmove(self.ptr, bytes(buf), min(len(buf), self.w * self.h * 4))

    def read(self) -> bytes:
        return ctypes.string_at(self.ptr, self.w * self.h * 4)

    def release(self) -> None:
        try:
            if self.own_dc:
                gdi32.DeleteDC(self.hdc)
            gdi32.DeleteObject(self.hbm)
        except Exception:
            pass
        self.ptr = None


def hex_rgb(s: str, default=(255, 255, 255)) -> tuple[int, int, int]:
    s = (s or "").strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:
        return default


# ------------------------------------------------------------------ 精灵（sprite）
def _sprite_dot(hdc, size: int, rgb, power: float = 2.2) -> Bitmap:
    bm = Bitmap(hdc, size, size)
    r_, g_, b_ = rgb
    c = (size - 1) / 2.0
    rad = max(1.0, size / 2.0)
    buf = bytearray(size * size * 4)
    for y in range(size):
        dy = (y - c) / rad
        for x in range(size):
            d = math.hypot((x - c) / rad, dy)
            if d >= 1.0:
                continue
            aa = (1.0 - d) ** power
            i = (y * size + x) * 4
            buf[i] = int(b_ * aa)
            buf[i + 1] = int(g_ * aa)
            buf[i + 2] = int(r_ * aa)
            buf[i + 3] = int(255 * aa)
    bm.write(buf)
    return bm


def _sprite_streak(hdc, rgb, length: int = 64, thick: int = 3, angle_deg: float = 0.0) -> Bitmap:
    """雨丝：斜向细线，两头淡出（角度直接烘进贴图，AlphaBlend 不支持旋转）"""
    rad = math.radians(angle_deg)
    dx, dy = math.sin(rad), math.cos(rad)
    pad = thick * 2 + 1
    w = int(abs(dx) * length) + pad * 2
    h = int(dy * length) + pad * 2
    bm = Bitmap(hdc, max(3, w), max(3, h))
    r_, g_, b_ = rgb
    buf = bytearray(bm.w * bm.h * 4)
    steps = max(24, int(length * 1.6))
    for i in range(steps + 1):
        t = i / steps
        cx = pad + dx * length * t
        cy = pad + dy * length * t
        a0 = math.sin(math.pi * t) ** 0.65
        if a0 <= 0.01:
            continue
        for oy in range(-2, 3):
            for ox in range(-2, 3):
                d2 = ox * ox + oy * oy
                aa = a0 * math.exp(-d2 / 1.6)
                px, py = int(cx + ox), int(cy + oy)
                if not (0 <= px < bm.w and 0 <= py < bm.h):
                    continue
                idx = (py * bm.w + px) * 4
                av = int(255 * aa)
                if buf[idx + 3] >= av:
                    continue
                buf[idx] = int(b_ * aa)
                buf[idx + 1] = int(g_ * aa)
                buf[idx + 2] = int(r_ * aa)
                buf[idx + 3] = av
    bm.write(buf)
    return bm


def _sprite_ellipse(hdc, size: int, rgb, a_ratio: float = 0.42, rot: float = 0.0,
                    soft: float = 0.55) -> Bitmap:
    """花瓣 / 落叶：带旋转的椭圆"""
    bm = Bitmap(hdc, size, size)
    r_, g_, b_ = rgb
    c = (size - 1) / 2.0
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    ax = size / 2.0
    ay = max(1.5, size * a_ratio / 2.0)
    buf = bytearray(size * size * 4)
    for y in range(size):
        dy = y - c
        for x in range(size):
            dx = x - c
            u = (dx * cos_r + dy * sin_r) / ax
            v = (-dx * sin_r + dy * cos_r) / ay
            d = u * u + v * v
            if d >= 1.0:
                continue
            aa = min(1.0, ((1.0 - d) ** 0.5) / max(0.15, soft))
            # 头部稍亮，模拟花瓣的浅色边
            if v < -0.25:
                aa *= 0.72
            i = (y * size + x) * 4
            buf[i] = int(b_ * aa)
            buf[i + 1] = int(g_ * aa)
            buf[i + 2] = int(r_ * aa)
            buf[i + 3] = int(255 * aa)
    bm.write(buf)
    return bm


def _sprite_spark(hdc, size: int, rgb) -> Bitmap:
    """十字星芒，用于萤火虫 / 星光"""
    bm = Bitmap(hdc, size, size)
    r_, g_, b_ = rgb
    c = (size - 1) / 2.0
    buf = bytearray(size * size * 4)
    for y in range(size):
        dy = abs(y - c) / c
        for x in range(size):
            dx = abs(x - c) / c
            core = max(0.0, 1.0 - math.hypot(dx, dy) * 1.6)
            ray = max(0.0, 1.0 - min(dx, dy) * 3.2) * max(0.0, 1.0 - (dx + dy) * 0.55)
            aa = min(1.0, core + ray * 0.75)
            if aa <= 0.003:
                continue
            i = (y * size + x) * 4
            buf[i] = int(b_ * aa)
            buf[i + 1] = int(g_ * aa)
            buf[i + 2] = int(r_ * aa)
            buf[i + 3] = int(255 * aa)
    bm.write(buf)
    return bm


def _sprite_ring(hdc, diam: int, rgb, thick: int = 7) -> Bitmap:
    """涟漪圆环（只画环带，省时间）"""
    bm = Bitmap(hdc, diam + 2, diam + 2)
    r_, g_, b_ = rgb
    c = (diam + 1) / 2.0
    buf = bytearray((diam + 2) * (diam + 2) * 4)
    rad = diam / 2.0
    steps = max(180, int(diam * 2))
    for i in range(steps):
        ang = math.pi * 2 * i / steps
        ca, sa = math.cos(ang), math.sin(ang)
        for k in range(-thick, thick + 1):
            rr = rad - abs(k)
            if rr <= 0:
                continue
            x = int(c + rr * ca)
            y = int(c + rr * sa)
            if not (0 <= x < diam + 2 and 0 <= y < diam + 2):
                continue
            aa = (1.0 - abs(k) / thick) ** 1.4
            idx = (y * (diam + 2) + x) * 4
            if buf[idx + 3] >= int(255 * aa):
                continue
            buf[idx] = int(b_ * aa)
            buf[idx + 1] = int(g_ * aa)
            buf[idx + 2] = int(r_ * aa)
            buf[idx + 3] = int(255 * aa)
    bm.write(buf)
    return bm


class SpriteSet:
    """某种颜色下的一套贴图"""

    def __init__(self, hdc, rgb, rain_angle: float = 12.0):
        self.rgb = rgb
        self.dot = _sprite_dot(hdc, 32, rgb)
        self.dot_big = _sprite_dot(hdc, 64, rgb, 1.8)
        self.streak = _sprite_streak(hdc, rgb, 64, 3, rain_angle)
        self.spark = _sprite_spark(hdc, 40, rgb)
        self.petals = [_sprite_ellipse(hdc, 28, rgb, 0.40, rot) for rot in
                       (0, 0.785, 1.571, 2.356, 3.142, 3.927, 4.712, 5.498)]
        self.leaves = [_sprite_ellipse(hdc, 26, rgb, 0.30, rot) for rot in
                       (0, 0.7, 1.4, 2.1, 2.8, 3.5, 4.2, 4.9)]
        self.glow = _sprite_dot(hdc, 160, rgb, 3.0)
        self.rings = {}
        self._hdc = hdc

    def ring(self, diam: int, thick: int = 7) -> Bitmap:
        key = (diam // 8 * 8, thick)
        bm = self.rings.get(key)
        if bm is None:
            bm = _sprite_ring(self._hdc, max(24, key[0]), self.rgb, thick)
            self.rings[key] = bm
        return bm

    def release(self):
        for bm in [self.dot, self.dot_big, self.streak, self.spark, self.glow,
                   *self.petals, *self.leaves, *self.rings.values()]:
            bm.release()


# ------------------------------------------------------------------ 参数表
KINDS = {
    "rain":    {"label": "雨丝",   "def": {"count": 220, "speed": 1.0, "size": 1.0,
                                           "alpha": 0.55, "color": "#a8c8ff", "angle": 12}},
    "snow":    {"label": "飘雪",   "def": {"count": 150, "speed": 1.0, "size": 1.0,
                                           "alpha": 0.85, "color": "#ffffff"}},
    "petal":   {"label": "樱花瓣", "def": {"count": 70,  "speed": 1.0, "size": 1.0,
                                           "alpha": 0.90, "color": "#ffc0d4"}},
    "firefly": {"label": "萤火虫", "def": {"count": 45,  "speed": 1.0, "size": 1.0,
                                           "alpha": 0.95, "color": "#ffe08a"}},
    "bubble":  {"label": "气泡",   "def": {"count": 60,  "speed": 1.0, "size": 1.0,
                                           "alpha": 0.55, "color": "#d9f4ff"}},
    "ember":   {"label": "火星",   "def": {"count": 70,  "speed": 1.0, "size": 1.0,
                                           "alpha": 0.90, "color": "#ff9a4d"}},
    "star":    {"label": "星光",   "def": {"count": 90,  "speed": 1.0, "size": 1.0,
                                           "alpha": 0.90, "color": "#ffffff"}},
    "leaf":    {"label": "落叶",   "def": {"count": 40,  "speed": 1.0, "size": 1.0,
                                           "alpha": 0.95, "color": "#e0a556"}},
    # ---- 氛围类（偏「好看」而非「天气」）
    "aurora":  {"label": "极光",   "def": {"count": 90,  "speed": 0.6, "size": 1.6,
                                           "alpha": 0.22, "color": "#5cf0c8"}},
    "bokeh":   {"label": "光斑",   "def": {"count": 26,  "speed": 0.35, "size": 1.8,
                                           "alpha": 0.30, "color": "#ffd9a0"}},
    "warp":    {"label": "星空穿越", "def": {"count": 150, "speed": 1.0, "size": 1.0,
                                            "alpha": 0.85, "color": "#cfe3ff"}},
    "meteor":  {"label": "流星",   "def": {"count": 14,  "speed": 1.0, "size": 1.0,
                                           "alpha": 0.95, "color": "#ffffff", "angle": 32}},
}

DEFAULT_SCENE = {
    "name": "新的特效壁纸",
    "bg": {"type": "color", "src": "", "color": "#0b1020", "color2": "#1b2a4a",
           "motion": "kenburns", "motion_speed": 1.0,
           "strength": 1.0, "blur": 1.0, "focus": 1.0},
    "fx": [{"kind": "rain", **KINDS["rain"]["def"]}],
    "mouse": {"glow": {"on": False, "size": 360, "alpha": 0.35, "color": "#ffd27a"},
              "ripple": {"on": True, "size": 520, "alpha": 0.55, "color": "#ffffff"}},
    "clock": {"on": False, "pos": "lt", "size": 56, "color": "#ffffff",
              "alpha": 0.92, "seconds": False, "only_time": False},
    "text": {"on": False, "value": "", "pos": "lb", "size": 26, "color": "#ffffff",
             "alpha": 0.9},
}


def num(v, default: float, lo: float | None = None, hi: float | None = None) -> float:
    """把任何来源的值（None / "" / NaN / 字符串 / 布尔）安全转成有限浮点。

    场景 JSON 里出现 null 时，float(None) 会直接抛 TypeError 让引擎起来就挂，
    所以所有从配置读数字的地方都必须走这里。
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        f = float(default)
    if f != f or f in (float("inf"), float("-inf")):
        f = float(default)
    if lo is not None and f < lo:
        f = lo
    if hi is not None and f > hi:
        f = hi
    return f


def inum(v, default: int, lo: int | None = None, hi: int | None = None) -> int:
    return int(round(num(v, default, lo, hi)))


def norm_scene(cfg: dict | None) -> dict:
    """补齐缺省值，兼容旧版本配置（含 null 字段的老场景）"""
    cfg = dict(cfg or {})
    out = json_deep_copy(DEFAULT_SCENE)
    if isinstance(cfg.get("name"), str) and cfg["name"].strip():
        out["name"] = cfg["name"].strip()[:40]
    bg = cfg.get("bg") or {}
    if isinstance(bg, dict):
        # 只合并有值的字段：老场景里可能是 null，留着会一路传到 float() 里炸掉
        out["bg"].update({k: bg[k] for k in out["bg"]
                          if k in bg and bg[k] is not None})
    out["bg"]["type"] = str(out["bg"].get("type") or "color")
    out["bg"]["src"] = str(out["bg"].get("src") or "")
    out["bg"]["motion_speed"] = num(out["bg"].get("motion_speed"), 1.0, 0.1, 4.0)
    out["bg"]["strength"] = num(out["bg"].get("strength"), 1.0, 0.0, 3.0)
    out["bg"]["blur"] = num(out["bg"].get("blur"), 1.0, 0.0, 3.0)
    out["bg"]["focus"] = num(out["bg"].get("focus"), 1.0, 0.3, 1.8)
    fx = []
    for item in cfg.get("fx") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in KINDS:
            continue
        merged = {"kind": kind, **KINDS[kind]["def"]}
        merged.update({k: item[k] for k in merged
                       if k in item and item[k] is not None})
        merged["count"] = inum(merged["count"], 0, 0, 400)
        merged["alpha"] = num(merged["alpha"], 0.9, 0.05, 1.0)
        merged["size"] = num(merged["size"], 1.0, 0.3, 3.0)
        merged["speed"] = num(merged["speed"], 1.0, 0.1, 4.0)
        if "angle" in merged:
            merged["angle"] = num(merged["angle"], 12.0, -80.0, 80.0)
        fx.append(merged)
    out["fx"] = fx
    for key in ("mouse", "clock", "text"):
        if isinstance(cfg.get(key), dict):
            for sub, val in cfg[key].items():
                if isinstance(out[key].get(sub), dict) and isinstance(val, dict):
                    out[key][sub].update(val)
                elif sub in out[key]:
                    out[key][sub] = val
    return out


def json_deep_copy(o):
    return _dc(o)


def _dc(o):
    if isinstance(o, dict):
        return {k: _dc(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_dc(v) for v in o]
    return o


# ------------------------------------------------------------------ 背景
def find_ffmpeg() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (getattr(os.sys, "_MEIPASS", here), here):
        d = os.path.join(base, "vendor", "imageio_ffmpeg", "binaries")
        if os.path.isdir(d):
            cand = sorted(f for f in os.listdir(d) if f.lower().startswith("ffmpeg"))
            if cand:
                return os.path.join(d, cand[0])
    for p in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(p, "ffmpeg.exe")
        if os.path.isfile(exe):
            return exe
    return ""


def probe_size(ffmpeg: str, path: str) -> tuple[int, int]:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True,
                             text=True, timeout=20, encoding="utf-8", errors="ignore").stderr
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 1920, 1080


class VideoBg:
    """视频背景：ffmpeg 解码 → 直接读进 DIB → 一次 BitBlt/StretchBlt 上屏"""

    DECODE_MAX_W = 2560          # 4K 屏上把解码宽度压到 2560，避免每秒 1GB 的管道

    def __init__(self, hdc, ffmpeg, path, sw, sh):
        self.sw, self.sh = sw, sh
        self.dw, self.dh = sw, sh
        if sw > self.DECODE_MAX_W:
            self.dw = self.DECODE_MAX_W
            self.dh = int(round(sh * self.dw / sw / 2)) * 2
        self.hdc = hdc
        self.bm = Bitmap(hdc, self.dw, self.dh)
        self.need = self.dw * self.dh * 4
        self.bmi = _bmi(sw, sh)
        vf = (f"scale={self.dw}:{self.dh}:force_original_aspect_ratio=increase,"
              f"crop={self.dw}:{self.dh}")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-re", "-stream_loop", "-1",
               "-i", path, "-an", "-sn", "-vf", vf, "-r", "30",
               "-f", "rawvideo", "-pix_fmt", "bgra", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     bufsize=1024 * 1024, creationflags=0x08000000)

    def ready(self) -> bool:
        return self.proc.poll() is None

    def frame(self, hdc) -> bool:
        base = self.bm.ptr.value
        off = 0
        while off < self.need:
            chunk = self.proc.stdout.read(self.need - off)
            if not chunk:
                return False
            ctypes.memmove(base + off, chunk, len(chunk))
            off += len(chunk)
        if self.dw == self.sw and self.dh == self.sh:
            gdi32.BitBlt(hdc, 0, 0, self.sw, self.sh, self.bm.hdc, 0, 0, SRCCOPY)
        else:
            gdi32.SetStretchBltMode(hdc, COLORONCOLOR)
            gdi32.StretchBlt(hdc, 0, 0, self.sw, self.sh, self.bm.hdc,
                             0, 0, self.dw, self.dh, SRCCOPY)
        # 大块 blit 会被驱动延后执行，不 flush 的话它会盖掉同帧后面画的粒子/时钟
        gdi32.GdiFlush()
        return True

    def release(self):
        try:
            self.proc.kill()
        except Exception:
            pass
        self.bm.release()


class ImageBg:
    """图片背景：先一次性高质量缩放到 1.25 倍屏，再逐帧取窗口做缓慢推拉"""

    ZMAX = 1.25

    def __init__(self, hdc, ffmpeg, path, sw, sh):
        self.sw, self.sh = sw, sh
        self.hdc = hdc
        self.dw, self.dh = int(sw * self.ZMAX), int(sh * self.ZMAX)
        self.bm = Bitmap(hdc, self.dw, self.dh)
        self.ok = False
        try:
            raw = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", path,
                                  "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgra", "-"],
                                 capture_output=True, timeout=60).stdout
            vw, vh = probe_size(ffmpeg, path)
            if len(raw) >= vw * vh * 4:
                src = Bitmap(hdc, vw, vh)
                src.write(raw[:vw * vh * 4])
                # cover 裁切
                if vw / vh > self.dw / self.dh:
                    ch = vh
                    cw = int(vh * self.dw / self.dh)
                    sx, sy = (vw - cw) // 2, 0
                else:
                    cw = vw
                    ch = int(vw * self.dh / self.dw)
                    sx, sy = 0, (vh - ch) // 2
                gdi32.SetStretchBltMode(self.bm.hdc, HALFTONE)
                gdi32.SetBrushOrgEx(self.bm.hdc, 0, 0, None)
                gdi32.StretchBlt(self.bm.hdc, 0, 0, self.dw, self.dh,
                                 src.hdc, sx, sy, cw, ch, SRCCOPY)
                src.release()
                self.ok = True
        except Exception:
            self.ok = False

    def frame(self, hdc, t: float, speed: float) -> None:
        if not self.ok:
            return
        # 平滑来回推拉：z 从 1.0 到 1.2
        period = 46.0 / max(0.1, speed)
        ph = (t % period) / period
        ease = 0.5 - 0.5 * math.cos(2 * math.pi * ph * 2 % (2 * math.pi))
        ease = 0.5 - 0.5 * math.cos(4 * math.pi * ph)
        z = 1.0 + 0.2 * (ease * 0.5 + 0.5) * 0.999          # 1.0 → 1.2
        ww = int(self.dw / z)
        wh = int(self.dh / z)
        # 缓慢平移
        px = (self.dw - ww) * (0.5 + 0.32 * math.sin(2 * math.pi * (t / (period * 1.7))))
        py = (self.dh - wh) * (0.5 + 0.32 * math.cos(2 * math.pi * (t / (period * 2.3))))
        gdi32.SetStretchBltMode(hdc, COLORONCOLOR)
        gdi32.StretchBlt(hdc, 0, 0, self.sw, self.sh, self.bm.hdc,
                         int(px), int(py), ww, wh, SRCCOPY)

    def release(self):
        self.bm.release()


class ParallaxBg:
    """照片视差背景：一张照片拆成「远 / 近」两层，鼠标一动就有立体感。

    · 近层 = 原图，中心清晰、四周羽化（alpha 遮罩），跟随鼠标位移大
    · 远层 = 同一张图高斯模糊，位移小，还会极慢地呼吸缩放
    遮罩和模糊都交给 ffmpeg 做（像素级运算在 C 里跑），Python 只负责贴图。
    """

    ZMAX = 1.26                 # 图层比屏幕大 26%，留出位移余量
    LAYER_MAX_W = 3840

    def __init__(self, hdc, ffmpeg, path, sw, sh, strength=1.0, blur=1.0, focus=1.0):
        self.sw, self.sh = sw, sh
        self.hdc = hdc
        self.ok = False
        self.strength = max(0.0, min(3.0, float(strength or 1.0)))
        self.blur = max(0.0, min(3.0, float(blur or 1.0)))
        self.focus = max(0.3, min(1.8, float(focus or 1.0)))
        self.ex = self.ey = 0.0          # 缓动后的鼠标（-1 ~ 1）
        self.dw = min(int(sw * self.ZMAX), self.LAYER_MAX_W)
        self.dh = max(2, int(round(self.dw * sh / sw / 2)) * 2)
        self.ww = max(2, int(round(self.dw / self.ZMAX)))
        self.wh = max(2, int(round(self.dh / self.ZMAX)))
        self.far = Bitmap(hdc, self.dw, self.dh)
        self.near = Bitmap(hdc, self.dw, self.dh)
        self.far_ok = self.near_ok = False
        sigma = max(1.5, min(60.0, 9.0 * self.blur * (sh / 1080.0)))
        self._build_far(ffmpeg, path, sigma)
        self._build_near(ffmpeg, path)
        self.ok = self.far_ok or self.near_ok

    # ---- 远层：模糊
    def _build_far(self, ffmpeg, path, sigma: float) -> None:
        fc = (f"scale={self.dw}:{self.dh}:force_original_aspect_ratio=increase,"
              f"crop={self.dw}:{self.dh},gblur=sigma={sigma:.2f}")
        raw = self._run(ffmpeg, ["-i", path, "-vf", fc])
        if raw and len(raw) >= self.dw * self.dh * 4:
            self.far.write(raw[:self.dw * self.dh * 4])
            self.far_ok = True

    # ---- 近层：清晰 + 中心 alpha 遮罩（预乘）
    def _build_near(self, ffmpeg, path) -> None:
        mask = None
        try:
            import tempfile
            fd, mask = tempfile.mkstemp(suffix=".pgm", prefix="ws_mask_")
            with os.fdopen(fd, "wb") as f:
                f.write(_radial_mask_pgm(240, 135, self.focus))
            fc = (f"[1:v]scale={self.dw}:{self.dh}:flags=bicubic,format=gray[mk];"
                  f"[0:v]scale={self.dw}:{self.dh}:force_original_aspect_ratio=increase,"
                  f"crop={self.dw}:{self.dh},format=rgba[im];"
                  # AlphaBlend 要预乘 alpha；ffmpeg 的 premultiply 滤镜在这里会丢颜色，
                  # 改用 geq 逐像素乘（一次性，2016×1134 约 0.3 秒）
                  f"[im][mk]alphamerge,format=rgba,"
                  f"geq=r='r(X,Y)*alpha(X,Y)/255':g='g(X,Y)*alpha(X,Y)/255':"
                  f"b='b(X,Y)*alpha(X,Y)/255':a='alpha(X,Y)'[v]")
            raw = self._run(ffmpeg, ["-i", path, "-i", mask,
                                     "-filter_complex", fc, "-map", "[v]"])
            if raw and len(raw) >= self.dw * self.dh * 4:
                self.near.write(raw[:self.dw * self.dh * 4])
                self.near_ok = True
        except Exception:
            self.near_ok = False
        finally:
            if mask:
                try:
                    os.unlink(mask)
                except Exception:
                    pass

    @staticmethod
    def _run(ffmpeg, args) -> bytes:
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", *args,
               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgra", "-"]
        try:
            return subprocess.run(cmd, capture_output=True, timeout=90).stdout
        except Exception:
            return b""

    # ---- 逐帧
    def frame(self, hdc, t: float, speed: float = 1.0, mouse=None) -> None:
        if not self.ok:
            return
        if mouse:
            tx = max(-1.0, min(1.0, (mouse[0] / max(1, self.sw) - 0.5) * 2.0))
            ty = max(-1.0, min(1.0, (mouse[1] / max(1, self.sh) - 0.5) * 2.0))
            ease = 0.10 * max(0.2, min(3.0, speed))
            self.ex += (tx - self.ex) * min(1.0, ease)
            self.ey += (ty - self.ey) * min(1.0, ease)

        mx = (self.dw - self.ww) / 2.0
        my = (self.dh - self.wh) / 2.0
        # 位移量按「可移动余量」的比例算，换分辨率不用改参数；近层动得比远层多才像视差
        sxf = self.ex * self.strength * mx * 0.06
        syf = self.ey * self.strength * my * 0.06
        sxn = self.ex * self.strength * mx * 0.22
        syn = self.ey * self.strength * my * 0.22

        if self.far_ok:
            # 远层：极慢呼吸缩放 + 小位移
            breathe = 0.5 - 0.5 * math.cos(t * 0.14 * max(0.2, speed))
            fw = int(self.ww * (1.0 + 0.055 * breathe))
            fh = int(self.wh * (1.0 + 0.055 * breathe))
            sx = (self.dw - fw) / 2.0 + sxf
            sy = (self.dh - fh) / 2.0 + syf
            gdi32.SetStretchBltMode(hdc, COLORONCOLOR)
            gdi32.StretchBlt(hdc, 0, 0, self.sw, self.sh, self.far.hdc,
                             int(sx), int(sy), fw, fh, SRCCOPY)
        else:
            gdi32.SetStretchBltMode(hdc, COLORONCOLOR)
            gdi32.StretchBlt(hdc, 0, 0, self.sw, self.sh, self.near.hdc,
                             int(mx), int(my), self.ww, self.wh, SRCCOPY)

        if self.near_ok:
            sx = mx + sxn
            sy = my + syn
            bf = _BLENDFUNC(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            msimg32.AlphaBlend(hdc, 0, 0, self.sw, self.sh, self.near.hdc,
                               int(sx), int(sy), self.ww, self.wh, bf)
        gdi32.GdiFlush()

    def release(self):
        self.far.release()
        self.near.release()


def _radial_mask_pgm(w: int, h: int, focus: float = 1.0) -> bytes:
    """生成一张径向渐变灰度图（PGM）：中心 255（清晰），边缘 0（露出模糊层）"""
    r0 = 0.16 + 0.34 * focus
    r1 = 0.55 + 0.50 * focus
    span = max(0.05, r1 - r0)
    rows = []
    for y in range(h):
        v = (y + 0.5) / h * 2.0 - 1.0
        row = bytearray(w)
        for x in range(w):
            u = (x + 0.5) / w * 2.0 - 1.0
            r = math.hypot(u * 0.95, v * 0.95)
            k = (r - r0) / span
            k = 0.0 if k < 0.0 else (1.0 if k > 1.0 else k)
            k = k * k * (3.0 - 2.0 * k)          # smoothstep
            row[x] = int(255 * (1.0 - k))
        rows.append(bytes(row))
    head = b"P5\n%d %d\n255\n" % (w, h)
    return head + b"".join(rows)


class ColorBg:
    """纯色 / 竖向双色渐变（用一张 1×256 的渐变贴图拉伸，比逐行填充快）"""

    def __init__(self, hdc, c1, c2, sw, sh):
        self.sw, self.sh = sw, sh
        self.r1 = hex_rgb(c1, (11, 16, 32))
        self.r2 = hex_rgb(c2 or c1, self.r1)
        self.bm = Bitmap(hdc, 2, 256)
        buf = bytearray(2 * 256 * 4)
        for y in range(256):
            k = y / 255.0
            r = int(self.r1[0] + (self.r2[0] - self.r1[0]) * k)
            g = int(self.r1[1] + (self.r2[1] - self.r1[1]) * k)
            b = int(self.r1[2] + (self.r2[2] - self.r1[2]) * k)
            for x in range(2):
                i = (y * 2 + x) * 4
                buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = b, g, r, 255
        self.bm.write(buf)

    def frame(self, hdc, t: float) -> None:
        gdi32.SetStretchBltMode(hdc, COLORONCOLOR)
        gdi32.StretchBlt(hdc, 0, 0, self.sw, self.sh, self.bm.hdc, 0, 0, 2, 256, SRCCOPY)

    def release(self):
        self.bm.release()


# ------------------------------------------------------------------ 粒子
class P:
    __slots__ = ("x", "y", "vx", "vy", "s", "ph", "dir", "spin", "k",
                 "b", "a", "r")            # b: 极光基准高度  a: 极坐标角度  r: 极坐标半径

    def __init__(self):
        self.x = self.y = self.vx = self.vy = 0.0
        self.s = 1.0
        self.ph = random.random() * 6.283
        self.dir = random.randint(0, 7)
        self.spin = random.uniform(-2.2, 2.2)
        self.k = 1.0
        self.b = self.a = self.r = 0.0


class Effect:
    def __init__(self, cfg: dict, sprites: SpriteSet, sw: int, sh: int, k: float = 1.0):
        self.kind = cfg["kind"]
        self.cfg = cfg
        self.sp = sprites
        self.k = k                      # 屏幕高度 / 1080，用于把尺寸、速度归一到同一观感
        self.sw, self.sh = sw, sh
        self.parts: list[P] = []
        self.n = int(cfg["count"])
        for _ in range(self.n):
            p = P()
            self._spawn(p, first=True)
            self.parts.append(p)

    # ---- 生成
    def _spawn(self, p: P, first: bool = False) -> None:
        k = self.kind
        sw, sh = self.sw, self.sh
        p.ph = random.random() * 6.283
        p.dir = random.randint(0, 7)
        p.spin = random.uniform(-2.0, 2.0)
        if k == "rain":
            p.x = random.uniform(-120, sw + 120)
            p.y = random.uniform(-sh, sh) if first else random.uniform(-sh * 0.4, -20)
            v = random.uniform(0.75, 1.35)
            p.vy, p.vx = v, v * math.tan(math.radians(self.cfg.get("angle", 12)))
            p.s = random.uniform(0.7, 1.5)
        elif k in ("snow", "petal", "leaf"):
            p.x = random.uniform(-40, sw + 40)
            p.y = random.uniform(0, sh) if first else -30
            p.vy = random.uniform(0.18, 0.42)
            p.vx = 0.0
            p.s = random.uniform(0.6, 1.5) if k == "snow" else random.uniform(0.75, 1.35)
        elif k in ("firefly", "ember"):
            p.x = random.uniform(0, sw) if k == "firefly" else random.uniform(0, sw)
            p.y = random.uniform(0, sh) if first else (sh + 20 if k == "ember"
                                                       else random.uniform(0, sh))
            p.vy = random.uniform(-10, -26) if k == "ember" else random.uniform(-14, 14)
            p.vx = random.uniform(-14, 14) if k == "firefly" else random.uniform(-8, 8)
            p.s = random.uniform(0.6, 1.5)
        elif k == "bubble":
            p.x = random.uniform(0, sw)
            p.y = random.uniform(0, sh) if first else sh + 20
            p.vy = random.uniform(-40, -90)
            p.vx = random.uniform(-6, 6)
            p.s = random.uniform(0.5, 1.4)
        elif k == "star":
            p.x = random.uniform(0, sw)
            p.y = random.uniform(0, sh)
            p.vy = p.vx = 0.0
            p.s = random.uniform(0.35, 1.1)
            p.spin = random.uniform(0.4, 2.0)
        elif k == "aurora":
            p.x = random.uniform(-sw * 0.2, sw * 1.2)
            p.b = random.uniform(sh * 0.10, sh * 0.68)
            p.y = p.b
            p.s = random.uniform(0.7, 1.7)
            p.spin = random.uniform(0.22, 0.78)
            p.vx = random.uniform(8, 30) * random.choice((-1.0, 1.0))
            p.vy = 0.0
        elif k == "bokeh":
            p.x = random.uniform(-40, sw + 40)
            p.y = random.uniform(0, sh) if first else sh + 70
            p.vy = random.uniform(-30, -8)
            p.vx = random.uniform(-12, 12)
            p.s = random.uniform(0.5, 1.9)
        elif k == "warp":
            p.a = random.random() * 6.283
            p.r = random.uniform(0, max(sw, sh) * 0.55) if first else random.uniform(0, 24)
            p.s = random.uniform(0.6, 1.6)
            p.vy = p.vx = 0.0
        elif k == "meteor":
            p.x = random.uniform(-sw * 0.4, sw * 0.85)
            p.y = random.uniform(-sh * 0.6, sh) if first else random.uniform(-sh * 0.5, -40)
            v = random.uniform(0.55, 1.15)
            p.vy, p.vx = v, v * math.tan(math.radians(self.cfg.get("angle", 32)))
            p.s = random.uniform(0.7, 1.6)

    # ---- 更新
    def step(self, dt: float, t: float) -> None:
        k = self.kind
        speed = num(self.cfg.get("speed"), 1.0, 0.1, 4.0)
        sw, sh = self.sw, self.sh
        for p in self.parts:
            if k == "rain":
                p.x += p.vx * 1500 * speed * self.k * dt
                p.y += p.vy * 1500 * speed * self.k * dt
                if p.y > sh + 60 or p.x > sw + 160 or p.x < -160:
                    self._spawn(p)
            elif k in ("snow", "petal", "leaf"):
                p.ph += dt * (1.6 if k == "snow" else 1.1) * speed
                p.x += (p.vx + math.sin(p.ph) * (26 if k == "snow" else 44)) * speed * self.k * dt
                p.y += p.vy * 160 * speed * self.k * dt
                if k != "snow":
                    p.dir = int((p.ph * 1.6 + p.spin) % 8)
                if p.y > sh + 40 or p.x < -60 or p.x > sw + 60:
                    self._spawn(p)
            elif k == "firefly":
                p.ph += dt * 1.3 * speed
                p.x += (p.vx + math.sin(p.ph * 0.7) * 30) * speed * self.k * dt
                p.y += (p.vy + math.cos(p.ph * 0.9) * 26) * speed * self.k * dt
                if p.x < -20:
                    p.x = sw + 20
                elif p.x > sw + 20:
                    p.x = -20
                if p.y < -20:
                    p.y = sh + 20
                elif p.y > sh + 20:
                    p.y = -20
            elif k == "ember":
                p.ph += dt * 2.4 * speed
                p.x += (p.vx + math.sin(p.ph) * 16) * speed * self.k * dt
                p.y += p.vy * speed * self.k * dt
                if p.y < -30:
                    self._spawn(p)
            elif k == "bubble":
                p.ph += dt * 1.4 * speed
                p.x += (p.vx + math.sin(p.ph) * 12) * speed * self.k * dt
                p.y += p.vy * speed * self.k * dt
                if p.y < -40:
                    self._spawn(p)
            elif k == "star":
                p.ph += dt * p.spin * speed
            elif k == "aurora":
                p.ph += dt * p.spin * speed
                p.x += p.vx * speed * self.k * dt
                p.y = p.b + math.sin(p.ph) * sh * 0.05
                if p.x < -sw * 0.35:
                    p.x = sw * 1.35
                elif p.x > sw * 1.35:
                    p.x = -sw * 0.35
            elif k == "bokeh":
                p.ph += dt * 0.65 * speed
                p.x += (p.vx + math.sin(p.ph) * 16) * speed * self.k * dt
                p.y += p.vy * speed * self.k * dt
                if p.y < -100:
                    self._spawn(p)
            elif k == "warp":
                p.r += (40 + p.r * 1.2) * speed * self.k * dt
                if p.r > math.hypot(sw, sh) * 0.64:
                    p.a = random.random() * 6.283
                    p.r = random.uniform(0, 24)
                    p.s = random.uniform(0.6, 1.6)
            elif k == "meteor":
                p.x += p.vx * 900 * speed * self.k * dt
                p.y += p.vy * 900 * speed * self.k * dt
                if p.y > sh + 200 or p.x > sw + 400:
                    self._spawn(p)

    # ---- 绘制
    def draw(self, hdc, blit) -> None:
        k = self.kind
        size_f = num(self.cfg.get("size"), 1.0, 0.3, 3.0) * self.k
        alpha = num(self.cfg.get("alpha"), 0.9, 0.05, 1.0)
        for p in self.parts:
            if k == "rain":
                spr = self.sp.streak
                blit(spr, p.x, p.y, int(spr.w * p.s * size_f), int(spr.h * p.s * size_f),
                     alpha * 0.55)
            elif k == "snow":
                a = alpha * (0.55 + 0.45 * math.sin(p.ph) ** 2)
                blit(self.sp.dot_big, p.x, p.y, int(26 * p.s * size_f), 0, a)
            elif k in ("petal", "leaf"):
                spr = (self.sp.petals if k == "petal" else self.sp.leaves)[p.dir]
                blit(spr, p.x, p.y, int(34 * p.s * size_f), 0, alpha)
            elif k == "firefly":
                a = alpha * (0.25 + 0.75 * (0.5 + 0.5 * math.sin(p.ph * 1.7)) ** 1.5)
                blit(self.sp.spark, p.x, p.y, int(30 * p.s * size_f), 0, a)
            elif k == "ember":
                a = alpha * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(p.ph * 2.6)))
                blit(self.sp.dot, p.x, p.y, int(16 * p.s * size_f), 0, a)
            elif k == "bubble":
                a = alpha * (0.45 + 0.35 * math.sin(p.ph))
                blit(self.sp.dot_big, p.x, p.y, int(30 * p.s * size_f), 0, max(0.05, a))
            elif k == "star":
                a = alpha * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(p.ph)) ** 2)
                blit(self.sp.spark, p.x, p.y, int(16 * p.s * size_f), 0, a)
            elif k == "aurora":
                a = alpha * max(0.0, 0.45 + 0.55 * math.sin(p.ph * 0.8)) ** 1.2
                d = int(360 * p.s * size_f)
                blit(self.sp.glow, p.x, p.y, int(d * 0.42), int(d * 1.5), max(0.02, a))
            elif k == "bokeh":
                a = alpha * (0.55 + 0.45 * math.sin(p.ph * 1.4))
                blit(self.sp.glow, p.x, p.y, int(150 * p.s * size_f), 0, max(0.02, a))
            elif k == "warp":
                cx, cy = self.sw * 0.5, self.sh * 0.5
                ca, sa = math.cos(p.a), math.sin(p.a) * 0.78
                a0 = alpha * min(1.0, p.r / 110.0)
                for j in range(6):
                    f = j / 6.0
                    rr = p.r - f * (6 + p.r * 0.075)
                    if rr <= 0:
                        break
                    d = int((7 + p.r * 0.038) * p.s * size_f * (1.0 - f * 0.25))
                    blit(self.sp.dot, cx + ca * rr, cy + sa * rr,
                         max(2, d), 0, a0 * (1.0 - f * 0.42))
            elif k == "meteor":
                spr = self.sp.streak
                blit(spr, p.x, p.y, int(spr.w * 1.1 * p.s * size_f),
                     int(spr.h * 2.6 * p.s * size_f), alpha * 0.62)
                blit(self.sp.spark, p.x, p.y, int(22 * p.s * size_f), 0, alpha)


# ------------------------------------------------------------------ 涟漪 / 文字
class Ripple:
    __slots__ = ("x", "y", "t", "life")

    def __init__(self, x, y, life=1.35):
        self.x, self.y, self.t, self.life = x, y, 0.0, life


class RippleLayer:
    def __init__(self, sprites: SpriteSet, max_size: int, alpha: float, k: float = 1.0):
        self.sp = sprites
        self.k = k
        self.max_size = max(120, int(max_size * k))
        self.alpha = max(0.05, min(1.0, alpha))
        self.items: list[Ripple] = []

    def add(self, x, y):
        if len(self.items) < 12:
            self.items.append(Ripple(x, y))

    def step(self, dt):
        for r in self.items:
            r.t += dt
        self.items = [r for r in self.items if r.t < r.life]

    def draw(self, hdc, blit):
        for r in self.items:
            k = r.t / r.life
            diam = int(60 + (self.max_size - 60) * (k ** 0.55))
            a = self.alpha * (1.0 - k) ** 1.6
            blit(self.sp.ring(diam), r.x, r.y, 0, 0, a)


class TextLayer:
    """时钟 / 自定文字：先画到黑底 DIB，再用亮度当 alpha、着色后贴上去（有抗锯齿）"""

    DT_NOPREFIX = 0x0800
    DT_CALCRECT = 0x0400

    def __init__(self, hdc, sw, sh, k: float = 1.0):
        self.hdc = hdc
        self.k = k
        self.sw, self.sh = sw, sh
        self.bm: Bitmap | None = None
        self.key = None
        self.pos = (0, 0)
        self._measure_dc = gdi32.CreateCompatibleDC(hdc)

    def _render(self, text: str, size: int, color: str) -> None:
        pad = max(6, int(size * 0.34))
        dc = self._measure_dc
        font = gdi32.CreateFontW(-size, 0, 0, 0, 600, 0, 0, 0, 0, 0, 0, 0, 0, "微软雅黑")
        old = gdi32.SelectObject(dc, font)
        gdi32.SetBkMode(dc, TRANSPARENT)
        gdi32.SetTextColor(dc, 0x00FFFFFF)

        rect = w.RECT(0, 0, 0, 0)
        user32.DrawTextW(dc, text, -1, ctypes.byref(rect),
                         self.DT_CALCRECT | self.DT_NOPREFIX)
        tw = max(8, rect.right - rect.left)
        th = max(8, rect.bottom - rect.top)
        bw = min(self.sw, tw + pad * 2)
        bh = min(self.sh, th + pad * 2)

        if self.bm is None or self.bm.w != bw or self.bm.h != bh:
            if self.bm:
                self.bm.release()
            self.bm = Bitmap(self.hdc, bw, bh)
        self.bm.fill(0, 0, 0, 0)                       # 全透明黑底
        mem = self.bm.hdc
        gdi32.SelectObject(mem, font)
        gdi32.SetBkMode(mem, TRANSPARENT)
        gdi32.SetTextColor(mem, 0x00FFFFFF)            # 白字 → 亮度即 alpha
        r2 = w.RECT(pad, pad, bw - pad, bh - pad)
        user32.DrawTextW(mem, text, -1, ctypes.byref(r2), self.DT_NOPREFIX)
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(font)

        # 上色 + 预乘
        r_, g_, b_ = hex_rgb(color)
        raw = self.bm.read()
        buf = bytearray(len(raw))
        for i in range(0, len(raw), 4):
            lum = raw[i]                               # 白字灰度
            if lum == 0:
                continue
            buf[i] = (b_ * lum) // 255
            buf[i + 1] = (g_ * lum) // 255
            buf[i + 2] = (r_ * lum) // 255
            buf[i + 3] = lum
        self.bm.write(buf)

    def _place(self, pos: str, size: int) -> None:
        margin = int(size * 0.9)
        bw, bh = self.bm.w, self.bm.h
        x = {"l": margin, "c": (self.sw - bw) // 2, "r": self.sw - bw - margin}
        y = {"t": margin, "c": (self.sh - bh) // 2, "b": self.sh - bh - margin}
        self.pos = (x.get((pos or "lt")[0], margin), y.get((pos or "lt")[1], margin))

    def update(self, cfg: dict, t: float) -> bool:
        if not cfg.get("on"):
            return False
        size = max(12, min(600, int(cfg.get("size", 48) * self.k)))
        now = time.localtime()
        clock_txt = time.strftime("%H:%M:%S" if cfg.get("seconds") else "%H:%M", now)
        if cfg.get("only_time"):
            text = clock_txt
        else:
            text = clock_txt + "\n" + time.strftime("%m月%d日 ", now) + "周" + \
                "一二三四五六日"[now.tm_wday]
        key = (text, size, cfg.get("color"), cfg.get("pos"), self.sw, self.sh)
        if key != self.key:
            self._render(text, size, cfg.get("color", "#ffffff"))
            self.key = key
        self._place(cfg.get("pos", "lt"), size)
        return True

    def draw(self, hdc, blit, alpha: float):
        if self.bm is None:
            return
        blit(self.bm, self.pos[0] + self.bm.w / 2, self.pos[1] + self.bm.h / 2, 0, 0, alpha)


class PlainTextLayer(TextLayer):
    def update(self, cfg: dict, t: float) -> bool:
        if not cfg.get("on"):
            return False
        val = (cfg.get("value") or "").strip()
        if not val:
            return False
        size = max(12, min(600, int(cfg.get("size", 26) * self.k)))
        text = "\n".join(val.split("\n")[:4])
        key = (text, size, cfg.get("color"), cfg.get("pos"), self.sw, self.sh)
        if key != self.key:
            self._render(text, size, cfg.get("color", "#ffffff"))
            self.key = key
        self._place(cfg.get("pos", "lb"), size)
        return True


# ------------------------------------------------------------------ 主渲染器
class Renderer:
    def __init__(self, hdc, sw: int, sh: int, cfg: dict, log=None):
        self.hdc = hdc
        self.sw, self.sh = sw, sh
        self.cfg = norm_scene(cfg)
        self.log = log or (lambda m: None)
        self.k = max(0.4, sh / 1080.0)
        self.t0 = time.time()
        self.ffmpeg = find_ffmpeg()
        self.bg = None
        self.effects: list[Effect] = []
        self.sprite_sets: list[SpriteSet] = []
        self.glow_sp: SpriteSet | None = None
        self.ripple: RippleLayer | None = None
        self.clock = TextLayer(hdc, sw, sh, self.k)
        self.plain = PlainTextLayer(hdc, sw, sh, self.k)
        self.mx = self.my = -999
        self.click_was = False
        self.clock_t = 0.0
        self.frames = 0

    # ---- 初始化
    def start(self) -> None:
        bg = self.cfg["bg"]
        path = bg.get("src") or ""
        btype = bg.get("type") or "color"
        try:
            if btype == "video" and path and os.path.isfile(path) and self.ffmpeg:
                self.bg = VideoBg(self.hdc, self.ffmpeg, path, self.sw, self.sh)
                self.log(f"bg=video {path}")
            elif btype == "para" and path and os.path.isfile(path) and self.ffmpeg:
                pbg = ParallaxBg(self.hdc, self.ffmpeg, path, self.sw, self.sh,
                                 num(bg.get("strength"), 1.0, 0.0, 3.0),
                                 num(bg.get("blur"), 1.0, 0.0, 3.0),
                                 num(bg.get("focus"), 1.0, 0.3, 1.8))
                if pbg.ok:
                    self.bg = pbg
                    self.log(f"bg=para {path} far={pbg.far_ok} near={pbg.near_ok}")
                else:
                    pbg.release()
                    self.log("视差层失败，回退图片背景")
                    img = ImageBg(self.hdc, self.ffmpeg, path, self.sw, self.sh)
                    if img.ok:
                        self.bg = img
                        self.log("bg=image(回退)")
            elif btype == "image" and path and os.path.isfile(path) and self.ffmpeg:
                img = ImageBg(self.hdc, self.ffmpeg, path, self.sw, self.sh)
                if img.ok:
                    self.bg = img
                    self.log(f"bg=image {path}")
                else:
                    img.release()
            if self.bg is None:
                self.bg = ColorBg(self.hdc, bg.get("color"), bg.get("color2"),
                                  self.sw, self.sh)
                self.log("bg=color")
        except Exception as e:
            self.log(f"背景失败: {e}")
            self.bg = ColorBg(self.hdc, "#0b1020", "#1b2a4a", self.sw, self.sh)

        for item in self.cfg["fx"]:
            if item["count"] <= 0:
                continue
            sp = SpriteSet(self.hdc, hex_rgb(item.get("color")),
                           num(item.get("angle"), 12.0, -80.0, 80.0)
                           if item["kind"] in ("rain", "meteor") else 12.0)
            self.sprite_sets.append(sp)
            self.effects.append(Effect(item, sp, self.sw, self.sh, self.k))
        m = self.cfg["mouse"]
        g = m.get("glow") or {}
        if g.get("on"):
            self.glow_sp = SpriteSet(self.hdc, hex_rgb(g.get("color")))
        r = m.get("ripple") or {}
        if r.get("on"):
            sp = SpriteSet(self.hdc, hex_rgb(r.get("color")))
            self.sprite_sets.append(sp)
            self.ripple = RippleLayer(sp, int(r.get("size", 520)),
                                      float(r.get("alpha", 0.55)), self.k)
        self.log(f"fx={[e.kind + ':' + str(e.n) for e in self.effects]}")

    # ---- 贴图（hdc 取自 self.hdc）
    def _blit(self, spr, cx, cy, dw, dh, alpha):
        if alpha <= 0.01:
            return
        if not dw and not dh:
            dw, dh = spr.w, spr.h
        elif not dh:                       # 只给宽度时按比例缩放，保持圆形/方形
            dh = max(1, int(spr.h * dw / spr.w))
        elif not dw:
            dw = max(1, int(spr.w * dh / spr.h))
        x = int(cx - dw / 2)
        y = int(cy - dh / 2)
        bf = _BLENDFUNC(AC_SRC_OVER, 0, max(0, min(255, int(alpha * 255))), AC_SRC_ALPHA)
        msimg32.AlphaBlend(self.hdc, x, y, dw, dh, spr.hdc, 0, 0, spr.w, spr.h, bf)

    # ---- 鼠标
    def _poll_mouse(self):
        pt = w.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return
        self.mx, self.my = pt.x, pt.y
        down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        if down and not self.click_was and self.ripple:
            if self._over_desktop(pt):
                self.ripple.add(pt.x, pt.y)
        self.click_was = down

    @staticmethod
    def _over_desktop(pt) -> bool:
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(64)
        for _ in range(4):
            if not hwnd:
                break
            user32.GetClassNameW(hwnd, buf, 64)
            if buf.value in DESKTOP_CLASSES:
                return True
            hwnd = user32.GetParent(hwnd)
        return False

    # ---- 每帧
    def frame(self, dt: float) -> bool:
        t = time.time() - self.t0
        hdc = self.hdc
        bg = self.cfg["bg"]

        # 0) 鼠标（视差背景要用当前帧的坐标，必须放在画背景之前）
        self._poll_mouse()

        # 1) 背景
        if isinstance(self.bg, VideoBg):
            if not self.bg.frame(hdc):
                self.log("视频流结束")
                return False
        elif isinstance(self.bg, ParallaxBg):
            self.bg.frame(hdc, t, num(bg.get("motion_speed"), 1.0, 0.1, 4.0),
                          mouse=(self.mx, self.my))
        elif isinstance(self.bg, ImageBg):
            self.bg.frame(hdc, t, num(bg.get("motion_speed"), 1.0, 0.1, 4.0))
        else:
            self.bg.frame(hdc, t)

        # 2) 鼠标光晕
        if self.glow_sp:
            g = self.cfg["mouse"]["glow"]
            pulse = 1.0 + 0.04 * math.sin(t * 1.6)
            self._blit(self.glow_sp.glow, self.mx, self.my,
                       int(g.get("size", 360) * pulse * self.k),
                       int(g.get("size", 360) * pulse * self.k),
                       num(g.get("alpha"), 0.35, 0.0, 1.0))

        # 3) 粒子
        for e in self.effects:
            e.step(dt, t)
            e.draw(hdc, self._blit)

        # 4) 涟漪
        if self.ripple:
            self.ripple.step(dt)
            self.ripple.draw(hdc, self._blit)

        # 5) 时钟 / 文字
        okc = self.clock.update(self.cfg["clock"], t)
        if okc:
            self.clock.draw(hdc, self._blit, num(self.cfg["clock"].get("alpha"), 0.92, 0.0, 1.0))
        if self.plain.update(self.cfg["text"], t):
            self.plain.draw(hdc, self._blit, num(self.cfg["text"].get("alpha"), 0.9, 0.0, 1.0))

        self.frames += 1
        gdi32.GdiFlush()
        return True

    def close(self) -> None:
        try:
            self.bg and self.bg.release()
        except Exception:
            pass
        for sp in self.sprite_sets:
            sp.release()
        if self.glow_sp:
            self.glow_sp.release()
        for bm in (self.clock.bm, self.plain.bm):
            if bm:
                bm.release()
        try:
            gdi32.DeleteDC(self.clock._measure_dc)
        except Exception:
            pass
