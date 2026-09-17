# -*- coding: utf-8 -*-
"""creep_stats 的精简版：不删临时文件（extract /fp 会直接覆盖），只输出
掉落 (类别,等级) 联合分布 vs camp 规模 —— 给 add_creeps.py 编码用。"""
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
sys.path.insert(0, HERE)
from creep_stats import LINK, clusters  # noqa: E402


def lvl(iid):
    if len(iid) == 4 and iid[0] == "Y" and iid[2] == "I" and iid[3].isdigit():
        return iid[1], int(iid[3])
    return None, None


def main():
    d = os.path.normpath(os.path.join(ROOT, "Maps", "."))
    joint = defaultdict(Counter)          # n camp -> {(class,level): count}
    per_unit = Counter()                  # 每个 set 里物品个数的分布
    n_sets_dist = Counter()               # 带掉落单位有几个 set
    for nm in sorted(f for f in os.listdir(d) if f.endswith((".w3m", ".w3x"))):
        dst = os.path.join(TMP, "war3mapUnits.doo")
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
            n = len(grp)
            for i in grp:
                u = cre[i]
                n_sets_dist[len(u.sets)] += 1
                for s in u.sets:
                    per_unit[len(s)] += 1
                    for iid, _ch in s:
                        a, b = lvl(iid)
                        if b:
                            joint[min(n, 7)][(a, b)] += 1
    print("【每单位 set 数】", dict(sorted(n_sets_dist.items())))
    print("【每 set 物品数】", dict(sorted(per_unit.items())))
    for n in sorted(joint):
        tot = sum(joint[n].values())
        row = ", ".join(f"({k},{v}):{c}" for (k, v), c in sorted(joint[n].items()))
        print(f"n<={n}: 总{tot}  {row}")


if __name__ == "__main__":
    main()
