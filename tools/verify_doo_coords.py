# -*- coding: utf-8 -*-
"""反推 doodad 世界坐标 → 地形格子的映射（用「树应站在陆地上」做判据）。

用法: python verify_doo_coords.py <map.w3x|w3m> [--exe MPQEditor路径]
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GROUND = 8192


def default_exe():
    """定位随项目自带的 ../bin/MPQEditor.exe（不依赖外部目录）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def parse_opts(argv):
    args, opts, i = [], {}, 0
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
    return args, opts


def load(path):
    d = open(path, "rb").read()
    pos = 9
    custom = struct.unpack_from("<I", d, pos)[0]; pos += 4
    ng = struct.unpack_from("<I", d, pos)[0]; pos += 4; pos += 4 * ng
    nc = struct.unpack_from("<I", d, pos)[0]; pos += 4; pos += 4 * nc
    w = struct.unpack_from("<I", d, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", d, pos)[0] - 1; pos += 4
    ox, oy = struct.unpack_from("<ff", d, pos); pos += 8
    return d, pos, w, h, ox, oy


def main():
    args, opts = parse_opts(sys.argv[1:])
    exe = opts.get("exe") or default_exe()
    tmp = os.path.join(HERE, "_tmp", "vdoo")
    for sub in ("w3e", "doo"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=True)

    for map_path in args:
        name = os.path.basename(map_path)
        w3e_dir = os.path.join(tmp, "w3e", name)
        doo_dir = os.path.join(tmp, "doo", name)
        for d in (w3e_dir, doo_dir):
            os.makedirs(d, exist_ok=True)
        for fn, dst in (("war3map.w3e", w3e_dir), ("war3map.doo", doo_dir)):
            p = os.path.join(dst, fn)
            if os.path.exists(p):
                os.remove(p)
            subprocess.run([exe, "extract", map_path, fn, dst, "/fp"],
                           capture_output=True, timeout=180)
        w3e_p = os.path.join(w3e_dir, "war3map.w3e")
        doo_p = os.path.join(doo_dir, "war3map.doo")
        if not (os.path.exists(w3e_p) and os.path.exists(doo_p)):
            print(f"{name}: 缺文件，跳过")
            continue

        d, HS, w, h, ox, oy = load(w3e_p)
        cols, rows = w + 1, h + 1
        water = [[False] * cols for _ in range(rows)]
        layer = [[0] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                off = HS + (r * cols + c) * 7
                gh, whf, fb, b5, b6 = struct.unpack_from("<HHBBB", d, off)
                water[r][c] = bool(fb & 0x40)
                layer[r][c] = b6 & 0x0F

        dd = open(doo_p, "rb").read()
        ver, sub, cnt = struct.unpack_from("<III", dd, 4)
        print(f"\n=== {name}: {w}x{h}  offset=({ox},{oy})  doo v{ver}.{sub} 条数={cnt}")

        cands = {
            "A=-W*128/2": -w * 64,
            "A=-(W-1)*128/2": -(w - 1) * 64,
            "A=-W*128/2+64": -w * 64 + 64,
            "A=header": ox,
        }
        for label, A in cands.items():
            land = wat = out = 0
            for i in range(cnt):
                o = 16 + i * 42
                x, y = struct.unpack_from("<ff", dd, o + 8)
                ci = int(round((x - A) / 128.0))
                cj = int(round((y - A) / 128.0))
                if not (0 <= ci < cols and 0 <= cj < rows):
                    out += 1; continue
                r = rows - 1 - cj
                if water[r][ci]:
                    wat += 1
                else:
                    land += 1
            tot = max(1, land + wat + out)
            print(f"  {label:16s} A={A:9.1f}  陆地 {land:5d} ({100*land/tot:5.1f}%)  "
                  f"水 {wat:5d} ({100*wat/tot:4.1f}%)  越界 {out:5d} ({100*out/tot:4.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
