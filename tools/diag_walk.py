# -*- coding: utf-8 -*-
"""刻完斜坡后逐岛核对可走连通性，并把断开的碎块信息打出来。

用法: python diag_walk.py [--size 64] [--seed 5007] [--no-merge]
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_height as G            # noqa: E402
from diag_carve import build_layer  # noqa: E402


def main():
    opts = {}
    for i, a in enumerate(sys.argv):
        if a.startswith("--") and i + 1 < len(sys.argv):
            opts[a[2:]] = sys.argv[i + 1]
    size = int(opts.get("size", 64))
    seed = int(opts.get("seed", 5007))
    do_merge = "--no-merge" not in sys.argv

    layer, is_water = build_layer(seed, size, 4, 0.30, 1.6, 2, 0.35, 2.0, 2, 2, 32, 16)
    L2 = layer.copy()
    ramp, L2, zf, info = G.carve_ramps(L2, is_water, run=4, max_jump=2)
    print(f"carve: {info}")
    if do_merge and info.get("ramps"):
        n = G.merge_orphan_flats(L2, is_water, ramp, max_jump=2)
        print(f"合并碎块: {n}")

    sp, _, _, dry = G._tile_derivatives(L2, is_water)
    flat = (sp == 0) & dry
    all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
    walk = flat | all4
    ilab, ni = G._components(dry)
    wlab, nw = G._components(walk)
    print(f"陆地岛 {ni} / 可走块 {nw}")
    for w in range(nw):
        m = wlab == w
        ys, xs = np.nonzero(m)
        lv = L2[:-1, :-1][m]
        vals, cnt = np.unique(lv, return_counts=True)
        rampn = int((all4 & m).sum())
        # 该块落在哪个岛里
        isl = int(ilab[ys[0], xs[0]])
        print(f"  块{w}: {len(ys)} 格 岛{isl} 行{ys.min()}..{ys.max()} 列{xs.min()}..{xs.max()}"
              f" 层位分布{dict(zip(vals.tolist(), cnt.tolist()))} ramp瓦片{rampn}")
    for i in range(ni):
        L = [int(v) for v in np.unique(wlab[(ilab == i) & walk]) if v >= 0]
        print(f"  岛{i}: 可走块 {L} {'✔' if len(L) <= 1 else '✘'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
