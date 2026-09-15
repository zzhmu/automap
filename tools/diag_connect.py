# -*- coding: utf-8 -*-
"""临时诊断：跑一遍地形流水线，把每块台地/可走连通块的面积和归属打出来，
用来定位「哪块台地走不通、为什么」。

不写地图文件。
"""
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from gen_height import (LAYER_ZERO, carve_ramps, fbm, limit_neighbor_jump,
                        mode_filter, _components, _tile_derivatives)


def build(rows, cols, seed, freq, levels, octaves, smooth, water_frac, max_jump):
    nprng = np.random.default_rng(seed)
    height = fbm(nprng, (rows, cols), freq, octaves=octaves)
    order = np.argsort(height, axis=None)
    quant = np.empty(height.size, dtype=np.float32)
    quant[order] = np.linspace(0.0, 1.0, height.size, dtype=np.float32)
    quant = quant.reshape(height.shape)
    is_water = quant < water_frac
    land_q = (quant - water_frac) / (1.0 - water_frac)
    lvl = np.clip(np.floor(land_q * levels), 0, levels - 1).astype(np.int32)
    code = np.where(is_water, 0, 1 + lvl)
    if smooth > 0:
        code = mode_filter(code, passes=smooth, values=levels + 2)
    is_water = code == 0
    layer = np.where(is_water, max(0, LAYER_ZERO - 1),
                     LAYER_ZERO + (code - 1)).astype(np.int16)
    layer = limit_neighbor_jump(layer, max_jump=max_jump)
    return layer, is_water


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    rows = cols = 97
    layer, is_water = build(rows, cols, seed, 1.6, 4, 2, 2, 0.30, 2)

    spread, grad, line, dry = _tile_derivatives(layer, is_water)
    H, W = spread.shape
    print(f"瓦片网格 {H}x{W}  干燥瓦片 {dry.sum()}  水域瓦片 {(~dry).sum()}")
    print("spread 直方图:", {int(v): int(c) for v, c in
                             zip(*np.unique(spread[dry], return_counts=True))})

    flat = (spread == 0) & dry
    lab, nlab = _components(flat)
    print(f"\n台地（四角同层的平地）: {nlab} 块")
    for i in range(nlab):
        m = lab == i
        ys, xs = np.nonzero(m)
        lay = np.bincount(layer[:-1, :-1][m]).argmax()
        print(f"  #{i:<2} 面积 {m.sum():>4}  层号 {lay}  "
              f"范围 y[{ys.min()}-{ys.max()}] x[{xs.min()}-{xs.max()}]")

    print(f"\n陆地连通块（忽略悬崖）: {_components(dry)[1]} 块")
    for i in range(_components(dry)[1]):
        m = _components(dry)[0] == i
        print(f"  岛 #{i} 面积 {m.sum():>4}")

    ramp, info = carve_ramps(layer, is_water, max_ramps=None)
    print(f"\n刻坡: {info}")
    all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
    walk = flat | all4
    wlab, nw = _components(walk)
    print(f"可走连通块: {nw} 块")
    for i in range(nw):
        m = wlab == i
        lays = sorted(set(layer[:-1, :-1][m].tolist()))
        print(f"  块 #{i} 面积 {m.sum():>4}  含层 {lays}")

    # 哪些台地没被任何坡道触到
    print("\n孤立台地检查（没有任何坡道瓦片贴着它）:")
    for i in range(nlab):
        m = lab == i
        ys, xs = np.nonzero(m)
        near = np.zeros_like(m)
        for y, x in zip(ys, xs):
            y0, y1 = max(0, y - 1), min(H, y + 2)
            x0, x1 = max(0, x - 1), min(W, x + 2)
            near[y0:y1, x0:x1] = True
        if not (near & all4).any():
            print(f"  #{i} 面积 {m.sum()}  ← 无坡道接出")
    # 非平地、非水、又没打坡的瓦片（真正的墙）
    wall = dry & (~flat) & (~all4)
    wl, wln = _components(wall)
    sizes = np.bincount(wl[wl >= 0]) if wln else np.array([])
    print(f"\n崖壁瓦片 {wall.sum()} 个，分 {wln} 段；最大一段 {int(sizes.max()) if wln else 0}")


if __name__ == "__main__":
    main()
