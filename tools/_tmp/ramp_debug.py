# -*- coding: utf-8 -*-
"""复现压力测试里「✘ 有非法瓦片」的那 2 个用例，并 dump 非法瓦片的四角层号。

用法:
    python tools/_tmp/ramp_debug.py land 70259
    python tools/_tmp/ramp_debug.py auto 70259
"""
import importlib.util
import os
import shutil
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "tools")
GH = os.path.join(TOOLS, "gen_height.py")

spec = importlib.util.spec_from_file_location("gh", GH)
gh = importlib.util.module_from_spec(spec)
sys.modules["gh"] = gh
spec.loader.exec_module(gh)

np = gh.np

DETAIL = {}


def patched_ramp_report(layer, ramp):
    """原逻辑复制一遍，把非法瓦片的位置与四角层号记下来。"""
    H, W = ramp.shape
    seen = np.zeros_like(ramp, dtype=bool)
    blocks = []
    for r0 in range(H):
        for c0 in range(W):
            if not ramp[r0, c0] or seen[r0, c0]:
                continue
            stack = [(r0, c0)]
            seen[r0, c0] = True
            n = 0
            rmin = rmax = r0
            cmin = cmax = c0
            while stack:
                r, c = stack.pop()
                n += 1
                rmin, rmax = min(rmin, r), max(rmax, r)
                cmin, cmax = min(cmin, c), max(cmax, c)
                for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= nr < H and 0 <= nc < W and ramp[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        stack.append((nr, nc))
            blocks.append((n, rmax - rmin + 1, cmax - cmin + 1))
    thick = Counter(min(bw, bh) for _, bw, bh in blocks)
    step = flat_low = flat_high = other = 0
    bad_tiles = []
    for r in range(H - 1):
        for c in range(W - 1):
            q = (layer[r, c], layer[r, c + 1], layer[r + 1, c], layer[r + 1, c + 1])
            if not (ramp[r, c] and ramp[r, c + 1] and ramp[r + 1, c] and ramp[r + 1, c + 1]):
                continue
            u = sorted(set(q))
            if len(u) == 1:
                flat_low += 1
            elif len(u) == 2 and u[1] - u[0] == 1 and q.count(u[0]) == 2:
                step += 1
            elif len(u) == 2 and u[1] - u[0] == 1:
                flat_high += 1
            else:
                other += 1
                bad_tiles.append((r, c, q, u))
    DETAIL["bad"] = bad_tiles
    DETAIL["ramp"] = ramp.copy()
    DETAIL["layer"] = layer.copy()
    return [
        f"斜坡几何自检: {len(blocks)} 块  {'✔ 没有非法瓦片' if other == 0 else '✘ 有非法瓦片'}",
        f"  垂直崖壁厚度分布(角点线数): {dict(sorted(thick.items()))}",
        f"  瓦片构成: 台阶(2低2高) {step} / 四角全低基地 {flat_low}"
        f" / 四角全高 {flat_high} / 其他(非法) {other}",
    ]


gh.ramp_report = patched_ramp_report

# ---- 连通性：把「被切断的岛」里的孤块位置与四角层位 dump 出来 ----
_orig_conn = gh.connectivity_report


def patched_connectivity_report(layer, is_water, ramp):
    out = _orig_conn(layer, is_water, ramp)
    if out[2]:                      # 有岛被切断
        spread, grad, line, dry = gh._tile_derivatives(layer, is_water)
        flat = (spread == 0) & dry
        all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
        walk = flat | all4
        ilab, n_island = gh._components(dry)
        wlab, n_walk = gh._components(walk)
        print(f"[conn] 陆地岛 {n_island} / 可走块 {n_walk} —— 逐岛 dump 被切断的")
        for i in range(n_island):
            labs = np.unique(wlab[(ilab == i) & walk])
            labs = labs[labs >= 0]
            if labs.size <= 1:
                continue
            sizes = sorted(((int(np.count_nonzero(wlab == L)), int(L)) for L in labs),
                           reverse=True)
            print(f"  岛{i}: 含 {labs.size} 个可走块，大小 {[s for s, _ in sizes]}")
            for _, L in sizes:
                m = (wlab == L) & walk
                ys, xs = np.nonzero(m)
                print(f"    块大小 {int(m.sum())}  范围 r{ys.min()}..{ys.max()} "
                      f"c{xs.min()}..{xs.max()}")
                if m.sum() <= 120:
                    r0, r1 = max(0, ys.min() - 2), min(m.shape[0], ys.max() + 3)
                    c0, c1 = max(0, xs.min() - 2), min(m.shape[1], xs.max() + 3)
                    print(f"    ── 四角层位(左上/右上/左下/右下) ·=本块 *=斜坡瓦片"
                          f" w=带水(不可用)")
                    for rr in range(r0, r1):
                        row = []
                        for cc2 in range(c0, c1):
                            q = (int(layer[rr, cc2]), int(layer[rr, cc2 + 1]),
                                 int(layer[rr + 1, cc2]), int(layer[rr + 1, cc2 + 1]))
                            wet = (is_water[rr, cc2] or is_water[rr, cc2 + 1]
                                   or is_water[rr + 1, cc2] or is_water[rr + 1, cc2 + 1])
                            pre = "*" if all4[rr, cc2] else ("·" if m[rr, cc2] else
                                                            ("w" if wet else " "))
                            row.append(pre + "".join(str(v) for v in q))
                        print(f"      {rr:3d} " + " ".join(row))
    return out


gh.connectivity_report = patched_connectivity_report

# ---- 追踪是谁刻出了那条非法斜坡 ----
STAGE = {}


def snapshot(tag, layer, ramp):
    """把当前 ramp 数组存档（只看合法性：是否存在 ΔL>1 的斜坡瓦片）。"""
    H, W = ramp.shape
    bad = []
    for r in range(H - 1):
        for c in range(W - 1):
            if not (ramp[r, c] and ramp[r, c + 1] and ramp[r + 1, c] and ramp[r + 1, c + 1]):
                continue
            q = (layer[r, c], layer[r, c + 1], layer[r + 1, c], layer[r + 1, c + 1])
            if max(q) - min(q) > 1:
                bad.append((r, c, tuple(int(v) for v in q)))
    # 顺便统计：全图有多少「多级崖壁」瓦片（spread>=2 且非水）
    multi = 0
    for r in range(H - 1):
        for c in range(W - 1):
            q = (layer[r, c], layer[r, c + 1], layer[r + 1, c], layer[r + 1, c + 1])
            if max(q) - min(q) >= 2:
                multi += 1
    STAGE[tag] = bad
    print(f"[STAGE {tag}] 非法斜坡瓦片 {len(bad)} 个 / 全图多级崖壁瓦片 {multi} 个" +
          (f"  例: {bad[:6]}" if bad else ""))


_orig_carve = gh.carve_ramps
_orig_drill = gh.drill_ramps_for_connectivity
_orig_drop = gh.drop_unreachable_terraces


def carve_wrap(layer, is_water, *a, **kw):
    snapshot("carve_post", layer, np.zeros_like(layer, dtype=bool))
    out = _orig_carve(layer, is_water, *a, **kw)
    snapshot("carve_post", out[1], out[0])
    return out


def drill_wrap(*a, **kw):
    snapshot("drill_pre", a[0], a[2])
    out = _orig_drill(*a, **kw)
    snapshot("drill_post", a[0], a[2])
    return out


def drop_wrap(*a, **kw):
    snapshot("drop_pre", a[0], a[2])
    out = _orig_drop(*a, **kw)
    snapshot("drop_post", a[0], a[2])
    return out


gh.carve_ramps = carve_wrap

_PROBE = [0]
_orig_stamp = gh._stamp_ramp


def stamp_wrap(*a, **kw):
    _PROBE[0] += 1
    if _PROBE[0] <= 4:
        print(f"[probe#{_PROBE[0]}] ramp={type(a[2]).__name__} "
              f"shape={getattr(a[2], 'shape', None)} layer.shape={a[0].shape} "
              f"nargs={len(a)} kw={sorted(kw)} u={a[4]} v={a[5]} "
              f"lv=({a[6]},{a[7]}) run={a[8]}")
    return _orig_stamp(*a, **kw)


gh._stamp_ramp = stamp_wrap
gh.drill_ramps_for_connectivity = drill_wrap
gh.drop_unreachable_terraces = drop_wrap

# ---- 记录每一次 _commit 的落点，看是不是两次刻斜坡叠在一起 ----
COMMITS = []
_orig_commit = gh._commit


def commit_wrap(layer, ramp, ramp_band, want, band, cell, a0, a1, mark=None):
    out = _orig_commit(layer, ramp, ramp_band, want, band, cell, a0, a1, mark)
    if out:
        COMMITS.append({
            "want": tuple((p, t) for p, t in want),
            "band": tuple(band),
            "cells": (tuple(cell(a, p) for a in range(a0, a1 + 1)
                            for p in (want[0][0], want[-1][0]))),
            "a0": a0, "a1": a1,
        })
    return out


gh._commit = commit_wrap

# _stamp_ramp 内部用全局名 _commit，所以打点生效

mode = sys.argv[1]
seed = sys.argv[2]
tpl = os.path.join(ROOT, "template", "128-128.w3m")
out = os.path.join(ROOT, "out", f"repro_{mode}_{seed}.w3x")
shutil.copyfile(tpl, out)

opts = [
    "--seed", seed, "--exe", os.path.join(ROOT, "bin", "MPQEditor.exe"),
    "--water", "0.30", "--mountain", "fbm", "--uplift", "220", "--ridge", "0.6",
    "--warp", "8", "--max-relief", "512", "--shelf-depth", "128",
    "--cliffs", "1", "--cliff-area", "0.15", "--cliff-size", "26",
    "--cliff-layers", "3", "--cliff-feather", "4",
    "--layer-min", "2", "--layer-max", "5",
    "--raise", "75", "--lower", "75", "--rough", "12", "--blob", "28",
    "--grain", "2.5", "--ledge", "0", "--flat", "0.15", "--flat-size", "20",
    "--water-relief", "0.5", "--height-step", "4", "--freq", "1.6",
    "--boundary", "ring", "--ramps", "auto", "--ramp-force", "1",
    "--trees", "0", "--density", "0.35",
]
if mode != "auto":
    opts += ["--base", mode]

sys.argv = ["gen_height.py", out] + opts
rc = gh.main()
print("REPRO rc =", rc)

bad = DETAIL.get("bad") or []
print(f"非法瓦片数: {len(bad)}")
layer = DETAIL.get("layer")
ramp = DETAIL.get("ramp")
for (r, c, q, u) in bad[:40]:
    # 该瓦片四角的完好程度 / 邻域层号
    print(f"  tile(r={r},c={c}) quad={q} uniq={u} spread={max(q)-min(q)}")
    if layer is not None:
        r0, r1 = max(0, r - 2), min(layer.shape[0], r + 4)
        c0, c1 = max(0, c - 2), min(layer.shape[1], c + 4)
        for rr in range(r0, r1):
            row = " ".join(f"{int(layer[rr, cc]):2d}" for cc in range(c0, c1))
            print(f"      L{rr:4d}: {row}")

# 统计：这些非法瓦片的层差分布
print("层差分布:", Counter(max(q) - min(q) for _, _, q, _ in bad))
print("唯一层数分布:", Counter(len(u) for _, _, _, u in bad))

# 找出覆盖非法瓦片四角的 _commit 落点
bad_corners = set()
for (r, c, q, u) in bad:
    bad_corners |= {(r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)}
print(f"非法瓦片四角(图像坐标 r,c): {sorted(bad_corners)}")
print(f"_commit 总次数: {len(COMMITS)}")
for i, cm in enumerate(COMMITS):
    hit = bad_corners & set(cm["cells"])
    tag = "  <<< 命中" if hit else ""
    print(f"  #{i:2d} a={cm['a0']}..{cm['a1']} want={cm['want']} band={cm['band']}"
          f" 端点线={cm['cells']}{tag}")
    if hit:
        print(f"        命中角点: {sorted(hit)}")
