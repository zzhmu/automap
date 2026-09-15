# -*- coding: utf-8 -*-
"""地图验收工具：把生成的 w3x 里的 war3map.w3e / war3map.doo 完整解析一遍，
自检「解析到文件尾零误差」，并把 doodad 的 z 与地形高度对账。

用法: python verify_map.py <map.w3x> [--exe MPQEditor路径] [--show 20]
"""
import os
import struct
import subprocess
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

GROUND_ZERO = 8192
LAYER_ZERO = 2
LAYER_STEP = 512


def default_exe():
    p = os.path.normpath(os.path.join(HERE, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def extract(exe, map_path, name, tmp):
    out = os.path.join(tmp, name)
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([exe, "extract", map_path, name, tmp, "/fp"],
                   capture_output=True, timeout=180)
    return out if os.path.exists(out) else None


def read_w3e_header(data):
    pos = 8
    pos += 1                      # tileset 字符
    pos += 4                      # custom tileset flag
    n = struct.unpack_from("<I", data, pos)[0]; pos += 4 + 4 * n   # ground 贴图表
    n = struct.unpack_from("<I", data, pos)[0]; pos += 4 + 4 * n   # cliff 贴图表
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8                      # 地图偏移 x/y
    return w, h, pos


def load_terrain(path):
    data = open(path, "rb").read()
    if data[:4] != b"W3E!":
        return None
    ver = struct.unpack_from("<I", data, 4)[0]
    W, H, HS = read_w3e_header(data)
    rows, cols = H + 1, W + 1
    per = (len(data) - HS) // (rows * cols)
    rest = (len(data) - HS) - per * rows * cols
    corner = np.zeros((rows, cols, 5), dtype=np.int32)
    flags_cnt = Counter()
    for cy in range(rows):
        for cx in range(cols):
            off = HS + (cy * cols + cx) * per
            gh, whf, fb, gv_cv, ct_lh = struct.unpack_from("<HHBBB", data, off)
            corner[cy, cx] = (gh, whf, fb, gv_cv, ct_lh)
            flags_cnt[(fb >> 4) & 0x0F] += 1
    return {"ver": ver, "W": W, "H": H, "rows": rows, "cols": cols,
            "per": per, "rest": rest, "corner": corner, "flags": flags_cnt}


def verify_terrain(t, show=0):
    print(f"war3map.w3e  v{t['ver']}  {t['W']}x{t['H']}  角点 {t['cols']}x{t['rows']}  "
          f"{t['per']} 字节/角点  尾部残留 {t['rest']} 字节")
    if t["per"] != 7:
        print("  ⚠ 本工具按 v11（7 字节）解析，其他版本结果不可信")
    ok = t["rest"] == 0
    print(f"  {'✔' if ok else '✘'} 解析到文件尾零误差")
    c = t["corner"]
    layer = c[:, :, 4] & 0x0F
    print(f"  层号分布: {dict(sorted(Counter(layer.ravel().tolist()).items()))}")
    fb = c[:, :, 2]
    print(f"  ramp {int(((fb >> 4) & 1).sum())} 角点 | "
          f"blight {int(((fb >> 5) & 1).sum())} | water {int((fb & 0x40 > 0).sum())} | "
          f"boundary2 {int(((fb >> 7) & 1).sum())}")
    b1 = int(((c[:, :, 1] & 0x4000) > 0).sum())
    print(f"  boundary1 {b1} 角点（最外一圈应为 {2 * t['cols'] + 2 * (t['rows'] - 2)}）")
    a = layer[:, :-1].astype(np.int16); b = layer[:, 1:]
    d1 = np.abs(a - b)
    vert = np.abs(layer[:-1, :] - layer[1:, :])
    print(f"  相邻角点层差: 水平 max {int(d1.max())}（>1 占 {100.0 * (d1 > 1).mean():.2f}%） "
          f"垂直 max {int(vert.max())}（>1 占 {100.0 * (vert > 1).mean():.2f}%）")
    return t


def we_height(t, cy, cx):
    gh = t["corner"][cy, cx, 0]
    ly = t["corner"][cy, cx, 4] & 0x0F
    return (gh - GROUND_ZERO + (ly - LAYER_ZERO) * LAYER_STEP) / 4.0


def verify_doo(path, t, show=0):
    data = open(path, "rb").read()
    magic, ver, sub, count = struct.unpack_from("<4sIII", data, 0)
    print(f"\nwar3map.doo  magic={magic!r} v{ver}.{sub}  记录数 {count}  "
          f"文件 {len(data)} 字节")
    REC = 42
    head, tail = 16, 8
    expect = head + count * REC + tail
    ok = len(data) == expect
    print(f"  {'✔' if ok else '✘'} 定长 {REC} 字节/条 + {tail} 字节尾部: "
          f"期望 {expect} / 实际 {len(data)}")

    ids = Counter()
    dz = []
    W, H = t["W"], t["H"]
    for k in range(count):
        off = head + k * REC
        oid = data[off:off + 4].decode("ascii", "replace")
        # 记录布局: id(4) variation(4) x,y,z(12) rotation(4) scale*3(12) flags(1) life(1) itemTable(4)
        (var, x, y, z, rot, sx, sy, sz, fl, life, item
         ) = struct.unpack_from("<I4f3fBBI", data, off + 4)
        ids[oid] += 1
        # 世界坐标 → 瓦片坐标（j 自下而上）
        fx = (x + W * 64.0) / 128.0 - 0.5
        fy = (y + H * 64.0) / 128.0 - 0.5
        i0, j0 = int(np.floor(fx)), int(np.floor(fy))
        if 0 <= i0 < t["cols"] - 1 and 0 <= j0 < t["rows"] - 1:
            zc = (we_height(t, j0, i0) + we_height(t, j0, i0 + 1)
                  + we_height(t, j0 + 1, i0) + we_height(t, j0 + 1, i0 + 1)) / 4.0
            dz.append(abs(z - zc))
    tail_bytes = data[head + count * REC:]
    print(f"  尾部 {tail} 字节: {tail_bytes.hex()}")
    print(f"  物件类型: {dict(ids.most_common(8))}")
    if dz:
        dz = np.array(dz)
        print(f"  高度对账: 平均误差 {dz.mean():.3f} 单位  最大 {dz.max():.3f}  "
              f"（>1 的有 {int((dz > 1).sum())} 个）")
    if show and show > 0:
        print("  前几条明细:")
        for k in range(min(show, count)):
            off = head + k * REC
            oid = data[off:off + 4].decode("ascii", "replace")
            var, x, y, z, rot = struct.unpack_from("<I4f", data, off + 4)
            print(f"    {oid} var={var} pos=({x:.0f},{y:.0f}) z={z:.2f} rot={rot:.2f}")
    return ok


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
        print(__doc__)
        return 1
    map_path = args[0]
    exe = opts.get("exe") or default_exe()
    show = int(opts.get("show", 0))
    tmp = os.path.join(HERE, "_tmp", "verify")
    os.makedirs(tmp, exist_ok=True)

    print(f"===== {os.path.basename(map_path)} =====")
    w3e = extract(exe, map_path, "war3map.w3e", tmp)
    if not w3e:
        print("war3map.w3e 提取失败")
        return 2
    t = load_terrain(w3e)
    verify_terrain(t)

    doo = extract(exe, map_path, "war3map.doo", tmp)
    if doo:
        verify_doo(doo, t, show=show)
    else:
        print("\n（无 war3map.doo）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
