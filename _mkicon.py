# -*- coding: utf-8 -*-
"""生成 ui/icon.ico（纯标准库，圆角矩形渐变 + 星点粒子）"""
import math
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent / "ui" / "icon.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 4  # 超采样倍数

C1 = (0x2A, 0x4B, 0xE0)   # 深蓝
C2 = (0x4C, 0x6B, 0xFF)   # 主蓝
C3 = (0x8B, 0x5C, 0xF6)   # 紫


def lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def grad(u, v):
    t = max(0.0, min(1.0, (u * 0.55 + v * 0.75)))
    return lerp(C1, C2, t / 0.72) if t < 0.72 else lerp(C2, C3, (t - 0.72) / 0.28)


def rounded_alpha(u, v, m=0.035, r=0.215):
    """圆角矩形内部为 1，外部 0（含 1px 级软边由超采样兜住）"""
    x0, x1 = m, 1 - m
    if u < x0 or u > x1 or v < x0 or v > x1:
        return 0.0
    cx = min(max(u, x0 + r), x1 - r)
    cy = min(max(v, x0 + r), x1 - r)
    d = math.hypot(u - cx, v - cy)
    if d <= r:
        return 1.0
    return 0.0


def star(u, v, cx, cy, r, sharp=0.42):
    """四角星（超椭圆反向），返回覆盖强度"""
    dx = abs(u - cx) / r
    dy = abs(v - cy) / r
    if dx > 1 or dy > 1:
        return 0.0
    k = dx ** sharp + dy ** sharp
    if k <= 1.0:
        return 1.0 - k * 0.15
    return 0.0


def dot(u, v, cx, cy, r):
    d = math.hypot(u - cx, v - cy)
    return max(0.0, 1.0 - d / r) ** 0.6 if d < r else 0.0


def render(size):
    w = h = size
    ss = SS
    px = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            r = g = b = a = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    u = (x + (sx + 0.5) / ss) / w
                    v = (y + (sy + 0.5) / ss) / h
                    al = rounded_alpha(u, v)
                    if al <= 0:
                        continue
                    col = grad(u, v)
                    # 星点粒子层
                    sp = max(star(u, v, 0.335, 0.335, 0.215),
                             dot(u, v, 0.655, 0.615, 0.072) * 0.92,
                             dot(u, v, 0.735, 0.395, 0.045) * 0.8,
                             dot(u, v, 0.485, 0.715, 0.038) * 0.7,
                             dot(u, v, 0.30, 0.735, 0.028) * 0.6)
                    sp = min(1.0, sp)
                    r += (col[0] + (255 - col[0]) * sp) * al
                    g += (col[1] + (255 - col[1]) * sp) * al
                    b += (col[2] + (255 - col[2]) * sp) * al
                    a += al
            n = ss * ss
            if a <= 0:
                row += b"\x00\x00\x00\x00"
            else:
                row += bytes((int(min(255, b / n)), int(min(255, g / n)),
                              int(min(255, r / n)), int(min(255, 255 * a / n))))
        px.append(row)
    # DIB 自下而上
    rows = b"".join(px[::-1])
    # AND 掩码：全 0（不透明交给 alpha）
    mask_row = ((w + 31) // 32) * 4
    mask = b"\x00" * (mask_row * h)
    hdr = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                      len(rows) + len(mask), 0, 0, 0, 0)
    return hdr + rows + mask


def main():
    blobs = [(s, render(s)) for s in SIZES]
    out = bytearray(struct.pack("<HHH", 0, 1, len(blobs)))
    off = 6 + 16 * len(blobs)
    for s, data in blobs:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32,
                           len(data), off)
        off += len(data)
    for _, data in blobs:
        out += data
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(bytes(out))
    print("wrote", OUT, len(out), "bytes")


if __name__ == "__main__":
    main()
