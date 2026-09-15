# -*- coding: utf-8 -*-
"""纯规则/噪声版随机地形生成器 —— 写高度、悬崖、水面到 war3map.w3e。

字段标定结论（见 tools/inspect_w3e.py 的实测验证）:
  v11 每角点 7 字节:
    u16 groundHeight                基准 8192 (ground zero)
    u16 waterHeight | 0x4000         0x4000 = boundary flag 1
    u8  flags<<4 | groundTexture     0x10 ramp / 0x20 blight / 0x40 water / 0x80 boundary2
    u8  groundVariation<<3 | cliffVariation
    u8  cliffTexture<<4 | layerHeight
  WE 显示高度 = (groundHeight - 8192 + (layer - 2) * 512) / 4
    → 层零位 = 2，每层 = 512 原始单位；layer 上限 14，写 15 会崩

用法:
  python gen_height.py <map.w3x> [选项]
常用选项:
  --out <路径>        另存为新地图（默认原地改，先备份）
  --no-backup         跳过备份（调用方自己已经复制过模板时用，避免堆积无用 .bak）
  --seed 12345        随机种子
  --freq 1.6          噪声基础频率，越小地形越大块
  --layer-min 2       最低高度层（WE 每条层线 = 128 高度单位，合法范围 0~14）
  --layer-max 5       最高高度层（留空时 = layer-min + layers - 1）
  --layers 4          陆地分几层（等价于 layer-max = layer-min + layers - 1）
  --octaves 2         噪声八度数，越高越碎（地形碎片化的主因，别乱加）
  --smooth 2          3x3 众数滤波次数，抹平台地毛刺；0=关闭
  --level-bias 2.0    层位偏置：1=各层等面积（马赛克感），越大越低平越像真地图
  --water 0.30        水域占地比例
应用高度（对应 WE 地形面板的「应用高度」那一栏，都是同一个台地内部的起伏，
不会变成悬崖。幅度单位统一是 WE 高度单位 = WE 高度条上的 1 格；一整层 = 128）:
  --raise 75          隆起：地面向上鼓包的幅度（σ，单位 WE 高度）
  --lower 75          凹陷：地面向下凹坑的幅度（σ）
  --rough 12          凹凸不平：表面颗粒感的幅度（σ，WE 的噪波笔刷就是这个量级）
  --blob 28           隆起/凹陷的团块尺寸（格，越大越是整片丘陵）
  --grain 2.5         凹凸不平的颗粒尺寸（格，越小越细碎）
  --ledge 0           台阶高度（WE 高度单位）：>0 时把宏观起伏量化成"平坦面 + 陡坎"，
                      对应 WE 的「高原/阶梯」笔刷；官方对战图 36%~64% 的相邻角点完全
                      等高就是这个原因。0 = 保持连续起伏（默认，观感最自然）
  --height-step 4     高度量化步长（原始单位）：4 = 1 WE 单位，与 WE 笔刷粒度一致
  --relief 0.35       旧参数（单位：层），等价于 --raise/--lower = relief×128，保留兼容
  --shade-exag 10     预览图的山体阴影垂直夸张倍数（只影响预览，不影响地图）
平整区域（对应 WE 的「平整」笔刷，让一部分地面彻底没有起伏）:
  --flat 0.15         平整区域占地图的比例，0 = 关闭
  --flat-size 20      平整区域的团块尺寸（格）
水体（实测官方对战图的水深全是整层的倍数，最常见 1 层，其次 2 层，少数 4 层）:
  --shelf 3           浅水岸带宽度（格）：离岸这么宽以内是浅水，之外是深水
  --deep 1            深水比浅水再深几层（1 层 = 128 WE 高度单位）
  --water-relief 0.5  水下起伏 = 陆地起伏 × 该比例（自动裁到水底不会冒出水面）
  --ramps auto        斜坡：auto=按连通性自动刻（默认）；0=关闭；N=最多 N 条
  --ramp-run 4        每条斜坡沿崖壁方向的瓦片数（官方长边集中在 5~8 条角点线）
  --ramp-force 1      1=找不到齐整崖段时把 5 条角点线就地整形（默认，斜着走的锯齿崖
                      也能刻出斜坡）；0=只接受本来就齐整的位置（会更常跳过）
  --cliff-texture auto 崖壁贴图索引（auto = 纹理集里第 2 套，官方地图的通用做法；
                      官方空模板里是 15 = 未指定）。整张图统一，不逐角点随机
  --min-plateau 0     小于该面积（格）的台地并入邻居，0=关闭（默认关）
  --min-island 32     小于该面积（格）的陆地碎岛并入水，0=关闭
  --min-lake 16       小于该面积（格）且不贴边的内陆水塘填平，0=关闭
  --max-jump 2        相邻角点允许的最大层差（官方地图存在 2 层崖）
  --boundary ring     地图边界标记（0x80 与 0x4000 这两个位是同一概念的两份拷贝，
                      带它 = 地图外，寻路可走率 0%）：
                        ring = 只留最外一圈（默认，整张地图可玩）
                        none = 全清
                        keep = 沿用模板边框（WE 自建的空模板用它标出游玩区之外的留白，
                               官方对战图如 LostTemple 则盖了 40% 的角点）
  --preview p.png     同时输出地形预览图
示例:
  python gen_height.py ../generated/rand1.w3x --seed 42 --water 0.28 --preview ../preview.png
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

    不这么做会连环炸：
      1. 子进程 print 中文时按系统区域设置编码（中文 Windows = cp936），父进程若按
         另一种编码解码 → UnicodeDecodeError，而且它发生在 subprocess 的读取线程里，
         父进程只会看到 r.stdout 是 None，接着 AttributeError，看起来完全不知所云。
      2. ✔ ✘ 这类字符**不在 GBK 字符集里**，cp936 下直接 print 就 UnicodeEncodeError。
    所以：进管道的输出一律 UTF-8（调用方按 UTF-8 解），人看的控制台保留原编码但
    把编码不了的字符替换掉，绝不因为一个符号把整次生成搞崩。
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
LAYER_ZERO = 2          # 层编号的零位
LAYER_STEP = 512        # 每层 = 512 原始单位
MAX_LAYER = 14          # 15 非法
WATER_FLAG = 0x40
RAMP_FLAG = 0x10
BLIGHT_FLAG = 0x20
BOUNDARY2_FLAG = 0x80   # flags 里的「地图边界外」标记（实测：带它的瓦片可走率 0%）
BOUNDARY_BIT = 0x4000   # waterHeight 里的「地图边界外」标记（同一个概念的另一份拷贝）
WATER_LEVEL = 8192      # 水面基准（默认层区间 layer_min=2 时的世界高度 = GROUND_ZERO）


def default_exe():
    """定位随项目自带的 ../bin/MPQEditor.exe（不依赖外部目录）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def read_header(data):
    pos = 8
    tileset = chr(data[pos]); pos += 1
    custom = struct.unpack_from("<I", data, pos)[0]; pos += 4
    n_ground = struct.unpack_from("<I", data, pos)[0]; pos += 4
    ground = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace") for i in range(n_ground)]
    pos += 4 * n_ground
    n_cliff = struct.unpack_from("<I", data, pos)[0]; pos += 4
    cliff = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace") for i in range(n_cliff)]
    pos += 4 * n_cliff
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return {"version": struct.unpack_from("<I", data, 4)[0], "tileset": tileset,
            "custom": custom, "ground": ground, "cliff": cliff,
            "width": w, "height": h, "header": pos}


def value_noise(nprng, shape, cells):
    """一块 cells x cells 的随机格点，双线性插值 + 多个八度叠加成 fBm。

    两个细节都是为了消除伪影：
      1. 插值权重用 smoothstep（3w²-2w³）而不是线性 —— 线性插值在格线上留折痕，
         多层八度叠起来就是一片 45° 的"砂纸斜纹"。
      2. 格点相位随机偏移 —— 格点数与角点数整除时（比如 129 角点配 65 格点），
         噪声节点刚好落在每个像素上，会渲染出规则的点阵/棋盘。相位一随机就散了。
    """
    rows, cols = shape
    gw = max(2, int(cells) + 1)
    gh = gw
    grid = nprng.random((gh, gw), dtype=np.float32)
    oy, ox = nprng.random(2).astype(np.float32)
    ys = np.linspace(0, gh - 1, rows, dtype=np.float32) + oy
    xs = np.linspace(0, gw - 1, cols, dtype=np.float32) + ox
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    wy = (ys - y0)[:, None]
    wx = (xs - x0)[None, :]
    y0 = np.mod(y0, gh); y1 = np.mod(y0 + 1, gh)
    x0 = np.mod(x0, gw); x1 = np.mod(x0 + 1, gw)
    wy = wy * wy * (3.0 - 2.0 * wy)
    wx = wx * wx * (3.0 - 2.0 * wx)
    top = grid[y0][:, x0] * (1 - wx) + grid[y0][:, x1] * wx
    bot = grid[y1][:, x0] * (1 - wx) + grid[y1][:, x1] * wx
    return top * (1 - wy) + bot * wy


def fbm(nprng, shape, freq, octaves=5, gain=0.5, lacunarity=2.0):
    """分形布朗运动，返回任意实数范围的二维数组。

    八度一旦细过「一个角点一格」就停：再细的内容在角点网格上直接混叠成假图案
    （规则点阵/棋盘），不是细节。
    """
    out = np.zeros(shape, dtype=np.float32)
    nyq = float(min(shape))
    amp, norm, f = 1.0, 0.0, freq
    for _ in range(octaves):
        if f > nyq:
            break
        out += amp * value_noise(nprng, shape, f)
        norm += amp
        amp *= gain
        f *= lacunarity
    return out / norm if norm > 0 else out


def unit_noise(nprng, shape, freq, **kw):
    """fBm 归一到「零均值 + 单位标准差」。

    这样「应用高度」的几个参数可以直接写成 WE 高度单位（--raise 70 = 鼓包处大约
    高出 70 格），跟 WE 高度条上的数字对得上；也不会因为改了尺度参数整个幅度就跑偏。
    """
    f = fbm(nprng, shape, freq, **kw).astype(np.float32)
    f = f - f.mean()
    s = float(f.std())
    return (f / s) if s > 1e-6 else f


def noise_cells(cols, size_tiles):
    """把「特征尺寸（格）」换算成 value_noise 的 cells 参数。

    value_noise 是在整张图上铺 int(cells)+1 个随机格点再做双线性插值，所以
    格点间距 ≈ cols / cells → 想要 size_tiles 格宽的起伏，就传 cells = cols/size。
    这样参数与地图尺寸无关：128 图上「28 格团块」和 256 图上「28 格团块」一样大。
    """
    return max(1.0, cols / max(1.0, float(size_tiles)))


def box_mean5(a):
    """5x5 边缘保形滑动均值（累积和实现，比卷积快）。"""
    k = 5
    pad = k // 2
    p = np.pad(a.astype(np.float32), pad, mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    R, C = a.shape
    s = (c[k:k + R, k:k + C] - c[0:R, k:k + C]
         - c[k:k + R, 0:C] + c[0:R, 0:C])
    return s / (k * k)


def shore_distance(is_water, cap=64):
    """每个水格到最近陆地的格数（多源 BFS，向量化膨胀，超过 cap 记 cap）。

    用来切「浅水岸带 / 深水区」：离岸近的是浅水，远的是深水，这样湖心深、岸边浅，
    跟真实水体一致（官方地图没有一条等宽的浅水描边）。
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


def relief_stats(fine, mask):
    """实测这块起伏场「低频(隆起/凹陷) / 高频(凹凸不平)」的 σ（单位 WE 高度）.

    口径与 tools/_tmp/analyze_height.py 一致：先换成 WE 高度单位，再用 5x5 均值
    把 5 格以上尺度算作低频、剩下的算高频。mask = 要统计的角点。
    """
    h = fine.astype(np.float32) / 4.0
    low = box_mean5(h)
    high = h - low
    sel = mask
    if sel.sum() < 50:
        sel = np.ones_like(mask)
    return (float(h[sel].std()), float(low[sel].std()), float(high[sel].std()))


def hillshade(height, az_deg=315.0, alt_deg=45.0, exag=10.0):
    """把高度场画成山体阴影（0~1 灰度），用来直观看出隆起/凹陷/颗粒感。

    exag 是垂直夸张倍数：真实比例下（1 格 = 128 世界单位，而起伏只有几十）
    阴影几乎全是平的，看不出东西，所以要放大。
    """
    az = np.deg2rad(90.0 - az_deg)
    alt = np.deg2rad(alt_deg)
    gy, gx = np.gradient(height.astype(np.float32) * exag)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    return np.clip(np.sin(alt) * np.sin(slope)
                   + np.cos(alt) * np.cos(slope) * np.cos(az - aspect), 0.0, 1.0)


def limit_neighbor_jump(layer, max_jump=1, passes=8):
    """WE 渲染相邻层落差过大会出异常 tearing，这里把相邻层差压到 max_jump 以内。"""
    rows, cols = layer.shape
    for _ in range(passes):
        changed = False
        for dy, dx in ((0, 1), (1, 0)):
            a = layer[:, :-1] if dx else layer[:-1, :]
            b = layer[:, 1:] if dx else layer[1:, :]
            diff = b - a
            over = np.abs(diff) > max_jump
            if not over.any():
                continue
            changed = True
            step = (np.abs(diff) - max_jump) / 2.0
            step = np.ceil(step) * np.sign(diff)
            if dx:
                layer[:, :-1] = np.where(over, (a + step).astype(np.int16), a)
                layer[:, 1:] = np.where(over, (b - step).astype(np.int16), b)
            else:
                layer[:-1, :] = np.where(over, (a + step).astype(np.int16), a)
                layer[1:, :] = np.where(over, (b - step).astype(np.int16), b)
        layer[:] = np.clip(layer, 0, MAX_LAYER)
        if not changed:
            break
    return layer


def _components(mask):
    """4 连通区域标记，返回 (label 数组, 区域数)，label=-1 表示不属于 mask。"""
    R, C = mask.shape
    lab = np.full((R, C), -1, dtype=np.int32)
    cur = 0
    for r in range(R):
        for c in range(C):
            if not mask[r, c] or lab[r, c] >= 0:
                continue
            lab[r, c] = cur
            stack = [(r, c)]
            while stack:
                y, x = stack.pop()
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < R and 0 <= nx < C and mask[ny, nx] and lab[ny, nx] < 0:
                        lab[ny, nx] = cur
                        stack.append((ny, nx))
            cur += 1
    return lab, cur


def _tile_derivatives(layer, is_water):
    """返回每个瓦片的 (层差, 梯度方向, 跳变线索引, 干燥)。索引均为自顶向下排布。"""
    a = layer[:-1, :-1]; b = layer[:-1, 1:]
    c_ = layer[1:, :-1]; d = layer[1:, 1:]
    spread = (np.maximum(np.maximum(a, b), np.maximum(c_, d))
              - np.minimum(np.minimum(a, b), np.minimum(c_, d)))
    di = np.abs(a - b) + np.abs(c_ - d)
    dj = np.abs(a - c_) + np.abs(b - d)
    grad = np.where(spread == 0, 0, np.where(di >= dj, 1, 2)).astype(np.int8)
    rows_g = np.arange(spread.shape[0])[:, None]
    cols_g = np.arange(spread.shape[1])[None, :]
    line = np.where(grad == 1,
                    cols_g + np.where(a < b, 0, 1),
                    rows_g + np.where(a < c_, 0, 1)).astype(np.int32)
    dry = ~(is_water[:-1, :-1] | is_water[:-1, 1:] | is_water[1:, :-1] | is_water[1:, 1:])
    return spread, grad, line, dry


def _shift(A, dy, dx):
    """把 A 整体平移 (dy, dx)，出界部分填 -1（用于众数滤波取邻域）。"""
    R, C = A.shape
    out = np.full((R, C), -1, dtype=A.dtype)
    ys0, ys1 = max(0, -dy), min(R, R - dy)
    yd0, yd1 = max(0, dy), min(R, R + dy)
    xs0, xs1 = max(0, -dx), min(C, C - dx)
    xd0, xd1 = max(0, dx), min(C, C + dx)
    out[yd0:yd1, xd0:xd1] = A[ys0:ys1, xs0:xs1]
    return out


def mode_filter(code, passes=2, values=16):
    """3x3 众数滤波，平局时保留原值。

    量化后的层场在阈值附近会被高频噪声打出「单角点毛刺」，把台地切成几十块
    肉眼看不见的小台阶；这一步把它们抹平，是台地能连成大片的关键。
    """
    L = code.astype(np.int32)
    R, C = L.shape
    rr = np.arange(R)[:, None]
    cc = np.arange(C)[None, :]
    for _ in range(passes):
        cnt = np.zeros((values, R, C), dtype=np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                S = _shift(L, -dy, -dx)
                m = S >= 0
                for v in range(values):
                    cnt[v] += (S == v) & m
        cnt[L, rr, cc] += 1          # 原值加一票 → 平局时保持不动
        L = np.argmax(cnt, axis=0).astype(np.int32)
    return L


def _multi_dijkstra(lab, passable, wmap):
    """多源 Dijkstra：每块台地的所有瓦片都是 0 距离源点，向外扩张。

    返回 (dist, owner, prev)。扩张到收敛后，相邻两瓦片 owner 不同的地方就是两块
    台地之间最省的通道口 —— 这等价于在「台地邻接图」上跑 Prim，一趟搞定。
    """
    H, W = lab.shape
    INF = np.int32(1 << 28)
    dist = np.full((H, W), INF, dtype=np.int32)
    owner = np.full((H, W), -1, dtype=np.int32)
    prev = np.full((H, W), -1, dtype=np.int32)
    pq = []
    for r, c in zip(*np.nonzero(lab >= 0)):
        dist[r, c] = 0
        owner[r, c] = lab[r, c]
        heapq.heappush(pq, (0, r * W + c))
    while pq:
        d, i = heapq.heappop(pq)
        r, c = divmod(i, W)
        if d > dist[r, c]:
            continue
        o = owner[r, c]
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if nr < 0 or nr >= H or nc < 0 or nc >= W or not passable[nr, nc]:
                continue
            nd = d + int(wmap[nr, nc])
            if nd < dist[nr, nc]:
                dist[nr, nc] = nd
                owner[nr, nc] = o
                prev[nr, nc] = i
                heapq.heappush(pq, (nd, nr * W + nc))
    return dist, owner, prev


def _plateau_levels(lab, nlab, layer):
    """每块台地（四角同层的连通平地）的层位 —— 取该块里平地的众数。"""
    lv = np.zeros(max(nlab, 1), dtype=np.int16)
    for k in range(nlab):
        m = lab == k
        if m.any():
            vals, cnt = np.unique(layer[:-1, :-1][m], return_counts=True)
            lv[k] = int(vals[np.argmax(cnt)])
    return lv


def _stamp_ramp(layer, is_water, ramp, zero_fine, u, v, lv_u, lv_v, run, margin,
                trace=None, force=True, max_jump=2):
    """在相邻瓦片 u / v（分属层位 lv_u / lv_v 的两块台地）之间盖一条 WE 合法斜坡。

    几何规则来自官方 51 张地图 / 3116 个 ramp 瓦片的实测（tools/diag_ramp.py）：
      * 斜坡是「垂直于崖壁 2 个瓦片厚」的一条带：
          瓦片 A（低侧基地）四角全在低层、四角全带 ramp 位；
          瓦片 B（台阶瓦片）2 角低 + 2 角高、四角全带 ramp 位；
        沿崖壁方向延续若干瓦片（官方长边集中在 5~8 条角点线）。
      * ramp 位只打 3 条角点线 = {高侧线, 共享线, 低侧线}，即 2 低 + 1 高。
        R 连块垂直于崖壁的厚度主导值就是 3（252/356）。
      * ramp 位绝不往高侧多给：官方「纯平地-高侧基地」只有 39/5346。
      * 层差恒为 1（Counter({1: 293, 2: 1})）。
      * cliffVariation 与斜坡无关（ramp 与普通崖壁取值分布几乎一致）→ 不用管。

    真正的几何是 **5 条角点线 / 4 个瓦片**（设低侧在左，层位记 lo < hi）：

        线:  L0=lo   L1=lo   L2=lo   L3=hi   L4=hi
        瓦片:    T0      T1      T2      T3
              平平   平平    台阶    平平
              (低侧翼) (基地) (台阶)  (高侧翼)

    T1/T2 是带 ramp 位的两块；T0/T3 是「翼」——它们必须是**平地**，否则斜坡
    两端接不上台地：低侧翼若成了崖壁瓦片，基地就悬空；高侧翼同理。
    早期实现只校验 L1/L3 两条线、不管翼，于是盖出来的斜坡有一头接不到台地，
    连通性自检就会报「有 1 座岛被崖壁切断」——症状像连通算法的问题，其实是几何没盖全。

    实现：
      1. 沿崖壁滑动 run+1 格，先找一段 5 条线**本来就全对**的位置（不动地形）；
      2. 找不到就「整形」：只要那 5 条线上的角点当前都还在 {lo, hi} 之内、且改动后
         相邻角点层差不超过 max_jump，就把 5 条线直接压成 lo/lo/lo/hi/hi。
         官方地图上的崖壁是 WE 刷出来的、天然齐整；我们的噪声地形常常是斜着走的
         锯齿崖（每两行错开一列），任何长度上都找不到齐整段，只能就地整形。

    返回 True/False。成功时 layer / ramp / zero_fine 已被就地修改。
    """
    def fail(msg):
        if trace is not None:
            trace.append(msg)
        return False

    rows, cols = layer.shape
    r, c = u
    r2, c2 = v
    dr, dc = r2 - r, c2 - c
    if abs(dr) + abs(dc) != 1 or lv_u == lv_v:
        return fail("不相邻或同层")
    hi, lo = max(lv_u, lv_v), min(lv_u, lv_v)
    if hi - lo != 1:
        return fail(f"层差 {hi - lo} ≠ 1")
    u_is_hi = lv_u == hi

    # 沿「垂直于崖壁」的轴：u 的外围线、共享线、v 的外围线，三条依次相邻
    if dc:
        axis = 0
        far_u = c if dc > 0 else c + 1
        shared = c + 1 if dc > 0 else c
        far_v = c + 2 if dc > 0 else c - 1
        n_perp, n_along = cols, rows
        base = r
    else:
        axis = 1
        far_u = r if dr > 0 else r + 1
        shared = r + 1 if dr > 0 else r
        far_v = r + 2 if dr > 0 else r - 1
        n_perp, n_along = rows, cols
        base = c

    far_hi = far_u if u_is_hi else far_v
    far_lo = far_v if u_is_hi else far_u
    dir_hi = 1 if far_hi > shared else -1
    dir_lo = 1 if far_lo > shared else -1
    out_hi = far_hi + dir_hi
    out_lo = far_lo + dir_lo
    p_lo, p_hi = min(out_lo, out_hi), max(out_lo, out_hi)
    if p_lo < margin or p_hi > n_perp - 1 - margin:
        return fail(f"贴边 (角点线 {p_lo}..{p_hi}, 需 ≥{margin})")

    def cell(a, p):
        return (a, p) if axis == 0 else (p, a)

    # 5 条角点线的目标层位：低侧 3 条全 lo，高侧 2 条全 hi
    want = ((out_lo, lo), (far_lo, lo), (shared, lo), (far_hi, hi), (out_hi, hi))
    want_of = dict(want)
    band = (far_lo, shared, far_hi)          # ramp 位只打这 3 条（官方口径）

    offsets = (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6)
    reasons = []
    forced = None
    for off in offsets:
        a0 = base - run // 2 + off
        a1 = a0 + run
        if abs(off) > run * 2 or a0 < margin or a1 > n_along - 1 - margin:
            continue
        clean = True          # 5 条线本来就全对
        legal = True          # 整形不越界：都在 {lo,hi} 内、邻居层差也够近
        bad = None
        for a in range(a0, a1 + 1):
            for p in range(p_lo, p_hi + 1):
                rr, cc = cell(a, p)
                if is_water[rr, cc]:
                    clean = legal = False
                    bad = f"off{off:+d}@a{a}: 角点线 {p} 带水"
                    break
                cur = int(layer[rr, cc])
                if cur == want_of[p]:
                    continue
                clean = False
                if cur != lo and cur != hi:
                    legal = False
                    bad = f"off{off:+d}@a{a}: 角点线 {p} 层位={cur} 不在 {{{lo},{hi}}} 内"
                    break
                for na, np_ in ((a - 1, p), (a + 1, p),
                                (a, p - 1), (a, p + 1)):
                    if na < 0 or na >= n_along or np_ < 0 or np_ >= n_perp:
                        legal = False
                        break
                    nb = int(layer[cell(na, np_)])
                    if nb < lo - 1 or nb > hi + 1:
                        legal = False
                        bad = (f"off{off:+d}@a{a}: 整形会与邻格 {nb} 差超过 "
                               f"{max_jump} 层")
                        break
                if not legal:
                    break
            if not legal:
                break
        if clean:
            return _commit(layer, ramp, zero_fine, want, band, cell, a0, a1, mark=None)
        if force and legal and forced is None:
            forced = (off, a0, a1)
        if bad:
            reasons.append(bad)
    if forced is not None:
        off, a0, a1 = forced
        return _commit(layer, ramp, zero_fine, want, band, cell, a0, a1, mark=off)
    return fail("; ".join(reasons[:3]) if reasons else "无可用偏移")


def _commit(layer, ramp, zero_fine, want, band, cell, a0, a1, mark=None):
    """把 5 条角点线压成 want 的目标层位，并给中间 3 条打 ramp 位、抹平起伏。"""
    for a in range(a0, a1 + 1):
        for p, t in want:
            rr, cc = cell(a, p)
            layer[rr, cc] = t
    for a in range(a0, a1 + 1):
        for p in band:
            rr, cc = cell(a, p)
            ramp[rr, cc] = True
            zero_fine[rr, cc] = True
    return True



def carve_ramps(layer, is_water, max_ramps=None, cliff_cost=6, cand_cap=0,
                edge_cost=8, edge_band=2, run=4, margin=2, max_jump=2, force=True):
    """按连通性需要刻斜坡，保证每块台地都有通道。

    做法:
      1. 每块台地（四角同层的连通平地）是一个节点；
      2. 多源 Dijkstra 向外扩张（穿过崖壁的代价高、贴地图边更贵），得到台地邻接图；
      3. 在邻接图上跑 Kruskal 最小生成树，确定「连通哪几对台地、从哪个口子过」；
      4. 在每个选中的口子上「盖」一条 WE 合法斜坡（见 _stamp_ramp）。

    cand_cap: 每对台地最多试几个候选口子（0 = 不限）。**别调小**：Dijkstra 最省的
    那几个口子恰好落在崖壁最薄最碎的「尖角」上（两块台地只在一个锯齿点相碰），
    那里高侧台地厚度不足，盖不上官方几何的斜坡；而真正齐整的崖段往往排在后面。
    实测 128x128 图：上限 8 → 有一对台地的 8 个最省口子全废、整岛被切断；
    上限 ≥16 才能选到合格口子。默认不限，靠「成功即 break」自然收口。

    返回 (ramp, layer, zero_fine, info)。注意 **layer 会被就地修改**：
    盖章时要压下共享角点线，而连通性自检必须用改完之后的层位。
    """
    spread, grad, line, dry = _tile_derivatives(layer, is_water)
    H, W = spread.shape
    # 只要「四角都不带水」就算通路：崖壁瓦片也能走（代价高而已）。
    # 早先这里加了 spread<=2 的门槛，会漏掉相邻角点层差 2 造成的 spread=3/4 瓦片，
    # 把同一座岛上的两块台地误判成「互不相邻」→ 那座岛永远补不上斜坡。
    passable = dry
    flat = (spread == 0) & dry
    lab, nlab = _components(flat)
    empty = np.zeros(layer.shape, dtype=bool)
    if nlab <= 1 or (lab < 0).all():
        return empty, layer, empty, {
            "components": int(nlab), "ramps": 0, "candidates": 0, "skipped": 0}

    # 代价图：平地便宜、崖壁贵；贴地图边再贵一点（不禁止，只在别无选择时才走边）
    wmap = np.where(flat, 1, cliff_cost).astype(np.int32)
    b = max(0, int(edge_band))
    if b and H > 2 * b and W > 2 * b:
        wmap[:b, :] += edge_cost
        wmap[-b:, :] += edge_cost
        wmap[:, :b] += edge_cost
        wmap[:, -b:] += edge_cost

    dist, owner, prev = _multi_dijkstra(lab, passable, wmap)
    plevel = _plateau_levels(lab, nlab, layer)

    # 候选口子条目 = (权重, 低侧瓦片索引, 高侧瓦片索引, 低侧层位, 高侧层位)。
    # 显式带上两个层位，别在盖章时再从 key 反推 —— key 是排序过的 owner 对，
    # 跟 u/v 的先后顺序无关，反推会把「谁高谁低」搞反、几何整个镜像。
    def add(pair_lists, o1, o2, w, u, v, lu, lv):
        if o1 < 0 or o2 < 0 or o1 == o2:
            return
        pair_lists.setdefault((min(o1, o2), max(o1, o2)), []).append((w, u, v, lu, lv))

    def owner_at(rr, cc):
        if 0 <= rr < H and 0 <= cc < W:
            return int(owner[rr, cc])
        return -1

    # 口子来源①（首选）：直接读「崖壁瓦片」的层位跳变方向。
    # 斜坡是垂直于崖壁的一条带，所以带的方向必须跟真实崖壁垂直。只按「相邻瓦片
    # owner 不同」找口子（来源②）会翻车：那种相邻只是 Dijkstra 的分界，在锯齿崖上
    # 常常**跟崖壁走向平行**，盖出来的带会横切台地、把台地拦腰切断（切下来的碎块
    # 就成了连不上的孤岛）。这里从一个 spread==1 的崖壁瓦片反推：四角谁低谁高就
    # 知道墙在哪条角点线上、低侧/高侧瓦片各是谁 —— 带的方向天然正确。
    # 台地身份用「墙外侧再一格」的瓦片 owner 去认（2u-v / 2v-u），不能用 u/v 自己
    # 的 owner：崖壁瓦片常被判给高侧那块台地，那样两边 owner 相同、口子直接被丢掉。
    cliff_mouths = {}
    for r in range(H):
        for c in range(W):
            a = layer[r, c]; b = layer[r, c + 1]
            cc = layer[r + 1, c]; d = layer[r + 1, c + 1]
            lo = min(a, b, cc, d); hi = max(a, b, cc, d)
            if hi - lo != 1:
                continue
            if is_water[r, c] or is_water[r, c + 1] or is_water[r + 1, c] or is_water[r + 1, c + 1]:
                continue
            u = v = None
            if a == cc and b == d and a != b:            # 墙沿列方向
                u, v = ((r, c), (r, c + 1)) if a == lo else ((r, c + 1), (r, c))
            elif a == b and cc == d and a != cc:         # 墙沿行方向
                u, v = ((r, c), (r + 1, c)) if a == lo else ((r + 1, c), (r, c))
            if u is None:
                continue                                  # 对角跳变，带方向不明确
            # 崖壁瓦片可以在最后一行/列，但「墙外侧那一格」的瓦片必须真实存在
            if not (0 <= u[0] < H and 0 <= u[1] < W
                    and 0 <= v[0] < H and 0 <= v[1] < W):
                continue
            o1 = owner_at(2 * u[0] - v[0], 2 * u[1] - v[1])
            o2 = owner_at(2 * v[0] - u[0], 2 * v[1] - u[1])
            if o1 < 0:
                o1 = int(owner[u])
            if o2 < 0:
                o2 = int(owner[v])
            add(cliff_mouths, o1, o2, int(dist[u]) + int(dist[v]),
                u[0] * W + u[1], v[0] * W + v[1], lo, hi)

    # 口子来源②（兜底）：相邻瓦片 owner 不同。方向不一定对，只在来源①给不出
    # 口子时才用（否则这一对台地就完全连不上了）。
    adj_mouths = {}
    for r in range(H):
        for c in range(W):
            o = int(owner[r, c])
            if o < 0:
                continue
            for nr, nc in ((r + 1, c), (r, c + 1)):
                if nr >= H or nc >= W:
                    continue
                o2 = int(owner[nr, nc])
                if o2 < 0 or o2 == o:
                    continue
                add(adj_mouths, o, o2, int(dist[r, c]) + int(dist[nr, nc]),
                    r * W + c, nr * W + nc, int(plevel[o]), int(plevel[o2]))

    cand = {}
    for k, lst in adj_mouths.items():
        cand[k] = sorted(cliff_mouths.get(k, [])) + sorted(lst)
    for k, lst in cliff_mouths.items():
        if k not in cand:
            cand[k] = sorted(lst)
    if cand_cap:
        for lst in cand.values():
            del lst[cand_cap:]

    parent = list(range(nlab))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ramp = np.zeros(layer.shape, dtype=bool)
    zero_fine = np.zeros(layer.shape, dtype=bool)
    carved = 0
    skipped = 0
    for key, lst in sorted(cand.items(), key=lambda kv: kv[1][0][0]):
        if find(key[0]) == find(key[1]):
            continue
        lv1, lv2 = int(plevel[key[0]]), int(plevel[key[1]])
        if abs(lv1 - lv2) != 1:          # 官方斜坡层差恒为 1，跨 2 层的口子不盖
            skipped += 1
            continue
        stamped = False
        # 优先「不动地形就能盖」的口子，找不到齐整崖段才允许整形。
        # 整形会改动 5 条角点线上的角点，在台地又窄又碎的地方容易把台地拦腰切断
        # （切下来的碎块就成了连不上的孤岛），所以能不整形就不整形。
        for rr in (run, max(2, run - 1), max(2, run - 2)):
            for fc in ((True, False) if force else (False,)):
                for _, u, v, lu, lv in lst:
                    r, c = divmod(u, W)
                    r2, c2 = divmod(v, W)
                    if _stamp_ramp(layer, is_water, ramp, zero_fine,
                                   (r, c), (r2, c2), lu, lv, rr, margin,
                                   force=fc, max_jump=max_jump):
                        stamped = True
                        break
                if stamped:
                    break
            if stamped:
                break
        if not stamped:                  # 整段崖壁都不齐整，这一对台地这次连不上
            skipped += 1
            continue
        parent[find(key[0])] = find(key[1])
        carved += 1
        if max_ramps is not None and carved >= max_ramps:
            break
    return ramp, layer, zero_fine, {
        "components": int(nlab), "ramps": carved,
        "candidates": len(cand), "skipped": skipped}


def clean_regions(code, min_island=32, min_lake=16):
    """清理碎岛碎塘:

      * 面积 < min_island 的陆地碎岛 → 并入水（贴地图边界的照样清，那里本来就不可达）；
      * 面积 < min_lake 且**不贴**地图边界的内陆水塘 → 填成邻域最常见的陆地高度
        （贴边的水域当成海，不动）。
    """
    code = code.copy()
    R, C = code.shape
    changed_i = changed_w = 0

    def border_components(mask, lab, n):
        """返回与地图最外圈相接的连通块编号集合。"""
        edge = np.zeros_like(mask)
        edge[0, :] = edge[-1, :] = True
        edge[:, 0] = edge[:, -1] = True
        hit = lab[mask & edge]
        return set(int(v) for v in np.unique(hit) if v >= 0)

    if min_island > 0:
        lab, n = _components(code > 0)
        for i in range(n):
            m = lab == i
            if m.sum() < min_island:
                code[m] = 0
                changed_i += 1

    if min_lake > 0:
        lab, n = _components(code == 0)
        ocean = border_components(code == 0, lab, n)
        for i in range(n):
            m = lab == i
            if m.sum() >= min_lake or i in ocean:
                continue
            vals = []
            ys, xs = np.nonzero(m)
            for y, x in zip(ys, xs):
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < R and 0 <= nx < C and code[ny, nx] > 0:
                        vals.append(int(code[ny, nx]))
            if not vals:
                continue
            code[m] = int(np.bincount(np.array(vals)).argmax())
            changed_w += 1
    return code, changed_i, changed_w


def connectivity_report(layer, is_water, ramp):
    """逐个陆地岛检查「岛内可走区域是否连成一体」。

    注意不能拿「陆地连通块数」和「可走连通块数」直接比：前者把崖壁瓦片也算进去，
    口径不同永远不可能相等。正确判据是——对每个陆地岛，落在它里面的可走瓦片
    只能属于同一个可走连通块。
    返回 (陆地岛数, 可走连通块数, 被崖壁切断的岛数)。
    """
    spread, grad, line, dry = _tile_derivatives(layer, is_water)
    flat = (spread == 0) & dry
    all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
    walk = flat | all4
    ilab, n_island = _components(dry)
    wlab, n_walk = _components(walk)
    bad = 0
    for i in range(n_island):
        labels = np.unique(wlab[(ilab == i) & walk])
        labels = labels[labels >= 0]
        if labels.size > 1:
            bad += 1
    return int(n_island), int(n_walk), int(bad)


def _cand_levels(layer, ys, xs):
    """碎块周围（紧邻角点）出现过的层位，按出现次数降序 —— 合并目标候选。"""
    seen, vals = set(), []
    rows, cols = layer.shape
    for y, x in zip(ys, xs):
        for yy, xx in ((y, x), (y, x + 1), (y + 1, x), (y + 1, x + 1)):
            for ny, nx in ((yy - 1, xx), (yy + 1, xx), (yy, xx - 1), (yy, xx + 1)):
                if 0 <= ny < rows and 0 <= nx < cols and (ny, nx) not in seen:
                    seen.add((ny, nx))
                    vals.append(int(layer[ny, nx]))
    if not vals:
        return []
    v, c = np.unique(np.array(vals), return_counts=True)
    return [int(v[k]) for k in np.argsort(-c)]


def _local_merge_ok(layer, is_water, ramp, keep, ys, xs, tgt, max_jump):
    """在局部窗口里试算：把碎块压到 tgt 后，层差不超标且碎块能接上主块。"""
    r0 = max(0, int(ys.min()) - 2)
    r1 = min(layer.shape[0], int(ys.max()) + 5)
    c0 = max(0, int(xs.min()) - 2)
    c1 = min(layer.shape[1], int(xs.max()) + 5)
    sub = layer[r0:r1, c0:c1].copy()
    ys2, xs2 = ys - r0, xs - c0
    for y, x in zip(ys2, xs2):
        sub[y, x] = sub[y, x + 1] = sub[y + 1, x] = sub[y + 1, x + 1] = tgt
    # 只看改动点附近的层差：窗口里本来就有别处的崖壁，全窗口取最大值会误判
    for y, x in zip(ys2, xs2):
        for yy, xx in ((y, x), (y, x + 1), (y + 1, x), (y + 1, x + 1)):
            for ny, nx in ((yy - 1, xx), (yy + 1, xx), (yy, xx - 1), (yy, xx + 1)):
                if 0 <= ny < sub.shape[0] and 0 <= nx < sub.shape[1]:
                    if abs(int(sub[ny, nx]) - tgt) > max_jump:
                        return False
    water = is_water[r0:r1, c0:c1]
    rsub = ramp[r0:r1, c0:c1]
    spread = (np.maximum(np.maximum(sub[:-1, :-1], sub[:-1, 1:]),
                         np.maximum(sub[1:, :-1], sub[1:, 1:]))
              - np.minimum(np.minimum(sub[:-1, :-1], sub[:-1, 1:]),
                           np.minimum(sub[1:, :-1], sub[1:, 1:])))
    dry_t = ~(water[:-1, :-1] | water[:-1, 1:] | water[1:, :-1] | water[1:, 1:])
    walk_t = ((spread == 0) & dry_t) | (rsub[:-1, :-1] & rsub[:-1, 1:]
                                        & rsub[1:, :-1] & rsub[1:, 1:])
    keep_t = keep[r0:r1 - 1, c0:c1 - 1]
    # 从碎块往外泛洪，看能不能碰到主块
    H, W = walk_t.shape
    seen = np.zeros_like(walk_t, dtype=bool)
    stack = [(int(ys2[0]), int(xs2[0]))]
    if not walk_t[stack[0]]:
        return False
    seen[stack[0]] = True
    while stack:
        y, x = stack.pop()
        if keep_t[y, x]:
            return True
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < H and 0 <= nx < W and walk_t[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                stack.append((ny, nx))
    return False


def merge_orphan_flats(layer, is_water, ramp, min_area=24, max_jump=2, rounds=6):
    """把被斜坡端头切下来的「孤立小块可走平地」并进同岛的主可走块。

    刻斜坡要在崖壁上压出 5 条整齐角点线，斜坡两个端头必然切出新崖壁；如果端头
    原本是一片平地，就会被切下一小块（几格）孤立出来。这种碎片在 WE 里就是几格
    上不去的台地，留着既难看又让连通性自检一直报「有 1 座岛被崖壁切断」。
    做法：逐岛取面积最大的可走块为主块，其余 <= min_area 的纯平地碎块，按邻接
    角点出现过的层位逐个试算（局部泛洪确认真能接上主块）后整体压过去。
    含 ramp 位的碎块属于斜坡本体，不动。返回合并掉的碎块数，layer 就地修改。
    """
    merged = 0
    for _ in range(rounds):
        spread, grad, line, dry = _tile_derivatives(layer, is_water)
        flat = (spread == 0) & dry
        all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
        walk = flat | all4
        ilab, n_isl = _components(dry)
        wlab, n_walk = _components(walk)
        did = 0
        for i in range(n_isl):
            m_isl = ilab == i
            ws = [int(v) for v in np.unique(wlab[m_isl & walk]) if v >= 0]
            if len(ws) <= 1:
                continue
            sizes = {w: int(((wlab == w) & m_isl).sum()) for w in ws}
            main = max(sizes, key=sizes.get)
            if sizes[main] < min_area * 3:
                continue                      # 岛上没有明显的主块，不动
            keep = wlab == main
            for w in ws:
                if w == main or sizes[w] > min_area or sizes[w] * 4 >= sizes[main]:
                    continue
                m = wlab == w
                ys, xs = np.nonzero(m)
                if not flat[ys, xs].all():
                    continue                  # 含 ramp 位 → 是斜坡的一部分
                for tgt in _cand_levels(layer, ys, xs):
                    if _local_merge_ok(layer, is_water, ramp, keep, ys, xs,
                                       tgt, max_jump):
                        for y, x in zip(ys, xs):
                            layer[y, x] = layer[y, x + 1] = tgt
                            layer[y + 1, x] = layer[y + 1, x + 1] = tgt
                        did += 1
                        break
        merged += did
        if did == 0:
            break
    return merged


def ramp_report(layer, ramp):
    """斜坡几何自检：把 ramp 角点按连通块分组，核对是否符合官方几何。

    官方基准（51 张官方地图 / 3116 个 ramp 瓦片）：
      * 垂直于崖壁的厚度 = 3 条角点线（252/356 块），即 2 个瓦片；
      * 瓦片构成 = 1 个「四角全低」的基地瓦片 + 1 个「2 低 2 高」的台阶瓦片，
        且两者四角全带 ramp 位；
      * 层差恒为 1。
    这里返回若干行文本，供主流程打印。
    """
    H, W = ramp.shape
    seen = np.zeros_like(ramp, dtype=bool)
    blocks = []
    for r0 in range(H):
        for c0 in range(W):
            if not ramp[r0, c0] or seen[r0, c0]:
                continue
            stack = [(r0, c0)]
            seen[r0, c0] = True
            n = 0
            rmin = rmax = r0
            cmin = cmax = c0
            while stack:
                r, c = stack.pop()
                n += 1
                rmin, rmax = min(rmin, r), max(rmax, r)
                cmin, cmax = cmin, max(cmax, c)
                for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= nr < H and 0 <= nc < W and ramp[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        stack.append((nr, nc))
            blocks.append((n, rmax - rmin + 1, cmax - cmin + 1))
    if not blocks:
        return ["斜坡几何自检: 无斜坡"]
    thick = Counter(min(bw, bh) for _, bw, bh in blocks)
    # 瓦片构成核对
    step = flat_low = flat_high = other = 0
    for r in range(H - 1):
        for c in range(W - 1):
            q = (layer[r, c], layer[r, c + 1], layer[r + 1, c], layer[r + 1, c + 1])
            if not (ramp[r, c] and ramp[r, c + 1] and ramp[r + 1, c] and ramp[r + 1, c + 1]):
                continue
            u = sorted(set(q))
            if len(u) == 1:
                flat_low += 1
            elif len(u) == 2 and u[1] - u[0] == 1 and q.count(u[0]) == 2:
                step += 1
            elif len(u) == 2 and u[1] - u[0] == 1:
                flat_high += 1
            else:
                other += 1
    ok = (thick.get(3, 0) == len(blocks)) and other == 0
    return [
        f"斜坡几何自检: {len(blocks)} 块  {'✔ 全部符合官方几何' if ok else '✘ 有异常'}",
        f"  垂直崖壁厚度分布(角点线数): {dict(sorted(thick.items()))}"
        f"   ← 官方主导值 3",
        f"  瓦片构成: 台阶(2低2高) {step} / 四角全低基地 {flat_low}"
        f" / 四角全高 {flat_high} / 其他 {other}",
    ]


def tile_layer(layer):
    """每个瓦片取四角均值取整，作为该瓦片的层值。"""
    a = layer[:-1, :-1].astype(np.int32); b = layer[:-1, 1:].astype(np.int32)
    c = layer[1:, :-1].astype(np.int32); d = layer[1:, 1:].astype(np.int32)
    return ((a + b + c + d + 2) // 4).astype(np.int16)


def despeckle_layers(layer, min_area=8, passes=3, max_jump=1):
    """把过小的台地并进相邻台地，减少碎斑；返回 (新 layer, 合并次数)。"""
    layer = layer.copy()
    merged = 0
    for _ in range(passes):
        tl = tile_layer(layer)
        H, W = tl.shape
        lab = np.full((H, W), -1, dtype=np.int32)
        cur = 0
        comps = []
        for r in range(H):
            for c in range(W):
                if lab[r, c] >= 0:
                    continue
                v = tl[r, c]
                stack = [(r, c)]
                lab[r, c] = cur
                cells = []
                while stack:
                    y, x = stack.pop()
                    cells.append((y, x))
                    for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                        if 0 <= ny < H and 0 <= nx < W and lab[ny, nx] < 0 and tl[ny, nx] == v:
                            lab[ny, nx] = cur
                            stack.append((ny, nx))
                comps.append((v, cells))
                cur += 1
        changed = False
        for v, cells in comps:
            if len(cells) >= min_area:
                continue
            # 统计相邻台地的层值，取最常见的并进去
            near = []
            for y, x in cells:
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < H and 0 <= nx < W and tl[ny, nx] != v:
                        near.append(int(tl[ny, nx]))
            if not near:
                continue
            target = int(np.bincount(np.array(near)).argmax())
            for y, x in cells:
                layer[y:y + 2, x:x + 2] = target
            merged += 1
            changed = True
        if changed:
            layer = limit_neighbor_jump(layer, max_jump=max_jump)
        if not changed:
            break
    return layer, merged


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
    args = []
    opts = {}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k, sep, v = a[2:].partition("=")
            if sep:
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]
                i += 1
            else:
                opts[k] = True
        else:
            args.append(a)
        i += 1

    if not args:
        print(__doc__)
        return 1
    map_path = args[0]
    seed = int(opts.get("seed", 20260915))
    freq = float(opts.get("freq", 1.6))
    # 高度层区间：地形（含水面之上的全部陆地台地）只占 [layer_min, layer_max] 这几层。
    # WE 里每上/下一层线 = 128 高度单位，所以层区间直接决定「悬崖能爬多高」。
    layer_min = int(opts.get("layer-min", LAYER_ZERO))
    levels = int(opts.get("layers", 4))
    layer_max = int(opts.get("layer-max", layer_min + levels - 1))
    water_frac = float(opts.get("water", 0.30))
    octaves = int(opts.get("octaves", 2))
    max_jump = int(opts.get("max-jump", 2))
    smooth = int(opts.get("smooth", 2))
    level_bias = float(opts.get("level-bias", 2.0))
    ramps_opt = str(opts.get("ramps", "auto"))
    ramp_run = int(opts.get("ramp-run", 4))
    ramp_force = str(opts.get("ramp-force", "1")) not in ("0", "false", "no")
    cliff_tex_opt = str(opts.get("cliff-texture", "auto"))
    boundary_mode = str(opts.get("boundary", "ring")).lower()
    exe = opts.get("exe") or default_exe()
    preview = opts.get("preview")
    out_path = opts.get("out")

    if not (0 <= water_frac < 1):
        print("--water 必须在 [0, 1) 之间")
        return 1
    if level_bias <= 0:
        print("--level-bias 必须大于 0（1=各层等面积，越大越低平）")
        return 1
    if ramp_run < 1:
        print("--ramp-run 至少为 1（斜坡沿崖壁方向的瓦片数）")
        return 1
    if boundary_mode not in ("ring", "none", "keep"):
        print("--boundary 只能是 ring（默认，只留最外一圈）/ none（全清）/ keep（保留模板）")
        return 1
    if layer_min < 1:
        print("--layer-min 至少为 1（水面要占最低一层，层号 0 会让岸边没有落差）")
        return 1
    if layer_max < layer_min:
        print(f"--layer-max({layer_max}) 不能小于 --layer-min({layer_min})")
        return 1
    if layer_max > MAX_LAYER:
        print(f"最高层 {layer_max} 超过合法上限 {MAX_LAYER}，请调小 --layer-max")
        return 1
    nlev = layer_max - layer_min + 1     # 陆地实际用到的层数
    water_layer = layer_min - 1          # 水面固定比最低层陆地再低一层

    tmp = make_tmp("genheight")

    target = map_path
    if out_path:
        shutil.copy2(map_path, out_path)
        target = out_path
        print(f"已复制模板到 {out_path}")
    elif opts.get("no-backup"):
        pass                                   # 调用方（random_map）已经自己复制过模板了，
                                               # 再给这份副本做备份纯属堆垃圾
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(os.path.dirname(HERE), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup = os.path.join(backup_dir, f"{os.path.basename(map_path)}.{stamp}.bak")
        shutil.copy2(map_path, backup)
        print(f"备份原图: {backup}")
        # 顺手清掉同名旧备份，只留最近 100 个：跑上千次实验也不会把目录撑爆
        try:
            stem = os.path.basename(map_path) + "."
            olds = sorted(f for f in os.listdir(backup_dir)
                          if f.startswith(stem) and f.endswith(".bak"))
            for f in olds[:-100]:
                os.remove(os.path.join(backup_dir, f))
        except BaseException:
            pass

    # 1. 取出来
    subprocess.run([exe, "extract", target, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=120)
    w3e_path = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(w3e_path):
        print("提取 war3map.w3e 失败")
        return 1

    data = bytearray(open(w3e_path, "rb").read())
    if data[:4] != b"W3E!":
        print("不是 w3e 文件")
        return 1
    info = read_header(data)
    W, H, HS = info["width"], info["height"], info["header"]
    rows, cols = H + 1, W + 1
    size = len(data) - HS
    per = size // (rows * cols)
    if per != 7:
        print(f"该文件每角点 {per} 字节，本脚本只支持 v11 (7 字节)")
        return 1
    print(f"{os.path.basename(target)}: {W}x{H}  角点 {cols}x{rows}  v{info['version']}  "
          f"tileset={info['tileset']}  cliff={info['cliff']}")

    nprng = np.random.default_rng(seed)

    # 2. 噪声 → 高度场
    height = fbm(nprng, (rows, cols), freq, octaves=octaves)
    # 按秩重分布成均匀分位，这样 --water 才是精确的水域占比
    order = np.argsort(height, axis=None)
    quant = np.empty(height.size, dtype=np.float32)
    quant[order] = np.linspace(0.0, 1.0, height.size, dtype=np.float32)
    quant = quant.reshape(height.shape)

    is_water = quant < water_frac
    land_q = (quant - water_frac) / (1.0 - water_frac)
    # 层位偏置：秩均匀分位会让每个层位各占 1/levels 土地，地形变成马赛克。
    # 取幂 → 压低层（平地）的面积占比，还原「大片平地 + 少量高地」的重尾分布。
    lvl = np.clip(np.floor(np.power(land_q, level_bias) * nlev), 0, nlev - 1)
    code = np.where(is_water, 0, 1 + lvl.astype(np.int32))
    if smooth > 0:
        code = mode_filter(code, passes=smooth, values=nlev + 2)
    # 清碎岛碎塘：留下成片的陆地和大块水域，避免地图被噪声打成筛子
    min_island = int(opts.get("min-island", 32))
    min_lake = int(opts.get("min-lake", 16))
    if min_island > 0 or min_lake > 0:
        code, n_island_fix, n_lake_fix = clean_regions(
            code, min_island=min_island, min_lake=min_lake)
        if n_island_fix or n_lake_fix:
            print(f"清理碎块: 抹掉 {n_island_fix} 座小岛, 填平 {n_lake_fix} 个小水塘")
    is_water = code == 0
    # 水面比岸边低 1 层：官方地图的湖岸就是一层落差。
    # ⚠️ 这里必须用 layer_min 而不是 LAYER_ZERO —— 否则 --layer-min 只改了层数、
    #    地形却仍然画在 2 层起，日志里报的高度区间全是假的。
    layer = np.where(is_water, water_layer,
                     layer_min + (code - 1)).astype(np.int16)
    layer = limit_neighbor_jump(layer, max_jump=max_jump)

    # 去碎斑：把过小台地并入邻居（众数滤波已能解决大部分碎片化，默认关闭）
    min_area = int(opts.get("min-plateau", 0))
    if min_area > 0:
        layer, merged = despeckle_layers(layer, min_area=min_area, max_jump=max_jump)
        layer = np.where(is_water, water_layer, layer).astype(np.int16)
        print(f"去碎斑: 合并 {merged} 块过小台地（最小台地面积 {min_area} 格）")

    # 斜坡：auto = 按连通性需要自动刻，0 = 关闭，N = 最多刻 N 条
    if ramps_opt == "0":
        ramp = np.zeros(layer.shape, dtype=bool)
        zero_fine = np.zeros(layer.shape, dtype=bool)
        ramp_info = {"components": 0, "ramps": 0, "candidates": 0, "disabled": True}
    else:
        limit = None if ramps_opt == "auto" else int(ramps_opt)
        # 注意：carve_ramps 会就地修改 layer（斜坡要压共享角点线），后面一律用改后的
        ramp, layer, zero_fine, ramp_info = carve_ramps(
            layer, is_water, max_ramps=limit, run=ramp_run, max_jump=max_jump,
            force=ramp_force)
        if ramp_info.get("ramps"):
            n_fix = merge_orphan_flats(layer, is_water, ramp,
                                       min_area=int(opts.get("orphan-area", 24)),
                                       max_jump=max_jump)
            if n_fix:
                print(f"      斜坡收尾: 合并 {n_fix} 块被斜坡端头切断的孤立平地")

    # ---- 应用高度：隆起 / 凹陷 / 凹凸不平 ----
    # 这三项合成的是「同一台地内部」的起伏（layer 不变，所以不会变成悬崖），
    # 对应 WE 地形面板的「应用高度」笔刷：
    #   低频场 → 隆起（正的半边）/ 凹陷（负的半边）：大尺度的鼓包与凹坑，地形"性格"
    #   高频场 → 凹凸不平：表面颗粒感，避免整片地像一块塑料板
    # 幅度单位 = WE 高度单位（1 单位 = 高度条上 1 格 = 4 原始单位；一整层 = 128）。
    # 官方对战图实测（tools/_tmp/analyze_height.py）：低频 σ 典型 ≈ 70、
    # 高频 σ 典型 ≈ 32、两者合计的台地内残差 σ 典型 ≈ 87。
    raise_amp = float(opts.get("raise", 75.0))
    lower_amp = float(opts.get("lower", 75.0))
    rough_amp = float(opts.get("rough", 12.0))
    blob = float(opts.get("blob", 28.0))     # 隆起/凹陷团块尺寸（格）
    grain = float(opts.get("grain", 2.5))    # 凹凸不平颗粒尺寸（格）
    if "relief" in opts and opts["relief"] is not True:
        # 旧参数兼容：relief 的单位是「层」，1 层 = 128 WE 高度单位
        r = float(opts["relief"]) * 128.0
        raise_amp = lower_amp = r
    # 幅度封顶：超过一整层（128），鼓起来的部分就扎进上一层的崖壁里了
    CAP = 120.0
    if max(raise_amp, lower_amp, rough_amp) > CAP:
        over = [n for n, v in (("--raise", raise_amp), ("--lower", lower_amp),
                               ("--rough", rough_amp)) if v > CAP]
        print(f"注意：{'、'.join(over)} 超过一整层（128），已压到 {CAP:.0f}，"
              f"再大会穿进上层崖壁")
        raise_amp, lower_amp, rough_amp = (min(raise_amp, CAP), min(lower_amp, CAP),
                                           min(rough_amp, CAP))

    lf = unit_noise(nprng, (rows, cols), noise_cells(cols, blob), octaves=3)
    bell = np.where(lf > 0, lf * raise_amp, lf * lower_amp)   # 上半 隆起 / 下半 凹陷
    hf = unit_noise(nprng, (rows, cols), noise_cells(cols, grain),
                    octaves=int(opts.get("rough-octaves", 3)),
                    gain=float(opts.get("rough-gain", 0.6)))
    macro = bell * 4.0                         # WE 高度单位 → 原始单位
    # 台阶化：官方对战图的地面其实是「大片平坦面 + 陡坎」（实测 36%~64% 的相邻角点完全
    # 等高），不是处处连续的坡。把宏观起伏量化到 ledge 高的台阶就得到这个观感，
    # 对应 WE 里「高原/阶梯」笔刷。0 = 保持连续。
    # 只量化宏观起伏：细颗粒（凹凸不平）要叠在台阶之上，一起量化会被台阶吃掉。
    ledge = float(opts.get("ledge", 0.0))
    if ledge > 0:
        step_raw = max(1.0, ledge * 4.0)
        macro = np.round(macro / step_raw) * step_raw
    fine = macro + hf * rough_amp * 4.0        # WE 高度单位 → 原始单位

    # ---- 平整区域：留一些完全没有隆起/凹陷的地方 ----
    # 对应 WE 的「平整」笔刷。拿一块低频场取分位当"平整场"，核心区把起伏乘 0，
    # 边缘用一段斜坡过渡（硬边界看起来像被刀切的）。
    flat_frac = float(opts.get("flat", 0.15))
    flat_peak = 0.0
    wflat = np.ones_like(is_water, dtype=np.float32)
    if flat_frac > 0:
        flat_size = float(opts.get("flat-size", 20.0))
        ff = unit_noise(nprng, (rows, cols), noise_cells(cols, flat_size), octaves=2)
        # 稍微偏向低层：官方地图的平整区大多是平原，不会长在高台地上 → 低层 ff 更小
        ff = ff - 0.35 * (1.0 - code.astype(np.float32) / max(1.0, nlev))
        frac = min(0.9, flat_frac)
        thr = float(np.percentile(ff, frac * 100.0))          # 最低的那 frac 比例变平整
        span = max(1e-6, float(ff.max()) - thr)
        wflat = np.clip((ff - thr) / (span * 0.25), 0.0, 1.0).astype(np.float32)
        fine = fine * wflat
        flat_peak = float(np.mean(wflat < 0.05)) * 100.0

    # ---- 水体：浅水 / 深水 + 水下起伏 ----
    # 水面高度实测 = 浅水层顶（layer_min 的底线，默认 gh 8192）；官方对战图的水深全是
    # 整层的倍数，最常见 1 层（=128 WE 高度单位），其次 2 层，少数深达 4 层。
    # 所以：浅水底 = 水面下 1 层（沿用原设置），深水底 = 水面下 deep 层。
    # 水下也能有隆起/凹陷，但必须裁到「水底不冒出水面」以内 —— 实测余量正好是 1 层
    # （512 原始单位），留 1/4 层做安全边，所以向上的空间是 384 原始单位。
    plane_raw = GROUND_ZERO + (layer_min - LAYER_ZERO) * LAYER_STEP   # 水面世界高度
    guard = LAYER_STEP // 4
    shelf = max(0.0, float(opts.get("shelf", 3.0)))
    deep_layers = max(0, int(round(float(opts.get("deep", 1.0)))))
    deep_layers = min(deep_layers, water_layer)
    wrelief = max(0.0, float(opts.get("water-relief", 0.5)))
    deep_water = np.zeros_like(is_water)
    if is_water.any() and deep_layers > 0:
        dist = shore_distance(is_water)
        jit = unit_noise(nprng, (rows, cols), noise_cells(cols, max(4.0, shelf * 2.5)))
        edge = np.clip(shelf * (1.0 + 0.7 * jit), 0.5, None)   # 岸带宽度带抖动，别像描边
        deep_water = is_water & (dist > edge)
    land_only = ~is_water
    sigma_land = float(fine[land_only].std()) if land_only.sum() > 50 else 0.0
    # 注意单位：sigma_land 是原始单位（4 原始单位 = 1 WE 高度单位），
    # 向上余量 (LAYER_STEP - guard) 也是原始单位，两边必须一致。
    amp_w_raw = min(wrelief * sigma_land, (LAYER_STEP - guard) / 2.5)
    if sigma_land > 1e-6:
        relief_w = fine * (amp_w_raw / sigma_land)              # 原始单位，σ = amp_w_raw
        cap_sh = LAYER_STEP - guard                            # 浅水向上余量
        cap_dp = deep_layers * LAYER_STEP - guard              # 深水向上余量
        fine = np.where(is_water,
                        np.where(deep_water,
                                 np.minimum(relief_w, cap_dp),
                                 np.minimum(relief_w, cap_sh)),
                        fine)
    # 坡面不能有起伏，否则斜坡是"搓板路"，WE 拉出来的坡也不平滑
    fine = np.where(zero_fine, 0, fine).astype(np.int16)
    # 高度量化到 1 WE 单位（= 4 原始单位），与 WE 笔刷的粒度一致：实测官方地图
    # （如 GolemsInTheMist）台地内残差的取值全是 4 的倍数。照做才像手刷出来的地形。
    hstep = max(1, int(opts.get("height-step", 4)))
    if hstep > 1:
        fine = (np.round(fine.astype(np.float32) / hstep) * hstep).astype(np.int16)
    # 水格换到深水层：layer 降 deep_layers 层，WE 里就画出真正的深水（颜色更暗）
    layer = np.where(deep_water, max(0, water_layer - deep_layers),
                     np.where(is_water, water_layer, layer)).astype(np.int16)

    # 起伏指标只在「非平整区的陆地」上统计：平整区本来就没有起伏，算进去会把
    # 官方的基准值带偏，看不出隆起/凹陷到底调对没有。
    meas = land_only & (wflat >= 0.95) if flat_frac > 0 else land_only
    tot_s, low_s, high_s = relief_stats(fine, meas)
    tail = "，不含平整区" if flat_frac > 0 else ""
    print(f"应用高度: 隆起 σ={raise_amp:.0f}  凹陷 σ={lower_amp:.0f}  "
          f"凹凸不平 σ={rough_amp:.0f}（WE 高度单位）"
          f"　团块 {blob:g} 格 / 颗粒 {grain:g} 格"
          + (f" / 台阶 {ledge:g}" if ledge > 0 else ""))
    print(f"      实测层内起伏(陆地{tail}): 合计 σ={tot_s:.0f}  低频 σ={low_s:.0f}  "
          f"高频 σ={high_s:.0f}   ← 官方对战图典型 87 / 70 / 32")
    if flat_frac > 0:
        print(f"平整区域: 约 {flat_peak:.1f}% 的陆地完全没有隆起/凹陷"
              f"（团块 {float(opts.get('flat-size', 20.0)):g} 格）")
    if is_water.any():
        n_sh = int((is_water & ~deep_water).sum())
        n_dp = int(deep_water.sum())
        if deep_layers > 0:
            print(f"水体: 浅水 {n_sh} 角点（水面下 1 层）/ 深水 {n_dp} "
                  f"（水面下 {1 + deep_layers} 层，离岸 > {shelf:g} 格）；"
                  f"水下起伏 σ={amp_w_raw / 4:.0f}（陆地起伏的 {wrelief * 100:.0f}%，"
                  f"向上裁到 {LAYER_STEP - guard} 原始单位以内）")
        else:
            print(f"水体: 全浅水 {n_sh} 角点（水面下 1 层，深水已关闭）；"
                  f"水下起伏 σ={amp_w_raw / 4:.0f}（陆地起伏的 {wrelief * 100:.0f}%，"
                  f"向上裁到 {LAYER_STEP - guard} 原始单位以内）")

    # 悬崖贴图：官方地图整张图用同一套（LostTemple 全是 index 1 = CLgr），
    # 而 WE 新建的空模板是 15（未指定）。逐角点随机是错的，会让崖壁贴图忽明忽暗。
    n_cliff = max(1, len(info["cliff"]))
    if cliff_tex_opt == "auto":
        cliff_tex = 1 if n_cliff >= 2 else 0
    else:
        cliff_tex = int(cliff_tex_opt) % max(1, min(n_cliff, 16))
    cliff_texture = np.full((rows, cols), cliff_tex, dtype=np.uint8)
    # 悬崖变体：官方实测的分布（0 占 45%，4 占 29%，1 占 18%，其余零星）。
    # 这个字段与斜坡无关（ramp 与普通崖壁分布几乎一致），纯粹是外观。
    cliff_variation = nprng.choice(
        8, size=(rows, cols),
        p=[0.45, 0.18, 0.018, 0.003, 0.29, 0.036, 0.018, 0.005]).astype(np.uint8)
    ground_variation = nprng.integers(0, 32, size=(rows, cols), dtype=np.uint8)

    # 3. 逐角点写回
    water_corners = 0
    blight_kept = 0
    tpl_b1 = tpl_b2 = 0          # 模板自带的两种边界标记数量（只统计，用于日志）
    for cy in range(rows):
        file_row = rows - 1 - cy      # 文件自下而上存行，图像第 0 行是地图顶部
        base = HS + file_row * cols * per
        for cx in range(cols):
            off = base + cx * per
            gh = GROUND_ZERO + int(fine[cy, cx])
            # 水面高度：必须跟着 layer_min 走。写死 8192 的话，一旦把最低层抬高
            # （例如 --layer-min 6），水面就落到地形下面，整张图一滴水都看不到。
            wh = plane_raw
            # 模板自带的 0x80(flags) / 0x4000(waterHeight) 是「地图边界外」标记：
            # 带它的瓦片寻路可走率 0%。LostTemple 拿它盖了 40% 的角点（真正的地图外框），
            # WE 自建的空模板则用它标出「游玩区之外的留白边框」。
            # 我们要的是整张可玩地图，所以默认整图清零、只在最外一圈补回（boundary=ring）。
            # 唯一保留的原有标记是 blight（枯地）。
            orig_flags = data[off + 4]
            orig_b1 = struct.unpack_from("<H", data, off + 2)[0] & BOUNDARY_BIT
            flags = orig_flags & BLIGHT_FLAG
            if orig_flags & BLIGHT_FLAG:
                blight_kept += 1
            if orig_flags & BOUNDARY2_FLAG:
                tpl_b2 += 1
            if orig_b1:
                tpl_b1 += 1
            if ramp[cy, cx]:
                flags |= RAMP_FLAG
            if is_water[cy, cx]:
                flags |= WATER_FLAG
                water_corners += 1
            edge = cy in (0, rows - 1) or cx in (0, cols - 1)
            if boundary_mode == "keep":
                # 保留模板自己的边框：0x4000 原样留着，并把 0x80 同步到同一批角点
                # （实测这两个位是同一个「地图外」概念的两份拷贝，必须一致）。
                boundary = orig_b1
                if boundary:
                    flags |= BOUNDARY2_FLAG
            elif boundary_mode == "none":
                boundary = 0
            else:                                    # ring（默认）
                boundary = BOUNDARY_BIT if edge else 0
                if edge:
                    flags |= BOUNDARY2_FLAG
            tex = data[off + 4] & 0x0F

            struct.pack_into("<H", data, off, max(0, min(0xFFFF, gh)))
            struct.pack_into("<H", data, off + 2, (wh & 0x3FFF) | boundary)
            data[off + 4] = (flags & 0xF0) | tex
            data[off + 5] = ((int(ground_variation[cy, cx]) & 0x1F) << 3) | (int(cliff_variation[cy, cx]) & 0x07)
            data[off + 6] = ((int(cliff_texture[cy, cx]) & 0x0F) << 4) | (int(layer[cy, cx]) & 0x0F)

    new_w3e = os.path.join(tmp, "war3map.w3e.new")
    open(new_w3e, "wb").write(bytes(data))

    # 4. 预览图
    if preview:
        img = np.zeros((rows, cols, 3), dtype=np.uint8)
        lv = layer.astype(np.float32)
        lo = float(lv.min())
        hi = float(lv.max())
        hi = lo + 1.0 if hi <= lo else hi
        t = (lv - lo) / (hi - lo)
        img[:, :, 0] = (90 + 140 * t).astype(np.uint8)
        img[:, :, 1] = (70 + 150 * t).astype(np.uint8)
        img[:, :, 2] = (40 + 110 * t).astype(np.uint8)
        # 叠一层山体阴影：不然「隆起/凹陷/凹凸不平」在纯色块上看不出来
        h_we = fine.astype(np.float32) / 4.0 + (layer.astype(np.float32) - LAYER_ZERO) * 128.0
        sh = 0.42 + 0.58 * hillshade(h_we, exag=float(opts.get("shade-exag", 10.0)))
        img = np.clip(img.astype(np.float32) * sh[:, :, None], 0, 255).astype(np.uint8)
        # 水面也叠一层柔和的阴影，否则「水下隆起/凹陷」在预览图上完全看不出来
        sh_soft = 0.55 + 0.45 * hillshade(h_we, exag=float(opts.get("shade-exag", 10.0)))
        for wm, wcol in ((is_water & ~deep_water, (60, 130, 210)),   # 浅水
                         (deep_water, (20, 60, 150))):               # 深水（更暗，和游戏里一致）
            if wm.any():
                c = np.array(wcol, dtype=np.float32)[None, :]
                img[wm] = np.clip(sh_soft[wm][:, None] * c, 0, 255).astype(np.uint8)
        ramp_tile = (ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:])
        img[:-1, :-1][ramp_tile] = (230, 170, 40)
        # 放大 4 倍：和撒树预览同尺寸，界面里并排显示时不会一个糊一个清
        Image.fromarray(img).resize((cols * 4, rows * 4), Image.NEAREST).save(preview)
        print(f"预览图: {preview}"
              f"（已叠山体阴影；水色浅=浅水 深=深水，隆起/凹陷/颗粒感可直接看出来）")

    # 5. 塞回 MPQ
    subprocess.run([exe, "add", target, new_w3e, "war3map.w3e"],
                   capture_output=True, timeout=120)

    unique_layers = np.unique(layer)
    h_lo = (layer_min - LAYER_ZERO) * 128
    h_hi = (layer_max - LAYER_ZERO) * 128
    print(f"高度层区间: {layer_min}~{layer_max} 层（WE 高度 {h_lo:.0f} ~ {h_hi:.0f}，"
          f"共 {nlev} 级台阶，每级 128；水面在第 {water_layer} 层）")
    print(f"层分布: { {int(v): int(np.count_nonzero(layer == v)) for v in unique_layers} }")
    print(f"水域角点: {water_corners} ({water_corners * 100.0 / (rows * cols):.1f}%)")
    n_edge = 2 * cols + 2 * rows - 4
    _bnd_desc = {
        "ring": f"只留最外一圈（{n_edge} 角点）",
        "none": "全清（整张地图无边界位）",
        "keep": f"沿用模板边框（0x4000 共 {tpl_b1} 角点，0x80 已同步）",
    }[boundary_mode]
    print(f"边界标记: {boundary_mode} → {_bnd_desc}"
          f"   模板原有 0x4000={tpl_b1} / 0x80={tpl_b2} 角点"
          f"   保留枯地: {blight_kept} 角点")
    n_island, n_walk, n_bad = connectivity_report(layer, is_water, ramp)
    print(f"斜坡: {ramp_info.get('ramps', 0)} 条 (台地 {ramp_info.get('components', 0)} 块, "
          f"候选崖边 {ramp_info.get('candidates', 0)} 处"
          + (f", 跳过 {ramp_info['skipped']} 处" if ramp_info.get("skipped") else "") + ")")
    for line in ramp_report(layer, ramp):
        print("      " + line)
    print(f"连通性自检: 陆地岛 {n_island} 块 / 可走连通块 {n_walk} 块  → "
          + ("每座岛内部都走得通 ✔" if n_bad == 0 else f"有 {n_bad} 座岛被崖壁切断 ✘"))
    print(f"完成: {target}")
    if not opts.get("keep-temp"):
        drop_tmp(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
