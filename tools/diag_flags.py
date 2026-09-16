# -*- coding: utf-8 -*-
"""用 war3map.wpm（寻路图）反推 w3e 里 0x40 / 0x80 / 0x4000 三个位的真实语义。

做法：wpm 是 4 倍分辨率的地面可走性真值，把它降采样到 w3e 的角点/瓦片网格，
再看每一类「位组合」对应的可走比例 —— 可走比例高的位组合就代表可行走。
"""
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def default_exe():
    p = os.path.normpath(os.path.join(HERE, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def read_header(data):
    pos = 8
    pos += 1
    pos += 4
    n_ground = struct.unpack_from("<I", data, pos)[0]; pos += 4 + 4 * n_ground
    n_cliff = struct.unpack_from("<I", data, pos)[0]; pos += 4 + 4 * n_cliff
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return w, h, pos


def load_w3e(path, tmp):
    subprocess.run([default_exe(), "extract", path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=120)
    f = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(f):
        return None
    data = open(f, "rb").read()
    W, H, HS = read_header(data)
    rows, cols = H + 1, W + 1
    corner = np.zeros((rows, cols, 5), dtype=np.int32)
    for cy in range(rows):
        for cx in range(cols):
            off = HS + (cy * cols + cx) * 7
            gh, whf, fb, gv_cv, ct_lh = struct.unpack_from("<HHBBB", data, off)
            corner[cy, cx] = (gh, whf, fb, gv_cv, ct_lh)
    return corner, rows, cols


def load_wpm(path, tmp):
    subprocess.run([default_exe(), "extract", path, "war3map.wpm", tmp, "/fp"],
                   capture_output=True, timeout=120)
    f = os.path.join(tmp, "war3map.wpm")
    if not os.path.exists(f):
        return None
    data = open(f, "rb").read()
    assert data[:4] == b"MP3W", data[:4]
    ver, w, h = struct.unpack_from("<III", data, 4)
    cells = np.frombuffer(data[16:16 + w * h], dtype=np.uint8).reshape(h, w)
    return cells, ver


def tile_cells(block, lab, rows, cols, fy, fx):
    """把 wpm 的 4x4 格按**瓦片**归拢：第 i 行 = 第 i 个 True 瓦片自己的 fy*fx 个格。

    ⚠️ 别写成 block.reshape(-1, fy*fx)[lab.ravel()] —— 那个 reshape 是按内存顺序切块
    （同一瓦片行里连续 fx 列会被切进同一块），和 lab.ravel() 的瓦片顺序对不上，会静默
    错位、把结论变成噪声。必须先 transpose(0,2,1,3) 让「瓦片」成为第一维。
    """
    t = block.transpose(0, 2, 1, 3).reshape(rows - 1, cols - 1, fy * fx)
    return t[lab].reshape(-1)


def main():
    path = sys.argv[1]
    tmp = os.path.join(HERE, "_tmp", "diagflags")
    os.makedirs(tmp, exist_ok=True)
    got = load_w3e(path, tmp)
    if got is None:
        print("w3e 提取失败")
        return 1
    corner, rows, cols = got
    gotw = load_wpm(path, tmp)
    if gotw is None:
        print("wpm 提取失败")
        return 1
    cells, ver = gotw
    ch, cw = cells.shape
    print(f"{os.path.basename(path)}: 角点 {cols}x{rows}  wpm {cw}x{ch} (v{ver})  "
          f"比例 {cw / (cols - 1):.2f}")
    print(f"wpm 取值直方图: {dict(zip(*[x.tolist() for x in np.unique(cells, return_counts=True)]))}")

    fy, fx = ch // (rows - 1), cw // (cols - 1)
    block = cells[:fy * (rows - 1), :fx * (cols - 1)].reshape(rows - 1, fy, cols - 1, fx)

    whf = corner[:, :, 1]
    fb = corner[:, :, 2]
    b1 = (whf & 0x4000) != 0
    water = (fb & 0x40) != 0
    b2 = (fb & 0x80) != 0
    ramp = (fb & 0x10) != 0
    layer = corner[:, :, 4] & 0x0F

    def spread_of(m):
        return m[:-1, :-1] | m[:-1, 1:] | m[1:, :-1] | m[1:, 1:]

    def allc(m):
        return m[:-1, :-1] & m[:-1, 1:] & m[1:, :-1] & m[1:, 1:]

    t_water = spread_of(water)
    t_ramp = allc(ramp)

    a = corner[:-1, :-1, 4] & 0x0F
    b = corner[:-1, 1:, 4] & 0x0F
    c_ = corner[1:, :-1, 4] & 0x0F
    d = corner[1:, 1:, 4] & 0x0F
    is_flat = (a == b) & (a == c_) & (a == d)

    # 地形推出的真值：四角同层且非水，或者四角都是斜坡
    terra_walk = (is_flat & ~t_water) | t_ramp
    for name, lab in (("地形判定可走", terra_walk), ("地形判定不可走", ~terra_walk)):
        vals = tile_cells(block, lab, rows, cols, fy, fx)
        cnt = np.bincount(vals, minlength=256)
        top = sorted(((int(v), int(n)) for v, n in enumerate(cnt) if n),
                     key=lambda x: -x[1])[:6]
        print(f"\n{name}（{int(lab.sum())} 瓦片）的 wpm 取值分布 top6:")
        for v, n in top:
            print(f"   值 {v:>3} (0x{v:02X})  {n:>7} 格  "
                  f"{100.0 * n / max(1, vals.size):>5.1f}%")
    _ = (b1, b2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
