# -*- coding: utf-8 -*-
"""在随机地形上摆放中立建筑 —— 重写 war3mapUnits.doo。

用法:
  python add_buildings.py <地图.w3x> [--ngol 12] [--ngme 2] ... [--seed 7]

每类建筑的「官方实测」基准 = 43 张 1.27a 原生对战图（.w3m）+ 113 张 TFT 官方图：
    id    名称          官方出现率        每图个数(中位/最大)  默认
    ngol  金矿          43/43 + 113/113   12 / 32             12
    ngme  地精商店      33/43 + 86/113    2 / 8               2
    ngad  地精实验室    14/43 + 49/113    0 / 12              1
    nmer  雇佣兵营地     9/43 + 16/113    0 / 4               1
    nfoh  生命之泉      12/43 + 36/113    0 / 6               1
    nmrk  市场           0/43 + 15/113    0 / 4               1
    ntav  酒馆           0/43 + 99/113    1 / 8               1

摆放规则（与撒树同一套地形口径）:
  - 建筑占地区域内所有角点都必须是「陆地 + 非地图边界外 + 层差 ≤ --flat-tol」
  - 距地图边缘 ≥ --edge 格，建筑之间 ≥ --min-dist 格
  - 默认避开树（读 war3map.doo 里的装饰物坐标）
  - 用「最远点采样」铺开，避免扎堆成一条直线
  - 模板残留的出生点 sloc 默认保留并重新落位/修正高度（--keep-sloc 0 可关闭）

单位的记录字段照抄官方图里同类建筑的众数（flags=2 owner=15 hp=-1 mana=-1
tacq=-1 heroLevel=1 customColor=-1 waygate=-1 scale=1），见 w3units.Unit 默认值。

🔴 朝向不是随机的：官方 43 张 1.27a 图 + 112 张 TFT 图里 **2900+ 座中立建筑的 angle
100% 都是 4.712389 rad（270°）**，一个例外都没有（金矿 1933 / 商店 325 / 酒馆 207 /
实验室 198 / 泉水 84 / 雇佣兵 67 / 市场 34 —— 全部 270°）。这是 WE 里放建筑时
默认的朝向，官方从不改它。所以默认写死 270°，只有显式给 --angle-jitter 才偏离。
"""
import math
import os
import shutil
import struct
import subprocess
import sys
from collections import Counter

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import w3units
from add_doodads import (force_utf8_stdout, make_tmp, drop_tmp, parse_opts,
                         read_w3e_header, parse_doo, default_exe)

force_utf8_stdout()

GROUND_ZERO = 8192
LAYER_ZERO = 2
LAYER_STEP = 512
TILE = 128.0

# (id, 中文名, 平地检查半径(格), 官方每图中位个数, 默认个数, 备注)
BUILDINGS = [
    ("ngol", "金矿",       3, 12, 12, "官方 43/43 图都有，每图中位 12 座"),
    ("ngme", "地精商店",   2,  2,  2, "33/43 图有，中位 2 个"),
    ("ngad", "地精实验室", 2,  0,  1, "14/43 图有，最多 4 个；TFT 图最多 12"),
    ("nmer", "雇佣兵营地", 2,  0,  1, "9/43 图有，最多 4 个"),
    ("nfoh", "生命之泉",   2,  0,  1, "12/43 图有，最多 4 个"),
    ("nmrk", "市场",       2,  0,  1, "TFT 官方图 15/113 有，1.27a 对战图不用"),
    ("ntav", "酒馆",       2,  1,  1, "TFT 官方图 99/113 有，中位 1 个"),
]
BY_ID = {b[0]: b for b in BUILDINGS}

#: 官方建筑朝向：4.712389 rad = 270°，实测 2900+ 座 100% 都是它（见文件头注释）
UNIT_ANGLE = 4.712389
# 预览图配色：都要和「水蓝 / 土黄 / 树绿」拉开，不然一眼看不出建筑在哪
COLORS = {"ngol": (255, 215, 0), "ngme": (255, 130, 0), "ngad": (170, 60, 230),
          "nmer": (220, 30, 30), "nfoh": (0, 230, 255), "nmrk": (255, 255, 255),
          "ntav": (255, 0, 255)}


def win_view(a, k):
    """滑窗视图 (rows-k+1, cols-k+1, k, k)。"""
    from numpy.lib.stride_tricks import sliding_window_view
    return sliding_window_view(a, (k, k))


def flat_ok(water, layer, boundary, W, H, radius, tol):
    """每个 tile 作为建筑中心时，±radius 覆盖的角点区是否合格。

    tile (i,j) 覆盖角点 [j, j+2r+1] × [i, i+2r+1]，窗口边长 k = 2r+2。
    """
    k = 2 * radius + 2
    ok = np.zeros((W, H), dtype=bool)
    if water.shape[0] < k or water.shape[1] < k:
        return ok
    # 窗口数组的索引是 [j, i]，ok 的索引是 [i, j] → 转置回来再裁到 (W, H)
    sw = win_view(water.astype(np.int32), k).sum(axis=(2, 3))
    sb = win_view(boundary.astype(np.int32), k).sum(axis=(2, 3))
    wl = win_view(layer.astype(np.int16), k)
    span = wl.max(axis=(2, 3)) - wl.min(axis=(2, 3))
    cond = (sw == 0) & (sb == 0) & (span <= tol)
    ok[:min(W, cond.shape[1]), :min(H, cond.shape[0])] = cond.T[
        :min(W, cond.shape[1]), :min(H, cond.shape[0])]
    return ok


def place_spots(nprng, ok, blocked, n, min_dist, W, H):
    """最远点采样：每次挑「离已放建筑最远」的合法点（前 5% 里随机）。

    ⚠️ 所有掩码一律形状 (W, H)、索引 [i, j]（与 add_doodads 的 picked 同口径）。
    ravel 后是 C 序 → 索引 = i*H + j，解回来必须 divmod(pick, H)，
    写成 (pick % W, pick // W) 会把 i/j 转置，方块图对、实际全错位。
    """
    spots = []
    dist = np.full((W, H), 1e9, dtype=np.float64)
    free = ok & ~blocked
    ii, jj = np.mgrid[0:W, 0:H]        # 轴 0 = i，轴 1 = j
    for k in range(n):
        cand = free if k == 0 else (free & (dist >= min_dist))
        idxs = np.flatnonzero(cand.ravel())
        if idxs.size == 0:
            break
        if k == 0:
            pick = int(nprng.choice(idxs))
        else:
            d = dist.ravel()[idxs]
            thr = np.quantile(d, 0.95)
            pick = int(nprng.choice(idxs[d >= thr]))
        i, j = divmod(pick, H)
        spots.append((i, j))
        dist = np.minimum(dist, np.hypot(ii - i, jj - j))
        free[i, j] = False
    return spots


def main():
    args, opts = parse_opts(sys.argv[1:])
    if not args:
        print(__doc__)
        return 1
    map_path = args[0]
    seed = int(opts.get("seed", 7))
    exe = opts.get("exe") or default_exe()
    preview = opts.get("preview")
    out_path = opts.get("out")
    flat_tol = max(0, int(opts.get("flat-tol", 1)))
    min_dist = float(opts.get("min-dist", 8))
    edge = max(1, int(opts.get("edge", 6)))
    gold = int(opts.get("gold", 12500))
    jitter = float(opts.get("angle-jitter", 0.0))      # 度；0 = 完全照官方（270°）
    avoid_trees = str(opts.get("avoid-trees", 1)) not in ("0", "false", "no")
    keep_sloc = str(opts.get("keep-sloc", 1)) not in ("0", "false", "no")
    keep_units = str(opts.get("keep-units", 0)) in ("1", "true", "yes")

    def as_int(v, dflt):
        if v is None or isinstance(v, bool):
            return dflt
        try:
            return max(0, int(float(v)))
        except ValueError:
            return dflt

    counts = {}
    for bid, _cn, _r, _med, dflt, _note in BUILDINGS:
        counts[bid] = as_int(opts.get(bid), dflt)
    # 表里没列出的建筑也允许直接 --nb-<id> N 指定，方便扩展
    for k, v in opts.items():
        if k.startswith("nb-") and k[3:] not in counts:
            counts[k[3:]] = as_int(v, 0)

    tmp = make_tmp("buildings")
    target = map_path
    if out_path:
        shutil.copy2(map_path, out_path)
        target = out_path

    for fn in ("war3map.w3e", "war3mapUnits.doo", "war3map.doo"):
        subprocess.run([exe, "extract", target, fn, tmp, "/fp"],
                       capture_output=True, timeout=180)
    w3e_p = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(w3e_p):
        print("提取 war3map.w3e 失败")
        return 1
    w3e = open(w3e_p, "rb").read()
    tileset, W, H, HS = read_w3e_header(w3e)
    cols, rows = W + 1, H + 1
    water = np.zeros((rows, cols), dtype=bool)
    boundary = np.zeros((rows, cols), dtype=bool)
    layer = np.zeros((rows, cols), dtype=np.int16)
    gheight = np.zeros((rows, cols), dtype=np.float32)
    for r in range(rows):
        for c in range(cols):
            off = HS + (r * cols + c) * 7
            gh, whf, fb, b5, b6 = struct.unpack_from("<HHBBB", w3e, off)
            water[r, c] = bool(fb & 0x40)
            boundary[r, c] = bool((fb & 0x80) or (whf & 0x4000))
            layer[r, c] = b6 & 0x0F
            gheight[r, c] = (gh - GROUND_ZERO + (layer[r, c] - LAYER_ZERO) * LAYER_STEP) / 4.0
    print(f"{os.path.basename(target)}: {W}x{H} tileset={tileset}")

    # 已有单位
    doo_u = os.path.join(tmp, "war3mapUnits.doo")
    if os.path.exists(doo_u):
        ver, sub, units, _ = w3units.parse(open(doo_u, "rb").read())
    else:
        ver, sub, units = 7, 9, []
    n_before = len(units)
    keep = []
    n_sloc = 0
    if keep_units:
        keep = list(units)
        n_sloc = sum(1 for u in units if u.id == "sloc")
    elif keep_sloc:
        for u in units:
            if u.id == "sloc":
                keep.append(u)
                n_sloc += 1
    print(f"原 units.doo {n_before} 条 → 保留 {len(keep)} 条"
          f"（出生点 {n_sloc}）")

    # 树（装饰物）占位
    blocked = np.zeros((W, H), dtype=bool)
    trees = np.zeros((W, H), dtype=bool)
    doo_d = os.path.join(tmp, "war3map.doo")
    if avoid_trees and os.path.exists(doo_d):
        blob = open(doo_d, "rb").read()
        _v, _s, recs, _t = parse_doo(blob)
        for rec in recs:
            if len(rec) < 42:
                continue
            x, y = struct.unpack_from("<2f", rec, 8)
            i = int((x + W * 64.0) / TILE)
            j = int((y + H * 64.0) / TILE)
            if 0 <= i < W and 0 <= j < H:
                trees[i, j] = True
        # 树本身 + 相邻 1 格都不放建筑
        blocked |= trees
        blocked[1:, :] |= trees[:-1, :]
        blocked[:-1, :] |= trees[1:, :]
        blocked[:, 1:] |= trees[:, :-1]
        blocked[:, :-1] |= trees[:, 1:]
        print(f"读 war3map.doo：{len(recs)} 个装饰物，{int(trees.sum())} 格有树（建筑避开）")

    # 出生点占位
    for u in keep:
        i = int((u.x + W * 64.0) / TILE)
        j = int((u.y + H * 64.0) / TILE)
        for di in range(-3, 4):
            for dj in range(-3, 4):
                ii, jj = i + di, j + dj
                if 0 <= ii < W and 0 <= jj < H:
                    blocked[ii, jj] = True

    nprng = np.random.default_rng(seed)
    # 雇佣兵营地按风格换模型变体（nmr0~9 是同一建筑在各 tileset 的版本，
    # L/F 官方就用普通 nmer，见 tools/tilesets.py）
    style = str(opts.get("style") or "").strip()
    merc_id = None
    if style:
        from tilesets import STYLES
        merc_id = STYLES.get(style, {}).get("merc")
    placed = []
    log = []
    for bid, cn, radius, med, dflt, _note in BUILDINGS:
        n = counts.get(bid, 0)
        if n <= 0:
            continue
        ok = flat_ok(water, layer, boundary, W, H, radius, flat_tol)
        ok[:edge, :] = False
        ok[W - edge:, :] = False
        ok[:, :edge] = False
        ok[:, H - edge:] = False
        spots = place_spots(nprng, ok, blocked, n, min_dist, W, H)
        for (i, j) in spots:
            uid = bid
            if bid == "nmer" and merc_id and merc_id != "nmer":
                uid = merc_id
            u = w3units.Unit(
                id=uid, x=(i + 0.5) * TILE - W * 64.0, y=(j + 0.5) * TILE - H * 64.0,
                z=0.0,
                angle=(UNIT_ANGLE + math.radians(nprng.uniform(-jitter, jitter))
                       if jitter else UNIT_ANGLE),
                owner=15, gold=(gold if bid == "ngol" else 12500),
            )
            u.z = round(float(np.mean([gheight[j, i], gheight[j, i + 1],
                                       gheight[j + 1, i], gheight[j + 1, i + 1]])), 4)
            keep.append(u)
            placed.append((bid, i, j))
            for di in range(-int(min_dist), int(min_dist) + 1):
                for dj in range(-int(min_dist), int(min_dist) + 1):
                    if di * di + dj * dj <= min_dist * min_dist:
                        ii, jj = i + di, j + dj
                        if 0 <= ii < W and 0 <= jj < H:
                            blocked[ii, jj] = True
        log.append(f"    {cn:<6}({bid}) 目标 {n:>2} → 放下 {len(spots):>2}"
                   + ("  ✘ 位置不够" if len(spots) < n else ""))

    # 出生点落位修正（模板的 sloc 是按空模板平地写的，地形换了得重算）
    n_fix = 0
    for u in keep:
        if u.id != "sloc":
            continue
        i = int((u.x + W * 64.0) / TILE)
        j = int((u.y + H * 64.0) / TILE)
        good = (0 <= i < W and 0 <= j < H and not water[j:j + 2, i:i + 2].any()
                and not boundary[j:j + 2, i:i + 2].any())
        if not good:
            ok = flat_ok(water, layer, boundary, W, H, 2, flat_tol)
            ok[:edge, :] = False
            ok[W - edge:, :] = False
            ok[:, :edge] = False
            ok[:, H - edge:] = False
            ok &= ~blocked
            idxs = np.flatnonzero(ok.ravel())
            if idxs.size:
                pick = int(nprng.choice(idxs))
                i, j = divmod(pick, H)
                u.x = (i + 0.5) * TILE - W * 64.0
                u.y = (j + 0.5) * TILE - H * 64.0
                n_fix += 1
                for di in range(-3, 4):
                    for dj in range(-3, 4):
                        ii, jj = i + di, j + dj
                        if 0 <= ii < W and 0 <= jj < H:
                            blocked[ii, jj] = True
        i = int((u.x + W * 64.0) / TILE)
        j = int((u.y + H * 64.0) / TILE)
        if 0 <= i < W and 0 <= j < H:
            u.z = round(float(np.mean([gheight[j, i], gheight[j, i + 1],
                                       gheight[j + 1, i], gheight[j + 1, i + 1]])), 4)
        u.raw = None

    # creation number 重排（官方图每条记录都有唯一编号）
    for k, u in enumerate(keep):
        u.creation = k

    new_doo = os.path.join(tmp, "war3mapUnits.doo.new")
    open(new_doo, "wb").write(w3units.build(keep, ver or 7, sub or 9, use_raw=False))

    cnt = Counter(b for b, _i, _j in placed)
    print(f"摆放中立建筑 {len(placed)} 座：" +
          "  ".join(f"{BY_ID.get(k, (k, k))[1]}×{v}" for k, v in cnt.items()))
    for line in log:
        print(line)
    print(f"    出生点修正 {n_fix} 个 / 间距 ≥{min_dist:.0f} 格 / 边缘留空 {edge} 格 / "
          f"平地容差 {flat_tol} 层 / 朝向 "
          + (f"270°±{jitter:g}°" if jitter else "270°（官方 2900+ 座建筑 100% 都是它）"))

    if preview:
        tw = np.zeros((W, H), dtype=bool)
        for j in range(H):
            for i in range(W):
                tw[i, j] = (water[j, i] and water[j, i + 1]
                            and water[j + 1, i] and water[j + 1, i + 1])
        disp = np.zeros((H, W, 3), dtype=np.uint8)
        disp[np.transpose(tw)[::-1]] = (60, 110, 200)
        land = ~np.transpose(tw)[::-1]
        disp[land] = (205, 195, 165)
        dt = np.transpose(trees)[::-1]
        disp[dt] = (40, 110, 40)
        for bid, i, j in placed:
            r = 1
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    yy, xx = H - 1 - (j + dj), i + di
                    if 0 <= yy < H and 0 <= xx < W:
                        disp[yy, xx] = COLORS.get(bid, (255, 0, 0))
        Image.fromarray(disp).resize((W * 4, H * 4), Image.NEAREST).save(preview)
        print(f"预览图: {preview}")

    subprocess.run([exe, "add", target, new_doo, "war3mapUnits.doo"],
                   capture_output=True, timeout=180)
    print(f"完成: {target}（war3mapUnits.doo {len(keep)} 条 = "
          f"保留 {len(keep) - len(placed)} + 新建筑 {len(placed)}）")
    if not opts.get("keep-temp"):
        drop_tmp(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
