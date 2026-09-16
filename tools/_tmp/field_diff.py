# -*- coding: utf-8 -*-
"""逐字段对比：我们的浅滩图 vs 官方有水地图，看水区角点还有没有别的差异。

w3e 每条角点 7 字节：
  0-1 groundHeight | 2-3 waterHeight|0x4000 | 4 flags<<4|groundTexture
  5 groundVariation<<3|cliffVariation    | 6 cliffTexture<<4|layer
"""
import os
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import inspect_water as iw  # noqa: E402

MAPS = r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps"
TMP = os.path.join(HERE, "fldiff")


def dump(path, tag):
    data = iw.extract(path, TMP)
    W, H, HS = iw.read_header(data)
    # w3e 头： 前 4 字节 "W3E!" + 4 字节 version，然后 tileset(1)，自定义(4)，
    #          n_ground(4) + 4*n_ground，n_cliff(4) + 4*n_cliff
    pos = 8
    tileset = data[pos:pos + 1].decode("latin1"); pos += 1
    pos += 4
    ng = struct.unpack_from("<I", data, pos)[0]; pos += 4
    gt = [data[pos + 4 * i:pos + 4 * i + 4].decode("latin1") for i in range(ng)]
    pos += 4 * ng
    nc = struct.unpack_from("<I", data, pos)[0]; pos += 4
    ct = [data[pos + 4 * i:pos + 4 * i + 4].decode("latin1") for i in range(nc)]
    pos += 4 * nc
    pos = HS                       # W-1 / H-1 / 8 字节 之后就是角点区（直接用 read_header 的结果）
    rows, cols = H + 1, W + 1
    a = __import__("numpy").frombuffer(data, dtype=__import__("numpy").uint8,
                                       count=rows * cols * 7, offset=HS)
    a = a.reshape(rows, cols, 7)
    gtex = a[:, :, 4] & 0x0F
    ctex = a[:, :, 6] >> 4
    lay = a[:, :, 6] & 0x0F
    water = (a[:, :, 4] & 0x40) != 0
    print("=" * 78)
    print(f"{tag}   tileset='{tileset}'  地面贴图 {gt}")
    print(f"{'':<{len(tag)}}   悬崖贴图 {ct}")
    for name, m in (("陆地", ~water), ("水区", water)):
        if not m.any():
            print(f"  {name}: 无")
            continue
        print(f"  {name} {int(m.sum())} 角点： groundTexture={sorted(Counter(gtex[m].tolist()).items())}"
              f"  cliffTexture={sorted(Counter(ctex[m].tolist()).items())}")
        print(f"{'':<12} layer={sorted(Counter(lay[m].tolist()).items())}")


dump(os.path.join(ROOT, "out", "验收_浅滩无深水.w3x"), "我们(浅滩)")
dump(os.path.join(MAPS, "(4)LostTemple.w3m"), "官方 LostTemple")
dump(os.path.join(MAPS, "(6)SwampOfSorrows.w3m"), "官方 SwampOfSorrows")
