# -*- coding: utf-8 -*-
"""量一量斜坡"凹到地心"到底凹了多少。

读一张生成好的图，找出所有斜坡瓦片，把每个斜坡站点周围 7x7 角点的
（层号 / 世界高度 WE）打出来，并统计：
  * 坡面带（ramp 位那 3 条角点线）的世界高度 与 两侧台地地面世界高度 的落差；
  * 落差是不是 128 的整数倍。

用法: python tools/_tmp/ramp_slope_probe.py <map.w3x> [最多打印几个站点]
"""
import importlib.util
import os
import sys
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "tools")
spec = importlib.util.spec_from_file_location("iw", os.path.join(TOOLS, "inspect_water.py"))
iw = importlib.util.module_from_spec(spec)
sys.modules["iw"] = iw
spec.loader.exec_module(iw)

GROUND_ZERO = 8192
LAYER_STEP = 512

path = sys.argv[1]
n_show = int(sys.argv[2]) if len(sys.argv) > 2 else 3
d = iw.load(path, os.path.join(TOOLS, "_tmp", "slope_probe"))
gh, layer, ramp = d["gh"], d["layer"], d["ramp"]
rows, cols = d["rows"], d["cols"]
# 世界高度（WE 高度单位），与 gen_height 的公式一致
world = (gh.astype(np.float32) - GROUND_ZERO
         + (layer.astype(np.float32) - 2) * LAYER_STEP) / 4.0

# 斜坡瓦片：四角都带 ramp 位
all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
ys, xs = np.nonzero(all4)
print(f"{os.path.basename(path)}: 层值 {dict(Counter(int(v) for v in np.unique(layer)))}"
      f"  斜坡瓦片 {len(ys)} 个  世界高度 {world.min():.0f} ~ {world.max():.0f} WE")

# 把斜坡瓦片按连通块分组
seen = np.zeros_like(all4)
groups = []
for r0, c0 in zip(ys.tolist(), xs.tolist()):
    if seen[r0, c0]:
        continue
    stack = [(r0, c0)]
    seen[r0, c0] = True
    cells = []
    while stack:
        r, c = stack.pop()
        cells.append((r, c))
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < all4.shape[0] and 0 <= nc < all4.shape[1] \
                    and all4[nr, nc] and not seen[nr, nc]:
                seen[nr, nc] = True
                stack.append((nr, nc))
    groups.append(cells)
print(f"斜坡连通块 {len(groups)} 个：大小分布 "
      f"{dict(Counter(len(g) for g in groups))}")

# 每个块：坡面高度范围 vs 坡外紧邻（再向外 1~2 格）的地面高度
print("\n=== 每个斜坡块：坡面世界高度 vs 坡外地面世界高度 ===")
print(f"{'#':>3} {'行':>4} {'列':>4} {'瓦片':>4}  {'坡面 WE':>15}  "
      f"{'坡外地面 WE':>16}  {'中位差':>8} {'最低差':>8}")
lows = []
for i, cells in enumerate(groups):
    rr = [r for r, _ in cells]
    cc = [c for _, c in cells]
    r0, r1 = min(rr), max(rr) + 1
    c0, c1 = min(cc), max(cc) + 1
    # 块的四角范围再向外扩 1 格 → 坡外一圈地面（去掉落在坡带里的角点）
    R0, R1 = max(0, r0 - 2), min(rows, r1 + 3)
    C0, C1 = max(0, c0 - 2), min(cols, c1 + 3)
    lay = np.zeros((R1 - R0, C1 - C0), dtype=bool)
    lay[r0 - R0:r1 + 2 - R0, c0 - C0:c1 + 2 - C0] = True     # 块覆盖的角点范围
    band = ramp[R0:R1, C0:C1] & lay
    base = lay & ~ramp[R0:R1, C0:C1]                          # 块范围内、非坡带
    outb = ~lay & ~ramp[R0:R1, C0:C1]                         # 块外一圈
    w = world[R0:R1, C0:C1]
    in_v = w[band]
    out_v = w[outb | base]
    if not in_v.size or not out_v.size:
        continue
    d_med = float(np.median(in_v) - np.median(out_v))
    d_min = float(in_v.min() - np.median(out_v))
    lows.append((d_min, i))
    print(f"{i:>3} {r0:>4} {c0:>4} {len(cells):>4}  "
          f"{in_v.min():>6.0f}~{in_v.max():>6.0f}  "
          f"{out_v.min():>6.0f}~{out_v.max():>7.0f}  "
          f"{d_med:>+8.0f} {d_min:>+8.0f}")

if lows:
    lows.sort()
    print(f"\n⚠️ 最矮的坡面相对周围地面下陷最多的 5 个站点: "
          + ", ".join(f"#{i} {v:+.0f}" for v, i in lows[:5]))
    print(f"坡面全体最低角点 {world.ravel()[
        ramp.ravel()].min():.0f} WE" if ramp.any() else "")
    diffs = [float(np.median(world[r0:r1 + 1, c0:c1 + 1][ramp[r0:r1 + 1, c0:c1 + 1]])
                   - np.median(world[r0:r1 + 1, c0:c1 + 1][~ramp[r0:r1 + 1, c0:c1 + 1]]))
             for r0, _, r1, c0, c1 in
             [(min(r for r, _ in g), None, max(r for r, _ in g) + 1,
               min(c for _, c in g), max(c for _, c in g) + 1) for g in groups]]
    print("坡面-坡外中位落差 /128 的余数: "
          + str(dict(Counter(int(round(v % 128)) for v in diffs if v == v))))

# 细看下陷最多的站点
order = [i for _, i in sorted(lows)[:n_show]]
for i in order:
    cells = groups[i]
    rr = [r for r, _ in cells]
    cc = [c for _, c in cells]
    r0, r1 = min(rr), max(rr) + 1
    c0, c1 = min(cc), max(cc) + 1
    R0, R1 = max(0, r0 - 3), min(rows, r1 + 5)
    C0, C1 = max(0, c0 - 3), min(cols, c1 + 5)
    print(f"\n--- 站点 {i}: 角点 r{r0}..{r1} c{c0}..{c1}（每角点打印 层号/世界WE）")
    print("      " + " ".join(f"{c:>9}" for c in range(C0, C1)))
    for r in range(R0, R1):
        row = []
        for c in range(C0, C1):
            mark = "*" if ramp[r, c] else " "
            row.append(f"{mark}{int(layer[r, c])}/{world[r, c]:>6.0f}")
        print(f"{r:>5} " + " ".join(row))
