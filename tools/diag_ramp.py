# -*- coding: utf-8 -*-
"""逆向 WC3 悬崖/斜坡在 w3e 里的精确编码 —— 只看官方地图，不从我们的生成图猜。

背景：我们能算出「哪两个台地该连通」，也把 ramp 位(0x10)铺上去了，
但 WE 里就是不出现斜坡。所以问题一定在**编码细节**上，不在连通算法上。

用法: python diag_ramp.py <map.w3m|w3x> [<map2> ...] [--exe 路径] [--window N]

输出：
  1. 悬崖瓦片总数 / 其中带 ramp 位的数量
  2. 悬崖瓦片「四角层位组合」的分布（normal vs ramp 分开统计）
  3. ramp 瓦片里，四角的 cliffTexture / cliffVariation / groundTexture / ramp位 的取值分布
  4. 若给 --window，打印若干 ramp 瓦片及其外围一圈的角点明细
"""
import os
import struct
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))

FLAG_RAMP = 0x10
FLAG_BLIGHT = 0x20
FLAG_WATER = 0x40
FLAG_BOUNDARY2 = 0x80


def default_exe():
    p = os.path.join(ROOT, "bin", "MPQEditor.exe")
    return p if os.path.exists(p) else "MPQEditor.exe"


def read_header(data):
    pos = 8
    tileset = chr(data[pos]); pos += 1
    custom = struct.unpack_from("<I", data, pos)[0]; pos += 4
    n = struct.unpack_from("<I", data, pos)[0]; pos += 4
    ground = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace")
              for i in range(n)]; pos += 4 * n
    m = struct.unpack_from("<I", data, pos)[0]; pos += 4
    cliff = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace")
             for i in range(m)]; pos += 4 * m
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return {"tileset": tileset, "ground": ground, "cliff": cliff,
            "W": w, "H": h, "HS": pos}


def load_corners(data):
    """返回逐角点字段的 numpy-free 列表：row-major，(rows, cols)。"""
    info = read_header(data)
    rows, cols = info["H"] + 1, info["W"] + 1
    C = []
    for cy in range(rows):
        row = []
        for cx in range(cols):
            off = info["HS"] + (cy * cols + cx) * 7
            gh, wh, fb, gvcv, ctlh = struct.unpack_from("<HHBBB", data, off)
            row.append({
                "gh": gh,
                "boundary1": bool(wh & 0x4000),
                "water_h": wh & 0x3FFF,
                "flags": fb >> 4,          # 高 4 位是标志
                "ramp": bool(fb & FLAG_RAMP),
                "blight": bool(fb & FLAG_BLIGHT),
                "water": bool(fb & FLAG_WATER),
                "boundary2": bool(fb & FLAG_BOUNDARY2),
                "tex": fb & 0x0F,           # groundTexture
                "gvar": gvcv >> 3,          # groundVariation 5bit
                "cvar": gvcv & 0x07,        # cliffVariation 3bit
                "ctex": ctlh >> 4,          # cliffTexture 4bit
                "layer": ctlh & 0x0F,       # layerHeight 4bit
            })
        C.append(row)
    return info, C


def tile(C, cx, cy):
    """返回瓦片 (cx,cy) 的四角，顺序 [左下, 右下, 左上, 右上]。"""
    return C[cy][cx], C[cy][cx + 1], C[cy + 1][cx], C[cy + 1][cx + 1]


def analyze(map_path, exe, window=0):
    tmp = os.path.join(HERE, "_tmp", "ramp")
    os.makedirs(tmp, exist_ok=True)
    p = os.path.join(tmp, "war3map.w3e")
    if os.path.exists(p):
        os.remove(p)
    subprocess.run([exe, "extract", map_path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=180)
    if not os.path.exists(p):
        print(f"{map_path}: 提取失败"); return
    data = open(p, "rb").read()
    info, C = load_corners(data)
    W, H = info["W"], info["H"]
    print(f"\n===== {os.path.basename(map_path)}  {W}x{H}  "
          f"tileset={info['tileset']}  cliff={info['cliff']} =====")

    normal, ramp = [], []
    for cy in range(H):
        for cx in range(W):
            q = tile(C, cx, cy)
            ls = [c["layer"] for c in q]
            if max(ls) == min(ls):
                continue                      # 平地瓦片
            if any(c["ramp"] for c in q):
                ramp.append((cx, cy, q))
            else:
                normal.append((cx, cy, q))

    print(f"悬崖瓦片（四角层位不全等）: {len(normal) + len(ramp)} 块"
          f"  → 普通崖壁 {len(normal)} / 带 ramp 位 {len(ramp)}")

    def pat(q):
        """把四角层位压成一个可读的模式串（左下 右下 / 左上 右上）。"""
        return f"{q[2]['layer']}{q[3]['layer']}/{q[0]['layer']}{q[1]['layer']}"

    print(f"\n【普通崖壁】四角层位模式 top12: "
          f"{Counter(pat(q) for _, _, q in normal).most_common(12)}")
    print(f"【普通崖壁】四角 cliffTexture top8: "
          f"{Counter(tuple(c['ctex'] for c in q) for _, _, q in normal).most_common(8)}")
    print(f"【普通崖壁】四角 cliffVariation top8: "
          f"{Counter(tuple(c['cvar'] for c in q) for _, _, q in normal).most_common(8)}")
    print(f"【普通崖壁】四角 groundTexture top8: "
          f"{Counter(tuple(c['tex'] for c in q) for _, _, q in normal).most_common(8)}")

    if ramp:
        print(f"\n【斜坡】四角层位模式 top12: "
              f"{Counter(pat(q) for _, _, q in ramp).most_common(12)}")
        print(f"【斜坡】四角 cliffTexture top8: "
              f"{Counter(tuple(c['ctex'] for c in q) for _, _, q in ramp).most_common(8)}")
        print(f"【斜坡】四角 cliffVariation top8: "
              f"{Counter(tuple(c['cvar'] for c in q) for _, _, q in ramp).most_common(8)}")
        print(f"【斜坡】四角 groundTexture top8: "
              f"{Counter(tuple(c['tex'] for c in q) for _, _, q in ramp).most_common(8)}")
        n_ramp_corner = Counter(sum(1 for c in q if c["ramp"]) for _, _, q in ramp)
        print(f"【斜坡】每块瓦片里带 ramp 位的角点数分布: {dict(sorted(n_ramp_corner.items()))}")
        # ramp 位到底落在低的一侧还是高的一侧？
        low_side = high_side = mixed = 0
        for _, _, q in ramp:
            ls = [c["layer"] for c in q]
            lo, hi = min(ls), max(ls)
            flags = [c["ramp"] for c in q]
            lows = [flags[k] for k in range(4) if ls[k] == lo]
            highs = [flags[k] for k in range(4) if ls[k] == hi]
            if all(lows) and not any(highs):
                low_side += 1
            elif all(highs) and not any(lows):
                high_side += 1
            else:
                mixed += 1
        print(f"【斜坡】ramp 位位置: 全在低侧 {low_side} / 全在高侧 {high_side} / 混合 {mixed}")
        # ramp 瓦片的层差
        print(f"【斜坡】层差分布: "
              f"{Counter(max(c['layer'] for c in q) - min(c['layer'] for c in q) for _, _, q in ramp)}")

    if window:
        print(f"\n---- {min(window, len(ramp))} 块 ramp 瓦片的邻域明细 ----")
        for cx, cy, q in ramp[:window]:
            print(f"\n  瓦片 ({cx},{cy})  层位模式 {pat(q)}")
            for dy in (2, 1, 0, -1):
                cyy = cy + dy
                if not (0 <= cyy <= H):
                    continue
                line = []
                for dx in (-1, 0, 1, 2):
                    cxx = cx + dx
                    if not (0 <= cxx <= W):
                        line.append(" " * 22)
                        continue
                    c = C[cyy][cxx]
                    mark = "*" if (dx in (0, 1) and dy in (0, 1)) else " "
                    line.append(f"{mark}L{c['layer']}ct{c['ctex']}cv{c['cvar']}"
                                f"t{c['tex']}{'R' if c['ramp'] else '-'}")
                print("   " + " ".join(line))


def main():
    args, opts, i = [], {}, 0
    argv = sys.argv[1:]
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k, sep, v = a[2:].partition("=")
            if sep:
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]; i += 1
            else:
                opts[k] = True
        else:
            args.append(a)
        i += 1
    if not args:
        print(__doc__); return 1
    exe = opts.get("exe") or default_exe()
    win = int(opts.get("window", 0) or 0)
    for a in args:
        analyze(a, exe, win)
    return 0


if __name__ == "__main__":
    sys.exit(main())
