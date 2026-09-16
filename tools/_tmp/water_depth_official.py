# -*- coding: utf-8 -*-
"""统计官方地图里「带水标记(0x40)的角点」的**水深分布**（WE 高度单位）。

目的：验证一个猜想 —— WC3 引擎是不是只在「水深 ≥ 1 整层(128 WE)」时才把地形
渲染成水面？如果官方图从来没有任何水角点浅于 128 WE，那我们的
--shelf-depth 96（= 0.75 层）就太浅了，WE 会当干地渲染 → 用户看到「纯陆地」。

用法: python tools/_tmp/water_depth_official.py [地图数上限]
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import inspect_water as iw  # noqa: E402

MAPS = r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps"
TMP = os.path.join(HERE, "wdepth")
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 40

names = sorted(f for f in os.listdir(MAPS) if f.lower().endswith((".w3m", ".w3x")))
# 均匀抽样，避免全是最小的图
step = max(1, len(names) // LIMIT)
picked = names[::step][:LIMIT]

rows = []
for n in picked:
    p = os.path.join(MAPS, n)
    try:
        d = iw.load(p, TMP)
    except SystemExit as e:
        print(f"  跳过 {n}: {e}")
        continue
    except Exception as e:                       # noqa: BLE001
        print(f"  跳过 {n}: {type(e).__name__}: {e}")
        continue
    water, world, whf = d["water"], d["world"], d["whf"]
    # ⚠️ 必须用**逐角点** waterHeight，不能拿全图众数当水面 —— 官方图部分角点的
    # waterHeight 是变化的（LostTemple 就有 8192/8224/8357/8440 四种），
    # 用众数会把那些角点算成「水在水面之上」这种荒唐值。
    plane = (whf & 0x3FFF).astype(np.int32)
    if not water.any():
        rows.append((n, 0.0, None))
        continue
    depth = (plane[water] - world[water]) / 4.0
    rows.append((n, float(water.mean() * 100), depth))

print(f"{'地图':<34}{'水域%':>7}{'水角点':>9}{'最深':>8}{'p50':>8}{'p5':>8}{'min':>8}"
      f"{'<128占比':>10}")
print("-" * 92)
allmin = []
shallow_frac = []
for n, pct, depth in rows:
    if depth is None:
        print(f"{n:<34}{0:>7.1f}{'无水':>9}")
        continue
    m = float(depth.min())
    allmin.append(m)
    frac = float((depth < 128.0).mean() * 100)
    shallow_frac.append(frac)
    print(f"{n:<34}{pct:>7.1f}{len(depth):>9}{depth.max():>8.0f}"
          f"{np.percentile(depth, 50):>8.0f}{np.percentile(depth, 5):>8.0f}"
          f"{m:>8.0f}{frac:>9.1f}%")

if allmin:
    a = np.array(allmin)
    sf = np.array(shallow_frac)
    print("-" * 92)
    print(f"共 {len(a)} 张有水的官方图：")
    print(f"  水角点最浅深度 min  的分布: 最小={a.min():.0f}  p25={np.percentile(a, 25):.0f} "
          f"p50={np.percentile(a, 50):.0f}  max={a.max():.0f} WE")
    print(f"  少于 128 WE（不满 1 层）的水角点占比: 平均 {sf.mean():.1f}%  最大 {sf.max():.1f}%")
    print(f"  完全没有 <128 WE 水角点的图: {int((sf == 0).sum())}/{len(sf)}")
