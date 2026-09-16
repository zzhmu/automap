# -*- coding: utf-8 -*-
"""铁证：官方图里「水标记但深度<128」的区域，引擎当水还是当干地？

两条独立证据：
 ① 地表贴图（w3e 的 groundTexture）—— 水域瓦片铺的是水面贴图，干地不是。
    统计 深水(≥128) / 浅水标记(<128) / 陆地 三类角点各自的贴图索引分布。
 ② 寻路图（war3map.wpm）—— 水面瓦片不可走。看浅水标记区的 pathing 字节
    跟深水区是否同类、跟陆地是否不同。

用法: python tools/_tmp/water_truth.py (9)Riverrun.w3m ...
"""
import os
import struct
import subprocess
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402
import shore_depth_profile as DP  # noqa: E402

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")


def tile_names(data):
    pos = 8
    pos += 1
    pos += 4
    ng = struct.unpack_from("<I", data, pos)[0]; pos += 4
    names = []
    for i in range(ng):
        names.append(data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace"))
    return names


def wpm(path, tmp):
    subprocess.run([A.default_exe(), "extract", path, "war3map.wpm", tmp, "/fp"],
                   capture_output=True, timeout=240)
    p = os.path.join(tmp, "war3map.wpm")
    if not os.path.exists(p):
        return None
    b = open(p, "rb").read()
    if b[:4] != b"MP3W":
        return None
    ver, w, h = struct.unpack_from("<III", b, 4)
    return np.frombuffer(b, np.uint8, count=w * h, offset=16).reshape(h, w), w, h


def main():
    maps = sys.argv[1:] or ["(9)Riverrun.w3m", "(4)LostTemple.w3m",
                            "(8)BloodvenomFalls.w3m", "(4)MysticIsles.w3m"]
    tmp = A.make_tmp("wtruth")
    try:
        for fn in maps:
            p = fn if os.path.isabs(fn) else os.path.join(MAPS, fn)
            if not os.path.exists(p):
                print("缺", fn)
                continue
            depth, water, outside, plane = DP.load2(p, tmp)
            subprocess.run([A.default_exe(), "extract", p, "war3map.w3e", tmp, "/fp"],
                           capture_output=True, timeout=240)
            data = open(os.path.join(tmp, "war3map.w3e"), "rb").read()
            names = tile_names(data)
            _ts, w, h, hs = A.read_w3e_header(data)
            R, C = h + 1, w + 1
            a = np.frombuffer(data, np.uint8, count=R * C * 7, offset=hs).reshape(-1, 7)
            tex = (a[:, 4] & 0x0F).reshape(R, C)
            print(f"\n{fn}  贴图表({len(names)}): {names}")
            deep = water & (depth >= 128)
            shal = water & (depth < 128)
            land = ~water & ~outside
            for lab, m in (("深水≥128", deep), ("水标记<128", shal), ("陆地", land)):
                if m.sum() == 0:
                    continue
                c = Counter(tex[m].tolist())
                top = ", ".join(f"{names[i] if i < len(names) else i}:{n}"
                                for i, n in c.most_common(6))
                print(f"   {lab:<10} n={int(m.sum()):>6}  贴图 top: {top}")
            wm = wpm(p, tmp)
            if wm is None:
                print("   （无 wpm）")
                continue
            wm, ww, wh_ = wm
            # wpm 是 4x4 角点一格；把角点掩码降到 wpm 网格
            kh, kw = wm.shape
            def to_cell(m):
                out = np.zeros((kh, kw), np.int64)
                cnt = np.zeros((kh, kw), np.int64)
                for yy in range(min(R, kh * 4)):
                    for xx in range(min(C, kw * 4)):
                        out[yy // 4, xx // 4] += int(m[yy, xx])
                        cnt[yy // 4, xx // 4] += 1
                return out, cnt
            for lab, m in (("深水≥128", deep), ("水标记<128", shal), ("陆地", land)):
                s, n = to_cell(m)
                sel = n > 0
                frac = s[sel] / n[sel]
                keep = frac > 0.5
                if not keep.any():
                    continue
                cc = Counter(wm[sel][keep].tolist())
                top = ", ".join(f"0x{v:02X}:{n2}" for v, n2 in cc.most_common(4))
                print(f"   wpm {lab:<10} 占多数的格子 pathing: {top}")
    finally:
        A.drop_tmp(tmp)


main()
