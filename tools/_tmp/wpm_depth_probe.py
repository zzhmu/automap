# -*- coding: utf-8 -*-
"""用官方地图反推：WC3 引擎是拿「几个整层的深度」来分浅水/深水的？

wpm（war4map.wpm，WE 自己算的寻路图）是引擎判定「能不能走」的真值。
把 wpm 的 4x4 格降到瓦片级，再看它跟「该瓦片的水深档数」怎么对应：
  - 如果 1 档深的水瓦片 → 某个「可走/浅水」值，2 档深 → 另一个值，那分界线就实锤了；
  - 如果 1 档和 2 档取值一样，说明引擎不区分，浅水只是视觉。

用法: python tools/_tmp/wpm_depth_probe.py [地图名片段...]
"""
import os
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import diag_flags as df  # noqa: E402
import inspect_water as iw  # noqa: E402

MAPS = r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps"
TMP = os.path.join(HERE, "wpmdepth")

want = sys.argv[1:] or ["(4)LostTemple", "(6)Stromguarde", "(2)HillsOfGlory",
                        "(6)SwampOfSorrows", "(4)MysticIsles"]
allm = sorted(f for f in os.listdir(MAPS) if f.lower().endswith((".w3m", ".w3x")))
names = []
for w in want:
    names += [n for n in allm if w.lower() in n.lower() and n not in names]

for n in names:
    path = os.path.join(MAPS, n)
    d = iw.load(path, TMP)
    gotw = df.load_wpm(path, TMP)
    if gotw is None:
        print(f"{n}: wpm 提取失败")
        continue
    cells, ver = gotw
    ch, cw = cells.shape
    rows, cols = d["rows"], d["cols"]
    plane = (d["whf"] & 0x3FFF).astype(np.int32)
    depth_we = (plane - d["world"]) / 4.0                     # 逐角点水深（WE）
    lvl = np.round(depth_we / 128.0)                          # 水深档（1 档 = 128 WE）
    water = d["water"]

    fy, fx = ch // (rows - 1), cw // (cols - 1)
    block = cells[:fy * (rows - 1), :fx * (cols - 1)].reshape(rows - 1, fy, cols - 1, fx)
    # 转成「每瓦片一格」的形状： (rows-1, cols-1, fy*fx)
    block = block.transpose(0, 2, 1, 3).reshape(rows - 1, cols - 1, fy * fx)

    # 瓦片 = 四角；档数取四角里最深的那个（只要有一角是水就算水瓦片）
    lv_t = lvl[:-1, :-1]
    for m in (lvl[:-1, 1:], lvl[1:, :-1], lvl[1:, 1:]):
        lv_t = np.maximum(lv_t, m)
    w_t = (water[:-1, :-1] | water[:-1, 1:] | water[1:, :-1] | water[1:, 1:])
    lv_t = np.where(w_t, np.clip(lv_t, 0, 4), 0).astype(np.int32)

    print("=" * 78)
    print(f"{n}   wpm {cw}x{ch}  每瓦片 {fx}x{fy} 格   瓦片 {cols - 1}x{rows - 1}")
    for L in range(0, 5):
        m = lv_t == L
        n_tile = int(m.sum())
        if not n_tile:
            continue
        vals = block[m].ravel()
        cnt = np.bincount(vals, minlength=256)
        top = sorted(((int(v), int(c)) for v, c in enumerate(cnt) if c),
                     key=lambda x: -x[1])[:5]
        tag = "陆地/无水" if L == 0 else f"水深 {L} 档（{L * 128} WE）"
        print(f"  {tag:<22} 瓦片 {n_tile:>6}  wpm 取值: "
              + " / ".join(f"{v}(0x{v:02X})×{c}" for v, c in top))
    # 汇总：把「水深档」和 wpm 值做交叉表
    tab = defaultdict(Counter)
    for L in range(0, 5):
        m = lv_t == L
        if m.any():
            tab[L] = Counter(block[m].ravel().tolist())
    print("  ---- 交叉表（行=水深档，列=wpm 值 → 占比）----")
    for L in sorted(tab):
        tot = sum(tab[L].values())
        s = "  ".join(f"{v}(0x{v:02X}):{100 * c / tot:.0f}%"
                      for v, c in tab[L].most_common(4))
        print(f"    档{L}: {s}")
