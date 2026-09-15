# -*- coding: utf-8 -*-
"""实测官方地图「层内地面起伏」——即 WE 地形面板「应用高度」那些笔刷留下的效果。

背景：w3e 里每角点有两个高度来源
  groundHeight (raw, 基准 8192, 4 raw = 1 WE 高度单位)
  layerHeight  (0=层2, 每层 512 raw = 128 WE 高度单位) —— 这一层是「悬崖」的量化层
WE 高度 = (groundHeight - 8192 + (layer-2)*512) / 4
所以「同一个 layer 内部」的 groundHeight 变化 = 平滑的隆起/凹陷/凹凸不平，不是悬崖。
本脚本就量这个内部残差，用来给生成器的参数定基准。

指标：
  resid         = groundHeight - 该台地(同 layer 连通块)内 groundHeight 均值
  low_freq      = resid 的 5x5 局部均值      → 对应 WE 的「隆起/凹陷」笔刷（大尺度）
  high_freq     = resid - low_freq          → 对应 WE 的「凹凸不平」笔刷（小尺度噪波）
  单位统一换成 WE 高度单位（除以 4），这样和 WE 界面里的数字对得上。
"""
import os
import re
import shutil
import struct
import subprocess
import sys
from collections import deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

PUB = os.path.normpath(os.path.join(ROOT, ".."))          # "... publish"
MAPS = os.path.join(PUB, "Maps")
EXE = os.path.normpath(os.path.join(ROOT, "bin", "MPQEditor.exe"))

GROUND_ZERO = 8192
LAYER_STEP = 512


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


def read_w3e_header(data):
    pos = 8
    pos += 1
    pos += 4
    ng = struct.unpack_from("<I", data, pos)[0]; pos += 4
    pos += 4 * ng
    nc = struct.unpack_from("<I", data, pos)[0]; pos += 4
    pos += 4 * nc
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return w, h, pos


def load(path, tmp):
    subprocess.run([EXE, "extract", path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=180)
    p = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(p):
        return None
    data = open(p, "rb").read()
    if data[:4] != b"W3E!":
        return None
    W, H, HS = read_w3e_header(data)
    cols, rows = W + 1, H + 1
    if len(data) - HS != rows * cols * 7:
        return None
    gh = np.zeros((rows, cols), dtype=np.int32)
    layer = np.zeros((rows, cols), dtype=np.int16)
    bad = np.zeros((rows, cols), dtype=bool)          # 水 / 地图外
    for r in range(rows):
        for c in range(cols):
            off = HS + (r * cols + c) * 7
            g, whf, fb, _b5, b6 = struct.unpack_from("<HHBBB", data, off)
            gh[r, c] = g
            layer[r, c] = b6 & 0x0F
            bad[r, c] = bool(fb & 0x40) or bool((whf & 0x4000)) or bool(fb & 0x80)
    return gh, layer, bad, W, H


def plateau_labels(layer, ok):
    """同 layer 的 4 邻接连通块 = 一块台地（被悬崖隔开）。"""
    rows, cols = layer.shape
    lab = np.full((rows, cols), -1, dtype=np.int32)
    n = 0
    for r in range(rows):
        for c in range(cols):
            if not ok[r, c] or lab[r, c] >= 0:
                continue
            q = deque([(r, c)])
            lab[r, c] = n
            while q:
                y, x = q.popleft()
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < rows and 0 <= nx < cols and ok[ny, nx] \
                            and lab[ny, nx] < 0 and layer[ny, nx] == layer[y, x]:
                        lab[ny, nx] = n
                        q.append((ny, nx))
            n += 1
    return lab, n


def box_mean(a, k=5):
    """边缘保形的 kxk 均值（用累积和做，够快）。"""
    pad = k // 2
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(np.cumsum(p, 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    rows = a.shape[0]
    cols = a.shape[1]
    out = np.zeros_like(a, dtype=np.float64)
    r0 = np.arange(rows)
    c0 = np.arange(cols)
    for i in (0,):
        pass
    # out[y,x] = mean of p[y:y+k, x:x+k]
    Yi = np.add.outer(r0, np.arange(k + 1))
    Xi = np.add.outer(c0, np.arange(k + 1))
    P = c[Yi][:, :, Xi]              # (rows, k+1, cols, k+1)
    out = (P[:, k, :, k] - P[:, 0, :, k] - P[:, k, :, 0] + P[:, 0, :, 0]) / (k * k)
    return out


def analyze(path, tmp, label):
    got = load(path, tmp)
    if got is None:
        return None
    gh, layer, bad, W, H = got
    rows, cols = layer.shape
    ok = ~bad
    # 只统计够大的台地：小块台地本身就一两格，量残差没意义
    lab, n = plateau_labels(layer, ok)
    if n == 0:
        return None
    cnt = np.bincount(lab[lab >= 0].ravel(), minlength=n)
    keep = np.zeros(n, dtype=bool)
    keep[cnt >= 40] = True
    sel = (lab >= 0) & keep[lab]
    if sel.sum() < 200:
        return None
    # 台地内去均值 → 残差（单位换成 WE 高度单位）
    resid = np.zeros((rows, cols), dtype=np.float64)
    for k in np.nonzero(keep)[0]:
        m = lab == k
        resid[m] = gh[m] - gh[m].mean()
    resid /= 4.0
    low = box_mean(resid, 5)
    high = resid - low
    d_adj = np.abs(np.diff(gh, axis=0)) / 4.0
    return {
        "name": label,
        "size": f"{W+1}x{H+1}",
        "resid_std": float(resid[sel].std()),
        "resid_p01": float(np.percentile(resid[sel], 1)),
        "resid_p99": float(np.percentile(resid[sel], 99)),
        "low_std": float(low[sel].std()),
        "high_std": float(high[sel].std()),
        "high_p99": float(np.percentile(np.abs(high[sel]), 99)),
        "adj_p50": float(np.percentile(d_adj, 50)),
        "adj_p99": float(np.percentile(d_adj, 99)),
        "plats": int(keep.sum()),
        "cells": int(sel.sum()),
    }


def main():
    maps = find_maps()
    print(f"官方地图 {len(maps)} 张（{MAPS}）\n")
    tmp = os.path.join(HERE, "hgt_r%d" % os.getpid())
    os.makedirs(tmp, exist_ok=True)
    rows = []
    for i, p in enumerate(maps, 1):
        r = analyze(p, tmp, os.path.basename(p))
        if r is None:
            continue
        rows.append(r)
        print(f"[{i}/{len(maps)}] {r['name'][:34]:<34} {r['size']:>9}  "
              f"残差σ={r['resid_std']:6.2f}  低频σ={r['low_std']:6.2f}  "
              f"高频σ={r['high_std']:5.2f}  邻差p99={r['adj_p99']:5.1f}")

    if not rows:
        print("没读到数据")
        return 1
    print("\n" + "=" * 96)
    print("单位：WE 高度单位（1 = WE 里一格高度数字）")

    def agg(k):
        v = np.array([r[k] for r in rows], dtype=float)
        return np.percentile(v, [10, 50, 90])

    for k, name in (("resid_std", "台地内残差 σ"),
                    ("low_std", "低频(隆起/凹陷) σ"),
                    ("high_std", "高频(凹凸不平) σ"),
                    ("high_p99", "高频 |残差| p99"),
                    ("adj_p50", "相邻角点高差 中位"),
                    ("adj_p99", "相邻角点高差 p99")):
        p10, p50, p90 = agg(k)
        print(f"  {name:<22} p10={p10:7.2f}   典型={p50:7.2f}   p90={p90:7.2f}")
    print("=" * 96)

    # 参考：本项目当前生成的地图（若在）
    for cand in ("rand_657571.w3x", "ui_demo.w3x"):
        p = os.path.join(ROOT, "out", cand)
        if os.path.exists(p):
            r = analyze(p, tmp, "本项目 " + cand)
            if r:
                print(f"\n本项目参照 {cand}:  残差σ={r['resid_std']:.2f}  "
                      f"低频σ={r['low_std']:.2f}  高频σ={r['high_std']:.2f}  "
                      f"邻差p99={r['adj_p99']:.1f}")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
