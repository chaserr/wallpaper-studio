#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 PyInstaller 的 onedir 产物打成发行 zip。

用法:
    python mkzip.py <版本> [发行根目录] [--name <zip 里的应用名>]

示例:
    python mkzip.py 1.2.0 ./release
    python mkzip.py 1.2.0 ./release --name MyApp

约定: 发行根目录下有一个应用目录（含 _internal/ 和 .exe）。
zip 内结构保持「解压出一个应用文件夹」，不要把文件散在根目录。
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def find_app_dir(root: Path) -> Path:
    if (root / "_internal").is_dir():
        return root
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "_internal").is_dir():
            return d
    raise SystemExit(f"没在 {root} 下找到打包产物（需要含 _internal 目录的应用文件夹）")


def main() -> None:
    args = [a for a in sys.argv[1:]]
    name = None
    if "--name" in args:
        i = args.index("--name")
        name = args[i + 1]
        del args[i:i + 2]

    ver = args[0] if args else "1.0.0"
    root = Path(args[1]) if len(args) > 1 else Path.cwd() / "release"
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    app = find_app_dir(root)
    slug = name or app.name
    dst = root / f"{slug}-v{ver}-win64.zip"
    if dst.exists():
        dst.unlink()

    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(app.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(app.parent))
                n += 1
                if n % 200 == 0:
                    print("packed", n, flush=True)

    size_mb = dst.stat().st_size / 1048576
    print(f"files {n}")
    print(f"path  {dst}")
    print(f"size  {size_mb:.1f} MB")
    if any(ord(c) > 127 for c in dst.name):
        print("提示: 文件名含非 ASCII 字符，gh release upload 可能静默丢弃，建议用 --name 指定英文名")


if __name__ == "__main__":
    main()
