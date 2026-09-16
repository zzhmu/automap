# -*- coding: utf-8 -*-
"""把官方图的树网格渲染成 PNG，直观看看「真地图的树林」长什么样。

用法: python tools/_tmp/render_official_trees.py <地图> [...] [--out dir]
"""
import os
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402


def render(path, outdir):
    tmp = A.make_tmp("renderofficial")
    exe = A.default_exe()
    for fn in ("war3map.w3e", "war3map.doo"):
        subprocess.run([exe, "extract", path, fn, tmp, "/fp"], capture_output=True, timeout=180)
    w3e = open(os.path.join(tmp, "war3map.w3e"), "rb").read()
    _ts, W, H, HS = A.read_w3e_header(w3e)
    _v, _s, recs, _t = A.parse_doo(open(os.path.join(tmp, "war3map.doo"), "rb").read())

    ids = {}
    for r in recs:
        try:
            ids[r[:4].decode("ascii")] = ids.get(r[:4].decode("ascii"), 0) + 1
        except UnicodeDecodeError:
            pass
    tree_id = max(ids, key=ids.get) if ids else None

    tree = np.zeros((H, W), dtype=bool)
    water = np.zeros((H + 1, W + 1), dtype=bool)
    for r in recs:
        try:
            if r[:4].decode("ascii") != tree_id:
                continue
        except UnicodeDecodeError:
            continue
        x, y, _z = struct.unpack_from("<fff", r, 8)
        i = int(round((x + W * 64) / 128.0 - 0.5))
        j = int(round((y + H * 64) / 128.0 - 0.5))
        if 0 <= i < W and 0 <= j < H:
            tree[j, i] = True
    for r in range(H + 1):
        for c in range(W + 1):
            off = HS + (r * (W + 1) + c) * 7
            _gh, _whf, fb, _b5, _b6 = struct.unpack_from("<HHBBB", w3e, off)
            water[r, c] = bool(fb & 0x40)

    img = np.full((H, W, 3), (214, 205, 175), dtype=np.uint8)
    img[water[:-1, :-1]] = (70, 115, 200)          # 只看角点近似水掩码
    img[tree] = (18, 78, 18)
    name = os.path.basename(path)
    out = os.path.join(outdir, name + "_trees.png")
    Image.fromarray(img[::-1]).resize((W * 3, H * 3), Image.NEAREST).save(out)
    A.drop_tmp(tmp)
    print(f"{name}: {W}x{H} 树{int(tree.sum())} 密度{tree.sum()*100.0/(W*H):.1f}% → {out}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    outdir = HERE
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    os.makedirs(outdir, exist_ok=True)
    for p in args:
        render(p, outdir)


main()
