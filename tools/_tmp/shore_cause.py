# -*- coding: utf-8 -*-
"""岸线成因探针：官方岸线到底是「同层陡坡」还是「层差崖壁」？我们呢？

对每一条 4 邻接 (陆, 水) 边界，拆解落差 h_陆 - h_水 的来源：
    Δlayer  —— 层差贡献 128×Δlayer WE
    Δgh     —— 同层内的 groundHeight 落差贡献 /4 WE
    h_陆 - h_水 = (Δgh/4) + 128×Δlayer   （水面 raw = wh，两边共用）

再顺便量：
  · 岸线落差里「层差部分」占比
  · 陆侧第一排的 gh 分位（岸边地面是不是贴着水面）
"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402
import shore_stats as S  # noqa: E402

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")


def pairs_of(path, tmp):
    got = S.load(path, tmp)
    if got is None:
        return None
    h = got["h"]
    water = got["water"] & ~got["outside"]
    land = ~got["water"] & ~got["outside"]
    if water.sum() < 20:
        return None
    return h, water, land, got["layer"], got


def analyze(path, tmp):
    r = pairs_of(path, tmp)
    if r is None:
        return None
    h, water, land, layer, got = r
    dlayer, dgh, dh = [], [], []
    first_land = np.zeros_like(land)
    for m, si, sj in S.boundary_pairs(land, water):
        if m.any():
            dlayer.append(layer[si][m].astype(np.int32) - layer[sj][m].astype(np.int32))
            dgh.append(h[sj][m] - h[si][m])
            dh.append(h[si][m] - h[sj][m])
            first_land[si] |= m
    dlayer = np.concatenate(dlayer)
    dh = np.concatenate(dh)
    dgh = np.concatenate(dgh)
    tot = np.abs(dh).sum()
    lay_part = np.abs(dlayer * 128.0).sum()
    return dict(name=os.path.basename(path), n=len(dh),
                dh50=float(np.percentile(dh, 50)),
                dlayer_absmean=float(np.abs(dlayer).mean()),
                layer_pct=float(lay_part / max(1e-6, tot) * 100),
                same_layer_pct=float((dlayer == 0).mean() * 100),
                dlayer_hi_pct=float((dlayer > 0).mean() * 100),
                dlayer_lo_pct=float((dlayer < 0).mean() * 100),
                water_layer=str(sorted(set(np.unique(layer[water]).tolist()))[:8]),
                tpl_layer_span=(int(layer[~got["outside"]].min()),
                                int(layer[~got["outside"]].max())))


def main():
    maps = sys.argv[1:]
    if not maps:
        maps = [os.path.join(MAPS, f) for f in
                ("(4)LostTemple.w3m", "(6)DarkForest.w3m", "(9)Riverrun.w3m",
                 "(2)Harrow.w3m", "(4)Duskwood.w3m", "(8)BloodvenomFalls.w3m")]
    tmp = A.make_tmp("shorecause")
    try:
        print(f"{'地图':<28}{'岸线对数':>8}{'落差p50':>9}{'|Δlayer|均':>11}"
              f"{'同层%':>8}{'陆高层%':>9}{'陆低层%':>9}{'层差贡献%':>10}  层范围")
        rows = []
        for p in maps:
            p = p.replace("/", os.sep)
            if not os.path.isabs(p):
                p = os.path.join(ROOT, p)
            r = analyze(p, tmp)
            if r is None:
                print(f"  {os.path.basename(p)[:26]:<26} 无水/读不到")
                continue
            rows.append(r)
            print(f"{r['name'][:26]:<28}{r['n']:>8}{r['dh50']:>9.0f}"
                  f"{r['dlayer_absmean']:>11.3f}{r['same_layer_pct']:>8.1f}"
                  f"{r['dlayer_hi_pct']:>9.1f}{r['dlayer_lo_pct']:>9.1f}"
                  f"{r['layer_pct']:>10.1f}  {r['tpl_layer_span']}")
        if rows:
            print("\n汇总（均值）：")
            for k, lab in (("dh50", "岸线落差 p50"), ("dlayer_absmean", "|Δlayer| 均值"),
                           ("same_layer_pct", "水陆同层占比%"),
                           ("dlayer_hi_pct", "陆比水高一层%"),
                           ("layer_pct", "层差贡献%")):
                v = np.array([r[k] for r in rows], float)
                print(f"  {lab:<18} p10={np.percentile(v,10):7.2f}  "
                      f"中位={np.percentile(v,50):7.2f}  p90={np.percentile(v,90):7.2f}")
    finally:
        A.drop_tmp(tmp)


main()
