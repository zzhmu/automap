# -*- coding: utf-8 -*-
"""层graduate —— 单层内部最大可走坡度是多少？

背景：上一步已证实官方图里存在「整张图只有 1 个 layer 值、但 gh 跨度达 6144 原始单位」
的地图（= 1536 WE = 12 层落差，且因为全图同层所以一个悬崖都没有）。
那这类地形是不是处处可走？答案是「不一定」—— 即使没有层差（无崖），
如果相邻角点高度差太大，游戏照样可能判成不可走。

做法：拿官方图自带的 war3map.wpm（真实寻路图）当标准答案：
  对每个瓦片取四角，算出高差 dh（WE 高度单位），再看它对应的 4x4 个寻路格
  有多少是可走的（值 64）。挑出「四角同层 + 全是陆地 + 不带地图边界标记」的瓦片
  —— 这些是纯粹由连续坡度构成的，没有悬崖干扰 —— 按 dh 分桶统计可走率。

wpm 行序可能与 w3e 相反，用「水格里有没有水标记」这个独立信号来判方向。
"""
import os
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")
EXE = os.path.normpath(os.path.join(ROOT, "bin", "MPQEditor.exe"))
GROUND_ZERO = 8192
LAYER_STEP = 512


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


def find_maps():
    out = []
    for dirpath, _dirs, files in os.walk(MAPS):
        for f in files:
            if f.lower().endswith((".w3x", ".w3m")):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def main():
    maps = find_maps()
    parent = os.path.join(HERE, "ghslope_r%d" % os.getpid())
    os.makedirs(parent, exist_ok=True)

    buckets = {}          # dh 桶 -> [可走格数, 总格数]
    n_map = 0
    for idx, path in enumerate(maps):
        # ⚠️ 每张图解到自己的子目录，**绝不在循环里 os.remove** —— 单轮删多了会被
        # 环境的「批量删除确认」拦下来，脚本直接死在中途
        tmp = os.path.join(parent, "m%03d" % idx)
        try:
            for src in ("war3map.w3e", "war3map.wpm"):
                subprocess.run([EXE, "extract", path, src, tmp, "/fp"],
                               capture_output=True, timeout=120)
            pe = os.path.join(tmp, "war3map.w3e")
            pw = os.path.join(tmp, "war3map.wpm")
            if not (os.path.exists(pe) and os.path.exists(pw)):
                continue
            data = open(pe, "rb").read()
            W, H, HS = read_header(data)
            rows, cols = H + 1, W + 1
            arr = np.frombuffer(data, dtype=np.uint8, count=rows * cols * 7,
                                offset=HS).reshape(rows, cols, 7)
            gh = arr[:, :, 0].astype(np.int32) | (arr[:, :, 1].astype(np.int32) << 8)
            whf = arr[:, :, 2].astype(np.int32) | (arr[:, :, 3].astype(np.int32) << 8)
            flags = arr[:, :, 4]
            layer = (arr[:, :, 6] & 0x0F).astype(np.int16)
            # 文件自下而上存 → 翻成图像顺序（第 0 行 = 地图顶部）
            h_we = (gh - GROUND_ZERO + (layer - 2) * LAYER_STEP) / 4.0
            water = (flags & 0x40) != 0

            wdata = open(pw, "rb").read()
            if wdata[:4] != b"MP3W":
                continue
            _ver, ww, wh = struct.unpack_from("<III", wdata, 4)
            cells = np.frombuffer(wdata[16:16 + ww * wh], dtype=np.uint8).reshape(wh, ww)
            if (ww % 4) or (wh % 4) or ww // 4 != W or wh // 4 != H:
                continue
            walk = (cells == 64)
            tw, th = W, H

            # 方向判定：水面ovich grid 应该落在带水标记的瓦片上
            def agree(flip):
                lay = layer[::-1] if flip else layer
                wat = water[::-1] if flip else water
                wm = np.zeros((th, tw), bool)          # wpm 行序假设自顶向下
                for ty in range(th):
                    for tx in range(tw):
                        pass
                # 用向量化的块池化代替循环：瓦片 (ty,tx) 的 4 角是否带水
                blocks = wat[:th, :tw] | wat[:th, 1:tw + 1] | wat[1:th + 1, :tw] | wat[1:th + 1, 1:tw + 1]
                tileW = walk.reshape(th, 4, tw, 4).any(axis=(1, 3))
                return float((tileW[~blocks].mean()) - (tileW[blocks].mean()))

            flip = agree(True) >= agree(False)

            lay = layer[::-1] if flip else layer
            hw = h_we[::-1] if flip else h_we
            wat = water[::-1] if flip else water
            bnd = ((whf & 0x4000) != 0)[::-1] if flip else ((whf & 0x4000) != 0)

            n_map += 1
            for ty in range(th):
                sub_l = lay[ty:ty + 2, :]
                sub_h = hw[ty:ty + 2, :]
                sub_w = wat[ty:ty + 2, :]
                sub_b = bnd[ty:ty + 2, :]
                for tx in range(tw):
                    pass
                # 向量化：沿 tx 方向滚动取四角
                l0 = lay[ty:ty + 2, :tw]; l1 = lay[ty:ty + 2, 1:tw + 1]
                h0 = hw[ty:ty + 2, :tw]; h1 = hw[ty:ty + 2, 1:tw + 1]
                w0 = wat[ty:ty + 2, :tw]; w1 = wat[ty:ty + 2, 1:tw + 1]
                b0 = bnd[ty:ty + 2, :tw]; b1 = bnd[ty:ty + 2, 1:tw + 1]
                same = (l0[0] == l0[1]) & (l0[0] == l1[0]) & (l0[0] == l1[1])
                dry = ~(w0[0] | w0[1] | w1[0] | w1[1])
                nob = ~(b0[0] | b0[1] | b1[0] | b1[1])
                stack = np.stack([h0[0], h0[1], h1[0], h1[1]])
                dh = stack.max(axis=0) - stack.min(axis=0)
                sel = same & dry & nob
                if not sel.any():
                    continue
                blk = walk[ty * 4:(ty + 1) * 4, :].reshape(4, tw, 4)
                cnt = blk.sum(axis=(0, 2)).astype(np.float32)      # 每瓦片可走格数
                vals = dh[sel]
                cs = cnt[sel]
                for v, c in zip(vals, cs):
                    b = min(24, int(v // 8))
                    d = buckets.setdefault(b, [0.0, 0.0])
                    d[0] += float(c)
                    d[1] += 16.0
        except Exception as e:
            print("  x", os.path.basename(path), repr(e)[:80])

    print("参与统计的地图: %d 张\n" % n_map)
    print("%-16s %10s %10s" % ("瓦片内高差 dh(WE)", "瓦片数权重", "平均可走率"))
    print("-" * 42)
    total_prev = None
    for b in sorted(buckets):
        s, t = buckets[b]
        rate = s / max(1e-9, t)
        tag = ""
        if total_prev is not None and rate < total_prev * 0.75:
            tag = "   ← 开始塌陷"
        print("%-16s %10.0f %9.1f%%%s" % ("%d ~ %d" % (b * 8, b * 8 + 8), t / 16.0,
                                          rate * 100, tag))
        if total_prev is None:
            total_prev = rate
    print()
    print("读法：四角同层、无水面、无边界标记的瓦片里，随 height 差增大可走率怎么变。")
    print("若在某个 dh 之后可走率从 ~100% 掉下来，那就是游戏的「层内最大可走坡度」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
