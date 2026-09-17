# -*- coding: utf-8 -*-
"""在随机地形上摆放中立野怪（owner=12）—— 重写 war3mapUnits.doo 的层 3。

用法:
  python add_creeps.py <地图.w3x> [--guard-share 0.6] [--forest-camps auto]
      [--camp-scale 1.0] [--seed 7] [--preview out.png]

两种野怪点（camp），口径全部来自 45 张官方 1.27a/TFT 对战图 1269 个野怪点的实测
（tools/_tmp/creep_stats.py）:

  ① 守建筑野怪点   63% 的金矿、65% 的商店、59% 的实验室旁边有野怪点守着，
     点心离建筑 2~5 格（金矿 p50=3.2 格、商店 p50=2.4 格）。
     --guard-share 控制多大规模比例的建筑带守卫（默认 0.6 ≈ 官方 59%~65%）。
  ② 林中野怪点     其余野怪点（官方 464/1269 = 37%）离任何中立建筑 >9 格，
     单位更少（p50=3），这就是「树林角落里的野怪」。
     --forest-camps auto = 按图面积缩放（128×128 默认 16 个）。

组成: 从官方图实测导出的 183 个 camp 组合模板（tools/camp_templates.py，
出现 ≥3 次的组合）按频次加权抽样 —— 单位 id、数量搭配全是官方原样。
野怪点大小 p10/p50/p90 = 3/4/5 只，半径 p50 ≈ 1.7 格。

朝向: 🔴 野怪的 angle 是真随机（官方 644 个 nftr 有 546 种朝向），
别照搬建筑的 270° —— 那是 owner=15 建筑独有的规则。

掉落（--drops 1，默认开）:
  - 官方 1240/1269 个 camp 带掉落；chance 全部是 100；
  - 每份掉落 = 1 个 set × 1 个「随机物品表」条目（Y<类别>I<等级>，
    如 YiI3 = i 类 3 级）；
  - 物品份数随 camp 规模涨（官方实测 n=2→0.9 份、3→1.3、4→1.7、5→1.8、8→3+）；
  - (类别,等级) 联合分布直接查官方实测表（类别和等级不独立：Yk 只出 1~2 级、
    Yl 只出 7~8 级），且等级随 camp 变大整体上移 —— 大 camp 掉好东西。
  - 分配按等级来：等级高的野怪先拿（等级高的怪拿等级高的物品）；
    🔴 等级 > 6 的野怪必定掉装备（份数不够就补一份兜底）—— 野怪等级来自
    游戏 Units/UnitBalance.slk 的 level 字段，表在 creep_levels.py。
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
from add_buildings import (GROUND_ZERO, LAYER_ZERO, LAYER_STEP, TILE,
                           flat_ok, win_view)
from camp_templates import CAMP_TEMPLATES
from creep_levels import CREEP_LVL

force_utf8_stdout()

#: 会带守卫野怪点的建筑（官方实测守卫率 59%~65% 的三类）
GUARDED = ("ngol", "ngme", "ngad")

#: camp 里带掉落时的 (类别,等级) 联合分布 —— 官方 1269 个 camp 实测，
#: key = min(camp 只数, 7)。类别: i=随机物品 j=随机消耗品 k=永久(只 1~2 级)
#: l=神器(只 7~8 级)。
DROP_JOINT = {
    2: [(("k", 1), 42), (("i", 1), 14)],
    3: [(("k", 1), 127), (("i", 1), 108), (("i", 2), 83), (("j", 2), 67),
        (("j", 3), 50), (("k", 2), 32), (("i", 3), 24), (("i", 5), 8),
        (("j", 4), 10), (("i", 4), 4), (("j", 1), 5), (("j", 5), 5), (("i", 6), 1)],
    4: [(("k", 1), 171), (("k", 2), 100), (("i", 1), 61), (("i", 2), 57),
        (("j", 2), 65), (("j", 3), 61), (("j", 4), 65), (("i", 3), 48),
        (("i", 4), 37), (("i", 5), 31), (("j", 5), 30), (("i", 6), 9),
        (("j", 1), 4), (("l", 8), 2)],
    5: [(("k", 2), 82), (("k", 1), 79), (("i", 4), 38), (("i", 1), 34),
        (("i", 6), 28), (("j", 4), 32), (("j", 3), 29), (("j", 5), 24),
        (("j", 2), 22), (("i", 2), 18), (("i", 3), 27), (("i", 5), 9),
        (("j", 6), 4), (("l", 8), 5)],
    6: [(("k", 1), 17), (("k", 2), 10), (("j", 2), 15), (("i", 3), 16),
        (("l", 7), 10), (("l", 8), 6), (("i", 1), 9), (("j", 3), 11),
        (("j", 4), 6), (("j", 6), 5), (("j", 5), 4), (("i", 4), 2), (("i", 5), 2)],
    7: [(("k", 2), 29), (("k", 1), 16), (("l", 8), 11), (("j", 6), 7),
        (("i", 1), 9), (("i", 4), 7), (("i", 2), 6), (("j", 5), 5), (("i", 5), 4),
        (("j", 4), 4), (("l", 7), 3), (("j", 3), 3), (("i", 3), 2), (("j", 2), 2)],
}

#: camp 只数 → 平均掉落份数（官方实测，n≥8 按 3.0 计）
EXPECT_DROPS = {2: 0.9, 3: 1.3, 4: 1.7, 5: 1.8, 6: 1.85, 7: 2.0}

#: 官方野怪点组合模板的权重（出现次数）—— 加载后按 --style 的野怪池过滤
_TPL_IDS = [dict(c) for c, _w in CAMP_TEMPLATES]
_TPL_W = [w for _c, w in CAMP_TEMPLATES]


def filter_templates(style):
    """按风格的野怪 id 池过滤组合模板（全部 id 都在池内才保留，uDNR 不限）。"""
    if not style:
        return _TPL_IDS, _TPL_W
    from tilesets import STYLES
    pool = set(STYLES[style]["pool"]) | {"uDNR"}
    ids, ws = [], []
    for comp, w in zip(_TPL_IDS, _TPL_W):
        if all(uid in pool for uid in comp):
            ids.append(comp)
            ws.append(w)
    return ids, ws

#: 野怪预览图配色（红 = 野怪点，比建筑色更暗一档）
CREEP_COLOR = (200, 40, 40)


def tree_score(trees, k=5):
    """每个 tile 周围 k×k 窗口内的树数（含自己）—— 林中野怪点选址用。"""
    return win_view(trees.astype(np.int32), k).sum(axis=(2, 3))


def sample_drop(nprng, n, lmax=0):
    """camp 只数 n、窝内最高野怪等级 lmax → 掉落的 [(类别,等级), ...]。

    份数按官方均值抖动；查表用的 bucket = max(n, lmax)（窝里带高等级怪时，
    掉落等级整体上移 —— 官方 lv7/8 怪只在掉 7~8 级物品的窝里出现）。
    """
    exp = EXPECT_DROPS.get(min(n, 8), 3.0 if n >= 8 else 1.0)
    if n >= 8:
        exp = 3.0
    k = int(exp)
    if nprng.random() < exp - k:
        k += 1
    if k <= 0:
        return []
    bucket = min(max(n, min(lmax, 7)), 7)
    table = DROP_JOINT[bucket]
    ws = np.array([w for _it, w in table], dtype=np.float64)
    ws /= ws.sum()
    picks = nprng.choice(len(table), size=k, p=ws)
    return [table[p][0] for p in picks]


def drop_for_level(nprng, lv):
    """给等级 lv 的野怪生成一份掉落（等级贴着野怪等级走，类别守官方约束：
    Yk 只 1~2 级、Yl 只 7~8 级）。"""
    t = min(max(lv, 1), 8)
    if t >= 7:
        cls = "i" if nprng.random() < 0.6 else "l"
        level = 8 if (t >= 8 or nprng.random() < 0.5) else 7
    elif t >= 4:
        cls = "i" if nprng.random() < 0.55 else "j"
        level = min(6, max(3, t + int(nprng.integers(-1, 2))))
    else:
        table = DROP_JOINT[min(max(t, 2), 3)]
        ws = np.array([w for _it, w in table], dtype=np.float64)
        ws /= ws.sum()
        cls, level = table[int(nprng.choice(len(table), p=ws))]
    return cls, level


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
    edge = max(1, int(opts.get("edge", 6)))
    guard_share = float(opts.get("guard-share", 0.6))
    camp_scale = float(opts.get("camp-scale", 1.0))
    drops_on = str(opts.get("drops", 1)) not in ("0", "false", "no")
    fc = opts.get("forest-camps", "auto")
    forest_auto = str(fc).lower() in ("auto", "") or fc is True
    forest_n = -1 if forest_auto else max(0, int(float(fc)))
    guard_dist = float(opts.get("guard-dist", 3.5))       # 守卫点心离建筑均值（格）
    style = str(opts.get("style") or "").strip()
    tpl_ids, tpl_w = filter_templates(style)
    if style:
        from tilesets import STYLES
        pool = STYLES.get(style, {}).get("pool", [])
        print(f"风格野怪池: {style}（{len(pool)} 种 id）→ 可用组合模板 "
              f"{len(tpl_ids)}/{len(_TPL_IDS)}"
              + ("" if tpl_ids else "  ⚠ 池内无模板，回退全局"))
        if not tpl_ids:
            tpl_ids, tpl_w = _TPL_IDS, _TPL_W

    tmp = make_tmp("creeps")
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

    # 已有单位：建筑 + 出生点全保留，旧的 owner=12 野怪清掉（可重复运行）
    doo_u = os.path.join(tmp, "war3mapUnits.doo")
    if os.path.exists(doo_u):
        ver, sub, units, _ = w3units.parse(open(doo_u, "rb").read())
    else:
        ver, sub, units = 7, 9, []
    n_old_creeps = sum(1 for u in units if u.owner == 12)
    keep = [u for u in units if u.owner != 12]
    for u in keep:
        u.raw = None
    blds = [u for u in keep if u.owner == 15]
    slocs = [u for u in keep if u.id == "sloc"]
    print(f"原 units.doo {len(units)} 条（旧野怪 {n_old_creeps} 只清掉）→ "
          f"保留建筑 {len(blds)} + 出生点 {len(slocs)}")

    # 树占位（野怪不站在树格上，但允许贴着树 —— 官方野怪常在林缘）
    trees = np.zeros((W, H), dtype=bool)
    doo_d = os.path.join(tmp, "war3map.doo")
    n_doo = 0
    if os.path.exists(doo_d):
        blob = open(doo_d, "rb").read()
        _v, _s, recs, _t = parse_doo(blob)
        n_doo = len(recs)
        for rec in recs:
            if len(rec) < 42:
                continue
            x, y = struct.unpack_from("<2f", rec, 8)
            i = int((x + W * 64.0) / TILE)
            j = int((y + H * 64.0) / TILE)
            if 0 <= i < W and 0 <= j < H:
                trees[i, j] = True
        print(f"读 war3map.doo：{n_doo} 个装饰物，{int(trees.sum())} 格有树")

    # 合法落点：±1 格内 3×3 角点非水/非边界外/层差 ≤ 容差，非树，留边
    ok = flat_ok(water, layer, boundary, W, H, 1, flat_tol)
    # 但单位「脚下那格」必须完全同层 —— 层差 ≥1 的瓦片是垂直崖壁，
    # 站上去要么卡死要么观感破碎（inspect_units 的「悬崖上」判的就是这个）
    sp = win_view(layer.astype(np.int16), 2)
    tile_flat = (sp.max(axis=(2, 3)) - sp.min(axis=(2, 3))) == 0   # (H,W) 角点口径
    ok &= tile_flat.T[:W, :H]
    ok &= ~trees
    ok[:edge, :] = False
    ok[W - edge:, :] = False
    ok[:, :edge] = False
    ok[:, H - edge:] = False

    # 出生点周围留空（野怪不堵家门）
    home = np.zeros((W, H), dtype=bool)
    for u in slocs:
        i = int((u.x + W * 64.0) / TILE)
        j = int((u.y + H * 64.0) / TILE)
        home[max(0, i - 6):i + 7, max(0, j - 6):j + 7] = True
    ok &= ~home

    # 建筑占位（守卫点心至少离自家建筑 1 格，离别的建筑也隔开）
    bpos = [(int(round((u.x + W * 64.0) / TILE - 0.5)),
             int(round((u.y + H * 64.0) / TILE - 0.5)), u.id) for u in blds]
    bld_mask = np.zeros((W, H), dtype=bool)
    for i, j, _bid in bpos:
        bld_mask[max(0, i - 2):i + 3, max(0, j - 2):j + 3] = True
    okc = ok & ~bld_mask

    ts = np.zeros((W, H), dtype=np.int32)
    if trees.any():
        t5 = tree_score(trees)
        ts[:min(W, t5.shape[1]), :min(H, t5.shape[0])] = t5.T[
            :min(W, t5.shape[1]), :min(H, t5.shape[0])]

    nprng = np.random.default_rng(seed)
    camps = []          # (kind, ci, cj, [(uid, i, j), ...])
    occupied = np.zeros((W, H), dtype=bool)

    def tile_of(x, y):
        return int((x + W * 64.0) / TILE), int((y + H * 64.0) / TILE)

    def try_camp_center(ci0, cj0, rad_lo, rad_hi, pool):
        """在 (ci0,cj0) 周围 rad_lo~rad_hi 格的环带里找一个合法 camp 心。"""
        for _ in range(48):
            ang = nprng.uniform(0.0, 2 * math.pi)
            d = nprng.uniform(rad_lo, rad_hi) * TILE
            x, y = ci0 * TILE + TILE * 0.5 - W * 64.0 + math.cos(ang) * d, \
                   cj0 * TILE + TILE * 0.5 - H * 64.0 + math.sin(ang) * d
            i, j = tile_of(x, y)
            if 0 <= i < W and 0 <= j < H and pool[i, j]:
                return i, j
        return None

    def lay_camp(ci, cj):
        """按抽到的模板把单位撒在 camp 心周围（半径 ~1.6 格）。"""
        comp = tpl_ids[int(nprng.choice(len(tpl_ids), p=np.array(
            tpl_w, dtype=np.float64) / sum(tpl_w)))]
        placed = []
        r = 1.6
        for uid, cnt in comp.items():
            for _ in range(cnt):
                got = None
                for t in range(36):
                    rr = r if t < 24 else r + 1.2
                    ang = nprng.uniform(0.0, 2 * math.pi)
                    dd = nprng.uniform(0.2, rr) * TILE
                    x = (ci + 0.5) * TILE - W * 64.0 + math.cos(ang) * dd
                    y = (cj + 0.5) * TILE - H * 64.0 + math.sin(ang) * dd
                    i, j = tile_of(x, y)
                    if 0 <= i < W and 0 <= j < H and okc[i, j] and not occupied[i, j]:
                        got = (i, j)
                        break
                if got is None:      # 实在挤不下就贴 camp 心
                    if okc[ci, cj] and not occupied[ci, cj]:
                        got = (ci, cj)
                    else:
                        continue
                occupied[got[0], got[1]] = True
                placed.append((uid, got[0], got[1]))
        return comp, placed

    # ① 守建筑野怪点
    n_guard_try = n_guard_ok = 0
    for i, j, bid in bpos:
        if bid not in GUARDED or nprng.random() >= guard_share:
            continue
        n_guard_try += 1
        spot = try_camp_center(i, j, 2.0, 5.0, okc & ~occupied)
        if spot is None:
            continue
        comp, placed = lay_camp(*spot)
        if not placed:
            continue
        n_guard_ok += 1
        camps.append(("guard", spot[0], spot[1], placed, comp))
        occupied[max(0, spot[0] - 3):spot[0] + 4, max(0, spot[1] - 3):spot[1] + 4] = True

    # ② 林中野怪点：远离建筑（>12 格）、贴树林（5×5 窗口 ≥3 格有树）
    if forest_auto:
        n_forest = int(round(W * H / 1024.0 * camp_scale))
    else:
        n_forest = int(round(forest_n * camp_scale))
    n_forest_ok = 0
    if n_forest > 0:
        far_bld = np.ones((W, H), dtype=bool)
        ii, jj = np.mgrid[0:W, 0:H]
        for i, j, _bid in bpos:
            far_bld &= (np.hypot(ii - i, jj - j) > 12.0)
        for u in slocs:
            i, j = tile_of(u.x, u.y)
            far_bld &= (np.hypot(ii - i, jj - j) > 8.0)
        base = okc & far_bld & ~occupied
        pool = base & (ts >= 3)
        if pool.sum() < n_forest:
            pool = base & (ts >= 1)
        if pool.sum() < n_forest:
            pool = base
        # 最远点采样铺开，前 5% 里优先挑树多的
        dist = np.full((W, H), 1e9, dtype=np.float64)
        free = pool.copy()
        for k in range(n_forest):
            cand = free if k == 0 else (free & (dist >= 6.0))
            idxs = np.flatnonzero(cand.ravel())
            if idxs.size == 0:
                cand = free
                idxs = np.flatnonzero(cand.ravel())
                if idxs.size == 0:
                    break
            if k == 0:
                pick = int(nprng.choice(idxs))
            else:
                d = dist.ravel()[idxs]
                thr = np.quantile(d, 0.95)
                far = idxs[d >= thr]
                best = far[np.argmax(ts.ravel()[far])]
                pick = int(best)
            ci, cj = divmod(pick, H)          # 🔴 C 序 ravel ⇒ divmod(pick, H)
            comp, placed = lay_camp(ci, cj)
            if not placed:
                free[ci, cj] = False
                continue
            n_forest_ok += 1
            camps.append(("forest", ci, cj, placed, comp))
            dist = np.minimum(dist, np.hypot(ii - ci, jj - cj))
            free[ci, cj] = False
            occupied[max(0, ci - 2):ci + 3, max(0, cj - 2):cj + 3] = True

    # 生成 Unit 记录：owner=12、朝向真随机（官方 644 只 nftr 有 546 种朝向）
    new_units = []
    n_items = 0
    for kind, ci, cj, placed, comp in camps:
        us = []
        for uid, i, j in placed:
            u = w3units.Unit(id=uid, owner=12,
                             x=(i + 0.5) * TILE - W * 64.0,
                             y=(j + 0.5) * TILE - H * 64.0, z=0.0,
                             angle=float(nprng.uniform(0.0, 6.283185307)))
            u.z = round(float(np.mean([gheight[j, i], gheight[j, i + 1],
                                       gheight[j + 1, i], gheight[j + 1, i + 1]])), 4)
            us.append(u)
        if drops_on:
            lmax = max((CREEP_LVL.get(u.id, 0) for u in us), default=0)
            items = sample_drop(nprng, len(placed), lmax)
            n_items += len(items)
            # 掉落按野怪等级分配（等级 = 游戏 UnitBalance.slk 的 level 字段）：
            # 等级高的先拿、拿好的；🔴 等级 > 6 必定掉一份，且物品等级贴着怪等级走
            lv_of = lambda u: CREEP_LVL.get(u.id, 0)
            order = sorted(range(len(us)), key=lambda k: -lv_of(us[k]))
            items = sorted(items, key=lambda t: -t[1])
            got = [False] * len(us)
            for k in order:
                if lv_of(us[k]) <= 6:
                    continue
                it = drop_for_level(nprng, lv_of(us[k]))
                us[k].sets = us[k].sets + [[(f"Y{it[0]}I{it[1]}", 100)]]
                got[k] = True
                n_items += 1
            for it in items:      # 剩余的：优先给还没掉落的最高等级怪
                if not us:
                    break
                k = next((kk for kk in order if not got[kk]), order[0])
                us[k].sets = us[k].sets + [[(f"Y{it[0]}I{it[1]}", 100)]]
                got[k] = True
        new_units.extend(us)
    keep.extend(new_units)
    for k, u in enumerate(keep):
        u.creation = k

    new_doo = os.path.join(tmp, "war3mapUnits.doo.new")
    open(new_doo, "wb").write(w3units.build(keep, ver or 7, sub or 9, use_raw=False))

    kind_cnt = Counter(k for k, *_ in camps)
    n_creeps = sum(len(c[3]) for c in camps)
    print(f"摆放野怪 {n_creeps} 只 / {len(camps)} 个野怪点 "
          f"（守建筑 {kind_cnt.get('guard', 0)} + 林中 {kind_cnt.get('forest', 0)}），"
          f"掉落表 {n_items} 份（chance=100，等级>6 必掉、等级高的先拿）")
    print(f"    守卫率目标 {guard_share:.0%}（官方金矿 63% / 商店 65% / 实验室 59%）"
          f" / 林中目标 {n_forest} 个"
          + ("" if not forest_auto else "（auto=按图面积）"))
    sz = Counter(len(c[3]) for c in camps)
    print(f"    camp 只数分布 {dict(sorted(sz.items()))}（官方 p10/p50/p90 = 3/4/5）")

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
        disp[np.transpose(trees)[::-1]] = (40, 110, 40)
        for u in blds:
            i, j = tile_of(u.x, u.y)
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    yy, xx = H - 1 - (j + dj), i + di
                    if 0 <= yy < H and 0 <= xx < W:
                        disp[yy, xx] = (160, 130, 60)
        for _kind, ci, cj, placed, _comp in camps:
            yy, xx = H - 1 - cj, ci
            if 0 <= yy < H and 0 <= xx < W:
                disp[yy, xx] = CREEP_COLOR
            for _uid, i, j in placed:
                yy, xx = H - 1 - j, i
                if 0 <= yy < H and 0 <= xx < W:
                    disp[yy, xx] = (255, 90, 70)
        Image.fromarray(disp).resize((W * 4, H * 4), Image.NEAREST).save(preview)
        print(f"预览图: {preview}")

    subprocess.run([exe, "add", target, new_doo, "war3mapUnits.doo"],
                   capture_output=True, timeout=180)
    print(f"完成: {target}（war3mapUnits.doo {len(keep)} 条 = "
          f"保留 {len(keep) - len(new_units)} + 新野怪 {len(new_units)}）")
    if not opts.get("keep-temp"):
        drop_tmp(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
