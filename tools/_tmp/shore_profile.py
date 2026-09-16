# -*- coding: utf-8 -*-
"""量「陆 ↔ 水 衔接处」的断面：岸线落差 + 陆侧坡度剖面。

给「衔接不自然 / 坡度太大」这类主观感受一个可比的数字。

每角点解出来的量（WE 高度单位，单位就是 WE 高度条上的数字）：
  h = 世界高度 - 水面高度      h > 0 = 陆地，h < 0 = 水下（-h = 水深）
  世界高度 = (groundHeight - 8192 + (layer - 2) * 512) / 4
  水面高度 = (waterHeight 低 14 位 - 8192) / 4

输出四组统计：
  ① 水底深度            -h over 水角点
  ② 岸线落差            h(陆地角点) - h(相邻水角点)，逐条 4 邻接陆/水边界
  ③ 岸线第一排陆的高度  紧邻水的那些陆地角点的 h（大 = 岸边是堵墙）
  ④ 陆侧坡度剖面        离水 d 格（d=1..8）的陆地角点平均 h → 每格抬升多少 WE

用法: python tools/_tmp/shore_profile.py <地图> [<地图> ...]
      python tools/_tmp/shore_profile.py out/acc_auto.w3x "Z:/.../Maps/(2)Harrow.w3m"
"""
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402

GROUND_ZERO = 8192
LAYER_STEP = 512


def read_map(path, tmp):
    exe = A.default_exe()
    for fn in ("war3map.w3e",):
        subprocess.run([exe, "extract", path, fn, tmp, "/fp"], capture_output=True, timeout=180)
    p = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(p):
        return None
    w3e = open(p, "rb").read()
    _ts, W, H, HS = A.read_w3e_header(w3e)
    R, C = H + 1, W + 1
    gh = np.zeros((R, C), np.int32)
    surf = np.zeros((R, C), np.float32)
    layer = np.zeros((R, C), np.int32)
    water = np.zeros((R, C), bool)
    for r in range(R):
        for c in range(C):
            off = HS + (r * C + c) * 7
            g, whf, fb, _b5, b6 = struct.unpack_from("<HHBBB", w3e, off)
            gh[r, c] = g
            layer[r, c] = b6 & 0x0F
            water[r, c] = bool(fb & 0x40)
            surf[r, c] = ((whf & 0x3FFF) - GROUND_ZERO) / 4.0
    world = (gh - GROUND_ZERO + (layer - 2) * LAYER_STEP) / 4.0
    return world, surf, water, W, H


def neigh_pairs(mask_a, mask_b):
    """4 邻接里 a 与 b 相邻的角点对（返回 a 侧索引数组）。"""
    out = []
    out.append((mask_a[:, :-1] & mask_b[:, 1:], (slice(None), slice(0, -1))))
    out.append((mask_a[:, 1:] & mask_b[:, :-1], (slice(None), slice(1, None))))
    out.append((mask_a[:-1, :] & mask_b[1:, :], (slice(0, -1), slice(None))))
    out.append((mask_a[1:, :] & mask_b[:-1, :], (slice(1, None), slice(None))))
    return out


def dist_to(mask, cap=24):
    """每个角点到最近 mask=True 的 4 邻接距离（向量化膨胀）。"""
    d = np.full(mask.shape, cap, np.int32)
    d[mask] = 0
    cur = mask.copy()
    k = 1
    while cur.any() and k <= cap:
        nb = np.zeros_like(cur)
        nb[:, 1:] |= cur[:, :-1]
        nb[:, :-1] |= cur[:, 1:]
        nb[1:, :] |= cur[:-1, :]
        nb[:-1, :] |= cur[1:, :]
        new = nb & ~cur
        if not new.any():
            break
        d[new] = k
        cur |= new
        k += 1
    return d


def pct(a, q):
    a = np.asarray(a, dtype=float)
    if not len(a):
        return float("nan")
    return float(np.percentile(a, q))


def report(path, tmp):
    got = read_map(path, tmp)
    if got is None:
        print(f"  !! 读不到 {path}")
        return None
    world, surf, water, W, H = got
    h = world - surf
    n_w = int(water.sum())
    if n_w == 0:
        print(f"{os.path.basename(path):<26} 没有水，跳过")
        return None
    land = ~water

    depth = (-h)[water]

    # ② 岸线落差：4 邻接 (陆地, 水) 对
    drops = []
    for m, sl in neigh_pairs(land, water):
        if m.any():
            lw = h[sl]
            drops.append(lw[m])
    for m, sl in neigh_pairs(water, land):
        if m.any():
            lw = h[sl]
            drops.append(-lw[m])
    drops = np.concatenate(drops) if drops else np.array([])

    # ③ 岸线第一排陆
    first = np.zeros_like(land)
    for m, sl in neigh_pairs(land, water):
        first[sl] |= m
    first &= land

    # ④ 陆侧剖面
    dw = dist_to(water, cap=24)
    prof = []
    for d in range(1, 9):
        sel = land & (dw == d)
        prof.append(float(h[sel].mean()) if sel.any() else float("nan"))

    print(f"\n{os.path.basename(path)}  {W}x{H}  水角点 {n_w} ({n_w/water.size*100:.1f}%)")
    print(f"  ① 水底深度    p10={pct(depth,10):7.1f}  p50={pct(depth,50):7.1f}  "
          f"p90={pct(depth,90):7.1f}   （官方浅水底 = 128 的整层台阶）")
    print(f"  ② 岸线落差    p10={pct(drops,10):7.1f}  p50={pct(drops,50):7.1f}  "
          f"p90={pct(drops,90):7.1f}   n={len(drops)}")
    print(f"  ③ 岸线第一排陆 h  p10={pct(h[first],10):7.1f}  p50={pct(h[first],50):7.1f}  "
          f"p90={pct(h[first],90):7.1f}")
    print("  ④ 陆侧剖面(离水 d 格的平均 h): "
          + "  ".join(f"d{d}={v:5.0f}" for d, v in enumerate(prof, 1)))
    steps = [prof[i + 1] - prof[i] for i in range(7)
             if not (np.isnan(prof[i]) or np.isnan(prof[i + 1]))]
    print(f"     前 8 格平均每格抬升 {np.mean(steps):6.1f} WE/格"
          f"（128 WE/格 ≈ 45°，官方丘陵 §大概多少见下）")
    return dict(depth50=pct(depth, 50), drop50=pct(drops, 50),
                drop90=pct(drops, 90), first50=pct(h[first], 50), prof=prof)


def main():
    maps = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not maps:
        print(__doc__)
        return
    tmp = A.make_tmp("shoreprofile")
    try:
        for p in maps:
            p = p.replace("\\", os.sep).replace("/", os.sep)
            if not os.path.isabs(p):
                p = os.path.join(os.path.dirname(TOOLS), p)
            report(p, tmp)
    finally:
        A.drop_tmp(tmp)


main()
