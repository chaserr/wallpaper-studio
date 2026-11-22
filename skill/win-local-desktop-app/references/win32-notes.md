# Win32 / ctypes 常用片段

全部只用标准库，复制即用。每个都包了 `try/except`——Win32 调用失败应该是降级，不是崩溃。

## DPI 感知（建窗之前调用）

不做这一步，4K + 200% 缩放下窗口只画到屏幕的四分之一，或者坐标全错。

```python
import ctypes

def set_dpi_aware() -> None:
    """必须在创建任何窗口之前调用。"""
    try:  # Win10 1703+，per-monitor v2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:  # Win8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:  # 老系统
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
```

判断当前缩放比例（用于把逻辑尺寸换成物理像素）：

```python
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
```

## 设置桌面壁纸

```python
import winreg

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x01, 0x02

def set_wallpaper(path: str) -> bool:
    # 先固定填充方式，否则不同机器上会变拉伸/平铺
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, "10")  # 10=填充
            winreg.SetValueEx(k, "TileWallpaper", 0, winreg.REG_SZ, "0")
    except OSError:
        pass
    return bool(ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE))
```

`.mp4` 之类的视频文件不能用这个接口，要自己做层（见下面 WorkerW）。

## 删除文件到回收站（可还原）

比 `os.remove` 友好得多，用户删错了能在回收站找回来。

```python
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p),
                ("wFunc", ctypes.c_uint),
                ("pFrom", ctypes.c_wchar_p),
                ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", ctypes.c_int),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p)]

def send_to_recycle_bin(fp) -> bool:
    FO_DELETE = 3
    FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_SILENT, FOF_NOERRORUI = 0x0040, 0x0010, 0x0004, 0x0400
    try:
        op = _SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = str(fp.resolve()) + "\0\0"      # 必须以双 \0 结尾，坑点
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return rc == 0 and not op.fAnyOperationsAborted and not fp.exists()
    except Exception:
        return False
```

失败返回 `False`，由调用方决定是否硬删。目录必须是已存在的绝对路径。

## 把窗口铺到桌面图标之下（动态壁纸）

思路：`Progman` 下有 `WorkerW` 层，找到承载桌面图标的那一层，把自己的窗口 `SetParent` 上去。

```python
def find_workerw() -> int:
    """返回承载桌面图标的 WorkerW 句柄，找不到返回 0。"""
    u = ctypes.windll.user32
    progman = u.FindWindowW("Progman", None)
    # 0x111 是 WM_USER，0x7E9 是 0x052C... 惯例用 0x052C 让 Progman 派生 WorkerW
    u.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, None)
    found = ctypes.c_void_p()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _):
        shell = u.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
        if shell:
            worker = u.FindWindowExW(0, hwnd, "WorkerW", None)
            if worker:
                found.value = worker
                return False
        return True

    u.EnumWindows(_cb, 0)
    return found.value or 0
```

`SetParent(my_hwnd, workerw)` 之后窗口就沉到图标下面了。注意：Windows 11 某些版本 `WorkerW` 的层级会变，拿不到时降级成普通全屏窗口并记录日志。

## 其他容易忘的

- `os.startfile(path)` 用资源管理器打开目录，比 `subprocess` 干净
- 单实例检测：先 `socket.connect(("127.0.0.1", port))` 探一下，通了就说明已在运行，直接把 URL 丢给浏览器
- `ctypes.windll.user32.MessageBoxW(0, "文本", "标题", 0)` 做最简单的错误弹窗，不用 tkinter
- 读系统代理：`winreg` 的 `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings` 下 `ProxyServer` / `ProxyEnable`
