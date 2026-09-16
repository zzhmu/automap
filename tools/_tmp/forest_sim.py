# -*- coding: utf-8 -*-
"""纯网格仿真撒树算法（不碰 MPQ），用来把参数调到官方 p50 目标。

目标（43 张 1.27a 原生对战图实测）：
  密度 p50 12%（p10 8.4% / p90 19%）
  块数/树数 p50 0.092
  最大块 p50 205 格
  ≥100 格大林块数 p50 4
  树落 ≥100 大林比例 p50 33%
  孤立单株占块数 p50 49%

用法: python tools/_tmp/forest_sim.py [--density 0.15 --forest-share 0.35 ...]
输出每张图一行指标 + 多图汇总 + 预览 PNG。
"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402


def blobs_full(mask):
    """（已并入 add_doodads.forest_metrics，保留此名仅为兼容旧调用）"""
    return A.forest_metrics(mask)


def make_elig(W, H, seed, water_frac=0.0):
    """造一块可用格：默认全陆地；water_frac>0 时挖一块水（模拟水域占位）。"""
    el = np.zeros((W, H), dtype=bool)
    el[1:W - 1, 1:H - 1] = True
    if water_frac > 0:
        rng = np.random.default_rng(seed + 5)
        wr = A.norm01(A.fbm(rng, (W, H), 2.0, octaves=3))
        el &= wr > water_frac
    return el


def run(seed, opts, W=128, H=128, water_frac=0.0):
    density = opts["density"]
    forest_share = opts["forest_share"]
    forest_size = opts["forest_size"]
    clump_size = opts["clump_size"]
    clump_radius = opts["clump_radius"]
    gap = opts["clump_gap"]
    scatter = opts["scatter"]
    clump_bias = opts["clump_bias"]
    freq = opts["freq"]

    nprng = np.random.default_rng(seed)
    elig = make_elig(W, H, seed, water_frac)
    avail = int(elig.sum())
    rng2 = np.random.default_rng(seed + 991)
    field = A.build_forest_field(rng2, elig, freq, opts["edge_forest"], opts["edge_band"])
    fine = A.build_fine_field(rng2, (W, H), freq)
    n_total = int(round(avail * density))
    n_f = int(round(n_total * forest_share))
    n_s = int(round(n_total * scatter))
    n_c = max(0, n_total - n_f - n_s)

    taken = np.zeros((W, H), dtype=bool)
    n_forest, pf = A.place_forests(nprng, elig, taken, n_f, forest_size, field, fine=fine)
    n_clumps, pc = A.place_groves(nprng, elig, taken, n_c, clump_size, clump_radius,
                                  gap, field=field, clump_bias=clump_bias)
    ps = A.place_scatter(nprng, elig, taken, n_s, field=field,
                         size=opts.get("scatter_size", 1.5))
    short = n_total - (pf + pc + ps)
    pg = A.grow_along_edge(nprng, elig, taken, short, field=field, fine=fine) if short > 0 else 0

    fm = A.forest_metrics(taken)
    ntree = int(taken.sum())
    return dict(taken=taken, elig=elig, ntree=ntree, avail=avail, W=W, H=H,
                dens=ntree / float(W * H), n_blob=fm["n_blob"], max_sz=fm["max_sz"],
                lone=fm["lone"], n100=fm["n_big"], frac100=fm["frac_big"],
                ratio=fm["ratio"], iso8=fm["iso8"], iso2=fm["iso2"],
                dmed=fm["dmed"], dnear=fm["dnear"],
                n_forest=n_forest, n_clumps=n_clumps, pf=pf, pc=pc, ps=ps, pg=pg,
                target=n_total)


def main():
    opts = dict(density=0.18, forest_share=0.32, forest_size=170.0, clump_size=11.0,
                clump_radius=3.0, clump_gap=1.5, scatter=0.035, scatter_size=1.5,
                clump_bias=0.55, freq=2.2, edge_forest=0.55, edge_band=14.0)
    water = 0.0
    for a in sys.argv[1:]:
        k, _, v = a.lstrip("-").partition("=")
        k = k.replace("-", "_")
        if k in opts:
            opts[k] = float(v)
        elif k == "water":
            water = float(v)
    print("参数:", {k: round(v, 3) for k, v in opts.items()}, "water:", water)

    seeds = [11, 22, 33, 44, 55, 66]
    rows = []
    for s in seeds:
        r = run(s, opts, water_frac=water)
        rows.append(r)
        print(f"  seed {s:>3}: 密度{r['dens']*100:>4.1f}% 树{r['ntree']:>5} "
              f"块{r['n_blob']:>4} 最大{r['max_sz']:>4} ≥100:{r['n100']:>2} "
              f"大林占比{r['frac100']*100:>4.0f}% 单株{r['lone']*100:>3.0f}% "
              f"块/树{r['ratio']:.3f} | iso8{r['iso8']*100:>5.2f}% iso2{r['iso2']*100:>5.2f}% "
              f"d{r['dmed']:>4.0f} d≤3 {r['dnear']*100:>4.0f}% | 大林{r['n_forest']}"
              f"丛{r['n_clumps']} 散{r['ps']} 补{r['pg']}")

    def agg(k):
        v = np.array([r[k] for r in rows], dtype=float)
        return np.percentile(v, 50), v.mean()

    print("\n            " + "  我们p50   我们mean   官方p50")
    for k, lab, tgt in [("dens", "密度", 0.120), ("n_blob", "连片块数", 256),
                        ("max_sz", "最大块", 205), ("n100", "≥100块数", 4),
                        ("frac100", "树落大林比例", 0.332), ("lone", "孤立单株占比", 0.488),
                        ("ratio", "块数/树数", 0.0924),
                        ("iso8", "★8邻域孤立", 0.017), ("iso2", "★2格内无树", 0.001),
                        ("dmed", "★到大林格距中位", 9.0), ("dnear", "★距大林≤3格", 0.365)]:
        p50, mean = agg(k)
        print(f"  {lab:<14} {p50:>9.3f} {mean:>10.3f} {tgt:>9.3f}")

    # 预览（第一张）
    r = rows[0]
    t = r["taken"]
    img = np.full((r["H"], r["W"], 3), (200, 190, 160), dtype=np.uint8)
    img[~r["elig"].T] = (60, 110, 200)
    img[t.T] = (20, 90, 20)
    out = os.path.join(HERE, "forest_sim.png")
    Image.fromarray(img[::-1]).resize((r["W"] * 4, r["H"] * 4), Image.NEAREST).save(out)
    print(f"\n预览: {out}")


main()
