# -*- coding: utf-8 -*-
"""统计官方图里「野怪点 camp」的构成：多大、守什么、掉什么。

做法：owner=12 的单位按单链接聚类（阈值 LINK 世界单位）→ 每个 camp 记录
单位组成 / 半径 / 到最近中立建筑的距离和类型 / 掉落表。
"""
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import w3units

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.normpath(os.path.join(HERE, "..", "..", "bin", "MPQEditor.exe"))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
TMP = os.path.join(HERE, "creep")
os.makedirs(TMP, exist_ok=True)

LINK = 700.0            # 单链接阈值（世界单位）：同一窝野怪一般挤在这么近
TILE = 128.0
BLD = ("ngol", "ngme", "ngad", "nmer", "nfoh", "nmrk", "ntav",
       "nmr0", "nmr2", "nmr4", "nmr5", "nmr7", "nmr8", "nmr9", "nmrc", "nmrd", "nmre")


def clusters(xs, ys, link=LINK):
    n = len(xs)
    if n == 0:
        return []
    par = list(range(n))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    d = np.hypot(xs[:, None] - xs[None, :], ys[:, None] - ys[None, :])
    for i in range(n):
        for j in range(i + 1, n):
            if d[i, j] <= link:
                ra, rb = find(i), find(j)
                if ra != rb:
                    par[ra] = rb
    g = defaultdict(list)
    for i in range(n):
        g[find(i)].append(i)
    return list(g.values())


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    d = os.path.normpath(os.path.join(ROOT, "Maps", folder))
    camps = []
    for nm in sorted(f for f in os.listdir(d) if f.endswith((".w3m", ".w3x"))):
        dst = os.path.join(TMP, "war3mapUnits.doo")
        if os.path.exists(dst):
            os.remove(dst)
        subprocess.run([EXE, "extract", os.path.join(d, nm), "war3mapUnits.doo",
                        TMP, "/fp"], capture_output=True, timeout=180)
        if not os.path.exists(dst):
            continue
        _v, _s, units, _e = w3units.parse(open(dst, "rb").read())
        cre = [u for u in units if u.owner == 12]
        bld = [u for u in units if u.owner == 15 and u.id in BLD]
        if not cre:
            continue
        xs = np.array([u.x for u in cre])
        ys = np.array([u.y for u in cre])
        for grp in clusters(xs, ys):
            pts = [(cre[i].x, cre[i].y) for i in grp]
            cx = float(np.mean([p[0] for p in pts]))
            cy = float(np.mean([p[1] for p in pts]))
            rad = float(max(math.hypot(p[0] - cx, p[1] - cy) for p in pts))
            ids = Counter(cre[i].id for i in grp)
            # 掉落：整个 camp 里所有单位的 item set
            drops = []
            n_drop_unit = 0
            for i in grp:
                if cre[i].sets:
                    n_drop_unit += 1
                    for s in cre[i].sets:
                        for iid, chance in s:
                            drops.append((iid, chance))
            dbest, bid = 1e18, None
            for b in bld:
                dd = math.hypot(b.x - cx, b.y - cy)
                if dd < dbest:
                    dbest, bid = dd, b.id
            camps.append(dict(map=nm, n=len(grp), rad=rad, ids=ids, drops=drops,
                              n_drop_unit=n_drop_unit, db=dbest, bid=bid))
    print(f"扫描 {len(set(c['map'] for c in camps))} 张图 → {len(camps)} 个野怪点\n")

    def pct(v):
        v = sorted(v)
        return f"p10={v[len(v)//10]:.0f} p50={v[len(v)//2]:.0f} p90={v[len(v)*9//10]:.0f}"

    print(f"【camp 规模】单位数: {pct([c['n'] for c in camps])}   "
          f"分布 {dict(sorted(Counter(c['n'] for c in camps).items()))}")
    print(f"【camp 半径】世界单位: {pct([c['rad'] for c in camps])}   "
          f"格: {pct([c['rad']/TILE for c in camps])}")
    near = [c for c in camps if c["db"] <= 1200]
    print(f"\n【守建筑】离最近中立建筑 ≤1200（≈9格）的 camp: {len(near)}/{len(camps)} "
          f"({len(near)*100//max(1,len(camps))}%)")
    print(f"   守的建筑类型: {dict(Counter(c['bid'] for c in near).most_common(8))}")
    print(f"   守建筑 camp 的单位数: {pct([c['n'] for c in near])}")
    far = [c for c in camps if c["db"] > 1200]
    print(f"【纯野点】离建筑 >1200 的 camp: {len(far)}  "
          f"单位数 {pct([c['n'] for c in far])}")
    print(f"\n【掉落】有掉落的 camp: {sum(1 for c in camps if c['drops'])}/{len(camps)}")
    nd = Counter(c["n_drop_unit"] for c in camps if c["n_drop_unit"])
    print(f"   camp 内带掉落的单位个数: {dict(sorted(nd.items()))}")
    print(f"   掉落物品数/camp: {dict(sorted(Counter(len(c['drops']) for c in camps).items()))}")
    items = Counter(i for c in camps for i, _ in c["drops"])
    print(f"\n【物品池 top30】")
    for k, v in items.most_common(30):
        print(f"   {k} × {v}")
    print(f"\n【chance 分布】{dict(Counter(ch for c in camps for _i, ch in c['drops']).most_common(10))}")
    # 单位数 vs 掉落物品数
    print("\n【camp 单位数 → 平均掉落物品数 / 有掉落比例】")
    byn = defaultdict(list)
    for c in camps:
        byn[c["n"]].append(len(c["drops"]))
    for n in sorted(byn):
        if n > 12:
            continue
        v = byn[n]
        print(f"   {n:>2} 个单位: {len(v):>4} 个 camp  平均掉落 {sum(v)/len(v):.2f} 件  "
              f"有掉落 {sum(1 for x in v if x)*100//len(v)}%")
    # 掉落等级 vs camp 规模：物品 id = Y + 类别 + I + 等级（如 YiI3 = 随机物品 Yi 类 3 级）
    def lvl(iid):
        if len(iid) == 4 and iid[0] == "Y" and iid[2] == "I" and iid[3].isdigit():
            return iid[1], int(iid[3])
        return None, None

    print("\n【掉落 (类别,等级) 联合分布 vs camp 规模】—— 类别和等级不独立（Yk 只到2级、Yl 只有7/8级）")
    joint = defaultdict(Counter)
    for c in camps:
        b = min(c["n"], 6)
        for iid, _ch in c["drops"]:
            cls, lv = lvl(iid)
            if lv:
                joint[b][(cls, lv)] += 1
    for n in sorted(joint):
        tot = sum(joint[n].values())
        items = ", ".join(f"({k},{v}):{c}" for (k, v), c in sorted(joint[n].items()))
        print(f"   n={n}: 总{tot}  {items}")

    print("\n【掉落等级 vs camp 规模】行=camp 单位数，列=物品等级")
    ltab = defaultdict(Counter)
    ctab = defaultdict(Counter)
    for c in camps:
        for iid, _ch in c["drops"]:
            cls, lv = lvl(iid)
            if lv:
                ltab[c["n"]][lv] += 1
                ctab[c["n"]][cls] += 1
    allv = sorted({v for cc in ltab.values() for v in cc})
    print("      " + "".join(f"{v:>6}级" for v in allv) + "   类别分布")
    for n in sorted(ltab):
        row = "".join(f"{ltab[n][v]:>7}" for v in allv)
        print(f"   {n:>2} 个" + row + f"   {dict(ctab[n].most_common())}")

    print("\n【守金矿 camp vs 纯野点的掉落对比】")
    for tag, sel in (("守金矿(≤1200)", [c for c in camps if c["bid"] == "ngol" and c["db"] <= 1200]),
                     ("守商店", [c for c in camps if c["bid"] == "ngme" and c["db"] <= 1200]),
                     ("纯野点(>1200)", [c for c in camps if c["db"] > 1200])):
        lv = Counter()
        cl = Counter()
        nn = []
        for c in sel:
            nn.append(c["n"])
            for iid, _ch in c["drops"]:
                a, b = lvl(iid)
                if b:
                    lv[b] += 1
                    cl[a] += 1
        if not sel:
            continue
        print(f"   {tag:<16} n={len(sel):>4} 单位数均值 {sum(nn)/len(nn):.2f}  "
              f"等级分布 {dict(sorted(lv.items()))}  类别 {dict(cl.most_common())}")

    # 建筑「有没有守卫」+ 守卫离建筑多远
    print("\n【建筑守卫覆盖率】camp 中心离建筑 ≤1200（≈9格）算守卫")
    per = defaultdict(lambda: [0, 0])
    dists = defaultdict(list)
    for c in camps:
        if c["bid"] is None:
            continue
        per[c["bid"]][1] += 1
        if c["db"] <= 1200:
            per[c["bid"]][0] += 1
            dists[c["bid"]].append(c["db"])
    for k in BLD:
        if k not in per:
            continue
        g, tot = per[k]
        dd = sorted(dists[k])
        if not dd:
            continue
        q = lambda f: dd[min(len(dd) - 1, int(len(dd) * f))]
        print(f"   {k}: {g}/{tot} 有守卫 ({g*100//tot}%)  "
              f"距离 p10={q(.1):.0f} p50={q(.5):.0f} p90={q(.9):.0f} 世界单位"
              f" = {q(.1)/TILE:.1f}/{q(.5)/TILE:.1f}/{q(.9)/TILE:.1f} 格")

    print("\n【野怪 id 池】出现过的 camp 数 top25（同一 id 在多张图出现才算通用）")
    idcamp = Counter()
    idmap = defaultdict(set)
    for c in camps:
        for k in c["ids"]:
            idcamp[k] += 1
            idmap[k].add(c["map"])
    for k, v in idcamp.most_common(25):
        print(f"   {k}: {v:>4} 个 camp / {len(idmap[k]):>2} 张图")

    # 常见的单位组合
    print("\n【常见单位组合（camp 内 id 计数，top 20）】")
    combos = Counter(tuple(sorted(c["ids"].items())) for c in camps)
    for k, v in combos.most_common(20):
        print(f"   ×{v:<3} {dict(k)}")


if __name__ == "__main__":
    main()
    # 导出 camp 组合模板（≥3 次出现），供 add_creeps.py 内嵌
    import json
    camps2 = []
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    d = os.path.normpath(os.path.join(ROOT, "Maps", folder))
    seen = Counter()
    for nm in sorted(f for f in os.listdir(d) if f.endswith((".w3m", ".w3x"))):
        dst = os.path.join(TMP, "war3mapUnits.doo")
        if os.path.exists(dst):
            os.remove(dst)
        subprocess.run([EXE, "extract", os.path.join(d, nm), "war3mapUnits.doo",
                        TMP, "/fp"], capture_output=True, timeout=180)
        if not os.path.exists(dst):
            continue
        _v, _s, units, _e = w3units.parse(open(dst, "rb").read())
        cre = [u for u in units if u.owner == 12]
        if not cre:
            continue
        xs = np.array([u.x for u in cre])
        ys = np.array([u.y for u in cre])
        for grp in clusters(xs, ys):
            seen[tuple(sorted(Counter(cre[i].id for i in grp).items()))] += 1
    keep = {k: v for k, v in seen.items() if v >= 3}
    out = os.path.join(HERE, "..", "camp_templates.py")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write('"""官方 1.27a 对战图的野怪点(camp)组成模板，由 tools/_tmp/creep_stats.py 导出。\n\n')
        f.write("每项 = (组成 Counter, 出现次数权重)。出现 <3 次的组合没收录。\n")
        f.write('id 全部来自官方图实测，游戏里一定有效。"""\n\n')
        f.write("CAMP_TEMPLATES = [\n")
        for k, v in sorted(keep.items(), key=lambda kv: -kv[1]):
            f.write(f"    ({dict(k)!r}, {v}),\n")
        f.write("]\n")
    print(f"导出 {len(keep)} 个 camp 模板 → {os.path.normpath(out)}")
