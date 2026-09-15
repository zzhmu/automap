# -*- coding: utf-8 -*-
"""诊断 carve_ramps：复现「刻斜坡之前」的层场，逐对台地打印候选口子为何盖不上章。

用法: python diag_carve.py [--seed 4001] [--size 128] [--layers 4] [--water 0.30]
                          [--show 3] [--pair A B]
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_height as G  # noqa: E402


def build_layer(seed, size, levels, water, freq, octaves, relief, level_bias,
                smooth, max_jump, min_island, min_lake):
    rows = cols = size + 1
    nprng = np.random.default_rng(seed)
    height = G.fbm(nprng, (rows, cols), freq, octaves=octaves)
    order = np.argsort(height, axis=None)
    quant = np.empty(height.size, dtype=np.float32)
    quant[order] = np.linspace(0.0, 1.0, height.size, dtype=np.float32)
    quant = quant.reshape(height.shape)
    is_water = quant < water
    land_q = (quant - water) / (1.0 - water)
    lvl = np.clip(np.floor(np.power(land_q, level_bias) * levels), 0, levels - 1)
    code = np.where(is_water, 0, 1 + lvl.astype(np.int32))
    if smooth > 0:
        code = G.mode_filter(code, passes=smooth, values=levels + 2)
    if min_island > 0 or min_lake > 0:
        code, _, _ = G.clean_regions(code, min_island=min_island, min_lake=min_lake)
    is_water = code == 0
    layer = np.where(is_water, max(0, G.LAYER_ZERO - 1),
                     G.LAYER_ZERO + (code - 1)).astype(np.int16)
    layer = G.limit_neighbor_jump(layer, max_jump=max_jump)
    return layer, is_water


def main():
    opts = {}
    for i, a in enumerate(sys.argv):
        if a.startswith("--") and i + 1 < len(sys.argv):
            opts[a[2:]] = sys.argv[i + 1]
    seed = int(opts.get("seed", 4001))
    size = int(opts.get("size", 128))
    levels = int(opts.get("layers", 4))
    water = float(opts.get("water", 0.30))
    show = int(opts.get("show", 3))
    want = opts.get("pair")
    run = int(opts.get("ramp-run", 4))

    layer, is_water = build_layer(
        seed, size, levels, water, freq=1.6, octaves=2, relief=0.35,
        level_bias=2.0, smooth=2, max_jump=2, min_island=32, min_lake=16)

    spread, grad, line, dry = G._tile_derivatives(layer, is_water)
    H, W = spread.shape
    passable = dry & (spread <= 2)
    flat = (spread == 0) & dry
    lab, nlab = G._components(flat)
    print(f"台地 {nlab} 块")
    wmap = np.where(flat, 1, 6).astype(np.int32)
    b = 2
    wmap[:b, :] += 8; wmap[-b:, :] += 8; wmap[:, :b] += 8; wmap[:, -b:] += 8
    dist, owner, prev = G._multi_dijkstra(lab, passable, wmap)

    cand = {}
    for r in range(H):
        for c in range(W):
            o = int(owner[r, c])
            if o < 0:
                continue
            for nr, nc in ((r + 1, c), (r, c + 1)):
                if nr >= H or nc >= W:
                    continue
                o2 = int(owner[nr, nc])
                if o2 < 0 or o2 == o:
                    continue
                w = int(dist[r, c]) + int(dist[nr, nc])
                cand.setdefault((min(o, o2), max(o, o2)), []).append(
                    (w, r * W + c, nr * W + nc))
    plevel = G._plateau_levels(lab, nlab, layer)
    for k, v in sorted(cand.items()):
        v.sort()
    print(f"候选崖边 {len(cand)} 对\n")

    # 台地邻接图的连通分量：9 块台地只有 7 条边是不够连通的（至少需要 8 条）
    par = list(range(nlab))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for (a, bb) in cand:
        par[find(a)] = find(bb)
    roots = {}
    for k in range(nlab):
        roots.setdefault(find(k), []).append(k)
    print("台地邻接图连通分量:")
    for rt, mem in roots.items():
        print(f"  分量 {rt}: 台地 {mem}  层位 {[int(plevel[m]) for m in mem]}")
    if len(roots) > 1:
        print(f"  → 台地邻接图本身不连通（{len(roots)} 段），"
              f"缺 {len(roots) - 1} 条边，光靠候选口子补不上\n")
    else:
        print()

    # ---- 陆地岛 / 可走块分析（与 connectivity_report 同口径）----
    dry_mask = dry
    ilab, n_island = G._components(dry_mask)
    print(f"陆地岛(dry 连通块) {n_island} 块")
    for i in range(n_island):
        m = ilab == i
        plats = sorted(set(int(lab[r, c]) for r, c in zip(*np.nonzero(m)) if lab[r, c] >= 0))
        print(f"  岛 {i}: 面积 {int(m.sum())}  台地 {plats} "
              f"层位 {[int(plevel[p]) for p in plats]}")

    sim = "--sim" in sys.argv
    if sim:
        cap = int(opts.get("cap", 0)) or None
        print(f"\n=== 模拟 carve_ramps 主循环（就地改 layer，每对口子上限 {cap}）===")
        lc = layer.copy()
        rp = np.zeros(layer.shape, dtype=bool)
        zf = np.zeros(layer.shape, dtype=bool)
        par2 = list(range(nlab))

        def f2(x):
            while par2[x] != x:
                par2[x] = par2[par2[x]]
                x = par2[x]
            return x

        carved = 0
        for key, lst in sorted(cand.items(), key=lambda kv: kv[1][0][0]):
            lst = lst[:cap] if cap else lst
            if f2(key[0]) == f2(key[1]):
                print(f"  - 台地对 {key}: 已连通，跳过")
                continue
            lv1, lv2 = int(plevel[key[0]]), int(plevel[key[1]])
            if abs(lv1 - lv2) != 1:
                print(f"  ! 台地对 {key}: 层差 {abs(lv1 - lv2)} ≠ 1，跳过")
                continue
            got = None
            best_tr = None
            for _, u, v in lst:
                r, c = divmod(u, W); r2, c2 = divmod(v, W)
                tr = []
                if G._stamp_ramp(lc, is_water, rp, zf, (r, c), (r2, c2), lv1, lv2, run, 2,
                                 trace=tr):
                    got = ((r, c), (r2, c2))
                    break
                if best_tr is None:
                    best_tr = tr
            if got is None:
                print(f"  ✘ 台地对 {key} 层位 {lv1}->{lv2}: {len(lst)} 个口子全失败"
                      f"  原因示例: {best_tr[0] if best_tr else '-'}")
            else:
                par2[f2(key[0])] = f2(key[1])
                carved += 1
                print(f"  ✔ 台地对 {key} 层位 {lv1}->{lv2}: 盖在 {got}  (第 {carved} 条)")
        print(f"  共刻 {carved} 条；台地并成 {len(set(f2(k) for k in range(nlab)))} 组")

        # 盖章后再看可走块
        spread2, _, _, dry2 = G._tile_derivatives(lc, is_water)
        flat2 = (spread2 == 0) & dry2
        all4 = rp[:-1, :-1] & rp[:-1, 1:] & rp[1:, :-1] & rp[1:, 1:]
        walk2 = flat2 | all4
        wlab, n_walk = G._components(walk2)
        print(f"  盖章后可走块 {n_walk}")
        for i in range(n_island):
            L = np.unique(wlab[(ilab == i) & walk2])
            L = L[L >= 0]
            if L.size > 1:
                print(f"  ✘ 岛 {i} 内部可走块 {list(L)} → 仍被切断")
            else:
                print(f"  ✔ 岛 {i} 内部可走块 {list(L)}")

    pair_list = sorted(cand.items(), key=lambda kv: kv[1][0][0])
    for key, lst in pair_list:
        if want and f"{key[0]},{key[1]}" != want:
            continue
        lv1, lv2 = int(plevel[key[0]]), int(plevel[key[1]])
        ok = 0
        first_trace = None
        first_mouth = None
        for _, u, v in lst:
            r, c = divmod(u, W); r2, c2 = divmod(v, W)
            tr = []
            lc = layer.copy()
            rp = np.zeros(layer.shape, dtype=bool)
            zf = np.zeros(layer.shape, dtype=bool)
            if G._stamp_ramp(lc, is_water, rp, zf, (r, c), (r2, c2), lv1, lv2, run, 2,
                             trace=tr):
                ok += 1
            elif first_trace is None:
                first_trace = tr
                first_mouth = ((r, c), (r2, c2))
        flag = "✔" if ok else "✘"
        print(f"{flag} 台地对 {key} 层位 {lv1}->{lv2}  候选 {len(lst)} 个，可盖章 {ok} 个")
        if not ok and first_trace:
            (r, c), (r2, c2) = first_mouth
            print(f"    首个口子 瓦片U({r},{c}) 瓦片V({r2},{c2})  失败原因: {first_trace[0]}")
            if show > 0:
                dump(layer, is_water, (r, c), (r2, c2), lv1, lv2)
                show -= 1
    return 0


def dump(layer, is_water, u, v, lv1, lv2):
    """打印口子周围的角点层位小地图（W=水）。"""
    r, c = u
    r2, c2 = v
    dc = c2 - c
    if dc:
        far_u = c if dc > 0 else c + 1
        shared = c + 1 if dc > 0 else c
        far_v = c + 2 if dc > 0 else c - 1
        axis = 0
        base = r
    else:
        dr = r2 - r
        far_u = r if dr > 0 else r + 1
        shared = r + 1 if dr > 0 else r
        far_v = r + 2 if dr > 0 else r - 1
        axis = 1
        base = c
    print(f"    U 层位={lv1} V 层位={lv2}  far_u={far_u} shared={shared} far_v={far_v} "
          f"axis={'列' if axis == 0 else '行'}")
    R, C = layer.shape
    a0, a1 = max(0, base - 7), min((R if axis == 0 else C), base + 8)
    p0, p1 = max(0, min(far_u, far_v) - 4), min((C if axis == 0 else R),
                                                max(far_u, far_v) + 5)
    for a in range(a0, a1):
        line = []
        for p in range(p0, p1):
            rr, cc = (a, p) if axis == 0 else (p, a)
            if not (0 <= rr < R and 0 <= cc < C):
                line.append("  ")
                continue
            ch = "W" if is_water[rr, cc] else str(int(layer[rr, cc]))
            mark = ""
            if p == far_u:
                mark = "<"
            elif p == shared:
                mark = "="
            elif p == far_v:
                mark = ">"
            line.append(ch + mark)
        tag = " <<< 口子行" if a == base else ""
        print(f"      a={a:3d} " + " ".join(line) + tag)


if __name__ == "__main__":
    sys.exit(main())
