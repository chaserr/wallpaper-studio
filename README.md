# 壁纸工坊 · Wallpaper Studio

一个跑在 Windows 本机的桌面壁纸工具：找图、存图、换壁纸，外加一个能自己做粒子特效壁纸的工作室。
界面是 pywebview 原生窗口，后端只有 Python 标准库，数据全部留在本地。

## 功能

- **必应每日精选**：拉取必应每日一图，可选 4K
- **必应图片搜索**：任意关键词，可筛「壁纸级大图」，下滑自动翻页
- **Wallhaven 高清**：分类 / 分辨率 / 排序筛选（需系统代理）
- **我的图库**：所有设为壁纸的图都会存进本地图库
  - 一键设为桌面壁纸
  - 删除（二次确认 → 移入 Windows 回收站，可还原）
  - 定时轮播、上一张回滚
- **动态壁纸**：导入本机 mp4/webm/GIF，或从 Mixkit 在线素材库挑免费视频，
  用 WorkerW 铺到桌面图标之下，自带 30fps 左右的 ffmpeg 视频解码
- **特效壁纸 · 自制**：背景（渐变/图片/视频）+ 粒子（雨、雪、花瓣、萤火虫、气泡、
  火星、星光、落叶）+ 鼠标互动（跟随光晕、点击涟漪）+ 时钟文字，参数实时预览，
  可保存成「场景」随时套用

## 运行

```bat
python app.py          :: 桌面窗口
python app.py --browser  :: 退化成浏览器标签页（没有 WebView2 时）
```

没有 pywebview 时会自动回退到浏览器模式，所以最小依赖是「有 Python 就行」。

## 依赖

| 用途 | 依赖 | 是否必需 |
| --- | --- | --- |
| 原生桌面窗口 | `pywebview` + `pythonnet` | 可选，缺失则用浏览器 |
| 动态壁纸解码 | `imageio-ffmpeg` 提供的 `ffmpeg.exe` | 可选，缺失则动态壁纸不可用 |

`vendor/` 目录放的是打包用的 ffmpeg 二进制，体积大，未入库。想启用动态壁纸，可以：

```bat
pip install imageio-ffmpeg
```

或把 `ffmpeg.exe` 放到 `vendor\imageio_ffmpeg\binaries\` 下，或直接装进系统 PATH。

## 目录结构

```
app.py            HTTP 服务 + 壁纸设置 + 图库/场景/动态壁纸接口 + 桌面窗口
dynwall.py        动态壁纸引擎（WorkerW 层 + ffmpeg rawvideo 管道）
fx.py             特效壁纸渲染引擎（GDI/AlphaBlend/粒子/涟漪/文字）
ui/index.html     主界面（单文件，含样式与脚本）
ui/studio.js      自制特效壁纸的参数面板与 Canvas 预览
ui/studio.css
_mkicon.py        纯标准库生成 icon.ico
start.bat         Windows 启动脚本
```

壁纸与场景数据不在仓库里，默认存于 `E:\Wallpapers`（无 E 盘则落到 `图片\Wallpapers`），
可用环境变量 `WALLPAPER_DATA_ROOT` 覆盖。

## 打包

```bat
pyinstaller --noconfirm --distpath _build --workpath _build/work _build\壁纸工坊.spec
```
