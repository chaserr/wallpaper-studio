# 踩坑清单

按「现象 → 根因 → 修法」记，都是真机上真出现过的。多数不只适用于这个项目，凡是「Python 服务 + 本地 UI + 打包发布」的组合都会撞上。

## 一、界面与接口

### 1. 图库里所有缩略图都是灰的，但接口 200

**现象**：列表项数量正确、文件名正确，图片一张都不显示。

**根因**：前端给缩略图统一套了外链代理 `px(url)` → `/proxy?u=...`，而 `/proxy` 只接受 `http(s)` 开头的地址，本地 `/file?name=xxx` 被判定非法直接 400。

**修法**：按 URL 类型分流，不要把「本机地址」和「外链」混在一个包装函数里。

```js
const raw = it.thumb || it.url || '';
const thumb = /^(https?:)?\/\//i.test(raw) ? px(raw) : raw;
```

### 2. 图片能下来但浏览器不渲染

**现象**：`curl` 拿到 200 和完整字节，浏览器 `<img>` 却空白。

**根因**：MIME 表用 MIME 字符串做 key（`{"image/jpeg": ".jpg"}`），查询时却拼了扩展名去查（`EXT_BY_TYPE.get("image" + ".jpg")` → 查的是 `image.jpg`），永远 miss，回落成 `application/octet-stream`。

**修法**：另建一张「扩展名 → MIME」正向表，别复用反向表。反向表用来「从 Content-Type 猜扩展名」，不能拿来「从扩展名取 Content-Type」。

### 3. 保存成功提示了，但文件没变 / 引擎崩了

**现象**：点保存，界面打勾「已保存」，重启后参数还是旧的。

**根因**：前端 `+undefined` 算出 `NaN` → `JSON.stringify` 变 `null` → 后端 `float(None)` 抛 `TypeError` → 被外层 `except` 吞掉 → 前端只看 HTTP 200 就提示成功。

**修法**（三件事一起做）：

- 后端每个数值都过 `num(v, default, lo, hi)`，`None` / `NaN` / `"abc"` 一律回默认值
- 写盘用临时文件 + `os.replace`，`json.dump(..., allow_nan=False)`
- 前端 `api()` 要检查 `j.ok`，不能只看状态码

### 4. 切 tab 后列表被旧数据覆盖

**现象**：点「每日精选」再快速点「我的图库」，最终显示的是每日精选。

**根因**：两个请求并发，慢的那个后到，直接覆盖了 `state.items` 并重渲染。

**修法**：全局递增序号，回包时比对。

```js
const my = (state.seq = (state.seq || 0) + 1);
const j = await api(url);
if (my !== state.seq) return;
```

### 5. 载入预设后总残留一层默认特效

**现象**：套用「极光雪原」，画面上还飘着雨。

**根因**：预设只覆盖它自己声明的字段，默认场景里 `fx.rain.on = true` 没被关掉。

**修法**：载入前先把所有开关显式置 false，再逐条应用预设；或者让预设包含完整字段。

## 二、图形与渲染

### 6. ffmpeg 预乘后颜色发灰

**现象**：羽化遮罩合并后，边缘变成灰白，颜色被洗掉。

**根因**：`premultiply` 滤镜按 bt709 矩阵处理，非 RGB 空间的素材会被改色。

**修法**：手动按 alpha 预乘，保住原色。

```
geq=r='r(X,Y)*alpha(X,Y)/255':g='g(X,Y)*alpha(X,Y)/255':b='b(X,Y)*alpha(X,Y)/255':a='alpha(X,Y)'
```

### 7. 幂函数算亮度时偶发崩溃

**现象**：某些帧上渲染线程抛异常，画面卡住。

**根因**：`(0.45 + 0.55*sin(t)) ** 1.2`，当 sin 为负时底数为负，分数次幂在 Python 里返回复数（js 里是 NaN）。

**修法**：先夹紧再取幂：`max(0.0, 0.45 + 0.55*math.sin(t)) ** 1.2`。

### 8. 鼠标视差总慢半拍

**现象**：鼠标动了，画面滞后一帧才跟上。

**根因**：主循环里「先画背景、后轮询鼠标」，用到的永远是上一帧的坐标。

**修法**：把 `poll_mouse()` 提到渲染之前，一帧内先取状态再画。

## 三、打包

### 9. 打包时删不掉旧的 dist 目录

**现象**：`pyinstaller` 报无法删除 `dist/app/` 下的文件。

**根因**：安全软件 / 目录被占用 / 系统的删除保护，直接清空旧产物被拦。

**修法**：每次打到**新的** distpath（`out2`、`out3`…），或先 `mv` 旧目录再打。别跟删除较劲。

### 10. 源码能跑，打包版启动就闪退

**排查顺序**（按命中率）：

1. 资源路径——`RES_DIR = Path(sys._MEIPASS)` 还是 `Path(__file__).parent`，两个分支都要正确
2. `hiddenimports`——动态 import 的模块（`webview.platforms.winforms`）不会被自动收集
3. 数据文件——`datas=[('ui', 'ui')]` 写的是相对 spec 的路径，容易指错
4. 用 `--console` 打一次看报错，别用 `console=False` 猜

### 11. 打包版跑起来后进程秒退

**现象**：GUI 模式（无控制台）双击后什么也没发生。

**根因**：`console=False` 下任何未捕获异常都无声无息。

**修法**：在主入口最外层包 `try/except`，把 traceback 写进 `app.log`；发版前用 `--browser` 之类能观察的模式跑一遍。

## 四、发布与协作工具

### 12. `gh release upload` 中文文件名被吞

**现象**：上传 `壁纸工坊-v1.0.0.zip`，资产列表里没有这个文件，也没报错。

**修法**：资产名一律用 ASCII（`WallpaperStudio-v1.0.0-win64.zip`）。删除资产时用 API，避免 `-` 开头被当成 flag：

```bash
gh api -X DELETE repos/{owner}/{repo}/releases/assets/{asset_id}
```

### 13. `git push` 502 Bad Gateway

**根因**：shell 里残留的 `https_proxy` 指向一个已经退出的本地代理，git 走了它。

**修法**：单次清除代理配置再推，不要改全局配置。

```bash
git -c http.proxy= -c https.proxy= push origin main
```

### 14. Git Bash 下 `robocopy /E` 变成路径 `E:\`

**根因**：MSYS 把 `/E` 当成盘符路径转换了。

**修法**：用 `//E` 双斜杠，或干脆改用 PowerShell 的 `Copy-Item -Recurse -Force`。

## 五、自动化验收

### 15. 无头浏览器截图永远不生成

**现象**：`msedge --headless --screenshot` 加 `--virtual-time-budget` 后卡住，文件不出现。

**根因**：页面里有常驻 `requestAnimationFrame`（canvas 动画）时，虚拟时间永远不会「走完」。

**修法**：截静态页面；必须截动画页就改成「打开 → 固定延时 → 用 CDP 截图」，别指望 `--virtual-time-budget`。

### 16. 截图里带了开发机的绝对路径

**现象**：界面底部有一行「程序目录 D:\Xxx 素材目录 E:\Yyy」，截图发出去就泄露了本地目录结构。

**修法**：截图前裁剪掉，或把这类信息做成可折叠的「详情」；公开仓库的图一定要重新看一遍底部。
