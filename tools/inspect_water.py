# -*- coding: utf-8 -*-
"""校验生成图（或任意 .w3x/.w3m）的水体是否合法。

死条件：**任何带水标记(0x40)的角点，其世界高度都必须低于水面**，否则 WE 会把水
画穿、露出干地或破洞。水面高度不靠猜 —— 直接从 w3e 的 waterHeight 字段读
（低 14 位是水面原始高度，最高位 0x4000 是「地图边界外」标记），所以
`--layer-min` 改成多少都能自动跟上。

用法：
    python tools/inspect_water.py out/foo.w3x
    python tools/inspect_water.py out/foo.w3x --deep 1 --min-land-gap 0
"""
import os
import struct
import subprocess
import sys
import time
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

EXE = os.path.normpath(os.path.join(ROOT, "bin", "MPQEditor.exe"))
GROUND_ZERO = 8192
LAYER_STEP = 512
BOUNDARY_BIT = 0x4000
WATER_FLAG = 0x40


def force_utf8_stdout():
    """进管道/被重定向时强制 UTF-8，避免 cp936 遇到 ✔ 之类的字符直接崩。"""
    for s in (sys.stdout, sys.stderr):
        if s is None:
            continue
        if s.isatty():
            try:
                s.reconfigure(errors="replace")
            except Exception:
                pass
        else:
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def read_header(data):
    pos = 8
    pos += 1
    pos += 4
    ng = struct.unpack_from("<I", data, pos)[0]; pos += 4
    pos += 4 * ng
    nc = struct.unpack_from("<I", data, pos)[0]; pos += 4
    pos += 4 * nc
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return w, h, pos


def extract(path, tmp):
    os.makedirs(tmp, exist_ok=True)
    r = subprocess.run([EXE, "extract", path, "war3map.w3e", tmp, "/fp"],
                       capture_output=True, timeout=120)
    out = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(out):
        raise SystemExit(f"提取 war3map.w3e 失败: "
                         f"{(r.stderr or b'').decode('utf-8', 'replace')[:200]}")
    return open(out, "rb").read()


def shallow_width(is_water, cap=64):
    """每个水格到最近陆地的格数（多源 BFS，和 gen_height.shore_distance 同一算法）。

    用来还原生成器里「离岸 ≤ shelf 格 = 浅水」的判定，验证浅水岸带宽度对不对。
    """
    rows, cols = is_water.shape
    d = np.full((rows, cols), cap, dtype=np.int16)
    d[~is_water] = 0
    cur = ~is_water
    step = 0
    while cur.any() and step < cap:
        step += 1
        nxt = np.zeros_like(cur)
        nxt[1:, :] |= cur[:-1, :]
        nxt[:-1, :] |= cur[1:, :]
        nxt[:, 1:] |= cur[:, :-1]
        nxt[:, :-1] |= cur[:, 1:]
        nxt &= is_water & (d == cap)
        if not nxt.any():
            break
        d[nxt] = step
        cur = nxt
    return d


def load(path, tmp):
    data = extract(path, tmp)
    W, H, HS = read_header(data)
    rows, cols = H + 1, W + 1
    arr = np.frombuffer(data, dtype=np.uint8, count=rows * cols * 7,
                        offset=HS).reshape(rows, cols, 7)
    gh = arr[:, :, 0].astype(np.int32) | (arr[:, :, 1].astype(np.int32) << 8)
    whf = arr[:, :, 2].astype(np.int32) | (arr[:, :, 3].astype(np.int32) << 8)
    flags = arr[:, :, 4]
    layer = (arr[:, :, 6] & 0x0F).astype(np.int16)
    return dict(gh=gh, whf=whf, flags=flags, layer=layer, rows=rows, cols=cols,
                water=(flags & WATER_FLAG) != 0,
                ramp=(flags & 0x10) != 0,
                # 世界高度必须算上 layer 项：gh 只是「层内偏移」
                world=gh + (layer.astype(np.int32) - 2) * LAYER_STEP)


def main():
    force_utf8_stdout()
    argv = sys.argv[1:]
    path, opts, i = None, {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]
                i += 2
            else:
                opts[k] = "1"
                i += 1
        else:
            if path is None:
                path = a
            i += 1
    if path is None:
        print(__doc__)
        return 2
    tmp = os.path.join(HERE, "_tmp", "wchk_r%d_%d" % (os.getpid(), int(time.time() * 1000) % 100000))
    d = load(path, tmp)
    gh, whf, layer, water, world = d["gh"], d["whf"], d["layer"], d["water"], d["world"]
    cols, rows = d["cols"], d["rows"]

    # 水面：waterHeight 字段的低 14 位（0x4000 是边界位，不属于高度）
    planes = (whf & 0x3FFF).astype(np.int32)
    vals, cnt = np.unique(planes, return_counts=True)
    order = np.argsort(-cnt)
    plane = int(vals[order[0]])
    print(f"{os.path.basename(path)}  {cols}x{rows} 角点")
    print("  waterHeight 字段取值: "
          + " / ".join(f"{int(v)}×{int(c)}" for v, c in zip(vals[order[:4]], cnt[order[:4]]))
          + ("   ← 有多个不同水面！" if len(vals) > 1 else ""))
    print(f"  水面世界高度 = {plane}（WE {(plane - GROUND_ZERO) / 4:.0f}）")

    if not water.any():
        print("  没有水角点")
        return 0
    w_ly = layer[water]
    w_wd = world[water]
    depth = (plane - w_wd) / 4.0                     # WE 高度单位
    above = int((w_wd >= plane).sum())
    print(f"  水角点 {int(water.sum())}（占 {water.mean() * 100:.1f}%）")
    print(f"  ★ 水面以上或齐平的水角点（必须为 0）: {above}"
          + ("  ✔" if above == 0 else "  ✘ 水会画穿！"))
    print(f"  水深 WE 高度单位分位: p1={np.percentile(depth, 1):.1f} "
          f"p50={np.percentile(depth, 50):.1f} p99={np.percentile(depth, 99):.1f} "
          f"min={depth.min():.1f} max={depth.max():.1f}")
    print(f"  水角点 layer 分布: {Counter(w_ly.tolist()).most_common(8)}")
    for L in sorted(set(w_ly.tolist())):
        m = w_ly == L
        dd = depth[m]
        print(f"    layer {L}: n={int(m.sum()):<6} 水深 p50={np.percentile(dd, 50):7.1f} "
              f"min={dd.min():7.1f} max={dd.max():7.1f} WE")
    print("  水底起伏（同 layer 内水深 σ）: "
          + " / ".join(f"L{L}={depth[w_ly == L].std():.1f}"
                       for L in sorted(set(w_ly.tolist()))))
    n_layers = len(set(w_ly.tolist()))
    print(f"  水深档数 = {n_layers}"
          + ("（只有一种水深，深水已关闭）" if n_layers == 1 else ""))

    land = ~water
    if land.any():
        lw = world[land]
        below = int((lw < plane).sum())
        print(f"  陆地世界高度最低 = {lw.min()}（WE {(lw.min() - plane) / 4:.1f}）；"
              f"低于水面但没带水标记的陆地角点 {below}"
              f"（官方对战图普遍存在，最多能到 7 成，不是错误）")
    # 水陆过渡：浅水岸带的实际宽度（离最近陆地有几个水格）
    if land.any() and opts.get("shelf"):
        try:
            want = float(opts["shelf"])
        except ValueError:
            want = None
        if want:
            sh = shallow_width(water)
            n_water = int(water.sum())
            near = int((water & (sh > 0) & (sh <= want)).sum())   # 陆地 d=0，必须排除
            far = n_water - near
            l_max = int(max(set(w_ly.tolist())))
            n_top = int((w_ly == l_max).sum())
            print(f"  按离岸距离: ≤ {want:g} 格 {near}（{near / n_water * 100:.1f}%）"
                  f" / 之外 {far}（{far / n_water * 100:.1f}%）")
            print(f"  按层: 最浅水面层 layer {l_max} {n_top}（{n_top / n_water * 100:.1f}%）"
                  + ("  ← 全图只有一种水深" if n_top == n_water else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
