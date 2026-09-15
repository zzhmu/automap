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
  --density 0.35      总体树木密度（占可用格子的比例）
  --slope-tol 1       允许的最大层差（1 = 可种在缓坡上）
  --freq 3.0          森林场尺度：决定"哪里适合长树"，越小森林区越大块
  --clump-size 26     每丛株数（会做 ±随机抖动）
  --clump-radius 4.5  丛半径（格）
  --clump-gap 2.1     丛心最小间距（× 丛半径）：太小会连成一片实心林
  --clump-bias 0.55   丛心有多偏向森林场高的地方（0 = 纯随机，1 = 纯按森林场）
  --scatter 0.015     丛外零星散树密度
  --tree-id WTst      强制树类型；默认从模板地图现有物件里自动学
  --keep              保留原有物件（默认清空后重新生成）
  --out <路径>        另存为新地图
  --no-backup         跳过备份（调用方自己已复制过模板时用，避免堆积无用 .bak）
  --preview p.png     输出撒树预览图（浅绿=森林区，深绿=实际种树）

撒树用的是"树丛播种"而不是"噪声取阈值"：后者等值线是连续闭合曲线，取分位只会得到
一大块连通的实心林。现在丛心按"森林场 × 抖动"打分 + 最小间距贪心接受，丛内按距离
抖动排序取够株数，不够就沿林缘（frontier）扩生，绝不随机撒孤立单株。
判定用 blob_stats()：连片块数 / 最大块 / 平均块 / 孤立单株占比。
"""
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

# 各 tileset 的常见树（仅作模板地图里学不到时的兜底）
FALLBACK_TREES = {
    "L": "LTlt", "A": "ATtr", "B": "BTtw", "N": "NTtw", "W": "WTst",
    "V": "VTlt", "Y": "YTlb", "X": "XTlt", "D": "DTsh", "F": "FTtw",
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


def place_clumps(nprng, elig, total, clump_size, clump_radius, gap_mul, bias=None,
                 clump_bias=0.55):
    """按「树丛」播种：先撒丛心（互相保证最小间距），再在每丛半径内填够株数。

    老做法（对噪声场取一个分位阈值）在数学上只能得到噪声的等值线包围块 ——
    覆盖率高时必然连成一整片实心林，观感就是"树全挤在一起"。
    显式播种把「每丛多大」和「丛与丛隔多远」变成两个直接可控的量：
      clump_size   每丛树数（泊松抖动，自然有大有小）
      clump_radius 丛半径（格），决定丛有多密
      gap_mul      丛心最小间距 = gap_mul * clump_radius，决定丛之间留多宽的林间空地
    bias 是低频森林场：丛心优先落在"森林区"里，所以大尺度上仍有疏密之分，
    但每一丛本身是小的，不会糊成一整块。
    """
    W, H = elig.shape
    picked = np.zeros((W, H), dtype=bool)
    if total <= 0 or not elig.any():
        return picked, 0, 0

    ei, ej = np.nonzero(elig)
    n_elig = len(ei)
    max_clumps = int(np.ceil(total / max(1.0, clump_size)))

    # 丛心候选打分：森林场 × 随机抖动，高分优先当丛心，低分区域自然成为空地
    score = nprng.random(n_elig).astype(np.float32)
    if bias is not None:
        score = bias[ei, ej] * (0.12 + 0.88 * score)
    order = np.argsort(-score)

    min_sep = max(1.0, gap_mul * clump_radius)
    sel_i, sel_j = [], []
    rr = int(np.ceil(clump_radius))
    for k in order:
        if len(sel_i) >= max_clumps:
            break
        ci, cj = int(ei[k]), int(ej[k])
        if ci < rr or cj < rr or ci >= W - rr or cj >= H - rr:
            continue
        ok = True
        for a, b in zip(sel_i, sel_j):
            if (a - ci) ** 2 + (b - cj) ** 2 < min_sep * min_sep:
                ok = False
                break
        if ok:
            sel_i.append(ci)
            sel_j.append(cj)

    placed = 0
    for ci, cj in zip(sel_i, sel_j):
        # 每丛株数与半径都做抖动 → 灌木丛/大树林混着来，不是一圈等大的圆斑
        quota = int(round(clump_size * float(nprng.uniform(0.35, 1.9))))
        quota = max(2, quota)
        rad = float(clump_radius * np.exp(nprng.normal(0.0, 0.32)))
        rad = float(min(max(rad, clump_radius * 0.45), clump_radius * 1.9))
        rr2 = int(np.ceil(rad))
        y0, y1 = max(0, cj - rr2), min(H, cj + rr2 + 1)
        x0, x1 = max(0, ci - rr2), min(W, ci + rr2 + 1)
        sub_elig = elig[x0:x1, y0:y1]
        if not sub_elig.any():
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]                 # (nj, ni)
        sub_elig = elig[x0:x1, y0:y1].T                 # 转成 (nj, ni) 与 dist 同形
        sub_taken = picked[x0:x1, y0:y1].T
        dist = np.sqrt((yy - cj) ** 2.0 + (xx - ci) ** 2.0)
        # 距离 + 噪声抖动：边缘参差、不是标准圆形
        d = dist + nprng.random(sub_elig.shape).astype(np.float32) * max(1.0, rad * 0.55)
        cand = np.nonzero(sub_elig & ~sub_taken & (dist <= rad))
        if not len(cand[0]):
            continue
        rank = np.argsort(d[cand])
        for t in rank[:quota]:
            j2 = y0 + int(cand[0][t])
            i2 = x0 + int(cand[1][t])
            picked[i2, j2] = True
            placed += 1
            if placed >= total:
                return picked, len(sel_i), 0

    # 株数没配平（丛心被最小间距限制放不下）：沿林缘向外生长。
    # 关键：从「还有空位的林缘格」里抽，而不是随机抽空格 —— 后者会撒出一堆孤零零的单株，
    # 看起来就是"分布很散很杂"，跟成丛的观感对不上。
    def _has_free(y, x):
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and elig[ny, nx] and not picked[ny, nx]:
                return True
        return False

    frontier = []
    if placed < total:
        fy, fx = np.nonzero(picked)
        for y, x in zip(fy, fx):
            if _has_free(int(y), int(x)):
                frontier.append((int(y), int(x)))
    grow = 0
    while placed < total and frontier:
        k = int(nprng.integers(0, len(frontier)))
        y, x = frontier[k]
        nbrs = [(y + dy, x + dx) for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0))
                if 0 <= y + dy < H and 0 <= x + dx < W
                and elig[y + dy, x + dx] and not picked[y + dy, x + dx]]
        if not nbrs:
            frontier[k] = frontier[-1]
            frontier.pop()
            continue
        ny, nx = nbrs[int(nprng.integers(0, len(nbrs)))]
        picked[ny, nx] = True
        placed += 1
        grow += 1
        if _has_free(ny, nx):
            frontier.append((ny, nx))
        if not _has_free(y, x):
            frontier[k] = frontier[-1]
            frontier.pop()
    return picked, len(sel_i), grow


def blob_stats(mask):
    """4 邻接连片统计，用来量化「树有多扎堆」。
    返回 (连片块数, 最大块面积, 平均块面积, 孤立单株占比)。"""
    mask = np.asarray(mask, dtype=bool)
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    sizes = []
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        stack = [(int(sy), int(sx))]
        seen[sy, sx] = True
        n = 0
        while stack:
            y, x = stack.pop()
            n += 1
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        sizes.append(n)
    if not sizes:
        return 0, 0, 0.0, 0.0
    sz = np.array(sizes)
    return len(sizes), int(sz.max()), float(sz.mean()), float(np.count_nonzero(sz == 1)) / len(sz)


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
    density = float(opts.get("density", 0.35))
    slope_tol = int(opts.get("slope-tol", 1))
    freq = float(opts.get("freq", 3.0))
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
    # 树丛播种：每丛株数、丛半径、丛间最小间距都是直接可控的旋钮，
    # 低频森林场只用来决定"丛心优先落在哪片区域"（大尺度上仍有疏密之分）。
    # ---------------------------------------------------------------
    clump_size = float(opts.get("clump-size", 26))
    clump_radius = float(opts.get("clump-radius", 4.5))
    gap_mul = float(opts.get("clump-gap", 2.1))
    scatter = min(max(float(opts.get("scatter", 0.015)), 0.0), 1.0)
    clump_bias = min(max(float(opts.get("clump-bias", 0.55)), 0.0), 1.0)
    clump_size = max(2.0, clump_size)
    clump_radius = max(1.0, clump_radius)
    gap_mul = max(1.0, gap_mul)

    if avail:
        nprng_local = np.random.default_rng(seed + 991)
        bias = norm01(fbm(nprng_local, (W, H), freq, octaves=2))
        n_clump_target = int(max(0, round(avail * density * (1.0 - scatter) / clump_size)))
        n_clump_tree = n_clump_target * clump_size
        n_scatter_tree = int(round(avail * density * scatter))
        picked, n_clumps, n_grow = place_clumps(
            nprng, elig, n_clump_tree, clump_size, clump_radius, gap_mul, bias=bias,
            clump_bias=clump_bias)
        if n_scatter_tree > 0:
            free = elig & ~picked
            fi, fj = np.nonzero(free)
            if len(fi):
                take = min(n_scatter_tree, len(fi))
                sel = nprng.choice(len(fi), size=take, replace=False)
                picked[fi[sel], fj[sel]] = True
        region = picked
    else:
        picked = np.zeros((W, H), dtype=bool)
        n_clumps = 0

    idx_i, idx_j = np.nonzero(picked)   # picked 形状 (W, H)，轴0 = i，轴1 = j
    ys, xs = idx_j, idx_i
    n_blob, blob_max, blob_avg, lone_ratio = blob_stats(picked)
    print(f"可用格子 {avail} ({avail*100.0/(W*H):.1f}%) → 种树 {len(ys)} 棵 "
          f"({len(ys)*100.0/(W*H):.1f}% 地图面积)")
    print(f"      树丛 {n_clumps} 丛（其中林缘扩生 {n_grow} 株）/ 丛半径 {clump_radius:.1f} 格 / "
          f"丛心最小间距 {gap_mul*clump_radius:.1f} 格 / 散树 {scatter*100:.1f}% / 森林场 freq={freq}")
    print(f"      连片度: {n_blob} 片，最大 {blob_max} 格，平均 {blob_avg:.1f} 格，"
          f"孤立单株占 {lone_ratio*100:.0f}%")

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
