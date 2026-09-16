# -*- coding: utf-8 -*-
"""造一张「水渲染探针图」：9 条竖带，一次把三个疑点全测出来。

背景：我们生成的图里，水跟陆地**同层**，深度只靠 groundHeight（≤96 WE = 0.75 层）；
而全部官方地图的水都在**比陆地低 1~2 个整层**的位置。到底 WE 靠什么认水？

9 条带（左→右）：
  1  纯陆地参照（水面之上 +1 WE）
  2  gh 下沉  4 WE（0.03 层），同层
  3  gh 下沉 32 WE（0.25 层），同层
  4  gh 下沉 96 WE（0.75 层），同层   ← 我们现在浅滩基底的深度上限
  5  gh 下沉 128 WE（1.00 层），同层
  6  gh 下沉 256 WE（2.00 层），同层
  7  整层下沉 1 层（layer 1，= 128 WE）
  8  整层下沉 2 层（layer 0，= 256 WE）
  9  同 4（96 WE 同层）但**不打 0x40 水标记**（对照组：标记到底有没有用）

用法: python tools/_tmp/water_probe_map2.py
产出: out/probe_water_depth.w3x + out/probe_water_depth_示意图.png
"""
import os
import shutil
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import inspect_water as iw  # noqa: E402

EXE = iw.EXE
GZ = iw.GROUND_ZERO
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "template", "128-128.w3m")
out = os.path.join(ROOT, "out", "probe_water_depth.w3x")
tmp = os.path.join(HERE, "wprobe2")

# (标签, groundHeight 相对水面的 WE, layer, 打水标记?)
# 注意「整层」两条：gh 保持跟陆地一样（+1 WE），只把 layer 降下去 —— 这才是官方地图的做法。
STRIPES = [
    ("land ref",        +1,   2, False),
    ("gh 4 WE",         -4,   2, True),
    ("gh 32 WE",        -32,  2, True),
    ("gh 96 WE",        -96,  2, True),
    ("gh 128 WE",       -128, 2, True),
    ("gh 256 WE",       -256, 2, True),
    ("layer 1",       +1,   1, True),
    ("layer 0",       +1,   0, True),
    ("gh96 noflag",   -96,  2, False),
]

shutil.copy2(src, out)
os.makedirs(tmp, exist_ok=True)
data = bytearray(iw.extract(out, tmp))
W, H, HS = iw.read_header(data)
cols, rows = W + 1, H + 1
band = cols // len(STRIPES)
for cy in range(rows):
    file_row = rows - 1 - cy
    for cx in range(cols):
        off = HS + (file_row * cols + cx) * 7
        k = min(len(STRIPES) - 1, cx // band)
        label, dh, lay, flag = STRIPES[k]
        is_w = (cx % band) not in (0, band - 1)
        if is_w:
            gh = GZ + int(round(dh * 4.0))
            fl = 0x40 if flag else 0x00
        else:
            gh = GZ + 4
            fl = 0x00
        struct.pack_into("<H", data, off, max(0, min(0xFFFF, gh)))
        struct.pack_into("<H", data, off + 2, GZ & 0x3FFF)
        data[off + 4] = (fl & 0xF0) | (data[off + 4] & 0x0F)
        data[off + 6] = (data[off + 6] & 0xF0) | (lay & 0x0F)

new_w3e = os.path.join(tmp, "war3map.w3e.new")
open(new_w3e, "wb").write(bytes(data))
r = subprocess.run([EXE, "add", out, new_w3e, "war3map.w3e"], capture_output=True, timeout=120)
print("塞回 MPQ:", "ok" if r.returncode == 0 else r.stdout.decode("utf-8", "replace")[:200])
print("产出:", out)
for i, (label, dh, lay, flag) in enumerate(STRIPES, 1):
    print(f"  第 {i} 条  {label:<16} 世界高度 {dh:>5} WE   layer={lay}  水标记={flag}")

# 示意图
from PIL import Image, ImageDraw  # noqa: E402
SC, IMG_W, IMG_H = 40, 720, 360
img = Image.new("RGB", (IMG_W, IMG_H), (58, 58, 62))
dr = ImageDraw.Draw(img)
b = IMG_W // len(STRIPES)
for k, (label, dh, lay, flag) in enumerate(STRIPES):
    depth = -(dh + (lay - 2) * 128.0)          # 实际水深（WE），含 layer 项
    if depth <= 0:
        col = (150, 140, 100)
    else:
        t = min(1.0, depth / 256.0)
        col = (int(120 * (1 - t) + 18 * t), int(195 * (1 - t) + 58 * t), int(235 * (1 - t) + 150 * t))
    x0 = k * b + 2
    dr.rectangle([x0, 6, x0 + b - 6, IMG_H - 66], fill=col, outline=(235, 235, 235))
    dr.multiline_text((x0 + 3, IMG_H - 60), f"#{k + 1}\n{label}\n{depth:.0f} WE",
                      fill=(245, 245, 245), spacing=2)
img.save(os.path.join(ROOT, "out", "probe_water_depth_示意图.png"))
print("示意图:", os.path.join(ROOT, "out", "probe_water_depth_示意图.png"))
