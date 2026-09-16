# -*- coding: utf-8 -*-
"""造一张「水深探针图」：竖向条纹，每条水带的水深固定（4/16/32/64/96/128/160/192/256 WE），
陆地一律抬到 +1 WE。放进 WE 一眼就能看出**引擎从哪个深度开始才把地形渲染成水**。

用法: python tools/_tmp/water_depth_probe_map.py [模板地图]
产出: out/_probe_depth.w3x
"""
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import inspect_water as iw  # noqa: E402

EXE = iw.EXE
GROUND_ZERO = iw.GROUND_ZERO
DEPTHS = [4, 16, 32, 64, 96, 128, 160, 192, 256]

src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "template", "128-128.w3m")
out = os.path.join(ROOT, "out", "probe_water_depth.w3x")
tmp = os.path.join(HERE, "wprobe")

os.makedirs(tmp, exist_ok=True)
import shutil  # noqa: E402
shutil.copy2(src, out)
data = bytearray(iw.extract(out, tmp))
W, H, HS = iw.read_header(data)
cols, rows = W + 1, H + 1
per = 7
print(f"源: {os.path.basename(src)}  {cols}x{rows} 角点  水深带: {DEPTHS}")

# 每条带的角点宽度
band = cols // len(DEPTHS)
for cy in range(rows):
    file_row = rows - 1 - cy
    for cx in range(cols):
        off = HS + (file_row * cols + cx) * per
        k = min(len(DEPTHS) - 1, cx // band)
        d = DEPTHS[k]
        # 每条带左右各留 1 角点的陆地缝，便于分辨边界
        is_w = (cx % band) not in (0, band - 1)
        fine = (-d * 4) if is_w else 4          # 水：-d WE；陆：+1 WE
        flags = 0x40 if is_w else 0x00
        struct.pack_into("<H", data, off, GROUND_ZERO + fine)
        struct.pack_into("<H", data, off + 2, GROUND_ZERO & 0x3FFF)
        data[off + 4] = (flags & 0xF0) | (data[off + 4] & 0x0F)
        data[off + 6] = (data[off + 6] & 0xF0) | 2      # 全图同层 = 2

new_w3e = os.path.join(tmp, "war3map.w3e.new")
open(new_w3e, "wb").write(bytes(data))
r = subprocess.run([EXE, "add", out, new_w3e, "war3map.w3e"],
                   capture_output=True, timeout=120)
print("塞回 MPQ:", "ok" if r.returncode == 0 else r.stdout.decode("utf-8", "replace")[:200])
print("产出:", out)
for k, d in enumerate(DEPTHS):
    print(f"  第 {k + 1} 条 水深 {d:>3} WE （{d / 128:.2f} 层）")
