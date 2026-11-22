# 骨架说明

把这个目录整个复制走，改个名字就是新项目。

```
app.py          HTTP 服务 + JSON API + 配置读写 + 单实例检测
ui/index.html   单文件界面（含样式与脚本）
start.bat       Windows 启动脚本
app.spec        PyInstaller onedir 打包配置
.gitignore      已经排掉日志、配置、打包产物
```

## 三步跑起来

```bat
python app.py            :: 桌面窗口（没装 pywebview 就自动开浏览器）
python app.py --browser   :: 强制浏览器模式，方便调试
```

## 改造成自己的工具

1. `APP_ID` / `APP_VER` 换成自己的名字
2. `detect_data_root()` 里的目录名换掉（默认 `E:\MyAppData`，没有 E 盘落 `图片\MyAppData`）
3. `list_items()` 换成自己的数据源
4. 在 `do_GET` / `do_POST` 的「在这里扩展」位置按同样的形状加路由
5. 界面改 `ui/index.html`——每次请求都从磁盘读，改完刷新即可

## 打包

```bat
pyinstaller --noconfirm --distpath out --workpath work app.spec
python ..\..\scripts\smoke.py out\MyApp\MyApp.exe
python ..\..\scripts\mkzip.py 0.1.0 out --name MyApp
```

## 必须保住的三条约定

- 接口永远返回 `{"ok": true/false, ...}`，错误信息写给用户看，不写错误码
- 任何来自前端的数值都过 `num()`
- 写配置用 `os.replace` 原子替换

这三条是这个骨架能长期迭代、不出现「提示成功但其实失败了」的根本原因。
