# 从 0 到发布：一个本地桌面工具的实战总结

这个目录是 [壁纸工坊](../README.md) 做完之后反向提炼的——把「从一句话需求到 GitHub Release」这一整条路上真正有用的东西抽出来，去掉和壁纸相关的部分，剩下能复用的。

两种形态，按需取：

| 文件 | 适合 |
| --- | --- |
| [`PROMPT.md`](PROMPT.md) | 想直接开工。整段复制给 AI，换成你自己的项目描述即可 |
| [`win-local-desktop-app/`](win-local-desktop-app/) | 想要能落地的脚手架。带可运行的骨架代码、踩坑清单、发布清单 |

## skill 里有什么

```
win-local-desktop-app/
├── SKILL.md                      七个阶段的方法论（架构决策 → 发布）
├── assets/app-skeleton/          可运行的骨架：python app.py 就能看到界面
│   ├── app.py                    服务 + 路由 + 配置原子写 + 数值清洗
│   ├── ui/index.html             单文件界面（含竞态令牌、错误上报）
│   ├── app.spec                  PyInstaller onedir 配置
│   ├── start.bat / .gitignore
│   └── README.md                 三步跑起来 + 改造成自己的工具
├── scripts/
│   ├── smoke.py                  打包后冒烟：起进程 → 等端口 → 打接口 → 收尸
│   └── mkzip.py                  发行 zip（保持「解压出一个文件夹」）
└── references/
    ├── win32-notes.md            壁纸 / 回收站 / DPI / WorkerW 的 ctypes 片段
    ├── pitfalls.md               16 个真实踩过的坑，按现象→根因→修法
    └── release-checklist.md      发版清单
```

## 骨架是真的能跑的

```bash
cp -r win-local-desktop-app/assets/app-skeleton ~/my-tool
cd ~/my-tool
python app.py            # 桌面窗口；没装 pywebview 就开浏览器
```

打包与验证：

```bash
pyinstaller --noconfirm --distpath out --workpath work app.spec
python ../scripts/smoke.py out/MyApp/MyApp.exe
python ../scripts/mkzip.py 0.1.0 out --name MyApp
```

## 安装成 WorkBuddy skill（可选）

把 `win-local-desktop-app/` 整个复制到 `~/.workbuddy/skills/` 下，之后遇到「做个 Windows 小工具」这类需求会自动命中。

## 为什么值得单独整理

做壁纸工坊的过程中，真正耗时的不是写功能，而是这些：

- 界面提示「保存成功」，但引擎其实崩了（`null` 一路传到 `float()`）
- 图库里所有缩略图全灰，因为本机地址被套进了只接受 http 的外链代理
- 图片 200 拿到了但浏览器不渲染，因为 MIME 表用错了键
- 打包版一闪而过，因为 `console=False` 把 traceback 吞了
- `gh release upload` 中文文件名被静默丢弃

这些坑和壁纸毫无关系，凡是「Python 服务 + 本地 UI + 打包发布」都会遇到。写在 `pitfalls.md` 里，下次直接跳过。

## 许可

和主项目一致，MIT。
