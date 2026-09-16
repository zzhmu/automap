# -*- coding: utf-8 -*-
"""常驻体检：地形世界高度是否落在「官方图从未越过的区间」内。

为什么要有这个工具：地形的**世界高度**一旦跌破 -256 WE，World Editor 能打开、
能正常显示，但**一编辑地形就闪退**。实测 45 张官方对战图：最低角点恰好卡在
-256.0（= layer 0 的世界基准 (0-2)*128），**没有一张图有任何角点低于它**；
最高 1536.0。这是一条硬边界，不是巧合。

用法：
    python tools/inspect_world_range.py                 # 体检 out/样图_*.w3x
    python tools/inspect_world_range.py out/foo.w3x     # 体检指定图

默认会先扫一遍 ../Maps 下的全部官方图当基准（45 张，约 1 分钟），
再逐张比生成图，越界的指标后面标 ✘。

指标（长度单位一律换算成 WE 高度 = (gh-8192+(layer-2)*512)/4）：
  intra   层内偏移 = (gh-8192)/4            —— 单层模式全靠它堆落差
  world   世界高度                          —— ★ 关键：必须 ∈ [-256, 1536]
  d_gh    相邻角点 gh 差（WE）              —— 同层内的陡坎
  d_world 相邻角点世界高度差（WE）          —— 表面坡度，官方 max 408
  d_layer 相邻角点层差
  depth   水角点的深度 = 水面 - 世界高度
"""
import glob
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
EXE = os.path.normpath(os.path.join(ROOT, "..", "..", "bin", "MPQEditor.exe"))
if not os.path.exists(EXE):
    EXE = os.path.normpath(os.path.join(ROOT, "bin", "MPQEditor.exe"))
OFFICIAL = os.path.normpath(os.path.join(ROOT, "..", "Maps"))
GROUND_ZERO = 8192
LAYER_STEP = 512


def read_header(data):
    pos = 8
    tileset = chr(data[pos]); pos += 1
    pos += 4                                     # custom tileset flag
    n_ground = struct.unpack_from("<I", data, pos)[0]; pos += 4
    pos += 4 * n_ground
    n_cliff = struct.unpack_from("<I", data, pos)[0]; pos += 4
    pos += 4 * n_cliff
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return struct.unpack_from("<I", data, 4)[0], tileset, w, h, pos


def read_w3e(path):
    data = open(path, "rb").read()
    if data[:4] != b"W3E!":
        return None
    ver, tileset, W, H, HS = read_header(data)
    if ver != 11:
        return None
    rows, cols = H + 1, W + 1
    if len(data) - HS != rows * cols * 7:
        return None
    gh = np.zeros((rows, cols), dtype=np.int32)
    wh = np.zeros((rows, cols), dtype=np.uint16)
    fl = np.zeros((rows, cols), dtype=np.uint8)
    ly = np.zeros((rows, cols), dtype=np.int16)
    for r in range(rows):
        for c in range(cols):
            o = HS + (r * cols + c) * 7
            gh[r, c], wh[r, c], fl[r, c], _b5, b6 = struct.unpack_from("<HHBBB", data, o)
            ly[r, c] = b6 & 0x0F
    return dict(W=W, H=H, gh=gh, wh=wh, flags=fl, layer=ly, tileset=tileset)


def metrics(m):
    gh, ly = m["gh"], m["layer"]
    world = (gh - GROUND_ZERO + (ly - 2) * LAYER_STEP) / 4.0
    intra = (gh - GROUND_ZERO) / 4.0
    plane = np.full_like(world, np.nan)
    plane_raw = (m["wh"] & 0x3FFF).astype(np.float32)
    plane = (plane_raw - GROUND_ZERO) / 4.0          # 水面当作 gh@layer2 解读
    d_gh = np.abs(np.diff(intra, axis=0)).max(), np.abs(np.diff(intra, axis=1)).max()
    d_w = np.abs(np.diff(world, axis=0)).max(), np.abs(np.diff(world, axis=1)).max()
    d_l = max(int(np.abs(np.diff(ly, axis=0)).max()), int(np.abs(np.diff(ly, axis=1)).max()))
    water = (m["flags"] & 0x40) != 0
    depth = (plane - world)[water] if water.any() else np.array([0.0])
    return {
        "intra_min": float(intra.min()), "intra_max": float(intra.max()),
        "intra_absmax": float(np.abs(intra).max()),
        "world_min": float(world.min()), "world_max": float(world.max()),
        "d_gh": float(max(d_gh)), "d_world": float(max(d_w)), "d_layer": d_l,
        "layer_min": int(ly.min()), "layer_max": int(ly.max()),
        "depth_max": float(depth.max()) if depth.size else 0.0,
        "n_water": int(water.sum()),
    }


KEYS = ["intra_min", "intra_max", "intra_absmax", "world_min", "world_max",
        "d_gh", "d_world", "d_layer", "layer_min", "layer_max", "depth_max"]


def main():
    maps = sys.argv[1:] or glob.glob(os.path.join(ROOT, "out", "样图_*.w3x"))
    # 官方图基准
    env = {k: [] for k in KEYS}
    n = 0
    tmp = os.path.join(HERE, "diag_we")
    os.makedirs(tmp, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(OFFICIAL, "*.w3*"))):
        r = subprocess.run([EXE, "extract", p, "war3map.w3e", tmp, "/fp"],
                           capture_output=True, timeout=120)
        f = os.path.join(tmp, "war3map.w3e")
        if not os.path.exists(f):
            continue
        try:
            m = read_w3e(f)
        except Exception:
            m = None
        os.remove(f)
        if not m:
            continue
        v = metrics(m)
        for k in KEYS:
            env[k].append(v[k])
        n += 1
    print(f"官方图基准：{n} 张\n")
    print(f"{'指标':<14}{'官方 min':>10}{'官方 max':>10}   | 生成图")
    hdr = False
    for p in maps:
        tmpf = os.path.join(tmp, "gen")
        os.makedirs(tmpf, exist_ok=True)
        subprocess.run([EXE, "extract", p, "war3map.w3e", tmpf, "/fp"],
                       capture_output=True, timeout=120)
        f = os.path.join(tmpf, "war3map.w3e")
        if not os.path.exists(f):
            print(f"{p}: 提取失败")
            continue
        m = read_w3e(f)
        os.remove(f)
        v = metrics(m)
        print(f"\n--- {os.path.basename(p)}  ({m['W']}x{m['H']}) ---")
        for k in KEYS:
            lo, hi = min(env[k]), max(env[k])
            x = v[k]
            flag = ""
            if k.endswith("_min") or k == "layer_min":
                flag = "  ✘ 低于官方下限" if x < lo - 1e-9 else ""
            else:
                flag = "  ✘ 超出官方上限" if x > hi + 1e-9 else ""
            print(f"  {k:<12}{lo:>10.1f}{hi:>10.1f}   |{x:>10.1f}{flag}")


if __name__ == "__main__":
    main()
