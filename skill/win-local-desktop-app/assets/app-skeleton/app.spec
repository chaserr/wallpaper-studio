# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

用法:
    pyinstaller --noconfirm --distpath out --workpath work app.spec

要点:
    · windowed 模式（console=False）下任何未捕获异常都无声无息，
      所以 app.py 的入口要把 traceback 写进日志
    · data 路径是相对本 spec 文件所在目录
    · 没装 pywebview 时下面的 hiddenimports 只会告警，不影响打包
"""

datas = [('ui', 'ui')]
hiddenimports = [
    'webview.platforms.winforms',   # 动态 import，不会被自动收集
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MyApp',
    debug=False,
    strip=False,
    upx=True,
    console=False,          # 调试打包问题时临时改 True，能直接看到报错
    icon='ui/icon.ico',     # 没有图标就删掉这行
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='MyApp',
)
