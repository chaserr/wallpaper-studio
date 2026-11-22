---
name: win-local-desktop-app
description: 用 Python 标准库从零做一个 Windows 本地优先（local-first）桌面工具——单个 HTTP 服务 + Web UI + pywebview 窗口 + ctypes/Win32 原生能力，零第三方依赖，数据全留在本机；再打包成 PyInstaller onedir 免安装包并发布到 GitHub Release。当用户要一个「没有广告、没有账号、不上传数据」的 Windows 小工具（壁纸、下载器、批量改名、本地看板、文件整理器）时使用。
agent_created: true
---

# 用标准库做一个 Windows 本地桌面工具，并发布出去

## 适用场景

用户要的东西有这些特征时用本流程：

- 单机、个人的小工具，不需要服务器、不需要账号
- 要有一块能长期迭代的界面（图片墙、列表、表单、参数面板）
- 需要碰 Windows 原生能力（换壁纸、写注册表、改文件、调 Win32 API）
- 交付形态是「解压双击就能用」的 exe，而不是让用户装 Python
- 明确的卖点是**没有广告、不上传、数据在自己硬盘上**

不适用：需要多人协作 / 云端同步 / 高并发后端的项目。

## 架构决策：为什么走 HTTP + 浏览器界面

桌面 GUI 框架（Tkinter / Qt / WinForms）在「漂亮的图片墙 + 实时参数预览」这类需求上成本极高，而且每加一个界面细节都要重新打包。本流程采用的组合是：

```
Python 进程（无第三方依赖）
├── ThreadingHTTPServer  →  127.0.0.1:8770   静态 UI + JSON API
├── pywebview 窗口（可选）→  失败就自动退化成浏览器标签页
└── ctypes / Win32       →  换壁纸、回收站、DPI、窗口层级
```

好处：界面用 HTML/CSS 写，改一行刷新就见效，不用重新打包。代价是进程里多一个 HTTP server——对单机工具完全可接受。

**关键约定：UI 每次请求都从磁盘读**（`UI_FILE.read_bytes()`），不要缓存到内存。这样改完 HTML/JS 刷新即生效，源码调试和打包版行为一致。

## 从 0 到发布的七个阶段

### 1. 定数据目录，先容器化路径

程序与数据分离。启动时探测一次，写进配置，之后所有路径都从它派生：

```python
def _detect_data_root() -> Path:
    env = os.environ.get("MYAPP_DATA_ROOT")      # 允许覆盖，方便测试
    if env:
        return Path(env)
    for drive in ("E:", "D:"):
        if Path(drive + "\\").exists():
            return Path(drive + "\\MyAppData")
    return Path(os.path.expanduser("~")) / "Pictures" / "MyAppData"
```

用户能一眼看到、能用资源管理器打开、拷走就能换机器——这是「数据是自己的」这句话的物理基础。

### 2. 先写服务骨架，接口一律返回 JSON

```python
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  self._route("GET")
    def do_POST(self): self._route("POST")
```

所有响应统一形状：成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": "人能看懂的原因"}`。前端只写一个 `api()` 函数解析，错误提示直接来自后端，不用在前端翻译错误码。

起始骨架见 `assets/app-skeleton/`，可直接复制改名。

**端口要重试**：从 8770 往上试十个端口，全占就说人话退出；启动前先探测「已在运行」，避免用户双击两次开两个实例。

### 3. 界面：一个文件搞定

`ui/index.html` 单文件装 HTML + CSS + JS，状态放一个 `state` 对象。列表渲染用模板字符串，事件用委托（`grid.addEventListener('click', ...)` 判断 `data-act`），避免每次重渲染后重新绑事件。

对异步列表必须加**竞态令牌**：快速切 tab 时，晚到的响应不能覆盖当前页。

```js
const my = (state.seq = (state.seq || 0) + 1);
const j = await api('/api/items');
if (my !== state.seq) return;      // 已经有更新的请求，丢弃
```

### 4. 接 Windows 原生能力（ctypes）

三个高频动作的可用写法在 `references/win32-notes.md`：设置壁纸、丢回收站、声明 DPI 感知。两条硬规则：

- 在**建窗之前**声明 DPI 感知，否则 4K@200% 下窗口只画一半
- 任何 Win32 调用都要包 `try/except`，失败降级而不是崩掉整个进程

### 5. 参数一律做数值清洗

这是最容易翻车的地方：前端某个滑块算出 `NaN`，`JSON.stringify` 变成 `null`，后端 `float(None)` 抛 `TypeError`，异常被外层 `except` 吞掉，界面却提示「保存成功」。

顺序是：**后端清洗 → 前端校验 → 双端默认值一致**。

```python
def num(v, default, lo=None, hi=None):
    try:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return default
    except (TypeError, ValueError):
        return default
    if lo is not None and f < lo: return lo
    if hi is not None and f > hi: return hi
    return f
```

写盘用「临时文件 + `os.replace`」保证原子性，`json.dump(..., allow_nan=False)` 保证不会写出非法 JSON。

### 6. 打包成免安装包

PyInstaller `onedir`（不是 `onefile`）：启动快、杀毒误报少、`_internal` 里能替换文件排查问题。

```bat
pyinstaller --noconfirm --distpath out --workpath work app.spec
```

打包后**必须**验证三件事，见 `scripts/smoke.py`：进程起得来、端口能通、核心接口返回 200。源码能跑不代表打包能跑——资源路径、hiddenimports 都可能出问题。

### 7. 发布

```bash
python scripts/mkzip.py 1.0.0 ./release
gh release create v1.0.0 release/*.zip --title "v1.0.0 · 一句话说清这版改了什么" --notes "..."
gh release view v1.0.0 --json assets --jq '.assets[] | "\(.name) \(.size)"'   # 校验资产真的传上去了
```

发布说明写「修了什么 / 加了什么 / 去掉了什么」三段，比罗列 commit 有用。完整清单见 `references/release-checklist.md`。

## 交付前的自检

- [ ] 干净机器（无 Python）双击 exe 能起来
- [ ] 拔掉网线，除联网功能外全部可用
- [ ] `config.json` / 日志 / 二进制资源都在 `.gitignore` 里
- [ ] 源码里没有硬编码的开发机绝对路径
- [ ] 所有写文件的接口在参数非法时返回 4xx 而不是 500
- [ ] 出错的路径会给用户一句人话，而不是 `Traceback`
- [ ] 同一份代码路径下，源码运行与打包运行的资源目录都正确（`RES_DIR` 分支）

## 已知坑

真实踩过的 14 个坑和根因分析在 `references/pitfalls.md`，动手前先扫一遍，能省几个小时。

## 资源

- `assets/app-skeleton/` — 可直接改名使用的骨架（服务 + UI + 启动脚本 + spec）
- `scripts/mkzip.py` — 发行 zip 打包（deflate，可指定根目录）
- `scripts/smoke.py` — 打包后冒烟：起进程、等端口、打接口、超时收尸
- `references/win32-notes.md` — 壁纸 / 回收站 / DPI / WorkerW 的 ctypes 片段
- `references/pitfalls.md` — 踩坑清单
- `references/release-checklist.md` — 发布清单
