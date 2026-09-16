# -*- coding: utf-8 -*-
"""一组参数 × 多种子扫一遍，对表官方 p50。纯网格，秒级。

用法: python tools/_tmp/forest_sweep.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import add_doodads as A  # noqa: E402
import forest_sim as S  # noqa: E402

TGT = dict(dens=0.120, n_blob=256, max_sz=205, n100=4, frac100=0.332,
           lone=0.488, ratio=0.0924, iso8=0.017, iso2=0.001, dmed=9.0, dnear=0.365)
LBL = dict(dens="密度", n_blob="块数", max_sz="最大块", n100="≥100块", frac100="树落大林",
           lone="单株占块", ratio="块/树", iso8="iso8", iso2="iso2",
           dmed="大林距中位", dnear="距大林≤3")

BASE = dict(density=0.18, forest_share=0.32, forest_size=170.0, clump_size=11.0,
            clump_radius=3.0, clump_gap=1.5, scatter=0.035, scatter_size=1.5,
            clump_bias=0.55, freq=2.2, edge_forest=0.55, edge_band=14.0)

CASES = [
    ("散株2.0", {"scatter_size": 2.0}),
    ("林160 散2.0", {"forest_size": 160.0, "scatter_size": 2.0}),
    ("林150 散2.0", {"forest_size": 150.0, "scatter_size": 2.0}),
    ("林140 散2.0", {"forest_size": 140.0, "scatter_size": 2.0}),
    ("林140 散2.0 林额.38", {"forest_size": 140.0, "scatter_size": 2.0,
                             "forest_share": 0.38}),
    ("林120 散2.0 林额.42", {"forest_size": 120.0, "scatter_size": 2.0,
                             "forest_share": 0.42}),
    ("林120 散2.0 林额.42 丛13", {"forest_size": 120.0, "scatter_size": 2.0,
                                  "forest_share": 0.42, "clump_size": 13.0}),
]
SEEDS = [11, 22, 33, 44, 55, 66]

keys = list(TGT)
print(f"{'方案':<22}" + "".join(f"{LBL[k]:>9}" for k in keys))
print(f"{'官方p50':<22}" + "".join(f"{TGT[k]:>9.3f}" for k in keys))
for name, over in CASES:
    opts = dict(BASE)
    opts.update(over)
    rows = [S.run(s, opts) for s in SEEDS]
    med = {k: float(np.median([r[k] for r in rows])) for k in keys}
    print(f"{name:<22}" + "".join(f"{med[k]:>9.3f}" for k in keys))
