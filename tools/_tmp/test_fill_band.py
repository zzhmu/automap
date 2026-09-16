# -*- coding: utf-8 -*-
"""fill_band_fine 单元验证：用一小片合成的「层号 + 坡带掩码」看它填成什么。

复刻 seed=777 站点 #5 的局部几何（文件行序）：坡带 r57..59 / c78..82，
r57 全低层(2)，r59 全高层(3)，r58 低层只有最右一格是高层。
"""
import importlib.util
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("gh", os.path.join(ROOT, "tools", "gen_height.py"))
gh = importlib.util.module_from_spec(spec)
sys.modules["gh"] = gh
spec.loader.exec_module(gh)

# 真实数据（世界 WE），来自 fill_debug 的「填充前」列
WORLD_BEFORE = np.array([
    # c76  c77  c78  c79  c80  c81  c82  c83  c84  c85
    [272, 293, 322, 312, 300, 282, 276, 270, 265, 249],   # r55
    [259, 277, 294, 286, 270, 258, 258, 249, 244, 233],   # r56
    [237, 252, 268, 270, 241, 235, 243, 239, 237, 226],   # r57  <- band
    [208, 213, 223, 239, 355, 354, 362, 361, 250, 237],   # r58  <- band
    [183, 197, 204, 343, 345, 347, 353, 349, 368, 348],   # r59  <- band
    [185, 198, 331, 343, 338, 336, 344, 354, 353, 353],   # r60
    [203, 344, 345, 352, 348, 343, 344, 343, 338, 346],   # r61
], dtype=np.float32)
LAYER = np.array([
    [2] * 10,
    [2] * 10,
    [2] * 10,
    [2, 2, 2, 2, 2, 2, 3, 2, 2, 2],      # r58：c82 是高层
    [2, 2, 3, 3, 3, 3, 3, 3, 3, 3],      # r59
    [2, 2, 3, 3, 3, 3, 3, 3, 3, 3],      # r60
    [2, 3, 3, 3, 3, 3, 3, 3, 3, 3],      # r61
], dtype=np.int16)
BAND = np.zeros((7, 10), dtype=bool)
BAND[2:5, 2:7] = True                      # r57..59, c78..82

fine = WORLD_BEFORE * 4.0 - (LAYER.astype(np.float32) - 2) * 512.0
filled, ok = gh.fill_band_fine(fine, LAYER, BAND)
wf = filled / 4.0 + (LAYER.astype(np.float32) - 2) * 128.0

print("band 掩码（前 7x10，列 c76..85；行 r55..61）：")
for r in range(7):
    print(f"  r{55 + r}  " + " ".join("#" if BAND[r, c] else "." for c in range(10)))
print("\nok 掩码：")
for r in range(7):
    print(f"  r{55 + r}  " + " ".join("+" if ok[r, c] else "." for c in range(10)))
print("\n世界 WE（层号/前->后）：")
for r in range(7):
    cells = []
    for c in range(10):
        m = "*" if BAND[r, c] else " "
        cells.append(f"{m}{int(LAYER[r, c])}:{WORLD_BEFORE[r, c]:>4.0f}->{wf[r, c]:>4.0f}")
    print(f"  r{55 + r}  " + " ".join(cells))

print("\n检查：")
bad = 0
for r, c in zip(*np.nonzero(BAND)):
    if not ok[r, c]:
        print(f"  ✘ ({r},{c}) 没填上")
        bad += 1
print(f"  未填角点 {bad} 个")
lo = wf[2, 2:7]
hi = wf[4, 2:7]
print(f"  坡带低线 r57: {lo.astype(int).tolist()}   紧邻低台地 r56: "
      f"{WORLD_BEFORE[1, 2:7].astype(int).tolist()}")
print(f"  坡带低线 r58: {wf[3, 2:7].astype(int).tolist()}")
print(f"  坡带高线 r59: {hi.astype(int).tolist()}   紧邻高台地 r60: "
      f"{WORLD_BEFORE[5, 2:7].astype(int).tolist()}")
