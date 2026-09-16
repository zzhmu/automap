# -*- coding: utf-8 -*-
"""水下坡度剖面：水从岸边往湖心是怎么变深的？

水面平面 = 该图 waterHeight 字段的众数（实测每张官方图 99.7% 角点是同一个值）。
水深 depth = (plane - world) / 4   （WE，>0 = 水下）
离岸距离 k = 到最近**陆地**角点的 4 邻接距离（k=1 = 紧贴岸的那排水面）。

输出：k=1..10 的深度剖面 + 深度分位 + 「浅水带宽度」（depth < 128 的水角点占比）。
"""
import os
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402
import shore_stats as S  # noqa: E402

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")


def load2(path, tmp):
    import subprocess
    subprocess.run([A.default_exe(), "extract", path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=240)
    data = open(os.path.join(tmp, "war3map.w3e"), "rb").read()
    _ts, w, h, hs = A.read_w3e_header(data)
    R, C = h + 1, w + 1
    a = np.frombuffer(data, np.uint8, count=R * C * 7, offset=hs).reshape(-1, 7)
    gh = a[:, 0].astype(np.uint16) | (a[:, 1].astype(np.uint16) << 8)
    wh = (a[:, 2].astype(np.uint16) | (a[:, 3].astype(np.uint16) << 8)) & 0x3FFF
    fb = a[:, 4]
    layer = a[:, 6] & 0x0F
    world = (gh.astype(np.float32) - 8192 + (layer.astype(np.float32) - 2) * 512) / 4.0
    plane = Counter(wh.tolist()).most_common(1)[0][0]
    water = ((fb & 0x40) != 0).reshape(R, C)
    outside = (((a[:, 2].astype(np.uint16) | (a[:, 3].astype(np.uint16) << 8)) & 0x4000)
               != 0) | ((fb & 0x80) != 0)
    outside = outside.reshape(R, C)
    depth = ((plane - 8192) / 4.0 - world).reshape(R, C)
    return depth, water & ~outside, outside, plane


def prof(path, tmp, tag):
    depth, water, outside, plane = load2(path, tmp)
    if water.sum() < 50:
        return None
    land = ~water & ~outside
    if land.sum() < 50:
        return None
    k = S.dist_to(land, cap=16)
    rows = []
    for d in range(1, 11):
        sel = water & (k == d)
        rows.append(float(np.median(depth[sel])) if sel.any() else float("nan"))
    dw = depth[water]
    return dict(name=os.path.basename(path), tag=tag, n=int(water.sum()),
                plane=plane, prof=rows,
                d1=[float(np.percentile(depth[water & (k == 1)], x))
                    for x in (10, 50, 90)] if (water & (k == 1)).any() else [np.nan]*3,
                deep=[float(np.percentile(dw, x)) for x in (10, 50, 90)],
                shallow128=float((dw < 124).mean() * 100),
                shallow32=float((dw < 32).mean() * 100),
                deep200=float((dw >= 200).mean() * 100))


def show(r):
    if r is None:
        return
    print(f"  {r['name'][:26]:<26} 水{r['n']:>6}  平面raw={r['plane']:<6} "
          f"水深p10/50/90={r['deep'][0]:6.0f}/{r['deep'][1]:6.0f}/{r['deep'][2]:6.0f}  "
          f"<128的占{r['shallow128']:5.1f}%  <32的{r['shallow32']:5.1f}%")
    print(f"     第一排水深 p10/50/90 = {r['d1'][0]:6.0f}/{r['d1'][1]:6.0f}/{r['d1'][2]:6.0f}")
    print("     离岸 k=1..10 水深中位: " + " ".join(f"{v:6.0f}" for v in r["prof"]))


def main():
    args = sys.argv[1:]
    ours = []
    if "--ours" in args:
        i = args.index("--ours")
        ours = args[i + 1:]
        args = args[:i]
    tmp = A.make_tmp("shoredepth")
    off, our = [], []
    try:
        if args:
            maps = args
        else:
            maps = [os.path.join(MAPS, f) for f in sorted(os.listdir(MAPS))
                    if f.lower().endswith(".w3m")]
            print(f"=== 官方 {len(maps)} 张 ===\n")
        for p in maps:
            q = p if os.path.isabs(p) else os.path.join(ROOT, p)
            if not os.path.exists(q):
                q = os.path.join(MAPS, p)
            r = prof(q, tmp, "official")
            if r:
                off.append(r)
                show(r)
        if not ours:
            od = os.path.join(ROOT, "out")
            ours = [os.path.join(od, f) for f in ("acc_auto.w3x", "gui_cliffs.w3x",
                                                  "gui_shallow.w3x")
                    if os.path.exists(os.path.join(od, f))]
        if ours:
            print("\n=== 本项目产物 ===\n")
            for p in ours:
                q = p if os.path.isabs(p) else os.path.join(ROOT, p)
                r = prof(q, tmp, "ours")
                if r:
                    our.append(r)
                    show(r)
        print("\n" + "=" * 100)
        for lab, rs in (("官方", off), ("我们", our)):
            if not rs:
                continue
            P = np.array([r["prof"] for r in rs], float)
            with np.errstate(all="ignore"):
                m = np.nanmedian(P, axis=0)
            print(f"【{lab}】n={len(rs)}  离岸 k=1..10 水深中位: "
                  + " ".join(f"{v:5.0f}" for v in m))
            for key, fmt in (("deep", "水深 p50"), ("shallow128", "<128 占比%")):
                v = np.array([r[key][1] if key == "deep" else r[key] for r in rs], float)
                v = v[~np.isnan(v)]
                print(f"   {fmt:<12} p10/50/90 = "
                      + "/".join(f"{x:6.1f}" for x in np.percentile(v, [10, 50, 90])))
        print("=" * 100)
    finally:
        A.drop_tmp(tmp)


if __name__ == "__main__":
    main()
