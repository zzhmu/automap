# -*- coding: utf-8 -*-
"""查 fill_band_fine 到底填了没有：打印坡带掩码 / ok 掩码 / fine 前后值。

用法: python tools/_tmp/fill_debug.py <out.w3x> <r0> <r1> <c0> <c1> [gen_height 参数...]
"""
import importlib.util
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "tools")


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


gh_mod = load_mod("gen_height", os.path.join(TOOLS, "gen_height.py"))

out = sys.argv[1]
r0, r1, c0, c1 = (int(v) for v in sys.argv[2:6])
rest = sys.argv[6:]

_orig = gh_mod.fill_band_fine


def wrap(fine, layer, band, radius=8):
    filled, ok = _orig(fine, layer, band, radius=radius)
    sl = (slice(r0, r1), slice(c0, c1))
    print("\n=== fill_band_fine ===")
    print(f"band 总计 {int(band.sum())} / ok {int(ok.sum())} / 未填 {int((band & ~ok).sum())}")
    ys, xs = np.nonzero(band)
    if ys.size:
        print("--- 坡带角点的行段分布 ---")
        for r in sorted(set(ys.tolist())):
            cs = sorted(xs[ys == r].tolist())
            print(f"  r{r:>4}: {cs[0]}..{cs[-1]}  ({len(cs)} 个)")
    print("--- band 掩码 (r%da..%d, c%dd..%d) ---" % (r0, r1, c0, c1))
    for r in range(r0, r1):
        print(f"{r:>5} " + " ".join("#" if band[r, c] else "." for c in range(c0, c1)))
    print("--- ok 掩码 ---")
    for r in range(r0, r1):
        print(f"{r:>5} " + " ".join("+" if ok[r, c] else "." for c in range(c0, c1)))
    print("--- layer (填充前) ---")
    for r in range(r0, r1):
        print(f"{r:>5} " + " ".join(f"{int(layer[r, c]):>3}" for c in range(c0, c1)))
    print("--- fine 前 / 后（世界 WE = fine/4 + 128*(layer-2)）---")
    for r in range(r0, r1):
        cells = []
        for c in range(c0, c1):
            wb = fine[r, c] / 4.0 + (int(layer[r, c]) - 2) * 128.0
            wa = filled[r, c] / 4.0 + (int(layer[r, c]) - 2) * 128.0
            m = "*" if band[r, c] else " "
            cells.append(f"{m}{wb:>6.0f}->{wa:>6.0f}")
        print(f"{r:>5} " + " ".join(cells))
    return filled, ok


gh_mod.fill_band_fine = wrap
sys.argv = ["gen_height.py", out] + rest
gh_mod.main()
