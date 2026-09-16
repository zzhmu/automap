# -*- coding: utf-8 -*-
"""找引擎的两个阈值：**水深到多少算「水」**、**水深到多少就不再能走**。

做法：wpm 是 WE 自己算的寻路真值（4x4 格 / 瓦片）。把每个 wpm 格对应的地形水深
算出来（WE 单位），按 8 WE 分桶，看 wpm 里各标志位随深度的变化：
  0x08 = 「水」标志          → 从哪个深度开始出现 = 引擎认水的阈值
  0x40 = 「可走地面」标志     → 从哪个深度开始消失 = 可走性的阈值
"""
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import diag_flags as df  # noqa: E402
import inspect_water as iw  # noqa: E402

MAPS = r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps"
TMP = os.path.join(HERE, "wpmthr")

names = sys.argv[1:] or ["(4)LostTemple", "(6)Stromguarde", "(2)HillsOfGlory",
                         "(6)SwampOfSorrows", "(4)MysticIsles", "(4)BootyBay",
                         "(2)PlunderIsle", "(6)Moonglade"]
allm = sorted(f for f in os.listdir(MAPS) if f.lower().endswith((".w3m", ".w3x")))
picked = []
for w in names:
    picked += [n for n in allm if w.lower() in n.lower() and n not in picked]

agg = defaultdict(lambda: np.zeros(9, dtype=np.int64))   # bucket -> [n, 0x40,0x08,0x0A,0x48,0xCA,0xCE,0x00,0x02]
for n in picked:
    path = os.path.join(MAPS, n)
    d = iw.load(path, TMP)
    gotw = df.load_wpm(path, TMP)
    if gotw is None:
        continue
    cells, _ = gotw
    ch, cw = cells.shape
    rows, cols = d["rows"], d["cols"]
    plane = (d["whf"] & 0x3FFF).astype(np.int32)
    depth_c = (plane - d["world"]) / 4.0
    fy, fx = ch // (rows - 1), cw // (cols - 1)
    # 每个 wpm 格 ← 角点（行 iy//fy, 列 ix//fx）
    ci = np.minimum(np.arange(ch) // fy, rows - 1)
    cj = np.minimum(np.arange(cw) // fx, cols - 1)
    dep = depth_c[np.ix_(ci, cj)]
    # 桶：深度 -256..256，每 8 WE 一个桶，索引 0..64
    b = np.clip(((dep + 256) / 8.0).astype(np.int32), 0, 64)
    vals = cells.astype(np.int32)
    v40 = (vals & 0x40) != 0
    v08 = (vals & 0x08) != 0
    flat_b = b.ravel()
    for k in range(65):
        m = flat_b == k
        if not m.any():
            continue
        nn = int(m.sum())
        agg[k][0] += nn
        sub = vals.ravel()[m]
        agg[k][1] += int(((sub & 0x40) != 0).sum())
        agg[k][2] += int(((sub & 0x08) != 0).sum())
        agg[k][3] += int((sub == 0x0A).sum())
        agg[k][4] += int((sub == 0x48).sum())
        agg[k][5] += int((sub == 0xCA).sum())
        agg[k][6] += int((sub == 0xCE).sum())
        agg[k][7] += int((sub == 0x00).sum())
        agg[k][8] += int((sub == 0x02).sum())
    _ = (v40, v08)

print(f"共 {len(picked)} 张图")
print(f"{'水深 WE':>10}{'格数':>10}{'0x40可走':>10}{'0x08水':>9}{'0x0A深水':>10}"
      f"{'0x48可走+水':>12}{'0xCA':>7}{'0xCE':>7}")
print("-" * 82)
for k in range(65):
    row = agg[k]
    if row[0] == 0:
        continue
    lo = -256 + k * 8
    n = row[0]
    p = lambda i: 100.0 * row[i] / n            # noqa: E731
    print(f"{lo:>10}{n:>10}{p(1):>9.0f}%{p(2):>8.0f}%{p(3):>9.0f}%"
          f"{p(4):>11.0f}%{p(5):>6.0f}%{p(6):>6.0f}%")
print("-" * 82)
print("读法：0x08 从哪一档开始冒头 = 引擎认水的深度；0x40 从哪一档掉到 0 = 可走性上限")
