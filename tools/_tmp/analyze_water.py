# -*- coding: utf-8 -*-
"""实测官方地图的水：水面高度、水底深度分布、浅水/深水各占多少。

w3e 里 groundHeight 是绝对高度（4 原始单位 = 1 WE 高度单位）。水面在 WC3 里是固定
高度（不随地图变），所以「水深 = 水面 − groundHeight」。本脚本反推这个水面高度，
并量出水底能压到多低 —— 这决定「水下隆起」能有多大幅度。
"""
import os
import shutil
import struct
import subprocess
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import analyze_height as A   # noqa: E402

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")
EXE = os.path.normpath(os.path.join(ROOT, "bin", "MPQEditor.exe"))


def load_flags(path, tmp):
    """返回 (gh, whf, layer, is_water, is_outside)，直接从 w3e 解析。"""
    subprocess.run([EXE, "extract", path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=180)
    p = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(p):
        return None
    data = open(p, "rb").read()
    if data[:4] != b"W3E!":
        return None
    W, H, HS = A.read_w3e_header(data)
    rows, cols = H + 1, W + 1
    if len(data) - HS != rows * cols * 7:
        return None
    arr = np.frombuffer(data, dtype=np.uint8, count=rows * cols * 7, offset=HS)
    arr = arr.reshape(rows, cols, 7)
    gh = (arr[:, :, 0].astype(np.int32) | (arr[:, :, 1].astype(np.int32) << 8))
    whf = (arr[:, :, 2].astype(np.int32) | (arr[:, :, 3].astype(np.int32) << 8))
    flags = arr[:, :, 4]
    layer = (arr[:, :, 6] & 0x0F).astype(np.int16)
    water = (flags & 0x40) != 0
    outside = ((flags & 0x80) != 0) | ((whf & 0x4000) != 0)
    return gh, whf, layer, water, outside


def find_maps():
    out = []
    for sub in ("", "FrozenThrone"):
        d = os.path.join(MAPS, sub) if sub else MAPS
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith((".w3m", ".w3x")):
                out.append(os.path.join(d, fn))
    return out


def main():
    maps = find_maps()
    tmp = os.path.join(HERE, "wat_r%d" % os.getpid())
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    all_w, all_l, all_lay, all_dep = [], [], [], []
    rows = []
    for p in maps:
        got = load_flags(p, tmp)
        if got is None:
            continue
        gh, whf, layer, water, outside = got
        if water.sum() < 50:
            continue
        w = gh[water].astype(np.float64)
        land = gh[~water & ~outside].astype(np.float64)
        if land.size < 200:
            continue
        # 水面假设 = waterHeight 字段低 14 位
        wl = (whf & 0x3FFF)[water].astype(np.float64)
        depth = wl - w                       # 正数 = 水底在水面之下
        all_w.append(w)
        all_l.append(land)
        all_lay.append(layer[water])
        all_dep.append(depth)
        rows.append((os.path.basename(p), int(water.sum()),
                     np.percentile(wl, 50), np.percentile(depth, 1),
                     np.percentile(depth, 50), np.percentile(depth, 99), depth.max(),
                     np.percentile(land, 50), land.min(),
                     sorted(set(int(v) for v in np.unique(layer[water])))))
    if not all_w:
        print("没读到水")
        return 1
    W = np.concatenate(all_w)
    L = np.concatenate(all_l)
    LA = np.concatenate(all_lay)
    D = np.concatenate(all_dep)
    print(f"\n汇总：水角点 {W.size} 个 / 陆角点 {L.size} 个（{len(rows)} 张图）")
    print("\n【假设】水面 = waterHeight 字段低 14 位（0x3FFF 掩码）")
    print("水角点「水深 = 水面 − groundHeight」分位（原始单位 / WE 高度单位）：")
    for q in (0.5, 1, 5, 25, 50, 75, 95, 99, 100):
        v = np.percentile(D, q)
        print(f"  p{q:<5} {v:8.1f} raw   {v/4:8.1f} WE")
    print(f"\n水深为负（水面低于地面 = 假设不成立）的占比："
          f"{(D < 0).mean()*100:.2f}%")
    print(f"水深 > 512（一层）的占比：{(D > 512).mean()*100:.2f}%")
    print(f"水深 > 1024（两层）的占比：{(D > 1024).mean()*100:.2f}%")
    print(f"\n水角点出现过的 layer 值分布：{Counter(LA.tolist()).most_common(12)}")

    print("\n各图明细（深度按 WE 高度单位）：")
    print(f"  {'地图':<28}{'水角点':>7}{'水面p50':>8}{'深p1':>7}{'深p50':>7}"
          f"{'深p99':>7}{'深max':>7}{'陆p50':>7}   layer")
    for n, c, wl, d1, d50, d99, dmx, lm, lmin, lays in rows[:26]:
        print(f"  {n[:28]:<28}{c:>7}{wl:>8.0f}{d1/4:>7.1f}{d50/4:>7.1f}"
              f"{d99/4:>7.1f}{dmx/4:>7.1f}{lm:>7.0f}   {lays}")

    # ---- 判定「陆地绝不会低于水面」这条不变式在官方图里是否成立 ----
    # 只在 waterHeight 字段干净的图（水面值一致 + 水深非负）上判定，避免被老图的
    # 陈旧字段带偏。
    print("\n【不变式检查】陆地世界高度 < 水面 的角点占比（只取 waterHeight 干净的图）:")
    print(f"  {'地图':<28}{'水面':>8}{'陆低于水面占比':>16}{'最低陆-水面(WE)':>18}")
    oks = 0
    for p in maps:
        got = load_flags(p, tmp)
        if got is None:
            continue
        gh, whf, layer, water, outside = got
        if water.sum() < 50:
            continue
        wl = (whf & 0x3FFF)[water]
        if wl.std() > 64:                       # 水面字段不一致 → 跳过
            continue
        plane = float(np.median(wl))
        world = gh + (layer.astype(np.int32) - 2) * 512
        if float(np.percentile(world[water], 50)) >= plane:   # 水深非负
            continue
        land = ~water & ~outside
        if land.sum() < 200:
            continue
        low = (world[land] < plane)
        oks += 1
        if low.mean() > 0 or oks <= 20:
            print(f"  {os.path.basename(p)[:28]:<28}{plane:>8.0f}"
                  f"{low.mean()*100:>15.2f}%{(world[land].min()-plane)/4:>18.1f}")
    print(f"  → 干净且水深非负的官方图共 {oks} 张")
    return 0


if __name__ == "__main__":
    sys.exit(main())
