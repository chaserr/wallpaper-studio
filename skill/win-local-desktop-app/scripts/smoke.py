#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打包后冒烟测试：起进程 → 等端口 → 打关键接口 → 收尸。

用法:
    python smoke.py <exe 或启动命令> [--port 8770] [--path /api/status] [--args "--browser"] [--timeout 30]

示例:
    python smoke.py out/app/app.exe
    python smoke.py out/app/app.exe --port 8770 --path /api/status
    python smoke.py -- python app.py --browser          # 也可以测源码

只依赖标准库。退出码 0 = 通过，1 = 失败（会打印原因）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def fetch(url: str, timeout: float = 3.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "smoke/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(2048).decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="要启动的可执行文件或命令")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--path", default="/api/status")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--uri", default="http://127.0.0.1:{port}")
    ns = ap.parse_args()

    cmd = [c for c in ns.cmd if c != "--"]
    if not cmd:
        print("用法: python smoke.py <exe> [--port 8770]")
        return 1

    if port_open("127.0.0.1", ns.port):
        print(f"✗ 端口 {ns.port} 已被占用，先关掉已在运行的实例")
        return 1

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    print(f"→ 启动: {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, **kwargs)

    try:
        # 1. 等端口
        while time.time() - t0 < ns.timeout:
            if proc.poll() is not None:
                out = (proc.stdout.read() or b"").decode("utf-8", "replace")
                print(f"✗ 进程提前退出（code={proc.returncode}）\n{out[:2000]}")
                return 1
            if port_open("127.0.0.1", ns.port):
                break
            time.sleep(0.4)
        else:
            print(f"✗ {ns.timeout}s 内端口 {ns.port} 没起来")
            return 1

        boot = time.time() - t0
        print(f"✓ 端口就绪，用时 {boot:.1f}s")

        # 2. 打首页
        base = ns.uri.format(port=ns.port)
        try:
            code, body = fetch(base + "/")
            if code != 200 or len(body) < 200:
                print(f"✗ 首页异常: {code}, {len(body)} 字节")
                return 1
            print(f"✓ 首页 200（{len(body)}+ 字节）")
        except Exception as e:
            print(f"✗ 首页请求失败: {e}")
            return 1

        # 3. 打关键接口
        try:
            code, body = fetch(base + ns.path)
            data = json.loads(body)
            if not data.get("ok"):
                print(f"✗ {ns.path} 返回 ok=false: {body[:300]}")
                return 1
            keys = ", ".join(list(data)[:6])
            print(f"✓ {ns.path} ok（{keys}…）")
        except Exception as e:
            print(f"✗ {ns.path} 失败: {e}")
            return 1

        # 4. 存活检查：接口打完再等几秒，确认没崩
        time.sleep(3)
        if proc.poll() is not None:
            out = (proc.stdout.read() or b"").decode("utf-8", "replace")
            print(f"✗ 3s 后进程已退出\n{out[:2000]}")
            return 1
        print("✓ 3s 后进程仍存活")

        if sys.platform == "win32":
            netsh = ["taskkill", "/PID", str(proc.pid), "/T", "/F"]
            subprocess.run(netsh, capture_output=True)
        else:
            proc.terminate()

        print("\n全部通过。")
        return 0

    finally:
        if proc.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                else:
                    proc.kill()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
