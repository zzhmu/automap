# -*- coding: utf-8 -*-
"""树林形态指标（add_doodads.forest_metrics）自检。

为什么必须有这个测试：`_neigh_any` / 「是否孤立」这类算子极易写错，而且两种错法
都**不会报错、只会给出漂亮但完全错误的统计**。本项目实测踩过两次：
  * `t & ~dilate(t, 1)`            → deque 里的 dilate 把自身算进去 → 孤立率恒 0
  * `t & ~(dilate(t, 1) & ~t)`     → 反向错误 → 孤立率恒 1
两次都据此得出过「官方 43 张图孤立率全为 0」/「全为 1」的假结论，白跑了一轮全量统计。
所以这里用**手工可算的小例子**把语义钉死。

用法: python tools/_tmp/test_forest_metrics.py     （退出码 0 = 全过）
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import add_doodads as A  # noqa: E402

FAIL = []


def check(name, got, want, tol=0.0):
    ok = abs(float(got) - float(want)) <= tol
    print(f"  {'✔' if ok else '✘'} {name:<34} got={got!r} want={want!r}")
    if not ok:
        FAIL.append(name)


def grid(pts, H=12, W=12):
    m = np.zeros((H, W), dtype=bool)
    for y, x in pts:
        m[y, x] = True
    return m


print("[1] _neigh_any：返回的是「逐格是否有别的 True」，且必须排除自身")
nb = A._neigh_any(grid([(5, 5)]), 1)
check("单点：自身那一格不算邻居", bool(nb[5, 5]), False)
check("单点：对角邻格算邻居", bool(nb[4, 4]), True)
check("单点：正交邻格算邻居", bool(nb[5, 6]), True)
check("单点：2 格外不算 r=1 邻居", bool(nb[5, 7]), False)
# 「孤立格」= mask & ~_neigh_any，这才是 forest_metrics 用的量
check("单点：孤立格数 = 1", (grid([(5, 5)]) & ~A._neigh_any(grid([(5, 5)]), 1)).sum(), 1)
check("正交相邻：孤立格数 = 0",
      (grid([(5, 5), (5, 6)]) & ~A._neigh_any(grid([(5, 5), (5, 6)]), 1)).sum(), 0)
check("对角相邻：孤立格数 = 0（8 邻域）",
      (grid([(5, 5), (6, 6)]) & ~A._neigh_any(grid([(5, 5), (6, 6)]), 1)).sum(), 0)
check("相距 3 格：孤立格数 = 2",
      (grid([(5, 5), (5, 8)]) & ~A._neigh_any(grid([(5, 5), (5, 8)]), 1)).sum(), 2)
check("相距 2 格 r=2：孤立格数 = 0",
      (grid([(5, 5), (5, 7)]) & ~A._neigh_any(grid([(5, 5), (5, 7)]), 2)).sum(), 0)

print("\n[2] forest_metrics 的孤立度语义")
m = grid([(5, 5)])
fm = A.forest_metrics(m)
check("单个孤立点 iso8", fm["iso8"], 1.0)
check("单个孤立点 iso2", fm["iso2"], 1.0)
m = grid([(5, 5), (5, 6)])
fm = A.forest_metrics(m)
check("两棵正交相邻 iso8", fm["iso8"], 0.0)
check("两棵正交相邻 iso2（2 格内互见）", fm["iso2"], 0.0)
# 「相距 3 格」= 8 邻域不相邻、但 2 格邻域内也没有 → 两个都是 iso8 且都是 iso2
m = grid([(5, 5), (5, 8)])
fm = A.forest_metrics(m)
check("相距 3 格 iso8 = 1", fm["iso8"], 1.0)
check("相距 3 格 iso2 = 1", fm["iso2"], 1.0)
# 「对角相邻」→ 4 连通是 2 个块、但 8 邻域不孤立（这正是官方 49% 单株块的来源）
m = grid([(5, 5), (6, 6)])
fm = A.forest_metrics(m)
check("对角相邻：块数 = 2（4 连通）", fm["n_blob"], 2)
check("对角相邻：单株占块 = 1.0", fm["lone"], 1.0)
check("对角相邻：iso8 = 0（8 邻域不孤立）", fm["iso8"], 0.0)

print("\n[3] forest_metrics 的连片/大林指标")
m = grid([(y, x) for y in range(3, 8) for x in range(3, 8)])   # 5x5 = 25 格
fm = A.forest_metrics(m, big_thresh=10)
check("5x5 方块：块数 = 1", fm["n_blob"], 1)
check("5x5 方块：最大块 = 25", fm["max_sz"], 25)
check("5x5 方块：n_big = 1", fm["n_big"], 1)
check("5x5 方块：树全在大林里 inbig", fm["inbig"], 1.0)
check("5x5 方块：到大林格距 = 0", fm["dmed"], 0.0)
check("5x5 方块：iso8 = 0", fm["iso8"], 0.0)
fm = A.forest_metrics(m, big_thresh=999)
check("阈值调高后不再是「大林」n_big", fm["n_big"], 0)
check("没有大林时 frac_big = 0", fm["frac_big"], 0.0)

print("\n[4] 到大林的距离（8 邻接 / Chebyshev）")
m = grid([(2, 2)])
d = A._dist_to(m)
check("自身距离 0", d[2, 2], 0)
check("正交 1 格", d[2, 3], 1)
check("对角 1 格 = 1（8 邻接）", d[3, 3], 1)
check("切比雪夫 5", d[7, 7], 5)
check("空 mask 时全为上限", A._dist_to(np.zeros((4, 4), bool), maxd=9).max(), 9)

print("\n" + "=" * 62)
if FAIL:
    print(f"✘ 自检失败 {len(FAIL)} 项: {FAIL}")
    sys.exit(1)
print("✔ 全过（forest_metrics 语义与官方统计口径一致）")
