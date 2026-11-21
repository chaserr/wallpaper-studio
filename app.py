# -*- coding: utf-8 -*-
"""
壁纸工坊 Wallpaper Studio
一个零依赖（仅标准库）的本地壁纸工具：
  - 必应每日精选（4K）
  - 必应图片搜索（任意关键词，可筛选壁纸级大图）
  - 下载到本地图库 / 一键设为桌面壁纸 / 历史回滚 / 定时轮播
运行：python app.py  （或双击 start.bat）
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import html as htmlmod
import json
import os
import random
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------- 基础路径
# 程序与数据分离：有 E 盘就用 E:\Wallpapers，没有就落到「图片\Wallpapers」
# （这样别人把自己的机器上跑也不需要手工改路径）
if getattr(sys, "frozen", False):
    # 打包成 exe 后：配置/日志放在 exe 旁边，资源解压在 sys._MEIPASS
    APP_DIR = Path(sys.executable).resolve().parent
    RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    RES_DIR = APP_DIR
CONF_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "app.log"
UI_FILE = RES_DIR / "ui" / "index.html"
APP_ID = "wallpaper-studio"


def _detect_data_root() -> Path:
    env = os.environ.get("WALLPAPER_DATA_ROOT")
    if env:
        return Path(env)
    for drive in ("E:", "D:"):
        try:
            if Path(drive + "\\").exists():
                return Path(drive + "\\Wallpapers")
        except OSError:
            pass
    return Path(os.path.expanduser("~")) / "Pictures" / "Wallpapers"


DATA_ROOT = _detect_data_root()
CACHE_DIR = DATA_ROOT / "_cache"
DEFAULT_LIB = DATA_ROOT
DYN_DIR = DATA_ROOT / "Dynamic"

for _d in (DATA_ROOT, CACHE_DIR, DYN_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_cfg_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# ---------------------------------------------------------------- 配置
def default_config() -> dict:
    return {
        "library": str(DEFAULT_LIB),
        "data_root": str(DATA_ROOT),
        "theme": "light",
        "lan": True,
        "wallhaven_proxy": "auto",
        "wallhaven_key": "",
        "rotate": {"enabled": False, "minutes": 30, "last_ts": 0},
        "history": [],
    }


def load_config() -> dict:
    cfg = default_config()
    try:
        if CONF_FILE.exists():
            data = json.loads(CONF_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
    except Exception as e:
        log(f"读取配置失败: {e}")
    cfg.setdefault("rotate", {"enabled": False, "minutes": 30, "last_ts": 0})
    cfg.setdefault("history", [])
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONF_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"保存配置失败: {e}")


def library_dir() -> Path:
    p = Path(load_config().get("library") or DEFAULT_LIB)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        p = DEFAULT_LIB
        p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- 网络
def sys_proxy() -> str | None:
    """读取 Windows 系统代理（Clash/青云梯之类开启后会写这里）"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            server, _ = winreg.QueryValueEx(k, "ProxyServer")
        if enable and server:
            if "=" in server:
                for part in server.split(";"):
                    if part.lower().startswith(("https=", "http=")):
                        return "http://" + part.split("=", 1)[1]
            return "http://" + server.split(";")[0]
    except Exception:
        pass
    return None


def wh_proxy() -> str | None:
    """Wallhaven 专用代理：auto=跟随系统代理，off=直连，也可填自定义地址"""
    cfg = load_config()
    val = cfg.get("wallhaven_proxy", "auto")
    if val in ("off", "", False, None):
        return None
    if val == "auto":
        return sys_proxy()
    return str(val)


_opener_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_opener_cache: dict[str, urllib.request.OpenerDirector] = {}


def _opener(proxy: str | None):
    if not proxy:
        return _opener_direct
    op = _opener_cache.get(proxy)
    if op is None:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        _opener_cache[proxy] = op
    return op


def http_get(url: str, timeout: int = 25, referer: str | None = None,
             max_bytes: int | None = None, proxy: str | None = None) -> tuple[bytes, str, str]:
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with _opener(proxy).open(req, timeout=timeout) as r:
        data = r.read(max_bytes) if max_bytes else r.read()
        return data, (r.headers.get("Content-Type") or "application/octet-stream"), r.geturl()


def is_wallhaven(url: str) -> bool:
    try:
        return "wallhaven.cc" in (urllib.parse.urlsplit(url).hostname or "")
    except Exception:
        return False


def origin_of(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url)
        return f"{p.scheme}://{p.netloc}/"
    except Exception:
        return ""


EXT_BY_TYPE = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "image/gif": ".gif", "image/bmp": ".bmp",
    "image/avif": ".avif", "video/mp4": ".mp4",
}


def guess_ext(ctype: str, url: str) -> str:
    ct = (ctype or "").split(";")[0].strip().lower()
    if ct in EXT_BY_TYPE:
        return EXT_BY_TYPE[ct]
    path = urllib.parse.urlsplit(url).path.lower()
    for e in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".mp4"):
        if path.endswith(e):
            return ".jpg" if e == ".jpeg" else e
    return ".jpg"


BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(text: str, limit: int = 36) -> str:
    s = BAD_CHARS.sub(" ", text or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s[:limit].strip(" .")
    return s or "壁纸"


# ---------------------------------------------------------------- 数据源：必应每日
def bing_daily(market: str = "zh-CN", n: int = 8) -> list[dict]:
    url = f"https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n={n}&mkt={market}"
    raw, _, _ = http_get(url, timeout=15)
    data = json.loads(raw.decode("utf-8", "ignore"))
    out = []
    for it in data.get("images", []):
        base = it.get("urlbase") or ""
        if not base:
            continue
        full = "https://www.bing.com" + base + "_UHD.jpg"
        alt = "https://www.bing.com" + (it.get("url") or "")
        out.append({
            "id": "bing-" + (it.get("startdate") or "") + "-" + market,
            "title": it.get("copyright") or "必应每日壁纸",
            "date": it.get("startdate") or "",
            "full": full,
            "alt": alt,
            "thumb": "https://www.bing.com" + base + "_400x240.jpg",
            "source": "必应每日",
            "market": market,
        })
    return out


# ---------------------------------------------------------------- 数据源：必应图片搜索
def bing_search(q: str, page: int = 0, count: int = 35, size: str = "wallpaper") -> list[dict]:
    params = {"q": q, "first": page * count, "count": count, "mmasync": "1"}
    url = "https://cn.bing.com/images/async?" + urllib.parse.urlencode(params)
    if size == "wallpaper":
        url += "&qft=+filterui:imagesize-wallpaper"
    elif size == "large":
        url += "&qft=+filterui:imagesize-large"
    ref = "https://cn.bing.com/images/search?q=" + urllib.parse.quote(q)
    raw, _, _ = http_get(url, timeout=20, referer=ref)
    h = raw.decode("utf-8", "ignore")

    items, seen = [], set()
    for m in re.finditer(r'<a[^>]+class="iusc"[^>]+m="([^"]+)"', h):
        try:
            meta = json.loads(htmlmod.unescape(m.group(1)))
        except Exception:
            continue
        murl, turl = meta.get("murl"), meta.get("turl") or ""
        if not murl or murl in seen:
            continue
        seen.add(murl)
        items.append({
            "id": hashlib.md5(murl.encode("utf-8")).hexdigest()[:12],
            "title": htmlmod.unescape(meta.get("t") or "") or "来自必应图片",
            "full": murl,
            "alt": "",
            "thumb": turl,
            "source": "必应图片",
        })
    if items:
        return items

    # 兜底：老版页面结构
    murls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', h)
    turls = re.findall(r'turl&quot;:&quot;(.*?)&quot;', h)
    for i, mu in enumerate(murls):
        if mu in seen:
            continue
        seen.add(mu)
        items.append({
            "id": hashlib.md5(mu.encode("utf-8")).hexdigest()[:12],
            "title": "来自必应图片",
            "full": mu,
            "alt": "",
            "thumb": turls[i] if i < len(turls) else "",
            "source": "必应图片",
        })
    return items


# ---------------------------------------------------------------- 数据源：Wallhaven
WH_CATEGORY = {"general": "综合", "anime": "动漫", "people": "人物"}


def wallhaven_search(q: str = "", page: int = 1, sorting: str = "toplist",
                     atleast: str = "", categories: str = "111", ratios: str = "",
                     colors: str = "") -> tuple[list[dict], dict]:
    """走代理访问 Wallhaven API；无 API Key 时仅能取 SFW（purity=100）"""
    cfg = load_config()
    params = {
        "categories": categories or "111",
        "purity": "100",
        "sorting": sorting or "toplist",
        "order": "desc",
        "page": max(1, page),
    }
    if q:
        params["q"] = q
    if atleast and atleast != "any":
        params["atleast"] = atleast
    if ratios and ratios != "any":
        params["ratios"] = ratios
    if colors:
        params["colors"] = colors
    key = (cfg.get("wallhaven_key") or "").strip()
    if key:
        params["apikey"] = key

    url = "https://wallhaven.cc/api/v1/search?" + urllib.parse.urlencode(params)
    try:
        raw, _, _ = http_get(url, timeout=30, proxy=wh_proxy(), max_bytes=4 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RuntimeError("Wallhaven 限流了（每分钟 45 次），等几秒再点")
        if e.code == 401:
            raise RuntimeError("API Key 无效，请检查配置")
        raise RuntimeError(f"Wallhaven 返回 {e.code}")
    d = json.loads(raw.decode("utf-8", "ignore"))

    items = []
    for it in d.get("data", []):
        cats = [WH_CATEGORY.get(c, c) for c in (it.get("category") or "").split()]
        res = it.get("resolution") or f"{it.get('dimension_x')}×{it.get('dimension_y')}"
        items.append({
            "id": it.get("id") or "",
            "title": f"{res} · {'/'.join(cats) or '壁纸'}",
            "res": res,
            "full": it.get("path") or "",
            "alt": "",
            "thumb": (it.get("thumbs") or {}).get("large") or (it.get("thumbs") or {}).get("original") or "",
            "preview": (it.get("thumbs") or {}).get("original") or "",
            "source": "Wallhaven",
            "page_url": it.get("url") or "",
        })
    meta = d.get("meta") or {}
    return items, {
        "page": meta.get("current_page", page),
        "last": meta.get("last_page", page),
        "total": meta.get("total", len(items)),
    }


# ---------------------------------------------------------------- 数据源：Mixkit 在线动态壁纸
# Mixkit 免费视频（Free License，可商用免署名），国内多数网络可直连；
# 页面卡片里有工整的结构，能直接取标题、封面和 1080P 直链。
MIXKIT_CATS = [
    ("cat", "猫咪"), ("nature", "自然"), ("animals", "动物"), ("sea", "海洋"),
    ("city", "城市"), ("night", "夜景"), ("abstract", "抽象"), ("space", "太空"),
    ("forest", "森林"), ("aerial", "航拍"), ("water", "水"), ("sky", "天空"),
    ("fire", "火焰"), ("snow", "雪"), ("rain", "雨"), ("technology", "科技"),
    ("transport", "交通"), ("food", "美食"), ("sport", "运动"), ("people", "人物"),
]
MIXKIT_SLUGS = {s for s, _ in MIXKIT_CATS}
_MX_ID = re.compile(r'data-item-grid--video-player-item-id-value="(\d+)"')
_MX_TITLE = re.compile(r'item-grid-video-player__overlay-video-title">\s*([^<]{2,160}?)\s*</span>')
_MX_DESC = re.compile(r'item-grid-video-player__overlay-video-description">\s*([^<]{2,300}?)\s*</span>', re.S)


def _mx_fetch(url: str, timeout: int = 25) -> str:
    """先直连，失败再借系统代理重试一次"""
    try:
        raw, _, _ = http_get(url, timeout=timeout, max_bytes=8 * 1024 * 1024)
        return raw.decode("utf-8", "ignore")
    except Exception:
        px = sys_proxy()
        if not px:
            raise
        log(f"Mixkit 直连失败，改走代理 {px}")
        raw, _, _ = http_get(url, timeout=timeout + 15, proxy=px,
                             max_bytes=8 * 1024 * 1024)
        return raw.decode("utf-8", "ignore")


def mixkit_list(slug: str = "cat", page: int = 1) -> list[dict]:
    slug = slug if slug in MIXKIT_SLUGS else "cat"
    page = max(1, min(60, int(page or 1)))
    html = _mx_fetch(f"https://mixkit.co/free-stock-video/{slug}/?page={page}")
    items, seen = [], set()
    for chunk in html.split('class="item-grid-card"')[1:]:
        chunk = chunk[:5000]
        m = _MX_ID.search(chunk)
        if not m:
            continue
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        t = _MX_TITLE.search(chunk)
        d = _MX_DESC.search(chunk)
        items.append({
            "id": vid,
            "title": htmlmod.unescape(t.group(1)) if t else f"动态壁纸 {vid}",
            "desc": htmlmod.unescape(d.group(1)) if d else "",
            "thumb": f"https://assets.mixkit.co/videos/{vid}/{vid}-thumb-720-0.jpg",
            "full": f"https://assets.mixkit.co/videos/{vid}/{vid}-1080.mp4",
            "alt": f"https://assets.mixkit.co/videos/{vid}/{vid}-720.mp4",
            "source": "Mixkit",
            "cat": slug,
            "page_url": f"https://mixkit.co/free-stock-video/x-{vid}/",
        })
    return items


def download_video(item: dict, on_progress=None) -> Path:
    last = None
    for u in [x for x in (item.get("full"), item.get("alt")) if x]:
        try:
            fp = _stream_download(u, DYN_DIR, item, None, on_progress)
            if fp.stat().st_size < 200 * 1024:
                fp.unlink(missing_ok=True)
                raise RuntimeError("文件过小，可能不是视频")
            return fp
        except Exception as e:
            last = e
            continue
    raise RuntimeError(f"下载失败：{last}")


def run_dyn_job(jid: str, item: dict, autoplay: bool = True) -> None:
    def prog(got: int, total: int):
        pct = min(96, int(got * 100 / total)) if total else min(90, int(got / 200000))
        msg = f"下载中 {got/1048576:.1f}MB" + (f" / {total/1048576:.1f}MB" if total else "")
        job_set(jid, pct=max(3, pct), msg=msg)

    try:
        job_set(jid, pct=2, msg="正在连接 Mixkit…")
        fp = download_video(item, on_progress=prog)
        if autoplay:
            job_set(jid, pct=97, msg="下载完成，正在铺到桌面…")
            dyn_start(fp.name)
            job_set(jid, state="done", pct=100, msg="已铺到桌面", set=True,
                    playing=True, name=fp.name, path=str(fp), ts=time.time())
        else:
            job_set(jid, state="done", pct=100, msg="已存入动态壁纸", set=False,
                    playing=False, name=fp.name, path=str(fp), ts=time.time())
    except Exception as e:
        log(f"在线动态壁纸失败: {e}")
        job_set(jid, state="error", pct=100, msg=str(e), ts=time.time())


def lan_urls(port: int) -> list[str]:
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith(("127.", "169.254.")) and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith(("127.", "169.254.")) and ip not in ips:
            ips.append(ip)
    except Exception:
        pass

    def rank(ip: str) -> int:
        # 家里/公司的真实局域网段优先，Tailscale(100.x) 这类虚拟网卡排后面
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            return 2
        if ip.startswith("100."):
            return 8
        return 5

    ips.sort(key=rank)
    return [f"http://{ip}:{port}/" for ip in ips]


# ---------------------------------------------------------------- 下载
def download_image(item: dict, lib: Path, on_progress=None) -> Path:
    candidates = [u for u in (item.get("full"), item.get("alt")) if u]
    if not candidates:
        raise ValueError("没有可下载的图片地址")
    last_err = None
    for u in candidates:
        px = wh_proxy() if is_wallhaven(u) else None
        try:
            return _stream_download(u, lib, item, px, on_progress)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"下载失败：{last_err}")


def _stream_download(u: str, lib: Path, item: dict, px: str | None, on_progress) -> Path:
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    headers["Referer"] = origin_of(u)
    req = urllib.request.Request(u, headers=headers)
    with _opener(px).open(req, timeout=180) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype and not (ctype.startswith("image/") or ctype.startswith("video/")):
            raise RuntimeError(f"返回类型不是图片: {ctype}")
        total = int(r.headers.get("Content-Length") or 0)
        ext = guess_ext(ctype, u)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        h8 = hashlib.md5(u.encode("utf-8")).hexdigest()[:6]
        target = lib / f"{stamp}_{safe_name(item.get('title', ''))}_{h8}{ext}"
        tmp = target.with_name(target.name + ".part")
        got = 0
        try:
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if on_progress:
                        on_progress(got, total)
            if got < 15000:
                raise RuntimeError("文件过小，可能不是图片")
            tmp.replace(target)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        return target


# ---------------------------------------------------------------- 设为壁纸
SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x01, 0x02


def set_wallpaper(path: Path) -> bool:
    p = str(Path(path).resolve())
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    if Path(p).suffix.lower() == ".mp4":
        raise ValueError("视频壁纸无法用系统接口设置，请拖进 Lively Wallpaper 播放")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, "10")  # 填充
            winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, "0")
    except Exception as e:
        log(f"设置壁纸样式失败（忽略）: {e}")
    ok = bool(ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, p, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE))
    if not ok:
        log("SystemParametersInfoW 返回失败")
    return ok


def shrink_history(cfg: dict, entry: dict) -> None:
    hist = [h for h in cfg.get("history", []) if h.get("path") != entry.get("path")]
    hist.insert(0, entry)
    cfg["history"] = hist[:40]


LIB_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".mp4"}


def list_library(lib: Path) -> list[dict]:
    out = []
    if not lib.exists():
        return out
    for f in lib.iterdir():
        if f.is_file() and f.suffix.lower() in LIB_EXTS:
            try:
                st = f.stat()
            except OSError:
                continue
            out.append({
                "name": f.name,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "url": "/file?name=" + urllib.parse.quote(f.name),
            })
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def send_to_recycle_bin(fp: Path) -> bool:
    """把文件丢进 Windows 回收站（失败返回 False，由调用方决定是否硬删）"""
    if sys.platform != "win32":
        return False
    try:
        class _SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", ctypes.c_void_p),
                        ("wFunc", ctypes.c_uint),
                        ("pFrom", ctypes.c_wchar_p),
                        ("pTo", ctypes.c_wchar_p),
                        ("fFlags", ctypes.c_ushort),
                        ("fAnyOperationsAborted", ctypes.c_int),
                        ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", ctypes.c_wchar_p)]

        FO_DELETE = 3
        FOF_SILENT = 0x0004
        FOF_NOCONFIRMATION = 0x0010
        FOF_ALLOWUNDO = 0x0040
        FOF_NOERRORUI = 0x0400

        op = _SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        # 路径必须以双 \0 结尾
        op.pFrom = str(fp.resolve()) + "\0\0"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return rc == 0 and not op.fAnyOperationsAborted and not fp.exists()
    except Exception as e:
        log(f"移入回收站失败: {e}")
        return False


def library_delete(name: str) -> dict:
    """从「我的图库」删除一张本地壁纸（优先移入回收站）"""
    lib = library_dir().resolve()
    raw = str(name or "").strip()
    if not raw:
        raise ValueError("缺少文件名")
    fp = (lib / raw).resolve()
    try:
        fp.relative_to(lib)
    except ValueError:
        raise PermissionError("非法文件名")
    if fp.parent != lib:
        raise PermissionError("非法文件名")
    if fp.suffix.lower() not in LIB_EXTS:
        raise PermissionError("不支持的文件类型")
    if not fp.is_file():
        raise FileNotFoundError("文件不存在")

    size = fp.stat().st_size
    recycled = send_to_recycle_bin(fp)
    if not recycled:
        fp.unlink(missing_ok=True)
    if fp.exists():
        raise OSError("文件被占用，删除失败（可能正被显示为桌面壁纸）")

    # 顺手清掉历史记录里指向这个文件的条目
    try:
        with _cfg_lock:
            cfg = load_config()
            hist = cfg.get("history") or []
            keep = [h for h in hist if Path(str(h.get("path") or "")).name != fp.name]
            if len(keep) != len(hist):
                cfg["history"] = keep
                save_config(cfg)
    except Exception as e:
        log(f"清理历史记录失败: {e}")

    return {"name": fp.name, "size": size, "recycled": recycled}


# ---------------------------------------------------------------- 动态壁纸
DYN_STATE = APP_DIR / "dyn_state.json"
DYN_VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif", ".m4v", ".wmv"}
DYN_LOCK = threading.Lock()


def find_ffmpeg() -> str:
    for base in (RES_DIR, APP_DIR):
        for p in sorted((base / "vendor" / "imageio_ffmpeg" / "binaries").glob("ffmpeg*.exe")):
            return str(p)
    for d in os.environ.get("PATH", "").split(os.pathsep):
        exe = Path(d) / "ffmpeg.exe"
        if exe.is_file():
            return str(exe)
    return ""


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok and code.value == 259)  # STILL_ACTIVE


def dyn_load() -> dict:
    try:
        return json.loads(DYN_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def dyn_save(st: dict) -> None:
    try:
        DYN_STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"写动态状态失败: {e}")


def dyn_status() -> dict:
    st = dyn_load()
    running = bool(st) and pid_alive(st.get("pid", 0))
    if st and not running:
        dyn_save({})
        st = {}
    return {"running": running, "name": st.get("name", ""), "pid": st.get("pid", 0),
            "since": st.get("since", 0)}


def dyn_stop(wait: float = 4.0) -> bool:
    st = dyn_load()
    if not st:
        return True
    stop_file = DYN_DIR / ".stop"
    try:
        stop_file.write_text("stop", encoding="utf-8")
    except Exception:
        pass
    pid = int(st.get("pid") or 0)
    deadline = time.time() + wait
    while time.time() < deadline:
        if not pid_alive(pid):
            break
        time.sleep(0.2)
    if pid_alive(pid):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
        except Exception:
            pass
    try:
        stop_file.unlink(missing_ok=True)
    except Exception:
        pass
    dyn_save({})
    return True


def engine_cmd(args: list[str]) -> list[str]:
    """拼出引擎进程的启动命令（打包版复用同一个 exe）"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--dyn", *args]
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw if pyw.is_file() else sys.executable)
    return [exe, str(APP_DIR / "dynwall.py"), *args]


def _engine_spawn(args: list[str], label: str, target: Path, kind: str) -> dict:
    stop_file = DYN_DIR / ".stop"
    try:
        stop_file.unlink(missing_ok=True)
    except Exception:
        pass
    dyn_stop()
    if not find_ffmpeg():
        raise RuntimeError("缺少 ffmpeg（vendor 目录不完整）")
    cmd = engine_cmd(args + ["--stop-file", str(stop_file)])
    log("启动引擎: " + " ".join(cmd))
    proc = subprocess.Popen(cmd, cwd=str(APP_DIR),
                            creationflags=0x08000000,  # CREATE_NO_WINDOW
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    st = {"pid": proc.pid, "name": label, "path": str(target),
          "kind": kind, "since": int(time.time())}
    dyn_save(st)
    for _ in range(40):
        time.sleep(0.2)
        if pid_alive(proc.pid):
            break
    time.sleep(1.2)
    if not pid_alive(proc.pid):
        dyn_save({})
        raise RuntimeError("引擎启动失败，详见 dynwall.log")
    return st


def dyn_start(name: str) -> dict:
    fp = (DYN_DIR / name).resolve()
    try:
        fp.relative_to(DYN_DIR.resolve())
    except ValueError:
        raise ValueError("非法文件名")
    if not fp.is_file():
        raise FileNotFoundError(name)
    return _engine_spawn(["--video", str(fp)], name, fp, "video")


def dyn_thumb(name: str) -> Path:
    """取视频第 1.5 秒画面做缩略图"""
    src = DYN_DIR / name
    key = hashlib.md5((src.name + str(src.stat().st_mtime)).encode()).hexdigest()[:16]
    out = CACHE_DIR / f"dynth_{key}.jpg"
    if out.exists():
        return out
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("缺少 ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", "1.5", "-i", str(src), "-frames:v", "1",
           "-vf", "scale=640:-1", str(out)]
    subprocess.run(cmd, capture_output=True, timeout=60)
    if not out.exists():
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(src), "-frames:v", "1", "-vf", "scale=640:-1", str(out)]
        subprocess.run(cmd, capture_output=True, timeout=60)
    if not out.exists():
        raise RuntimeError("无法生成缩略图")
    return out


def list_dynamic() -> list[dict]:
    out = []
    if not DYN_DIR.exists():
        return out
    for f in DYN_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in DYN_VIDEO_EXT:
            try:
                st = f.stat()
            except OSError:
                continue
            out.append({"name": f.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


# ---------------------------------------------------------------- 特效壁纸（场景）
# 一个「场景」= 背景（视频/图片/渐变）+ 粒子特效 + 鼠标互动 + 时钟文字，
# 存成 E:\Wallpapers\Scenes\<id>.json，由 dynwall.py 用 --scene 播放。
SCENE_DIR = DATA_ROOT / "Scenes"


def scene_dir() -> Path:
    d = SCENE_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _scene_id(s: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_-]", "", str(s or ""))[:40]


def scene_path(sid: str) -> Path:
    sid = _scene_id(sid)
    if not sid:
        raise ValueError("非法场景 id")
    return scene_dir() / f"{sid}.json"


def scene_summary(cfg: dict) -> str:
    names = {"rain": "雨", "snow": "雪", "petal": "花瓣", "firefly": "萤火虫",
             "bubble": "气泡", "ember": "火星", "star": "星光", "leaf": "落叶"}
    parts = [names.get(i.get("kind"), "") for i in (cfg.get("fx") or []) if i.get("count")]
    bg = (cfg.get("bg") or {}).get("type")
    tag = {"video": "视频", "image": "图片", "color": "渐变"}.get(bg, "")
    if tag:
        parts.insert(0, tag)
    m = cfg.get("mouse") or {}
    if (m.get("glow") or {}).get("on"):
        parts.append("跟随光晕")
    if (m.get("ripple") or {}).get("on"):
        parts.append("点击涟漪")
    return " · ".join([p for p in parts if p][:6])


def list_scenes() -> list[dict]:
    out = []
    d = scene_dir()
    for f in d.glob("*.json"):
        if f.name.startswith("."):
            continue
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
            mt = int(f.stat().st_mtime)
        except Exception:
            continue
        thumb = d / (f.stem + ".jpg")
        if not thumb.exists():
            thumb = d / (f.stem + ".png")
        out.append({"id": f.stem, "name": cfg.get("name") or f.stem,
                    "mtime": mt, "summary": scene_summary(cfg), "cfg": cfg,
                    "has_thumb": thumb.exists(),
                    "thumb": f"/api/scene/thumb?id={urllib.parse.quote(f.stem)}&t={mt}"})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def _preset(pid: str, label: str, tag: str, bg1: str, bg2: str, fx: list,
            glow: dict | None = None, hint: str = "") -> dict:
    """拼一份完整的场景配置（缺省项由 norm_scene 补），供「风格预设」一键载入"""
    return {
        "id": pid, "label": label, "tag": tag, "hint": hint,
        "cfg": {
            "name": label,
            "bg": {"type": "color", "src": "", "color": bg1, "color2": bg2,
                   "motion": "kenburns", "motion_speed": 1.0},
            "fx": fx,
            "mouse": {
                "glow": dict({"on": bool(glow), "size": 360, "alpha": 0.3,
                              "color": "#ffd27a"}, **(glow or {})),
                "ripple": {"on": True, "size": 520, "alpha": 0.5, "color": "#ffffff"},
            },
            "clock": {"on": False, "pos": "lt", "size": 56, "color": "#ffffff",
                      "alpha": 0.9, "seconds": False, "only_time": False},
            "text": {"on": False, "value": "", "pos": "lb", "size": 26,
                     "color": "#ffffff", "alpha": 0.9},
        },
    }


# 「参考观感、重画实现」：下面每张都是本机引擎里可实时渲染的参数组合，
# 不含任何第三方素材，所以能随便改参数、改颜色、再存成自己的。
SCENE_PRESETS = [
    _preset("rain-neon", "雨夜霓虹", "夜景", "#070b18", "#241638", [
        {"kind": "bokeh", "count": 16, "size": 1.4, "speed": 0.3, "alpha": 0.30,
         "color": "#ff6fae"},
        {"kind": "rain", "count": 200, "size": 0.9, "speed": 1.1, "alpha": 0.42,
         "color": "#9ec4ff", "angle": 12},
    ], {"color": "#7bd4ff"}),
    _preset("aurora-snow", "极光雪原", "极光", "#03121f", "#0a3444", [
        {"kind": "bokeh", "count": 14, "size": 1.9, "speed": 0.3, "alpha": 0.18,
         "color": "#a78bfa"},
        {"kind": "aurora", "count": 70, "size": 1.9, "speed": 0.5, "alpha": 0.20,
         "color": "#4dffd0"},
        {"kind": "snow", "count": 90, "size": 1.0, "speed": 0.8, "alpha": 0.55,
         "color": "#ffffff"},
    ], {"color": "#9ef7e0"}),
    _preset("sakura", "樱落春溪", "春天", "#241726", "#6d3c52", [
        {"kind": "petal", "count": 70, "size": 1.0, "speed": 1.0, "alpha": 0.9,
         "color": "#ffc0d4"},
        {"kind": "firefly", "count": 18, "size": 1.0, "speed": 0.7, "alpha": 0.6,
         "color": "#ffe9a8"},
    ], {"color": "#ffd0e0"}),
    _preset("firefly-forest", "萤火森林", "森林", "#04120e", "#10331f", [
        {"kind": "bokeh", "count": 12, "size": 1.5, "speed": 0.3, "alpha": 0.26,
         "color": "#7dffb0"},
        {"kind": "firefly", "count": 70, "size": 1.2, "speed": 0.9, "alpha": 0.95,
         "color": "#c8ff9e"},
    ], {"color": "#b6ff9e"}),
    _preset("deepsea", "深海微光", "深海", "#001018", "#00384a", [
        {"kind": "aurora", "count": 50, "size": 2.0, "speed": 0.4, "alpha": 0.14,
         "color": "#00e5ff"},
        {"kind": "bubble", "count": 60, "size": 1.0, "speed": 1.0, "alpha": 0.5,
         "color": "#cfeeff"},
    ], {"color": "#7ff0ff"}),
    _preset("cyber-galaxy", "赛博星河", "赛博", "#04010d", "#1a0a2e", [
        {"kind": "star", "count": 80, "size": 1.0, "speed": 0.8, "alpha": 0.8,
         "color": "#ff8ae2"},
        {"kind": "warp", "count": 170, "size": 1.0, "speed": 1.1, "alpha": 0.9,
         "color": "#a9d6ff"},
    ], {"color": "#c9a6ff"}),
    _preset("hearth", "壁炉余烬", "暖调", "#140803", "#3a1405", [
        {"kind": "bokeh", "count": 10, "size": 1.6, "speed": 0.35, "alpha": 0.22,
         "color": "#ff5e00"},
        {"kind": "ember", "count": 80, "size": 1.0, "speed": 1.0, "alpha": 0.9,
         "color": "#ff8a3d"},
    ], {"color": "#ff8a3d"}),
    _preset("milkyway", "银河穿越", "太空", "#01030c", "#0a1230", [
        {"kind": "star", "count": 120, "size": 1.0, "speed": 0.9, "alpha": 0.7,
         "color": "#ffffff"},
        {"kind": "warp", "count": 220, "size": 1.0, "speed": 1.3, "alpha": 0.85,
         "color": "#dbe9ff"},
    ], {"color": "#cfe0ff"}),
    _preset("morning-mist", "晨雾微光", "极简", "#1b2430", "#4b5c6e", [
        {"kind": "aurora", "count": 60, "size": 2.0, "speed": 0.35, "alpha": 0.13,
         "color": "#ffd9a8"},
        {"kind": "bokeh", "count": 18, "size": 1.7, "speed": 0.3, "alpha": 0.32,
         "color": "#ffe4b8"},
    ], {"color": "#ffe9c0"}),
    _preset("golden", "金色庆典", "节日", "#191104", "#3d2a08", [
        {"kind": "firefly", "count": 60, "size": 1.0, "speed": 1.1, "alpha": 0.9,
         "color": "#ffd166"},
        {"kind": "meteor", "count": 6, "size": 1.0, "speed": 1.1, "alpha": 0.7,
         "color": "#fff2c0", "angle": 28},
    ], {"color": "#ffd166"}),
    _preset("meteor-night", "流星夜空", "夜空", "#02060f", "#101a3a", [
        {"kind": "star", "count": 90, "size": 1.0, "speed": 0.9, "alpha": 0.75,
         "color": "#cfe0ff"},
        {"kind": "meteor", "count": 16, "size": 1.1, "speed": 1.0, "alpha": 0.95,
         "color": "#ffffff", "angle": 30},
    ], {"color": "#bfd4ff"}),
    _preset("autumn", "秋日落叶", "秋", "#1d1206", "#5a3617", [
        {"kind": "bokeh", "count": 12, "size": 1.6, "speed": 0.3, "alpha": 0.24,
         "color": "#ffcf8a"},
        {"kind": "leaf", "count": 45, "size": 1.1, "speed": 1.0, "alpha": 0.95,
         "color": "#e0a556"},
    ], {"color": "#ffc27a"}),
]


def scene_get(sid: str) -> dict:
    fp = scene_path(sid)
    if not fp.is_file():
        raise FileNotFoundError("场景不存在")
    return json.loads(fp.read_text(encoding="utf-8"))


def scene_save(body: dict) -> dict:
    from fx import norm_scene as _norm

    name = (body.get("name") or "我的特效壁纸").strip()[:40] or "我的特效壁纸"
    cfg = body.get("cfg") or {}
    if not isinstance(cfg, dict):
        raise ValueError("配置格式错误")
    # 统一规范化：把 null / NaN / 字符串数字都变成干净的数值，
    # 否则写进 JSON 后引擎读出来会 float(None) 崩掉
    cfg = _norm(cfg)
    cfg["name"] = name
    sid = _scene_id(body.get("id") or "")
    if not sid:
        sid = "sc_" + hashlib.md5(
            f"{time.time()}{name}{random.random()}".encode()).hexdigest()[:10]
    fp = scene_path(sid)
    text = json.dumps(cfg, ensure_ascii=False, indent=2, allow_nan=False)
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, fp)

    thumb = str(body.get("thumb") or "")
    if thumb:
        if "," in thumb[:200]:
            thumb = thumb.split(",", 1)[1]
        try:
            data = base64.b64decode(thumb)
        except Exception:
            data = b""
        if 800 < len(data) < 4_000_000:
            ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
            for old in (".jpg", ".png"):
                try:
                    (scene_dir() / (sid + old)).unlink(missing_ok=True)
                except Exception:
                    pass
            (scene_dir() / (sid + ext)).write_bytes(data)
    return {"id": sid, "name": name, "mtime": int(fp.stat().st_mtime)}


def scene_apply(sid: str = "", cfg: dict | None = None, name: str = "") -> dict:
    if cfg:
        # 还没保存的草稿：写一个临时场景文件直接播
        tmp = scene_dir() / ".preview.json"
        cfg = dict(cfg)
        cfg["name"] = name or cfg.get("name") or "预览"
        tmp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        target, label = tmp, cfg["name"]
    else:
        target = scene_path(sid)
        if not target.is_file():
            raise FileNotFoundError("场景不存在")
        label = json.loads(target.read_text(encoding="utf-8")).get("name") or sid
    if not target.exists():
        raise FileNotFoundError("场景文件不存在")
    return _engine_spawn(["--scene", str(target)], label, target, "scene")


# ---------------------------------------------------------------- 轮播线程
class Rotator(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop_evt = threading.Event()

    def run(self):
        while not self.stop_evt.is_set():
            try:
                cfg = load_config()
                rot = cfg.get("rotate", {})
                minutes = int(rot.get("minutes") or 0)
                if rot.get("enabled") and minutes > 0:
                    if time.time() - float(rot.get("last_ts") or 0) >= minutes * 60:
                        files = [lib / i["name"] for i in list_library(library_dir())
                                 if not i["name"].lower().endswith(".mp4")]
                        if files:
                            pick = random.choice(files)
                            set_wallpaper(pick)
                            with _cfg_lock:
                                c = load_config()
                                c["rotate"]["last_ts"] = time.time()
                                shrink_history(c, {"path": str(pick), "title": pick.stem,
                                                   "ts": int(time.time()), "auto": True})
                                save_config(c)
            except Exception as e:
                log(f"轮播异常: {e}")
            self.stop_evt.wait(20)


# ---------------------------------------------------------------- 下载任务（带进度）
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def job_new() -> str:
    jid = hashlib.md5(f"{time.time()}{random.random()}".encode()).hexdigest()[:12]
    with JOBS_LOCK:
        JOBS[jid] = {"state": "running", "pct": 0, "msg": "准备下载…", "ts": time.time()}
        if len(JOBS) > 40:
            for k in sorted(JOBS, key=lambda x: JOBS[x].get("ts", 0))[:len(JOBS) - 30]:
                JOBS.pop(k, None)
    return jid


def job_set(jid: str, **kw) -> None:
    with JOBS_LOCK:
        if jid in JOBS:
            JOBS[jid].update(kw)


def job_get(jid: str) -> dict | None:
    with JOBS_LOCK:
        return dict(JOBS[jid]) if jid in JOBS else None


def run_set_job(jid: str, item: dict) -> None:
    def prog(got: int, total: int):
        job_set(jid, pct=min(99, int(got * 100 / total)) if total else 50,
                msg=f"下载中 {got/1048576:.1f}MB" + (f" / {total/1048576:.1f}MB" if total else ""))

    try:
        lib = library_dir()
        fp = download_image(item, lib, on_progress=prog)
        job_set(jid, pct=99, msg="正在设置桌面壁纸…")
        if dyn_status().get("running"):
            job_set(jid, pct=99, msg="正在关闭动态壁纸…")
            dyn_stop()
        ok = set_wallpaper(fp)
        with _cfg_lock:
            cfg = load_config()
            shrink_history(cfg, {"path": str(fp), "title": item.get("title") or fp.stem,
                                 "ts": int(time.time())})
            save_config(cfg)
        job_set(jid, state="done", pct=100, msg="已设为桌面壁纸", set=ok,
                path=str(fp), name=fp.name, ts=time.time())
    except Exception as e:
        log(f"设置壁纸失败: {e}")
        job_set(jid, state="error", msg=str(e), ts=time.time())


# ---------------------------------------------------------------- HTTP 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "WallpaperStudio/1.0"
    protocol_version = "HTTP/1.1"

    # ---------- 工具
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 500):
        self._json({"ok": False, "error": msg}, code)

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def log_message(self, fmt, *args):
        pass

    # ---------- GET
    def do_GET(self):
        try:
            u = urllib.parse.urlsplit(self.path)
            path, qs = u.path, urllib.parse.parse_qs(u.query)

            if path in ("/", "/index.html"):
                if not UI_FILE.exists():
                    return self._err("界面文件缺失: ui/index.html", 500)
                return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")

            if path == "/api/status":
                cfg = load_config()
                return self._json({"ok": True, "app": APP_ID, "library": str(library_dir()),
                                   "rotate": cfg.get("rotate", {}),
                                   "count": len(list_library(library_dir())),
                                   "dyn": dyn_status(),
                                   "dynCount": len(list_dynamic()),
                                   "proxy": wh_proxy() or "",
                                   "proxy_auto": sys_proxy() or "",
                                   "lan": bool(cfg.get("lan", True)),
                                   "port": self.server.server_address[1],
                                   "dataRoot": str(DATA_ROOT)})

            if path == "/api/daily":
                market = (qs.get("market") or ["zh-CN"])[0]
                n = max(1, min(8, int((qs.get("n") or ["8"])[0])))
                return self._json({"ok": True, "items": bing_daily(market, n)})

            if path == "/api/search":
                q = (qs.get("q") or [""])[0].strip()
                if not q:
                    return self._err("请输入关键词", 400)
                page = max(0, int((qs.get("page") or ["0"])[0]))
                size = (qs.get("size") or ["wallpaper"])[0]
                items = bing_search(q, page=page, size=size)
                return self._json({"ok": True, "items": items, "page": page})

            if path == "/api/wh":
                q = (qs.get("q") or [""])[0].strip()
                page = max(1, int((qs.get("page") or ["1"])[0]))
                sorting = (qs.get("sorting") or ["toplist"])[0]
                atleast = (qs.get("atleast") or [""])[0]
                categories = (qs.get("categories") or ["111"])[0]
                ratios = (qs.get("ratios") or [""])[0]
                items, meta = wallhaven_search(q, page, sorting, atleast, categories, ratios)
                return self._json({"ok": True, "items": items, "meta": meta, "page": page})

            if path == "/api/mx":
                slug = (qs.get("cat") or ["cat"])[0]
                page = max(1, int((qs.get("page") or ["1"])[0]))
                try:
                    items = mixkit_list(slug, page)
                except Exception as e:
                    return self._err(f"Mixkit 访问失败：{e}（可开启代理后重试）", 502)
                return self._json({"ok": True, "items": items, "page": page,
                                   "cats": [{"slug": s, "name": n} for s, n in MIXKIT_CATS],
                                   "hasMore": len(items) >= 12})

            if path == "/api/share":
                port = self.server.server_address[1]
                cfg = load_config()
                return self._json({"ok": True, "lan": bool(cfg.get("lan", True)),
                                   "port": port, "urls": lan_urls(port)})

            if path == "/api/library":
                return self._json({"ok": True, "items": list_library(library_dir())})

            if path == "/api/dyn/list":
                return self._json({"ok": True, "items": list_dynamic(), "state": dyn_status(),
                                   "dir": str(DYN_DIR), "ffmpeg": bool(find_ffmpeg())})

            if path == "/api/dyn/thumb":
                name = (qs.get("name") or [""])[0]
                try:
                    fp = dyn_thumb(name)
                except Exception as e:
                    return self._err(f"缩略图失败: {e}", 500)
                return self._send(200, fp.read_bytes(), "image/jpeg")

            if path == "/api/scene/presets":
                items = []
                for p in SCENE_PRESETS:
                    cfg = json.loads(json.dumps(p["cfg"]))
                    cfg["name"] = p["label"]
                    items.append({"id": p["id"], "label": p["label"], "tag": p["tag"],
                                  "hint": p["hint"], "cfg": cfg})
                return self._json({"ok": True, "items": items})

            if path == "/api/scene/list":
                d = library_dir()
                lib = []
                for i in list_library(d):
                    i["path"] = str(d / i["name"])
                    lib.append(i)
                return self._json({"ok": True, "items": list_scenes(), "state": dyn_status(),
                                   "lib": lib, "dir": str(scene_dir())})

            if path == "/api/scene/thumb":
                sid = _scene_id((qs.get("id") or [""])[0])
                for ext, ct in ((".jpg", "image/jpeg"), (".png", "image/png")):
                    fp = scene_dir() / (sid + ext)
                    if sid and fp.is_file():
                        return self._send(200, fp.read_bytes(), ct)
                return self._err("没有缩略图", 404)

            if path == "/api/scene/get":
                try:
                    cfg = scene_get((qs.get("id") or [""])[0])
                except Exception as e:
                    return self._err(str(e), 404)
                return self._json({"ok": True, "cfg": cfg})

            if path == "/api/job":
                j = job_get((qs.get("id") or [""])[0])
                if not j:
                    return self._err("任务不存在或已过期", 404)
                return self._json({"ok": True, **j})

            if path == "/api/history":
                return self._json({"ok": True, "items": load_config().get("history", [])})

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
                      ".svg": "image/svg+xml", ".woff2": "font/woff2"}.get(
                          fp.suffix.lower(), "application/octet-stream")
                return self._send(200, fp.read_bytes(), ct)

            if path == "/file":
                name = (qs.get("name") or [""])[0]
                lib = (DYN_DIR if (qs.get("dyn") or [""])[0] else library_dir()).resolve()
                fp = (lib / name).resolve()
                try:
                    fp.relative_to(lib)
                except ValueError:
                    return self._err("非法路径", 403)
                if not fp.is_file():
                    return self._err("文件不存在", 404)
                ctype = EXT_BY_TYPE.get("image" + fp.suffix.lower(), "application/octet-stream")
                if fp.suffix.lower() == ".mp4":
                    ctype = "video/mp4"
                return self._send(200, fp.read_bytes(), ctype)

            if path == "/proxy":
                target = (qs.get("u") or [""])[0]
                if not target.startswith(("http://", "https://")):
                    return self._err("非法地址", 400)
                return self._proxy(target)

            return self._err("未找到", 404)
        except Exception as e:
            log(f"GET {self.path} 失败: {e}")
            return self._err(str(e))

    def _proxy(self, target: str):
        key = hashlib.sha1(target.encode("utf-8")).hexdigest()
        cache_f = CACHE_DIR / key
        type_f = CACHE_DIR / (key + ".type")
        if cache_f.exists() and type_f.exists():
            return self._send(200, cache_f.read_bytes(),
                              type_f.read_text(encoding="utf-8") or "image/jpeg")
        try:
            px = wh_proxy() if is_wallhaven(target) else None
            data, ctype, _ = http_get(target, timeout=120 if px else 30, referer=origin_of(target),
                                      max_bytes=60 * 1024 * 1024, proxy=px)
        except Exception as e:
            return self._err(f"图片获取失败: {e}", 502)
        ctype = (ctype or "image/jpeg").split(";")[0]
        try:
            if len(data) < 12 * 1024 * 1024:
                cache_f.write_bytes(data)
                type_f.write_text(ctype, encoding="utf-8")
        except Exception:
            pass
        return self._send(200, data, ctype)

    # ---------- POST
    def do_POST(self):
        try:
            path = urllib.parse.urlsplit(self.path).path
            body = self._body_json()

            if path == "/api/set":
                return self._api_set(body)
            if path == "/api/upload":
                return self._api_upload(body)
            if path == "/api/rollback":
                return self._api_rollback()
            if path == "/api/rotate":
                return self._api_rotate(body)
            if path == "/api/openfolder":
                os.startfile(str(library_dir()))
                return self._json({"ok": True})
            if path == "/api/mx/dl":
                url = str(body.get("full") or "").strip()
                if not url.startswith("https://assets.mixkit.co/"):
                    return self._err("非法的视频地址", 400)
                item = {"full": url, "alt": str(body.get("alt") or ""),
                        "title": str(body.get("title") or "动态壁纸")}
                autoplay = bool(body.get("autoplay", True))
                jid = job_new()
                threading.Thread(target=run_dyn_job, args=(jid, item, autoplay),
                                 daemon=True).start()
                return self._json({"ok": True, "job": jid})

            if path == "/api/share":
                with _cfg_lock:
                    cfg = load_config()
                    cfg["lan"] = bool(body.get("lan", True))
                    save_config(cfg)
                port = self.server.server_address[1]
                return self._json({"ok": True, "lan": cfg["lan"], "port": port,
                                   "urls": lan_urls(port), "restart": True})

            if path == "/api/dyn/start":
                try:
                    st = dyn_start(str(body.get("name") or ""))
                except Exception as e:
                    return self._err(str(e), 500)
                return self._json({"ok": True, "state": {"running": True, **st}})
            if path == "/api/dyn/stop":
                dyn_stop()
                return self._json({"ok": True})
            if path == "/api/scene/upload":
                return self._api_scene_upload(body)
            if path == "/api/scene/save":
                try:
                    r = scene_save(body)
                except Exception as e:
                    log("保存场景失败：" + traceback.format_exc())
                    msg = str(e).strip() or type(e).__name__
                    if isinstance(e, PermissionError):
                        msg = "文件被占用或没有写入权限（" + msg + "）"
                    elif isinstance(e, OSError):
                        msg = "写入磁盘失败（" + msg + "）"
                    return self._err("保存失败：" + msg, 400)
                return self._json({"ok": True, **r})
            if path == "/api/log":
                msg = str(body.get("msg") or "")[:2000]
                if msg:
                    log("前端上报：" + msg)
                return self._json({"ok": True})
            if path == "/api/scene/delete":
                sid = _scene_id(body.get("id") or "")
                if not sid:
                    return self._err("缺少 id", 400)
                if (dyn_load().get("path") or "").endswith(sid + ".json"):
                    dyn_stop()
                for ext in (".json", ".jpg", ".png"):
                    try:
                        (scene_dir() / (sid + ext)).unlink(missing_ok=True)
                    except Exception:
                        pass
                return self._json({"ok": True})
            if path == "/api/scene/apply":
                sid = str(body.get("id") or "")
                cfg = body.get("cfg")
                try:
                    st = scene_apply(sid, cfg if isinstance(cfg, dict) else None,
                                     str(body.get("name") or ""))
                except Exception as e:
                    return self._err(str(e), 500)
                return self._json({"ok": True, "state": {"running": True, **st}})
            if path == "/api/scene/stop":
                dyn_stop()
                return self._json({"ok": True})
            if path == "/api/dyn/import":
                return self._api_dyn_import(body)
            if path == "/api/library/delete":
                return self._api_library_delete(body)
            if path == "/api/dyn/delete":
                name = str(body.get("name") or "")
                fp = (DYN_DIR / name).resolve()
                try:
                    fp.relative_to(DYN_DIR.resolve())
                except ValueError:
                    return self._err("非法文件名", 403)
                if not fp.is_file():
                    return self._err("文件不存在", 404)
                st = dyn_load()
                if st.get("name") == name:
                    dyn_stop()
                fp.unlink(missing_ok=True)
                return self._json({"ok": True})
            if path == "/api/dyn/opendir":
                os.startfile(str(DYN_DIR))
                return self._json({"ok": True})
            if path == "/api/shutdown":
                self._json({"ok": True})
                threading.Timer(0.4, lambda: os._exit(0)).start()
                return
            return self._err("未找到", 404)
        except Exception as e:
            log(f"POST {self.path} 失败: {e}")
            return self._err(str(e))

    def _api_library_delete(self, body: dict):
        names = body.get("names")
        targets = [str(x) for x in names] if isinstance(names, list) else \
            [str(body.get("name") or "")]
        dones, errs = [], []
        for n in targets:
            try:
                dones.append(library_delete(n))
            except Exception as e:
                errs.append({"name": n, "error": str(e)})
        if not dones and errs:
            msg = errs[0]["error"]
            return self._err(msg, 404 if "不存在" in msg else 400)
        return self._json({"ok": True, "deleted": dones, "errors": errs,
                           "freed": sum(d.get("size") or 0 for d in dones),
                           "count": len(list_library(library_dir()))})

    def _api_set(self, body: dict):
        url = (body.get("url") or "").strip()
        title = (body.get("title") or "").strip()
        if not url:
            return self._err("缺少图片地址", 400)
        item = {"full": url, "alt": "", "title": title or "壁纸"}
        jid = job_new()
        threading.Thread(target=run_set_job, args=(jid, item), daemon=True).start()
        return self._json({"ok": True, "job": jid})

    def _api_scene_upload(self, body: dict):
        """「自制壁纸」上传背景素材：只存进本地，不影响当前桌面壁纸"""
        name = (body.get("name") or "素材").strip()
        raw = body.get("data") or ""
        if "," in raw[:100]:
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            return self._err("数据解析失败", 400)
        if len(data) < 1000:
            return self._err("文件太小", 400)
        ext = Path(name).suffix.lower()
        stem = safe_name(Path(name).stem) or "素材"
        if ext in DYN_VIDEO_EXT:
            DYN_DIR.mkdir(parents=True, exist_ok=True)
            target = DYN_DIR / f"{stem}{ext}"
            i = 2
            while target.exists():
                target = DYN_DIR / f"{stem}_{i}{ext}"
                i += 1
            target.write_bytes(data)
            return self._json({"ok": True, "type": "video", "name": target.name,
                               "path": str(target)})
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif", ".gif"):
            ext = ".jpg"
        target = library_dir() / f"{time.strftime('%Y%m%d_%H%M%S')}_{stem}{ext}"
        target.write_bytes(data)
        return self._json({"ok": True, "type": "image", "name": target.name,
                           "path": str(target),
                           "url": "/file?name=" + urllib.parse.quote(target.name)})

    def _api_upload(self, body: dict):
        name = (body.get("name") or "本地图片").strip()
        raw = body.get("data") or ""
        if "," in raw[:100]:
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            return self._err("图片数据解析失败", 400)
        if len(data) < 1000:
            return self._err("文件太小", 400)
        ext = Path(name).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".mp4"):
            ext = ".jpg"
        if ext in (".mp4", ".gif"):
            # 视频 / 动图 直接进动态壁纸区
            return self._api_dyn_import(body)
        lib = library_dir()
        target = lib / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_name(Path(name).stem)}{ext}"
        target.write_bytes(data)
        if dyn_status().get("running"):
            dyn_stop()
        ok = set_wallpaper(target)
        with _cfg_lock:
            cfg = load_config()
            shrink_history(cfg, {"path": str(target), "title": target.stem,
                                 "ts": int(time.time())})
            save_config(cfg)
        return self._json({"ok": True, "set": ok, "path": str(target), "name": target.name})

    def _api_dyn_import(self, body: dict):
        name = (body.get("name") or "动态壁纸.mp4").strip()
        raw = body.get("data") or ""
        if "," in raw[:100]:
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw)
        except Exception:
            return self._err("数据解析失败", 400)
        if len(data) < 10000:
            return self._err("文件太小", 400)
        ext = Path(name).suffix.lower()
        if ext not in DYN_VIDEO_EXT:
            ext = ".mp4"
        target = DYN_DIR / f"{safe_name(Path(name).stem)}{ext}"
        i = 2
        while target.exists():
            target = DYN_DIR / f"{safe_name(Path(name).stem)}_{i}{ext}"
            i += 1
        target.write_bytes(data)
        log(f"导入动态壁纸 {target.name} {len(data)/1048576:.1f}MB")
        return self._json({"ok": True, "name": target.name, "video": True, "dyn": True, "set": False})

    def _api_rollback(self):
        cfg = load_config()
        hist = [h for h in cfg.get("history", []) if os.path.isfile(h.get("path", ""))]
        if not hist:
            return self._err("没有可回滚的记录", 400)
        # hist[0] 是当前，取下一张
        target = hist[1] if len(hist) > 1 else hist[0]
        ok = set_wallpaper(target["path"])
        with _cfg_lock:
            c = load_config()
            shrink_history(c, {"path": target["path"], "title": target.get("title", ""),
                               "ts": int(time.time())})
            save_config(c)
        return self._json({"ok": True, "set": ok, "name": Path(target["path"]).name,
                           "title": target.get("title", "")})

    def _api_rotate(self, body: dict):
        with _cfg_lock:
            cfg = load_config()
            rot = cfg.get("rotate", {})
            if "enabled" in body:
                rot["enabled"] = bool(body["enabled"])
                rot["last_ts"] = time.time()
            if "minutes" in body:
                rot["minutes"] = max(1, min(1440, int(body["minutes"])))
            cfg["rotate"] = rot
            save_config(cfg)
        return self._json({"ok": True, "rotate": rot})


# ---------------------------------------------------------------- 启动
def find_running() -> int | None:
    for port in range(8770, 8790):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25) as s:
                s.sendall(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                data = s.recv(600)
                if b"wallpaper-studio" in data:
                    return port
        except OSError:
            continue
    return None


def say(msg: str) -> None:
    """pythonw 下 sys.stdout 为 None，print 会崩，统一走这里"""
    log(msg)
    try:
        if sys.stdout is not None:
            print(msg)
    except Exception:
        pass


def start_server():
    """起 HTTP 服务（界面与局域网共用），返回 (server, port)"""
    Rotator().start()
    host = "0.0.0.0" if load_config().get("lan", True) else "127.0.0.1"
    for p in range(8770, 8790):
        try:
            return ThreadingHTTPServer((host, p), Handler), p
        except OSError:
            continue
    return None, 0


def _dpi_aware() -> None:
    """必须在建窗前声明 DPI 感知，否则 4K@200% 下窗口只有一半可见区域"""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _place_window(w: int, h: int) -> None:
    """窗口起来后自己精确摆位：规避 pywebview 各版本 DPI 折算不一致的问题"""
    time.sleep(1.0)
    u = ctypes.windll.user32
    try:
        sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    except Exception:
        return
    w = min(w, sw - 80)
    h = min(h, sh - 120)
    x, y = max(0, (sw - w) // 2), max(0, int((sh - h) * 0.36))
    pid = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _lp):
        p = ctypes.c_ulong()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value != pid or not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, b, n + 1)
            if b.value == "壁纸工坊":
                found.append(hwnd)
        return True

    u.EnumWindows(cb, 0)
    for hwnd in found:
        u.ShowWindow(hwnd, 9)                     # SW_RESTORE
        u.SetWindowPos(hwnd, 0, x, y, w, h, 0x0004 | 0x0040)
    say(f"窗口摆位 {w}x{h} @({x},{y})，命中 {len(found)} 个窗口")


def desktop_window(url: str) -> bool:
    """原生窗口模式：用 Edge WebView2 承载界面，就是普通桌面软件的样子。
    成功（窗口被关闭）返回 True；不可用返回 False，由调用方退回浏览器。"""
    try:
        import webview
    except Exception as e:            # 没装 pywebview / 缺 WebView2 运行时
        say(f"窗口模式不可用（{e}）")
        return False

    _dpi_aware()
    try:
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        sw, sh = 1920, 1080
    w = max(1180, min(int(sw * 0.66), 2700))
    h = max(760, min(int(sh * 0.80), 1760))

    icon = RES_DIR / "ui" / "icon.ico"
    say(f"创建桌面窗口，目标 {w}x{h}（屏幕 {sw}x{sh}）")
    try:
        webview.create_window("壁纸工坊", url,
                              width=w, height=h,
                              min_size=(880, 600),
                              background_color="#0b1020",
                              text_select=True)
        webview.start(_place_window, (w, h),
                      icon=str(icon) if icon.is_file() else None)
    except Exception as e:
        say(f"窗口启动失败：{e}")
        return False
    return True


def main():
    argv = sys.argv[1:]
    if "--dyn" in argv:
        # 打包版引擎模式：同一个 exe，带 --dyn 就当动态壁纸进程用
        import dynwall
        sys.argv = ["dynwall"] + [a for a in argv if a != "--dyn"]
        return dynwall.main()

    # 无控制台（--windowed）时 stdout 是 None，第三方库一 print 就崩，先接管
    if getattr(sys, "frozen", False) and sys.stdout is None:
        try:
            _f = open(APP_DIR / "shell.log", "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = _f
        except Exception:
            pass
    try:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    browser_only = "--browser" in argv

    port = find_running()
    if port:
        url = f"http://127.0.0.1:{port}/"
        say(f"已在运行：{url}")
        if not browser_only and desktop_window(url):
            return
        webbrowser.open(url)
        return

    server, port = start_server()
    if server is None:
        say("没有可用端口（8770-8789）")
        return

    url = f"http://127.0.0.1:{port}/"
    say(f"壁纸工坊已启动：{url}")
    for lan in lan_urls(port):
        say(f"局域网内其它设备可访问：{lan}")

    if browser_only:
        say("浏览器模式：关闭此窗口即退出服务。")
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return

    threading.Thread(target=server.serve_forever, daemon=True).start()
    if desktop_window(url):
        say("窗口已关闭，退出。")
        return

    # 窗口起不来（缺少 WebView2 运行时等）：退回浏览器，进程继续驻留
    say("已改用浏览器打开，关闭此窗口即退出服务。")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
