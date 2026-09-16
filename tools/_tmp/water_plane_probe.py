# -*- coding: utf-8 -*-
"""细看几张官方地图：waterHeight 字段是否逐角点变化？水角点的「逐角点水深」是多少？

用法: python tools/_tmp/water_plane_probe.py [地图名片段...]
"""
import os
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import inspect_water as iw  # noqa: E402

MAPS = r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps"
TMP = os.path.join(HERE, "wplane")

want = sys.argv[1:] or ["LostTemple", "(2)HillsOfGlory", "(6)Stromguarde"]
names = []
allm = sorted(f for f in os.listdir(MAPS) if f.lower().endswith((".w3m", ".w3x")))
for w in want:
    names += [n for n in allm if w.lower() in n.lower() and n not in names]

for n in names:
    path = os.path.join(MAPS, n)
    d = iw.load(path, TMP)
    whf, world, water = d["whf"], d["world"], d["water"]
    plane = (whf & 0x3FFF).astype(np.int32)
    vals, cnt = np.unique(plane, return_counts=True)
    order = np.argsort(-cnt)
    print("=" * 78)
    print(f"{n}   {d['cols']}x{d['rows']}   水角点 {int(water.sum())} "
          f"({water.mean() * 100:.1f}%)")
    print("  waterHeight 取值 top6: "
          + " / ".join(f"{int(vals[i])}×{int(cnt[i])}" for i in order[:6])
          + f"   （共 {len(vals)} 种）")
    if not water.any():
        continue
    wb = plane[water]
    print(f"  水角点的 waterHeight 取值: min={wb.min()} max={wb.max()} "
          f"唯一值 {len(np.unique(wb))} 种")
    depth = (plane[water] - world[water]) / 4.0
    print(f"  逐角点水深 WE: min={depth.min():.0f} p5={np.percentile(depth, 5):.0f} "
          f"p50={np.percentile(depth, 50):.0f} p95={np.percentile(depth, 95):.0f} "
          f"max={depth.max():.0f}")
    # 水深是不是整层倍数（128 WE）？
    r = np.round(depth / 128.0)
    err = np.abs(depth - r * 128.0)
    print(f"  离「整层倍数(128WE)」的距离: p50={np.percentile(err, 50):.1f} "
          f"p95={np.percentile(err, 95):.1f} WE   "
          f"恰好整除占比={float((err < 1).mean()) * 100:.1f}%")
    ly = d["layer"][water]
    print(f"  水角点 layer 分布: {Counter(ly.tolist()).most_common(5)}")
