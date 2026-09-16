# -*- coding: utf-8 -*-
"""查 waterHeight 字段到底是「全图常量水面」还是「逐角点水面」。

顺带把每张图水面平面解出来（= wh 的出现最多的那个值），
再算「水深 vs 离岸距离」剖面 —— 看官方水里到底是怎么变深的。
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


def main():
    maps = sys.argv[1:] or [
        "(4)LostTemple.w3m", "(9)Riverrun.w3m", "(6)DarkForest.w3m",
        "(8)PlainsOfSnow.w3m", "(8)BloodvenomFalls.w3m", "(4)MysticIsles.w3m",
        "(6)GnollWood.w3m", "(12)IceCrown.w3m"]
    tmp = A.make_tmp("whprobe")
    try:
        for fn in maps:
            p = fn if os.path.isabs(fn) else os.path.join(MAPS, fn)
            if not os.path.exists(p):
                p = os.path.join(ROOT, fn)
            got = S.load(p, tmp)
            if got is None:
                print(f"{fn}: 读不到")
                continue
            raw = None
            # 直接从 load 里复用：wh 的分布要看原始字段，重读一次
            import subprocess
            subprocess.run([A.default_exe(), "extract", p, "war3map.w3e", tmp, "/fp"],
                           capture_output=True, timeout=240)
            data = open(os.path.join(tmp, "war3map.w3e"), "rb").read()
            _ts, w, h, hs = A.read_w3e_header(data)
            R, C = h + 1, w + 1
            a = np.frombuffer(data, np.uint8, count=R * C * 7, offset=hs).reshape(-1, 7)
            whs = (a[:, 2].astype(np.uint16) | (a[:, 3].astype(np.uint16) << 8)) & 0x3FFF
            c = Counter(whs.tolist())
            top = c.most_common(5)
            water = got["water"] & ~got["outside"]
            land = ~got["water"] & ~got["outside"]
            wh_water = Counter(whs[water.reshape(-1)].tolist()).most_common(3)
            print(f"\n{os.path.basename(p)}  {R}x{C}  水角点 {int(water.sum())}")
            print(f"  wh 全图取值数 {len(c)}，最常见: "
                  + ", ".join(f"{v}({n})" for v, n in top))
            print(f"  水角点上的 wh 最常见: "
                  + ", ".join(f"{v}({n})" for v, n in wh_water))
    finally:
        A.drop_tmp(tmp)


main()
