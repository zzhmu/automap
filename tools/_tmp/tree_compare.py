# -*- coding: utf-8 -*-
"""新旧撒树算法对比图（一次性诊断脚本，不属于正式工具链）。

左：老算法 = 对 fBm 噪声取一个分位阈值 → 必然连成大片实心林
右：新算法 = 树丛播种（每丛株数/半径/丛间距可控）
"""
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import add_doodads as A  # noqa: E402

SRC = os.path.join(ROOT, "out", "rmp_128.w3x")
SEED = 7
DENSITY = 0.35
FREQ = 3.0


def load_arrays():
    exe = A.default_exe()
    tmp = os.path.join(HERE, "cmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    subprocess.run([exe, "extract", SRC, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=180)
    w3e = open(os.path.join(tmp, "war3map.w3e"), "rb").read()
    _, W, H, HS = A.read_w3e_header(w3e)
    cols, rows = W + 1, H + 1
    water = np.zeros((rows, cols), dtype=bool)
    layer = np.zeros((rows, cols), dtype=np.int16)
    for r in range(rows):
        for c in range(cols):
            off = HS + (r * cols + c) * 7
            _, _, fb, _, b6 = struct.unpack_from("<HHBBB", w3e, off)
            water[r, c] = bool(fb & 0x40)
            layer[r, c] = b6 & 0x0F
    return W, H, water, layer


def eligibility(W, H, water, layer, slope_tol=1):
    dry = ~water
    elig = np.zeros((W, H), dtype=bool)
    for j in range(1, H - 1):
        for i in range(1, W - 1):
            c0 = dry[j, i] and dry[j, i + 1] and dry[j + 1, i] and dry[j + 1, i + 1]
            l4 = (layer[j, i], layer[j, i + 1], layer[j + 1, i], layer[j + 1, i + 1])
            elig[i, j] = c0 and (max(l4) - min(l4)) <= slope_tol
    return elig


def old_pick(rng, elig, W, H, density, freq):
    forest = A.norm01(A.fbm(rng, (W, H), freq))
    thr = float(np.quantile(forest[elig], 1.0 - density))
    return (forest >= thr) & elig


def render(water, W, H, picked):
    tw = np.zeros((W, H), dtype=bool)
    for j in range(H):
        for i in range(W):
            tw[i, j] = water[j, i] and water[j, i + 1] and water[j + 1, i] and water[j + 1, i + 1]
    img = np.full((H, W, 3), (200, 190, 160), dtype=np.uint8)
    img[np.transpose(tw)[::-1]] = (60, 110, 200)
    img[np.transpose(picked)[::-1]] = (20, 90, 20)
    return Image.fromarray(img).resize((W * 3, H * 3), Image.NEAREST)


def main():
    W, H, water, layer = load_arrays()
    elig = eligibility(W, H, water, layer)
    avail = int(elig.sum())

    rng1 = np.random.default_rng(SEED)
    old = old_pick(rng1, elig, W, H, DENSITY, 4.0)

    rng2 = np.random.default_rng(SEED)
    rng_bias = np.random.default_rng(SEED + 991)
    bias = A.norm01(A.fbm(rng_bias, (W, H), FREQ, octaves=2))
    target = int(round(avail * DENSITY * 0.985))
    new, ncl, ngrow = A.place_clumps(rng2, elig, target, 26.0, 4.5, 2.1, bias=bias, clump_bias=0.55)

    for name, m in (("老算法(单阈值)", old), ("新算法(树丛播种)", new)):
        b = A.blob_stats(m)
        print(f"{name}: {int(m.sum())} 棵, 连片 {b[0]} 片, 最大 {b[1]} 格, 平均 {b[2]:.1f}, "
              f"孤立 {b[3]*100:.0f}%")

    a = render(water, W, H, old)
    b = render(water, W, H, new)
    gap = 16
    canvas = Image.new("RGB", (a.width + b.width + gap, a.height + 34), (255, 255, 255))
    canvas.paste(a, (0, 34))
    canvas.paste(b, (a.width + gap, 34))
    d = ImageDraw.Draw(canvas)
    d.text((8, 10), f"BEFORE  old single-threshold  {int(old.sum())} trees  "
                    f"largest patch {A.blob_stats(old)[1]}", fill=(150, 20, 20))
    d.text((a.width + gap + 8, 10), f"AFTER  clump seeding  {int(new.sum())} trees  "
                                    f"largest patch {A.blob_stats(new)[1]}", fill=(20, 110, 20))
    out = os.path.join(ROOT, "out", "_tree_compare.png")
    canvas.save(out)
    print("对比图:", out)
    shutil.rmtree(os.path.join(HERE, "cmp"), ignore_errors=True)


if __name__ == "__main__":
    main()
