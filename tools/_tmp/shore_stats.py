# -*- coding: utf-8 -*-
"""岸线（陆 ↔ 水 衔接处）体检 —— 口径修正版。

## 口径（2026-09-16 修正，之前 shore_profile.py 的结论曾被我误当作废，其实是对的）

w3e v11 每角点 7 字节：
    u16 groundHeight | u16 waterHeight | u8 flags | u8 groundTex/var | u8 cliffTex<<4 | layer
其中 **waterHeight 不是逐角点水面，而是「本图水面平面的绝对 raw 高度」**——
它是常量（Riverrun 全图 9728、LostTemple 全图 8192），我们自己的写回逻辑
（gen_height.py L2415 `wh = plane_raw`）也是写常量，两边语义一致，不是 bug。

于是「某角点相对水面多高」= 该角点世界高度 − 水面平面世界高度：

    world = (gh   - 8192 + (layer-2)*512) / 4          # 角点世界高度（WE）
    surf  = (wh   - 8192) / 4                          # 水面平面世界高度（WE）
    h     = world - surf                               # h>0 陆地，h<0 水下（-h = 水深）

等价地 h < 0 ⟺ gh + (layer-2)*512 < wh ⟺ 该角点在地形上低于水面。
flags 的 0x40「water」位应当与 h<0 一致 —— 脚本里会实测这个一致率来自证口径。

## 输出指标（全部先剔除地图外角点 wh&0x4000 / flags&0x80）

    ① 水面覆盖、水深分位、水深是 128 整层倍数的比例
    ② 岸线落差 = h(陆) − h(相邻水)，逐条 4 邻接陆/水边界
    ③ 岸带坡度剖面：离水 d 格（d=1..12）的陆地角点
         · 平均 h       —— 岸台有多高
         · 平均 |∇h|    —— 那一圈有多陡
       并与「内陆」（离水 ≥ 16 格）的平均 |∇h| 对比 → 岸线是不是明显更陡
    ④ 「岸墙率」：岸线落差 ≥ 128 WE（一整层）的比例

用法:
    python tools/_tmp/shore_stats.py                    # 官方 43 张 + 本项目 out/ 里的产物
    python tools/_tmp/shore_stats.py --ours out/acc_auto.w3x out/gui_cliffs.w3x
"""
import json
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")

GROUND_ZERO = 8192
LAYER_STEP = 512
LAYER_ZERO = 2


# ---------------------------------------------------------------- 读 w3e
def load(path, tmp):
    exe = A.default_exe()
    subprocess.run([exe, "extract", path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=240)
    p = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(p):
        return None
    data = open(p, "rb").read()
    if data[:4] != b"W3E!":
        return None
    _ts, w, h, hs = A.read_w3e_header(data)
    R, C = h + 1, w + 1
    if len(data) - hs != R * C * 7:
        return None
    a = np.frombuffer(data, np.uint8, count=R * C * 7, offset=hs).reshape(R * C, 7)
    gh = a[:, 0].astype(np.uint16) | (a[:, 1].astype(np.uint16) << 8)
    wh = a[:, 2].astype(np.uint16) | (a[:, 3].astype(np.uint16) << 8)
    fb = a[:, 4]
    layer = a[:, 6] & 0x0F
    world = (gh.astype(np.float32) - GROUND_ZERO
             + (layer.astype(np.float32) - LAYER_ZERO) * LAYER_STEP) / 4.0
    surf = (np.bitwise_and(wh, 0x3FFF).astype(np.float32) - GROUND_ZERO) / 4.0
    water = (fb & 0x40).astype(bool)
    out_side = ((wh & 0x4000) != 0) | ((fb & 0x80) != 0)
    shape = (R, C)
    return dict(h=(world - surf).reshape(shape), water=water.reshape(shape),
                outside=out_side.reshape(shape), layer=layer.reshape(shape),
                wh_raw=int(np.bitwise_and(wh, 0x3FFF)[0]))


# ---------------------------------------------------------------- 距离场 / 坡度
def dist_to(mask, cap=32):
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


def slope_field(h):
    """每角点 4 邻接 |Δh| 的最大值（= 该点周围的局部陡度，WE/格）。"""
    g = np.zeros(h.shape, np.float32)
    for ax in (0, 1):
        d = np.abs(np.diff(h, axis=ax))
        if ax == 0:
            g[:-1, :] = np.maximum(g[:-1, :], d)
            g[1:, :] = np.maximum(g[1:, :], d)
        else:
            g[:, :-1] = np.maximum(g[:, :-1], d)
            g[:, 1:] = np.maximum(g[:, 1:], d)
    return g


def boundary_pairs(land, water):
    """4 邻接 (land_i, water_j) 的布尔掩码 + (i 的切片, j 的切片)。"""
    res = []
    res.append((land[:, :-1] & water[:, 1:], (slice(None), slice(0, -1)),
                (slice(None), slice(1, None))))
    res.append((land[:, 1:] & water[:, :-1], (slice(None), slice(1, None)),
                (slice(None), slice(0, -1))))
    res.append((land[:-1, :] & water[1:, :], (slice(0, -1), slice(None)),
                (slice(1, None), slice(None))))
    res.append((land[1:, :] & water[:-1, :], (slice(1, None), slice(None)),
                (slice(0, -1), slice(None))))
    return res


def q(a, p):
    a = np.asarray(a, dtype=float).ravel()
    return float(np.percentile(a, p)) if a.size else float("nan")


# ---------------------------------------------------------------- 单图体检
def report(path, tmp, tag=""):
    got = load(path, tmp)
    if got is None:
        return None
    h = got["h"]
    water = got["water"] & ~got["outside"]
    land = ~got["water"] & ~got["outside"]
    play = ~got["outside"]
    nw, np_ = int(water.sum()), int(play.sum())
    if np_ == 0 or nw * 100.0 / np_ < 1.0:
        return dict(name=os.path.basename(path), water_pct=nw * 100.0 / max(1, np_),
                    no_water=True)
    # 口径自证：flags 0x40 与 h<0 的一致率
    agree = float((got["water"][play] == (h[play] < 0)).mean()) * 100.0

    depth = (-h)[water]
    # ② 岸线落差：逐条 4 邻接 (陆, 水) 边界，取陆侧 h − 水侧 h
    drop = []
    for m, si, sj in boundary_pairs(land, water):
        if m.any():
            drop.append(h[si][m] - h[sj][m])
    for m, si, sj in boundary_pairs(water, land):
        if m.any():
            drop.append(h[sj][m] - h[si][m])
    drop = np.concatenate(drop) if drop else np.array([])

    dw = dist_to(water, cap=32)
    sl = slope_field(h)
    prof_h, prof_s = [], []
    for d in range(1, 13):
        sel = land & (dw == d)
        prof_h.append(float(h[sel].mean()) if sel.any() else float("nan"))
        prof_s.append(float(sl[sel].mean()) if sel.any() else float("nan"))
    sel_in = land & (dw >= 16) & (dw < 32)
    inland = float(sl[sel_in].mean()) if sel_in.any() else float("nan")

    step128 = float(np.mean(np.abs(depth / 128.0 - np.round(depth / 128.0)) < 0.02)) * 100
    wall = float(np.mean(drop >= 128.0)) * 100 if drop.size else float("nan")

    r = dict(name=os.path.basename(path), tag=tag, water_pct=nw * 100.0 / np_,
             agree=agree, depth=[q(depth, x) for x in (10, 50, 90)],
             step128=step128, drop=[q(drop, x) for x in (10, 50, 90)],
             drop_n=int(drop.size), wall=wall,
             prof_h=prof_h, prof_s=prof_s, inland=inland,
             surf_raw=got["wh_raw"])
    return r


def pr(r):
    if r is None:
        return
    if r.get("no_water"):
        print(f"  {r['name'][:30]:<30} 水 {r['water_pct']:5.1f}% → 跳过")
        return
    print(f"  {r['name'][:30]:<30} 水{r['water_pct']:5.1f}%  "
          f"口径一致{r['agree']:5.1f}%  "
          f"水深 p10/50/90={r['depth'][0]:6.1f}/{r['depth'][1]:6.1f}/{r['depth'][2]:6.1f} "
          f"(128倍 {r['step128']:4.1f}%)  "
          f"岸落差 p10/50/90={r['drop'][0]:6.1f}/{r['drop'][1]:6.1f}/{r['drop'][2]:6.1f} "
          f"岸墙率{r['wall']:5.1f}%")
    print(f"     岸带剖面 h: " + " ".join(f"{v:6.0f}" for v in r["prof_h"][:10]))
    tail = ""
    if r["inland"]:
        tail = (f"   内陆坡度 {r['inland']:6.0f}"
                f"   岸/内比 {r['prof_s'][0] / r['inland']:.2f}")
    print(f"     岸带坡度  : " + " ".join(f"{v:6.0f}" for v in r["prof_s"][:10]) + tail)


def agg(rows, key, idx=None):
    v = []
    for r in rows:
        if r.get("no_water"):
            continue
        x = r[key] if idx is None else r[key][idx]
        v.append(x)
    v = np.array(v, float)
    v = v[~np.isnan(v)]
    if not v.size:
        return (float("nan"),) * 3
    return tuple(np.percentile(v, [10, 50, 90]))


def main():
    args = sys.argv[1:]
    ours = []
    if "--ours" in args:
        i = args.index("--ours")
        ours = args[i + 1:]
        args = args[:i]
    tmp = A.make_tmp("shorestats")
    off_rows, our_rows = [], []
    try:
        if not args:
            maps = sorted(fn for fn in os.listdir(MAPS)
                          if fn.lower().endswith((".w3m", ".w3x")))
            print(f"=== 官方对战图 {len(maps)} 张（{MAPS}）===\n")
            for fn in maps:
                r = report(os.path.join(MAPS, fn), tmp, "official")
                if r is None:
                    print(f"  {fn[:30]:<30} 读不到，跳过")
                    continue
                if not r.get("no_water"):
                    off_rows.append(r)
                print(f"  {fn[:30]:<30} 水{r['water_pct']:5.1f}%"
                      + ("" if r.get("no_water") else
                         f"  口径一致{r['agree']:5.1f}%  "
                         f"水深 p50={r['depth'][1]:6.1f}(128倍{r['step128']:4.1f}%)  "
                         f"岸落差 p10/50/90={r['drop'][0]:5.0f}/{r['drop'][1]:5.0f}/"
                         f"{r['drop'][2]:5.0f}  岸墙率{r['wall']:4.0f}%"))
        else:
            for p in args:
                p = p.replace("\\", os.sep)
                if not os.path.isabs(p):
                    p = os.path.join(ROOT, p)
                r = report(p, tmp, "official")
                if r and not r.get("no_water"):
                    off_rows.append(r)
                pr(r)

        if not ours:
            cand = []
            od = os.path.join(ROOT, "out")
            for fn in sorted(os.listdir(od)):
                if fn.endswith(".w3x") and not fn.startswith("_"):
                    cand.append(os.path.join(od, fn))
            # 只取有代表性的几张，别把 out/ 全扫了
            pref = [c for c in cand if any(k in os.path.basename(c)
                                           for k in ("acc_auto", "gui_cliffs",
                                                     "gui_shallow", "acc_land"))]
            ours = pref or cand[:6]
        if ours:
            print("\n=== 本项目产物 ===\n")
            for p in ours:
                if not os.path.isabs(p):
                    p = os.path.join(ROOT, p)
                if not os.path.exists(p):
                    print(f"  {p} 不存在")
                    continue
                r = report(p, tmp, "ours")
                if r is None:
                    print(f"  {os.path.basename(p)} 读不到")
                    continue
                if not r.get("no_water"):
                    our_rows.append(r)
                pr(r)

        print("\n" + "=" * 108)
        print("官方有水的图：", len(off_rows), "  本项目：", len(our_rows))
        for name, rows in (("官方", off_rows), ("我们", our_rows)):
            if not rows:
                continue
            print(f"\n【{name}】n={len(rows)}")
            a = agg(rows, "water_pct")
            print(f"  水面覆盖%        p10/50/90 = {a[0]:6.1f} /{a[1]:6.1f} /{a[2]:6.1f}")
            a = agg(rows, "depth", 1)
            print(f"  水深 p50 (WE)    p10/50/90 = {a[0]:6.1f} /{a[1]:6.1f} /{a[2]:6.1f}")
            a = agg(rows, "step128")
            print(f"  水深是128倍数%   p10/50/90 = {a[0]:6.1f} /{a[1]:6.1f} /{a[2]:6.1f}")
            a = agg(rows, "drop", 1)
            print(f"  岸线落差 p50     p10/50/90 = {a[0]:6.1f} /{a[1]:6.1f} /{a[2]:6.1f}")
            a = agg(rows, "drop", 2)
            print(f"  岸线落差 p90     p10/50/90 = {a[0]:6.1f} /{a[1]:6.1f} /{a[2]:6.1f}")
            a = agg(rows, "wall")
            print(f"  岸墙率(≥128)%    p10/50/90 = {a[0]:6.1f} /{a[1]:6.1f} /{a[2]:6.1f}")
            # 剖面均值曲线
            ph = np.nanmean(np.array([r["prof_h"] for r in rows], float), axis=0)
            ps = np.nanmean(np.array([r["prof_s"] for r in rows], float), axis=0)
            inn = np.nanmean(np.array([r["inland"] for r in rows], float))
            print("  岸带平均 h      : " + " ".join(f"{v:6.0f}" for v in ph))
            print("  岸带平均坡度    : " + " ".join(f"{v:6.0f}" for v in ps))
            print(f"  内陆(≥16格)坡度 : {inn:6.0f}"
                  f"    d1坡度/内陆 = {ps[0]/inn:.2f}   d3/内陆 = {ps[2]/inn:.2f}")
        print("=" * 108)
    finally:
        A.drop_tmp(tmp)


if __name__ == "__main__":
    main()
