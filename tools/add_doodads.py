# -*- coding: utf-8 -*-
"""在地图上按算法撒树（写 war3map.doo）。

已验证的格式与约定（实测反推，见 verify_doo_coords.py）:
  war3map.doo: "W3do" + int version(7) + int sub(9) + int count
               每条 42 字节:
                 char[4] 类型ID | int variation | float x,y,z | float angle
                 float scaleX,Y,Z | u8 flags | u8 life | int editorId
               文件末尾 8 字节（实测为 0）
  世界坐标: 瓦片中心 x = (i + 0.5)*128 - W*64      (W = 横向瓦片数)
            地面 z = 该格四角最终高度均值
            最终高度 = (groundHeight - 8192 + (layer - 2)*512) / 4
  校验: Harrow 官方地图 1640 棵树 z 与四角高度均值误差 0.00

用法:
  python add_doodads.py <map.w3x> [选项]
选项:
  --seed 7            随机种子
  --density 0.18      总体树木密度（占可用格子的比例）
  --slope-tol 1       允许的最大层差（1 = 可种在缓坡上）
  --freq 2.2          内部森林场尺度：越小森林区越大块
  --edge-forest 0.55  边界林带权重（官方图的树大半贴边/岸线/崖脚成带）
  --edge-band 14      边界林带宽度（格）
  --forest-share 0.32 大林（成片林）吃掉多少比例的树
  --forest-size 170   单块大林的中位格数（实际尺寸对数正态抖动）
  --clump-size 11     小林丛的中位株数（尺寸对数正态抖动）
  --clump-radius 3.0  中位丛的半径（格）；更大的丛半径按 sqrt(株数) 等比放大
  --clump-gap 1.5     丛与丛之间的最小空隙（格）
  --clump-bias 0.55   丛心有多偏向森林场高的地方（0 = 纯随机，1 = 纯按森林场）
  --scatter 0.035     零星散树比例（优先落在森林场低的空旷地）
  --scatter-size 1.5  散树每团的中位株数；**1 = 一粒一粒单点撒（胡椒点）**，1.5~2.5 才自然
  --tree-id WTst      强制树类型；默认从模板地图现有物件里自动学
  --keep              保留原有物件（默认清空后重新生成）
  --out <路径>        另存为新地图
  --no-backup         跳过备份（调用方自己已复制过模板时用，避免堆积无用 .bak）
  --preview p.png     输出撒树预览图（浅绿=森林区，深绿=实际种树）

撒树分三层，复刻官方 1.27a 对战图的「重尾」结构（实测 43 张图的 p50 目标见
doc/三步地形生成方案.md）：①**大林**（少数几块、尺寸重尾、顺森林场拉长的连片，
吃掉约 1/3 的树）②**小林丛**（大量小块，株数对数正态、椭圆+噪边，不是等大圆斑）
③**散株**（优先落空旷地，且**成小团**撒）。株数不够时只沿现有林缘外扩，
**绝不随机撒孤立单株**。
判定用 forest_metrics()：连片块数 / 最大块 / 孤立单株占比 / 块数-树数比
＋「胡椒点」三项（iso8 / iso2 / 距大林格距）——**全项目只有这一份指标实现**，
GUI、仿真、官方基准脚本都调它，避免各写一份各错一套（踩过）。
"""
import heapq
import os
import shutil
import struct
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime

import numpy as np
from PIL import Image


def force_utf8_stdout():
    """管道/重定向时把标准输出统一成 UTF-8；直接开在控制台时保留控制台编码。

    理由同 gen_height.py：中文子进程若按 cp936 输出而父进程按别的编码解码会炸，
    且 ✔ ✘ 不在 GBK 里，cp936 下 print 本身就 UnicodeEncodeError。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            if s.isatty():
                s.reconfigure(errors="replace")
            else:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


force_utf8_stdout()

HERE = os.path.dirname(os.path.abspath(__file__))

GROUND_ZERO = 8192
LAYER_STEP = 512
LAYER_ZERO = 2
TILE = 128
DOO_TAIL = b"\x00" * 8

# 各 tileset 的常见树（仅作模板地图里学不到时的兜底；L/A/B/C/F/N/W/Y 照官方图实测
# —— N 图用 WTst 雪松、W 图用 WTtw，见 tools/_tmp/tileset_map_stats.py）
FALLBACK_TREES = {
    "L": "LTlt", "A": "ATtr", "B": "BTtw", "N": "WTst", "W": "WTtw",
    "C": "CTtr", "F": "FTtw", "Y": "LTlt",
    "V": "VTlt", "X": "XTlt", "D": "DTsh",
    "I": "ITtw", "Z": "ZTtw", "G": "GTsh",
}


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


def value_noise(nprng, shape, cells):
    rows, cols = shape
    gw = gh = max(2, int(cells) + 1)
    grid = nprng.random((gh, gw), dtype=np.float32)
    ys = np.linspace(0, gh - 1, rows, dtype=np.float32)
    xs = np.linspace(0, gw - 1, cols, dtype=np.float32)
    y0 = np.floor(ys).astype(int); y1 = np.clip(y0 + 1, 0, gh - 1)
    x0 = np.floor(xs).astype(int); x1 = np.clip(x0 + 1, 0, gw - 1)
    wy = (ys - y0)[:, None]; wx = (xs - x0)[None, :]
    top = grid[y0][:, x0] * (1 - wx) + grid[y0][:, x1] * wx
    bot = grid[y1][:, x0] * (1 - wx) + grid[y1][:, x1] * wx
    return top * (1 - wy) + bot * wy


def fbm(nprng, shape, freq, octaves=4, gain=0.5, lacunarity=2.0):
    out = np.zeros(shape, dtype=np.float32)
    amp, norm, f = 1.0, 0.0, freq
    for _ in range(octaves):
        out += amp * value_noise(nprng, shape, f)
        norm += amp
        amp *= gain
        f *= lacunarity
    return out / norm


def norm01(a):
    lo, hi = float(a.min()), float(a.max())
    return (a - lo) / max(1e-6, hi - lo)


def dist_transform(mask, maxd=64):
    """到 mask 边界的近似「8 邻接」距离（格）。

    mask=True 是可用区；返回的场在边界处 =1，往里逐渐变大（封顶 maxd）。
    用迭代膨胀实现（不引 scipy）：每轮把已覆盖区向 8 邻域扩一圈。
    """
    d = np.zeros(mask.shape, dtype=np.float32)
    cur = mask.copy()
    if not cur.any():
        return d
    d[cur] = maxd
    dist = 1
    offs = ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1))
    while dist <= maxd and cur.any():
        nb = np.zeros_like(cur)
        for dy, dx in offs:
            nb |= np.roll(np.roll(~cur, dy, 0), dx, 1)
        new = cur & nb
        if not new.any():
            break
        d[new] = dist
        cur &= ~new
        dist += 1
    return d


def build_forest_field(nprng, elig, freq, edge_forest=0.55, edge_band=14.0):
    """合成「森林场」：决定哪里像森林（只当权重用，不直接切阈值）。

    两块叠加：
      * 内部森林场 = 低频 fBm → 大尺度上哪片区域是林地
      * 边界林带   = exp(-到不可种区的距离/带宽) × 沿边噪声
        官方对战图的树大半贴在「地图边 / 岸线 / 崖脚」形成粗林带；沿边噪声是必须的，
        否则整圈林带会连成一个巨型块（实测最大连片块飙到 1000+，官方 p50 只有 205）。
    """
    fbm_field = norm01(fbm(nprng, elig.shape, freq, octaves=3))
    if edge_forest <= 0.0:
        return fbm_field
    d_border = dist_transform(elig, maxd=int(edge_band * 3) + 4)
    band = np.exp(-d_border / edge_band)
    band_noise = fbm(nprng, elig.shape, max(1.0, freq * 2.2), octaves=2)
    band = band * (0.40 + 0.75 * norm01(band_noise))
    return norm01(edge_forest * band + (1.0 - edge_forest) * fbm_field)


def build_fine_field(nprng, shape, freq):
    """细尺度噪声场（约 6~20 格尺度）：给区域生长当「代价抖动」。

    没有它，均匀场上的 Dijkstra 生长是完美菱形（L1 测地球），一眼就是程序生成。
    有了它，等代价线被打毛 → 大林边界参差、有岬角和内凹。
    """
    return norm01(fbm(nprng, shape, max(3.0, freq * 6.0), octaves=2))


def grow_region(nprng, elig, taken, si, sj, size, field=None, field_w=0.55,
                fine=None, fine_amp=3.0, roughness=0.45):
    """加权最短路区域生长：从 (si,sj) 长出一块 size 格的不规则连片。

    **不能只在局部「择优邻居」**：那样块会顺着森林场的高值脊线一路爬出去，
    在边界林带上长成一条长蛇，几个林核会串成一坨 1000+ 格的巨型块（实测）。
    改成堆式 Dijkstra：每个格子的代价 = 到种子的最短路径长度，边权 = 1
    × [1 + 1.6×(1-森林场)] × [1 + fine_amp×(细噪声-0.5)] × (1 + roughness×随机)。

    三个乘子的分工：大尺度森林场决定「往哪边扩」，细噪声把等代价线打毛（否则在
    均匀场上长出来是完美菱形 —— L1 测地球，一眼假），逐边随机再加一层颗粒感。
    返回实际长出格数（饿死在既有林/水/崖边时可能少于 size）。
    """
    W, H = elig.shape
    if not (0 <= si < W and 0 <= sj < H) or not elig[si, sj] or taken[si, sj]:
        return 0
    cost = np.full((W, H), np.inf, dtype=np.float64)
    cost[si, sj] = 0.0
    taken[si, sj] = True
    heap = [(0.0, si, sj)]
    n = 1
    DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0))
    while heap and n < size:
        c, i, j = heapq.heappop(heap)
        if c > cost[i, j] or (taken[i, j] and (i, j) != (si, sj)):
            continue
        for di, dj in DIRS:
            ni, nj = i + di, j + dj
            if not (0 <= ni < W and 0 <= nj < H) or not elig[ni, nj] or taken[ni, nj]:
                continue
            step = 1.0
            if field is not None:
                step *= 1.0 + 1.6 * (1.0 - float(field[ni, nj]))
            if fine is not None:
                step *= 1.0 + fine_amp * (float(fine[ni, nj]) - 0.5)
            if roughness > 0:
                step *= 1.0 + roughness * float(nprng.random())
            nc = c + max(0.05, step)
            if nc < cost[ni, nj]:
                cost[ni, nj] = nc
                heapq.heappush(heap, (nc, ni, nj))
        # 弹出即落子（第一次弹出就是最短路，之后同格的更大代价会被跳过）
        if (i, j) != (si, sj):
            taken[i, j] = True
            n += 1
    return n


def place_forests(nprng, elig, taken, n_tree, med_size, field, fine=None,
                 min_gap=2.2, sigma=0.5):
    """撒「大林」——树景的骨架。

    官方 1.27a 对战图实测：中位每张图有 4 块 ≥100 格的连片大林、吃掉约 33% 的树，
    最大块中位 205 格、长宽比中位 1.41（明显不是圆的）。所以大林必须
    (a) 数量少、(b) 尺寸重尾（有的 80 格、有的 400 格）、(c) 形状顺场拉长。
    做法：按「森林场² × 随机」排序挑林核（高场区优先），核间留出**与最大可能尺寸
    匹配**的间距（用中位尺寸算会把核放太近，长完就粘成一块巨型块 —— 实测能到 900+，
    官方 p50 只有 205），每个核用 grow_region 长成 med_size×lognormal 那么大的连片。
    返回 (核数, 实际种下株数)。
    """
    W, H = elig.shape
    if n_tree <= 0 or not elig.any():
        return 0, 0
    mean_size = med_size * float(np.exp(sigma * sigma / 2.0))
    max_clump = med_size * 2.2
    max_cores = max(1, int(round(n_tree / max(1.0, mean_size))))
    ei, ej = np.nonzero(elig)
    score = nprng.random(len(ei)).astype(np.float32)
    if field is not None:
        # 平方偏置：只在森林场最高的一片里出林核，不是全图均匀撒
        score = (field[ei, ej] ** 2.0) * (0.15 + 0.85 * score)
    order = np.argsort(-score)
    # 核间最小间距：按「单个核可能长到的最大半径」的 2 倍留白，否则长完会粘成一坨巨块
    sep = max(4.0, min_gap * 2.0 * float(np.sqrt(max_clump / np.pi)))
    # 离地图边的余量只看单个核的半径（**不能拿 sep 当边距** —— 128 的图里 sep 可能
    # 大到把整张图都算成"贴边"，结果一个核都放不下）
    ri = int(np.ceil(np.sqrt(max_clump / np.pi))) + 2
    cores = []
    placed, budget = 0, n_tree
    for k in order:
        if len(cores) >= max_cores or budget <= 0:
            break
        ci, cj = int(ei[k]), int(ej[k])
        if taken[ci, cj]:
            continue
        if ci < ri or cj < ri or ci >= W - ri or cj >= H - ri:
            continue
        if any((a - ci) ** 2 + (b - cj) ** 2 < sep * sep for a, b in cores):
            continue
        sz = int(round(med_size * float(np.exp(nprng.normal(0.0, sigma)))))
        sz = int(min(max(sz, 6), budget, max_clump))
        got = grow_region(nprng, elig, taken, ci, cj, sz, field=field, fine=fine)
        if got:
            cores.append((ci, cj))
            placed += got
            budget -= got
    return len(cores), placed


def _ellipse_drop(ci, cj, x0, x1, y0, y1, ang, ecc, rad, noise, nprng):
    """在窗口 [x0:x1, y0:y1] 上算「椭圆距离」与「椭圆距离+噪声」两个场。

    坐标系约定（**全项目统一**）：`np.mgrid[x0:x1, y0:y1][0]` 是 x 坐标、沿轴 0 变化；
    形状 (ni, nj) 与 `elig[x0:x1, y0:y1]` 完全一致。窗口切片一律写 [x 范围, y 范围]，
    一旦某个窗口反着写（如 mgrid[y范围, x范围]）就会得到转置的掩码、圈错地方。
    """
    xs, ys = np.mgrid[x0:x1, y0:y1]
    dx = (xs - ci).astype(np.float32)
    dy = (ys - cj).astype(np.float32)
    ca, sa = float(np.cos(ang)), float(np.sin(ang))
    u = dx * ca + dy * sa
    v = -dx * sa + dy * ca
    d_an = np.sqrt((u * ecc) ** 2 + (v / ecc) ** 2)
    return d_an, d_an + nprng.random(d_an.shape).astype(np.float32) * noise


def place_groves(nprng, elig, taken, n_tree, med_size, radius, gap,
                 field=None, clump_bias=0.55, sigma=0.85):
    """撒「小林丛」——树景的质感。

    官方实测：块数/树数中位 0.092（3000 棵树 ≈ 276 个独立块），最大块周长/面积中位 1.66
    （远大于圆盘的 4/sqrt(pi*A)）→ 说明**大部分树在大量小块里，而且块是不规则的**。
    所以这里：
      * 株数取对数正态（中位 med_size，多数 4~15 株，偶尔几十株）→ 尺寸重尾
      * 丛半径按 sqrt(株数) 缩放 → 各尺寸丛的疏密一致（半径旋钮 = 中位丛的半径）
      * 距离用**随机取向的椭圆** + 噪声抖动 → 拉长、参差，不是一个个等大圆斑
      * 丛心禁区半径 = 2×丛半径 + 空隙（关键：两个半径 r 的圆盘中心距离必须 > 2r
        才不相接；只按 r 留间距的话所有丛会连成一整张网 —— 实测 95 个丛只剩 9 个块）
    丛数不设上限，一直撒到株数够为止 → 不需要靠「沿林缘补生」去凑数（那会把大林喂爆）。
    返回 (丛数, 实际种下株数)。
    """
    W, H = elig.shape
    if n_tree <= 0 or not elig.any():
        return 0, 0
    ei, ej = np.nonzero(elig & ~taken)
    if not len(ei):
        return 0, 0
    score = nprng.random(len(ei)).astype(np.float32)
    if field is not None and clump_bias > 0:
        score = clump_bias * field[ei, ej] + (1.0 - clump_bias) * score
        score = score * (0.35 + 0.65 * nprng.random(len(ei)).astype(np.float32))
    order = np.argsort(-score)
    blocked = np.zeros((W, H), dtype=bool)
    # 已有树（含大林）外扩一圈当「丛心禁区」，否则小林丛会一片片粘到大林上，
    # 把大林的连片面积越喂越大（官方最大块 p50 只有 205 格）。
    if taken.any():
        base = 2.0 * radius + gap
        md = int(np.ceil(base)) + 2
        blocked |= (dist_transform(~taken, maxd=md) <= base) & ~taken
    placed, n_clump = 0, 0
    for k in order:
        if placed >= n_tree:
            break
        ci, cj = int(ei[k]), int(ej[k])
        if taken[ci, cj] or blocked[ci, cj]:
            continue
        quota = int(round(med_size * float(np.exp(nprng.normal(0.0, sigma)))))
        quota = max(3, quota)
        rad = radius * float(np.sqrt(quota / max(1.0, med_size)))
        rad = float(min(max(rad, 1.2), 20.0))
        rr2 = int(np.ceil(rad)) + 1
        x0, x1 = max(0, ci - rr2), min(W, ci + rr2 + 1)
        y0, y1 = max(0, cj - rr2), min(H, cj + rr2 + 1)
        ang = float(nprng.uniform(0.0, np.pi))
        ecc = float(np.clip(np.exp(nprng.normal(0.0, 0.32)), 0.5, 2.0))
        d_an, drop = _ellipse_drop(ci, cj, x0, x1, y0, y1, ang, ecc, rad,
                                   max(1.0, rad * 0.6), nprng)
        # 归属用「纯椭圆距离」保证每丛都能填满配额；排序用「椭圆+噪声」让选中的
        # 那一撮格子参差不齐（配额 < 圆盘面积时才有参差，所以半径要留够余量）
        cand = np.nonzero(elig[x0:x1, y0:y1] & ~taken[x0:x1, y0:y1] & (d_an <= rad))
        if not len(cand[0]):
            continue
        # 丛心禁区：同一个窗口、同一个坐标系（含各向异性形状），半径按本丛实际大小
        blocked[x0:x1, y0:y1] |= (d_an <= rad * 2.0 + gap)
        rank = np.argsort(drop[cand])
        n_clump += 1
        for t in rank[:quota]:
            i2 = x0 + int(cand[0][t])
            j2 = y0 + int(cand[1][t])
            taken[i2, j2] = True
            placed += 1
            if placed >= n_tree:
                return n_clump, placed
    return n_clump, placed


def place_scatter(nprng, elig, taken, n_tree, field=None, field_inv=True,
                  size=1.5, sigma=0.55):
    """零星散树：**成小团撒**，绝不一粒一粒独立撒。

    官方 43 张 1.27a 对战图实测（都按树数归一）：
      * 「8 邻域内一棵邻树都没有」的树 = 1.7%（p90 3.4%）
      * 「2 格邻域内一棵邻树都没有」的树 = **0.1%**（p90 0.4%）
    旧实现按 `(1-森林场)` 逐格独立抽样，这两个数分别是 3.0% 和 1.8%（官方 2~18 倍），
    视觉上就是「满地胡椒点」—— 这才是用户说的「像斑点一样分散」的真凶。
    所以散株也必须成团：
      ① 按 `(1-森林场)` 加权挑「丛心」（空旷地优先，和旧版一致）；
      ② 每个丛心在自己 **3×3 窗口内**再补几棵（株数取对数正态、中位 `size`）——
         窗口就这么大，补出来的树必然互为 8 邻域，`iso2` 直接归零；
      ③ `size=1` 的那一小撮才是官方那种「真孤立单株」，比例自然落在 1~2%。
    返回实际种下株数。
    """
    W, H = elig.shape
    if n_tree <= 0 or not elig.any():
        return 0
    ei, ej = np.nonzero(elig)
    if not len(ei):
        return 0
    score = nprng.random(len(ei)).astype(np.float32)
    if field is not None:
        w = (1.0 - field[ei, ej]) if field_inv else field[ei, ej]
        # 权重下限 + 二次随机：避免所有丛心都挤在森林场最低的那一小片
        score = np.maximum(w, 0.03) * (0.35 + 0.65 * score)
    order = np.argsort(-score)
    placed = 0
    rr = 1
    for k in order:
        if placed >= n_tree:
            break
        ci, cj = int(ei[k]), int(ej[k])
        if taken[ci, cj]:
            continue
        quota = int(round(size * float(np.exp(nprng.normal(0.0, sigma)))))
        quota = max(1, min(quota, n_tree - placed))
        x0, x1 = max(0, ci - rr), min(W, ci + rr + 1)
        y0, y1 = max(0, cj - rr), min(H, cj + rr + 1)
        win_e = elig[x0:x1, y0:y1]
        win_t = taken[x0:x1, y0:y1]
        cand = np.nonzero(win_e & ~win_t)
        if not len(cand[0]):
            continue
        # 丛心一定在窗口里且是 free 的，所以 cand 必然非空
        pick = nprng.permutation(len(cand[0]))[:quota]
        for t in pick:
            i2 = x0 + int(cand[0][t])
            j2 = y0 + int(cand[1][t])
            taken[i2, j2] = True
            placed += 1
            if placed >= n_tree:
                break
    return placed


def grow_along_edge(nprng, elig, taken, deficit, field=None, fine=None, chunk=8):
    """株数没配平时沿已有林的林缘向外生长（**绝不随机撒孤立单株** —— 那正是"分布很散"的元凶）。"""
    W, H = elig.shape
    placed = 0
    guard = 0
    while placed < deficit and guard < 400:
        guard += 1
        free = elig & ~taken
        if not free.any():
            break
        nb = np.zeros_like(taken)
        nb[1:, :] |= taken[:-1, :]
        nb[:-1, :] |= taken[1:, :]
        nb[:, 1:] |= taken[:, :-1]
        nb[:, :-1] |= taken[:, 1:]
        edge = free & nb
        ei, ej = np.nonzero(edge)
        if not len(ei):
            break
        k = int(nprng.integers(0, len(ei)))
        take = min(chunk, deficit - placed)
        got = grow_region(nprng, elig, taken, int(ei[k]), int(ej[k]), take,
                          field=field, fine=fine)
        if got <= 0:
            break
        placed += got
    return placed


def _blob_labels(mask):
    """4 邻接连片标记。返回 (标签图, 面积列表)。"""
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    sizes = []
    cur = 0
    for sy, sx in zip(*np.nonzero(mask)):
        if lab[sy, sx]:
            continue
        cur += 1
        stack = [(int(sy), int(sx))]
        lab[sy, sx] = cur
        n = 0
        while stack:
            y, x = stack.pop()
            n += 1
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = cur
                    stack.append((ny, nx))
        sizes.append(n)
    return lab, sizes


def blob_stats(mask):
    """4 邻接连片统计，用来量化「树有多扎堆」。
    返回 (连片块数, 最大块面积, 平均块面积, 孤立单株占块数比例)。"""
    mask = np.asarray(mask, dtype=bool)
    _lab, sizes = _blob_labels(mask)
    if not sizes:
        return 0, 0, 0.0, 0.0
    sz = np.array(sizes)
    return len(sizes), int(sz.max()), float(sz.mean()), float(np.count_nonzero(sz == 1)) / len(sz)


def _shift_or(mask, dy, dx):
    """把 mask 整体平移 (dy,dx) 后按位或（越界部分丢弃，**不做环绕**）。"""
    h, w = mask.shape
    out = np.zeros_like(mask)
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    out[ys0:ys1, xs0:xs1] = mask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def _neigh_any(mask, r):
    """r 邻域内是否存在**其它** True（显式不含自身）。

    标准 dilate 的语义是 `mask ∪ 邻域`，直接拿它判「是否孤立」会得到恒真的结果
    （本项目实测：先写成 `t & ~dilate(t,1)` 恒 0，改成 `t & ~(dilate(t,1) & ~t)` 又恒 1，
    两次都白跑了一轮统计）。所以这里从全零开始 OR 位移副本，且永不含 (0,0)。
    """
    out = np.zeros_like(mask)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx == 0:
                continue
            out |= _shift_or(mask, dy, dx)
    return out


def _dist_to(mask, maxd=512):
    """每个格子到最近 mask=True 格的 8 邻接（Chebyshev）距离，上限 maxd。

    多源 BFS 的膨胀写法：每轮把已覆盖区向外扩一圈。不引 scipy、也不写 Python 队列。
    """
    d = np.full(mask.shape, maxd, dtype=np.int32)
    d[mask] = 0
    cur = mask.copy()
    dist = 1
    while cur.any() and dist <= maxd:
        new = _neigh_any(cur, 1) & ~cur
        if not new.any():
            break
        d[new] = dist
        cur |= new
        dist += 1
    return d


def forest_metrics(mask, big_thresh=100, near=3):
    """树林形态指标（**全部按树数归一**）——「像不像真地图」的尺子。

    官方 1.27a 43 张原生对战图实测 p50（全量分位见 `tools/_tmp/foreststats_melee.txt`）：
      密度 0.120 | 块数 256 | 最大块 205 | ≥100 块数 4 | 树落大林 0.332
      孤立单株占块数 0.488 | 块数/树数 0.0924
      **iso8 0.017 / iso2 0.001 / 到大林格距中位 9 / 距大林≤3 格 0.365**
    后四项是「胡椒点」的直接度量，其中 `iso2`（2 格内一棵邻树都没有的树占比）最灵敏：
    官方 p50 只有 0.1%，凡是「一粒一粒均匀撒」的实现都会飙到百分之几。

    返回 dict：
      n/n_blob/max_sz/lone/n_big/frac_big/ratio —— 连片结构
      iso8/iso2 —— 孤立度（8 邻域 / 2 格邻域内无其它树，占树数）
      dmed/dnear/inbig —— 到大林（≥big_thresh 格块）的格距中位、≤near 格占比、落在大林内占比
    """
    mask = np.asarray(mask, dtype=bool)
    n = int(mask.sum())
    if n == 0:
        return dict(n=0, dens=0.0, n_blob=0, max_sz=0, lone=0.0, n_big=0, frac_big=0.0,
                    ratio=0.0, iso8=0.0, iso2=0.0, dmed=0.0, dnear=0.0, inbig=0.0)
    lab, sizes = _blob_labels(mask)
    sz = np.array(sizes)
    ids = [k + 1 for k, s in enumerate(sizes) if s >= big_thresh]
    big_mask = np.isin(lab, ids) if ids else np.zeros_like(mask)
    dtree = _dist_to(big_mask)[mask]
    return dict(
        n=n,
        dens=n / float(mask.size),
        n_blob=len(sizes),
        max_sz=int(sz.max()),
        lone=float((sz == 1).sum()) / len(sz),
        n_big=len(ids),
        frac_big=(float(sz[sz >= big_thresh].sum()) / n) if ids else 0.0,
        ratio=len(sizes) / float(n),
        iso8=float((mask & ~_neigh_any(mask, 1)).sum()) / n,
        iso2=float((mask & ~_neigh_any(mask, 2)).sum()) / n,
        dmed=float(np.median(dtree)),
        dnear=float((dtree <= near).sum()) / n,
        inbig=float((dtree == 0).sum()) / n,
    )


def read_w3e_header(data):
    pos = 8
    tileset = chr(data[pos]); pos += 1
    custom = struct.unpack_from("<I", data, pos)[0]; pos += 4
    ng = struct.unpack_from("<I", data, pos)[0]; pos += 4
    ground = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace") for i in range(ng)]
    pos += 4 * ng
    nc = struct.unpack_from("<I", data, pos)[0]; pos += 4
    pos += 4 * nc
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return tileset, w, h, pos


def parse_doo(blob):
    if blob[:4] != b"W3do":
        return 7, 9, [], blob
    ver, sub, cnt = struct.unpack_from("<III", blob, 4)
    recs = []
    for i in range(cnt):
        o = 16 + i * 42
        recs.append(blob[o:o + 42])
    tail = blob[16 + cnt * 42:]
    return ver, sub, recs, tail


def build_doo(ver, sub, recs, tail):
    out = bytearray()
    out += b"W3do"
    out += struct.pack("<III", ver, sub, len(recs))
    for r in recs:
        out += r
    out += tail if tail else DOO_TAIL
    return bytes(out)


def make_tmp(name):
    """给本次运行开一个干净且独占的临时目录。

    用「父目录尽力清空 + 本次唯一子目录」而不是复用固定目录：
      - 唯一子目录 → 永远不会有上次残留的文件被当成新数据（MPQ 提取失败时最容易踩）
      - 父目录尽力清空 → 正常环境下临时文件不会越积越多
      - 删除被拦下来（安全软件 / 系统删除保护）时不影响本次生成，也不影响正确性
    """
    parent = os.path.join(HERE, "_tmp", name)
    try:
        if os.path.exists(parent):
            shutil.rmtree(parent, ignore_errors=True)
    except BaseException:
        pass
    tmp = os.path.join(parent, "r%d_%d" % (os.getpid(), int(time.time() * 1000) % 100000))
    os.makedirs(tmp, exist_ok=True)
    return tmp


def drop_tmp(tmp):
    """收尾清理，纯尽力而为 —— 失败绝不能影响已经写好的地图。"""
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except BaseException:
        pass


def main():
    args, opts = parse_opts(sys.argv[1:])
    if not args:
        print(__doc__)
        return 1
    map_path = args[0]
    seed = int(opts.get("seed", 7))
    density = float(opts.get("density", 0.18))
    slope_tol = int(opts.get("slope-tol", 1))
    freq = float(opts.get("freq", 2.2))
    exe = opts.get("exe") or default_exe()
    out_path = opts.get("out")
    preview = opts.get("preview")
    keep = bool(opts.get("keep"))
    force_id = opts.get("tree-id")

    tmp = make_tmp("doodads")

    target = map_path
    if out_path:
        shutil.copy2(map_path, out_path)
        target = out_path
        print(f"已复制模板到 {out_path}")
    elif opts.get("no-backup"):
        pass                      # 调用方（random_map）已经复制过模板，这里再备份只是堆垃圾
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(os.path.dirname(HERE), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        back = os.path.join(backup_dir, f"{os.path.basename(map_path)}.{stamp}.bak")
        shutil.copy2(map_path, back)
        # 只留最近 100 个同名备份，跑批量实验也不会把目录撑爆
        try:
            stem = os.path.basename(map_path) + "."
            olds = sorted(f for f in os.listdir(backup_dir)
                          if f.startswith(stem) and f.endswith(".bak"))
            for f in olds[:-100]:
                os.remove(os.path.join(backup_dir, f))
        except BaseException:
            pass

    for fn in ("war3map.w3e", "war3map.doo"):
        subprocess.run([exe, "extract", target, fn, tmp, "/fp"], capture_output=True, timeout=180)
    w3e_p, doo_p = os.path.join(tmp, "war3map.w3e"), os.path.join(tmp, "war3map.doo")
    if not os.path.exists(w3e_p):
        print("提取 war3map.w3e 失败")
        return 1

    w3e = open(w3e_p, "rb").read()
    tileset, W, H, HS = read_w3e_header(w3e)
    cols, rows = W + 1, H + 1
    water = np.zeros((rows, cols), dtype=bool)
    layer = np.zeros((rows, cols), dtype=np.int16)
    gheight = np.zeros((rows, cols), dtype=np.float32)
    for r in range(rows):
        for c in range(cols):
            off = HS + (r * cols + c) * 7
            gh, whf, fb, b5, b6 = struct.unpack_from("<HHBBB", w3e, off)
            water[r, c] = bool(fb & 0x40)
            layer[r, c] = b6 & 0x0F
            gheight[r, c] = (gh - GROUND_ZERO + (layer[r, c] - LAYER_ZERO) * LAYER_STEP) / 4.0
    print(f"{os.path.basename(target)}: {W}x{H} tileset={tileset}")

    # 学模板地图的树类型
    old_ver, old_sub, old_recs, tail = (7, 9, [], DOO_TAIL)
    tree_id = None
    if os.path.exists(doo_p):
        old_ver, old_sub, old_recs, tail = parse_doo(open(doo_p, "rb").read())
        if old_recs:
            ids = Counter()
            for r in old_recs:
                try:
                    ids[r[:4].decode("ascii")] += 1
                except UnicodeDecodeError:
                    pass
            if ids:
                tree_id = ids.most_common(1)[0][0]
                print(f"模板里最常见的物件: {ids.most_common(3)} → 用作树类型 {tree_id}")
    if force_id:
        tree_id = force_id
    if not tree_id:
        tree_id = FALLBACK_TREES.get(tileset, "LTlt")
        print(f"模板无物件，按 tileset {tileset} 兜底选用 {tree_id}")
    tree_bytes = tree_id.encode("ascii")[:4].ljust(4, b"\x00")

    nprng = np.random.default_rng(seed)

    # 可种树的格子：四角都不含水、四角同层（平地，避免种在崖边）、不在最外圈
    dry = ~water
    elig = np.zeros((W, H), dtype=bool)
    for j in range(1, H - 1):
        for i in range(1, W - 1):
            c0 = dry[j, i] and dry[j, i + 1] and dry[j + 1, i] and dry[j + 1, i + 1]
            l4 = (layer[j, i], layer[j, i + 1], layer[j + 1, i], layer[j + 1, i + 1])
            c1 = (max(l4) - min(l4)) <= slope_tol
            elig[i, j] = c0 and c1
    avail = int(elig.sum())

    # ---------------------------------------------------------------
    # 撒树分三层（复刻官方对战图的重尾结构）：
    #   ① 大林  —— 少数几块、尺寸重尾、顺森林场拉长的连片，吃掉 forest_share 的树
    #   ② 小林丛—— 大量小块（株数对数正态、椭圆+噪边），块数/树数才追得上官方
    #   ③ 散株  —— 优先落森林场低的空旷地，但**必须成小团**（见 place_scatter）
    # 森林场只决定「哪里像森林」（大尺度疏密），不直接当阈值切。
    # ---------------------------------------------------------------
    density = float(opts.get("density", 0.18))
    forest_share = min(max(float(opts.get("forest-share", 0.32)), 0.0), 0.9)
    forest_size = max(10.0, float(opts.get("forest-size", 170)))
    clump_size = float(opts.get("clump-size", 11))
    clump_radius = float(opts.get("clump-radius", 3.0))
    clump_gap = float(opts.get("clump-gap", 1.5))
    scatter = min(max(float(opts.get("scatter", 0.035)), 0.0), 1.0)
    scatter_size = max(1.0, float(opts.get("scatter-size", 1.5)))
    clump_bias = min(max(float(opts.get("clump-bias", 0.55)), 0.0), 1.0)
    edge_forest = min(max(float(opts.get("edge-forest", 0.55)), 0.0), 1.0)
    edge_band = max(2.0, float(opts.get("edge-band", 14)))
    clump_size = max(2.0, clump_size)
    clump_radius = max(1.0, clump_radius)
    clump_gap = max(0.0, clump_gap)

    n_forest = n_clumps = n_grow = 0
    n_forest_tree = n_grove_tree = n_scatter_tree = 0
    if avail:
        nprng_local = np.random.default_rng(seed + 991)
        # 森林场：内部低频 + 边界林带（官方图的树大半贴边/岸线/崖脚成带）
        field = build_forest_field(nprng_local, elig, freq, edge_forest, edge_band)
        fine = build_fine_field(nprng_local, (W, H), freq)
        n_total = int(round(avail * density))
        n_forest_tree = int(round(n_total * forest_share))
        n_scatter_tree = int(round(n_total * scatter))
        n_grove_tree = max(0, n_total - n_forest_tree - n_scatter_tree)

        picked = np.zeros((W, H), dtype=bool)
        n_forest, placed_f = place_forests(nprng, elig, picked, n_forest_tree,
                                           forest_size, field, fine=fine)
        n_clumps, placed_c = place_groves(nprng, elig, picked, n_grove_tree,
                                          clump_size, clump_radius, clump_gap,
                                          field=field, clump_bias=clump_bias)
        placed_s = place_scatter(nprng, elig, picked, n_scatter_tree, field=field,
                                 size=scatter_size)
        short = n_total - (placed_f + placed_c + placed_s)
        n_grow = grow_along_edge(nprng, elig, picked, short, field=field,
                                 fine=fine) if short > 0 else 0
    else:
        picked = np.zeros((W, H), dtype=bool)

    idx_i, idx_j = np.nonzero(picked)   # picked 形状 (W, H)，轴0 = i，轴1 = j
    ys, xs = idx_j, idx_i
    fm = forest_metrics(picked)
    n_tree = len(ys)
    print(f"可用格子 {avail} ({avail*100.0/(W*H):.1f}%) → 种树 {n_tree} 棵 "
          f"({n_tree*100.0/(W*H):.1f}% 地图面积, 目标密度 {density*100:.0f}%)")
    print(f"      大林 {n_forest} 块 / {n_forest_tree} 株（share {forest_share*100:.0f}%, "
          f"中位 {forest_size:.0f} 格）  小林丛 {n_clumps} 丛 / {n_grove_tree} 株"
          f"（中位 {clump_size:.0f} 株, 半径 {clump_radius:.1f} 格, 空隙 {clump_gap:.1f} 格）")
    print(f"      散株 {n_scatter_tree} 株（{scatter*100:.0f}%，每团中位 {scatter_size:.1f} 株）"
          f"/ 林缘补生 {n_grow} 株 / 森林场 freq={freq}，"
          f"边界林带 {edge_forest*100:.0f}%（带宽 {edge_band:.0f} 格）")
    # 官方 1.27a 43 张原生对战图 p50 目标（口径见 forest_metrics 文档字符串）
    print(f"      连片度: {fm['n_blob']} 片，最大 {fm['max_sz']} 格，"
          f"孤立单株占块数 {fm['lone']*100:.0f}%，块数/树数 {fm['ratio']:.3f}，"
          f"树落大林 {fm['frac_big']*100:.0f}%"
          f"（官方 p50: 256 片 / 205 格 / 49% / 0.092 / 33%）")
    print(f"      胡椒点: 8邻域孤立 {fm['iso8']*100:.2f}%，2格内无树 {fm['iso2']*100:.2f}%，"
          f"到大林格距中位 {fm['dmed']:.0f}，距大林≤3格 {fm['dnear']*100:.0f}%"
          f"（官方 p50: 1.7% / 0.1% / 9 / 36%）")

    recs = list(old_recs) if keep else []
    eid = max([struct.unpack_from("<i", r, 38)[0] for r in old_recs] + [0]) if old_recs else 0
    for i, j in zip(xs, ys):
        eid += 1
        wx = (int(i) + 0.5) * TILE - W * 64
        wy = (int(j) + 0.5) * TILE - H * 64
        wz = float(np.mean([gheight[j, i], gheight[j, i + 1], gheight[j + 1, i], gheight[j + 1, i + 1]]))
        variation = int(nprng.integers(0, 9))
        angle = float(nprng.uniform(0.0, 6.283185307))
        scale = float(nprng.uniform(0.85, 1.15))
        rec = bytearray(42)
        rec[0:4] = tree_bytes
        struct.pack_into("<i", rec, 4, variation)
        struct.pack_into("<fff", rec, 8, wx, wy, round(wz, 4))
        struct.pack_into("<f", rec, 20, round(angle, 6))
        struct.pack_into("<fff", rec, 24, scale, scale, scale)
        rec[36] = 2       # flags：与官方地图里的树一致
        rec[37] = 100     # life %
        struct.pack_into("<i", rec, 38, eid)
        recs.append(bytes(rec))

    new_doo = os.path.join(tmp, "war3map.doo.new")
    open(new_doo, "wb").write(build_doo(old_ver or 7, old_sub or 9, recs, tail))

    if preview:
        # 角点网格 (rows, cols) 自下而上；取每格四角合成瓦片图，再翻成自顶向下用于显示
        tile_water = np.zeros((W, H), dtype=bool)
        for j in range(H):
            for i in range(W):
                tile_water[i, j] = (water[j, i] and water[j, i + 1]
                                    and water[j + 1, i] and water[j + 1, i + 1])
        disp_water = np.transpose(tile_water)[::-1]        # (H, W) 自顶向下
        disp_trees = np.transpose(picked)[::-1]
        img = np.full((H, W, 3), (200, 190, 160), dtype=np.uint8)
        img[disp_water] = (60, 110, 200)
        img[disp_trees] = (20, 90, 20)
        Image.fromarray(img).resize((W * 4, H * 4), Image.NEAREST).save(preview)
        print(f"预览图: {preview}")

    subprocess.run([exe, "add", target, new_doo, "war3map.doo"], capture_output=True, timeout=180)
    print(f"完成: {target}（树 {len(recs)} 个，原物件 {0 if not keep else len(old_recs)} 个保留）")
    if not opts.get("keep-temp"):
        drop_tmp(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
