# -*- coding: utf-8 -*-
"""森林分布算法对比：图灵斑图 vs 泊松簇过程 vs 本项目实际输出。

关键：图灵斑图要按「斑点中心」当一棵树来量（按像素量会把同一个斑点内的相邻像素
算成最近邻，指标完全失真）。

生态学判据（Clark & Evans 1954，森林结构分析的标准指标之一）：
  R = 观测平均最近邻距离 / 完全随机(泊松)期望距离 = r_obs / (1/(2*sqrt(N/A)))
    R = 1        完全随机
    R → 0        最大聚集
    R = 2.1491   完美六边形规则排布（理论最大值）
  实测成熟林分：R 一般落在 0.76 ~ 1.25；下木层/更新苗明显聚集（R ≈ 0.76~0.93），
  上层乔木因自疏竞争反而接近随机甚至略偏规则。
  NN-CV = 最近邻距离的变异系数：泊松 ≈ 0.52，越大越聚集。
"""
import os
import re
import shutil
import struct
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402

N = 160                      # 输出网格
N_RD = 320                   # 反应扩散跑在高一档分辨率，再把斑点中心缩回 N
SEED = 20260915
OUT = os.path.join(ROOT, "out", "_forest_algo_compare.png")
MAP = os.path.join(ROOT, "out", "ui_demo.w3x")


# ---------------------------------------------------------------- 图灵斑图
def gray_scott(f, k, steps=9000, n=N_RD, du=0.16, dv=0.08, dt=1.0, seed=1):
    """Gray-Scott 反应扩散：U + 2V -> 3V（自催化），V -> P（衰减）。
    图案形态完全由 (f, k) 决定：自复制斑点 / 迷宫条纹 / 蠕虫…"""
    rng = np.random.default_rng(seed)
    u = np.ones((n, n), dtype=np.float32)
    v = np.zeros((n, n), dtype=np.float32)
    for _ in range(24):                       # 多处随机播种，图案填满更快
        cy, cx = rng.integers(20, n - 20, 2)
        u[cy - 8:cy + 8, cx - 8:cx + 8] = 0.5
        v[cy - 8:cy + 8, cx - 8:cx + 8] = 0.25
    v += 0.02 * rng.random((n, n)).astype(np.float32)

    def lap(a):
        return (np.roll(a, 1, 0) + np.roll(a, -1, 0) +
                np.roll(a, 1, 1) + np.roll(a, -1, 1) - 4.0 * a)

    for _ in range(steps):
        uvv = u * v * v
        u += dt * (du * lap(u) - uvv + f * (1.0 - u))
        v += dt * (dv * lap(v) + uvv - (f + k) * v)
    return v


def components(mask):
    """4 邻接连通块 → 返回 (质心数组, 面积数组)。"""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    cents, sizes = [], []
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        stack = [(int(sy), int(sx))]
        seen[sy, sx] = True
        acc = []
        while stack:
            y, x = stack.pop()
            acc.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        a = np.array(acc, dtype=np.float32)
        cents.append(a.mean(0))
        sizes.append(len(acc))
    return np.array(cents, dtype=np.float32).reshape(-1, 2), np.array(sizes)


def spots_to_trees(v, size_lo=6, scale=N / float(N_RD)):
    """阈值化 → 连通块 → 取质心当树，再缩放到 N 网格。"""
    m = v > 0.20
    cents, sizes = components(m)
    if len(cents) == 0:
        return np.zeros((N, N), dtype=bool), np.zeros((0, 2), dtype=np.float32)
    keep = sizes >= size_lo
    c = cents[keep] * scale
    grid = np.zeros((N, N), dtype=bool)
    ii = np.clip(c[:, 1].round().astype(int), 0, N - 1)
    jj = np.clip(c[:, 0].round().astype(int), 0, N - 1)
    grid[ii, jj] = True          # 注意 grid 用 (i,j) = (x,y)
    return grid, np.stack([jj, ii], 1).astype(np.float32)   # 返回 (x,y)


# ---------------------------------------------------------------- 指标
def clark_evans(pts, area, sample=1400, seed=0):
    n = len(pts)
    if n < 8:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, size=min(sample, n), replace=False)
    p = pts[idx].astype(np.float32)
    d = np.sqrt(((p[:, None, :] - p[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    nn = d.min(1)
    density = float(len(idx)) / float(area)
    exp_nn = 0.5 / np.sqrt(density)          # 泊松期望最近邻距离
    return float(nn.mean() / exp_nn), float(nn.std() / nn.mean())


def grid_to_pts(mask):
    ii, jj = np.nonzero(mask)
    return np.stack([jj, ii], 1).astype(np.float32)


def fbm_field(shape, freq, octaves, seed):
    return A.norm01(A.fbm(np.random.default_rng(seed), shape, freq, octaves=octaves))


# ---------------------------------------------------------------- 点过程
def poisson(area_mask, total, seed=4):
    rng = np.random.default_rng(seed)
    ys, xs = np.nonzero(area_mask)
    sel = rng.choice(len(ys), size=min(total, len(ys)), replace=False)
    m = np.zeros_like(area_mask)
    m[ys[sel], xs[sel]] = True
    return m


def cluster_process(area_mask, total, sigma, seed=3, hard_core=0.0, per=26.0, parent_sep=0.0):
    """泊松簇过程（Thomas / Neyman-Scott）＝生态学里"母树散播"的标准模型：
      父点（母树）→ 子点（种子）以高斯散布在父点周围。
      parent_sep > 0 时给父点加最小间距（Matern 硬核）—— 不加的话簇会互相重叠糊成一片，
      看起来反而像随机，这正是"系数没调对"最容易犯的错。
      hard_core > 0 再叠加子点之间的最小株距（林分自疏）。"""
    rng = np.random.default_rng(seed)
    ys, xs = np.nonzero(area_mask)
    elig = np.stack([xs, ys], 1).astype(np.float32)
    suit = fbm_field(area_mask.shape, 3.0, 2, SEED)[ys, xs] ** 1.5
    w = suit / suit.sum()
    n_parent = max(1, int(total / per))
    if parent_sep > 0:
        # 适宜度高的优先当母树，同时保证彼此拉开 → 簇既落在好地段又不糊成一片
        sel = []
        for t in np.argsort(-w):
            if len(sel) >= n_parent:
                break
            p = elig[t]
            if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= parent_sep ** 2 for q in sel):
                sel.append(p)
        par = np.array(sel, dtype=np.float32)
    else:
        par = elig[rng.choice(len(elig), size=min(n_parent, len(elig)), replace=False, p=w)]
    H, W = area_mask.shape
    ii, jj = [], []
    for cx, cy in par:
        want = int(rng.integers(max(2, int(per * 0.4)), int(per * 1.8)))
        got = att = 0
        while got < want and att < want * 10:
            att += 1
            # 子点只在可种格上落地：落到水/崖上的种子就当没活下来，继续散播
            x = int(round(cx + rng.normal(0, sigma)))
            y = int(round(cy + rng.normal(0, sigma)))
            if 0 <= x < W and 0 <= y < H and area_mask[y, x]:
                ii.append(x)
                jj.append(y)
                got += 1
    ii = np.array(ii, dtype=int)
    jj = np.array(jj, dtype=int)

    if hard_core > 0:
        cell = max(1, int(np.ceil(hard_core)))
        occ = {}
        kept = []
        for t in rng.permutation(len(ii)):
            x, y = int(ii[t]), int(jj[t])
            hit = False
            for gy in range(y - cell, y + cell + 1):
                for gx in range(x - cell, x + cell + 1):
                    for (px, py) in occ.get((gx, gy), ()):
                        if (px - x) ** 2 + (py - y) ** 2 < hard_core ** 2:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    break
            if not hit:
                kept.append((x, y))
                occ.setdefault((x, y), []).append((x, y))
        ii = np.array([k[0] for k in kept], dtype=int)
        jj = np.array([k[1] for k in kept], dtype=int)

    mask = np.zeros((H, W), dtype=bool)
    seen = set()
    for x, y in zip(ii, jj):            # 一个格子只留一棵（WC3 里树占格）
        if (x, y) not in seen:
            seen.add((x, y))
            mask[y, x] = True
    return mask


def pts_to_grid(pts, n=N):
    g = np.zeros((n, n), dtype=bool)
    if len(pts):
        i = np.clip(pts[:, 1].round().astype(int), 0, n - 1)
        j = np.clip(pts[:, 0].round().astype(int), 0, n - 1)
        g[i, j] = True
    return g


# ---------------------------------------------------------------- 真实输出
def load_real():
    """读实际生成的地图：树坐标 + 可种区域。"""
    if not os.path.exists(MAP):
        return None, None
    exe = A.default_exe()
    tmp = os.path.join(HERE, "pat_r%d_%d" % (os.getpid(), int(np.random.randint(999))))
    os.makedirs(tmp, exist_ok=True)
    subprocess.run([exe, "extract", MAP, "war3map.w3e", tmp, "/fp"], capture_output=True, timeout=180)
    subprocess.run([exe, "extract", MAP, "war3map.doo", tmp, "/fp"], capture_output=True, timeout=180)
    w3e_p = os.path.join(tmp, "war3map.w3e")
    doo_p = os.path.join(tmp, "war3map.doo")
    if not (os.path.exists(w3e_p) and os.path.exists(doo_p)):
        return None, None
    w3e = open(w3e_p, "rb").read()
    _, W, H, HS = A.read_w3e_header(w3e)
    cols, rows = W + 1, H + 1
    water = np.zeros((rows, cols), dtype=bool)
    layer = np.zeros((rows, cols), dtype=np.int16)
    for r in range(rows):
        for c in range(cols):
            off = HS + (r * cols + c) * 7
            _, _, fb, _, b6 = struct.unpack_from("<HHBBB", w3e, off)
            water[r, c] = bool(fb & 0x40)
            layer[r, c] = b6 & 0x0F
    dry = ~water
    elig = np.zeros((W, H), dtype=bool)
    for j in range(1, H - 1):
        for i in range(1, W - 1):
            c0 = dry[j, i] and dry[j, i + 1] and dry[j + 1, i] and dry[j + 1, i + 1]
            l4 = (layer[j, i], layer[j, i + 1], layer[j + 1, i], layer[j + 1, i + 1])
            elig[i, j] = c0 and (max(l4) - min(l4)) <= 1
    _, _, recs, _ = A.parse_doo(open(doo_p, "rb").read())
    mask = np.zeros((W, H), dtype=bool)
    for r in recs:
        x, y = struct.unpack_from("<ff", r, 8)
        i = int(round((x + W * 64) / 128.0 - 0.5))
        j = int(round((y + H * 64) / 128.0 - 0.5))
        if 0 <= i < W and 0 <= j < H:
            mask[i, j] = True
    return mask, elig


# ---------------------------------------------------------------- 渲染
def render(mask, bg=None, scale=3):
    H, W = mask.shape
    img = np.full((H, W, 3), (208, 198, 170), dtype=np.uint8)
    if bg is not None:
        img[~bg] = (150, 176, 205)          # 不可种（水/崖）= 淡蓝，和草地分开
    img[mask] = (24, 88, 34)
    return Image.fromarray(img).resize((W * scale, H * scale), Image.NEAREST)


def main():
    cache = os.path.join(HERE, "pat_rd.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        spot_pts, lab_pts = z["spot"], z["lab"]
        print("复用缓存的反应扩散斑图（删掉 tools/_tmp/pat_rd.npz 可重算）")
    else:
        print("跑 1/5  Gray-Scott 反应扩散（图灵斑点）…")
        _g, spot_pts = spots_to_trees(gray_scott(f=0.035, k=0.065, seed=SEED))
        print("       得到斑点", len(spot_pts), "个")
        print("跑 2/5  Gray-Scott 反应扩散（图灵迷纹）…")
        _g, lab_pts = spots_to_trees(gray_scott(f=0.022, k=0.051, seed=SEED), size_lo=6)
        np.savez(cache, spot=spot_pts, lab=lab_pts)
    spot_grid = pts_to_grid(spot_pts)
    lab_grid = pts_to_grid(lab_pts)

    print("跑 3/5  读真实地形 …")
    real, elig = load_real()
    if elig is None:
        print("!! 读不到 out/ui_demo.w3x")
        return 1
    area = int(elig.sum())
    total = int(area * 0.32)

    print("跑 4/5  点过程（泊松 / 簇 / 簇+自疏）…")
    pois = poisson(elig, total, seed=SEED)
    # 母点最小间距 9.5 = 本项目生成器的丛心间距；不加这一条，簇会互相重叠糊成随机
    thomas = cluster_process(elig, total, sigma=3.0, seed=SEED, per=26.0, parent_sep=9.5)
    overthin = cluster_process(elig, total, sigma=3.0, seed=SEED, per=26.0,
                              parent_sep=9.5, hard_core=2.0)
    # 本项目实际在用的算法：同样的"母点 + 散播"，但丛内是"按距离填充最近的格子"
    # （等价于林分里抢地盘的密实块），而不是各自独立落点
    suit_full = fbm_field(elig.shape, 3.0, 2, SEED)
    shipped, _ncl, _ngrow = A.place_clumps(
        np.random.default_rng(SEED), elig, int(total * 0.985), 26.0, 4.5, 2.1,
        bias=suit_full, clump_bias=0.55)

    # 图灵斑点 × 适宜度场：只在"适宜"的地方保留斑图
    suit_n = fbm_field((N, N), 3.0, 2, SEED)
    thr = float(np.quantile(suit_n, 0.55))
    masked_grid = spot_grid & (suit_n >= thr)

    print("跑 5/5  统计 …\n")
    rows = []

    def stat(name, mask, pts, ar):
        nb, bmax, bavg, _lone = A.blob_stats(mask)
        r, cv = clark_evans(pts, ar)
        rows.append((name, int(mask.sum()), nb, bmax, bavg, r, cv))

    stat("① 泊松随机（基准）", pois, grid_to_pts(pois), area)
    stat("② 图灵斑点（斑点中心）", spot_grid, spot_pts, N * N)
    stat("③ 图灵斑点 × 适宜度场", masked_grid, grid_to_pts(masked_grid), N * N)
    stat("④ 图灵迷纹（斑点中心）", lab_grid, lab_pts, N * N)
    stat("⑤ 纯 Thomas 簇过程", thomas, grid_to_pts(thomas), area)
    stat("⑥ 过度自疏（反例）", overthin, grid_to_pts(overthin), area)
    stat("⑦ place_clumps（本项目算法）", shipped, grid_to_pts(shipped), area)
    stat("⑧ 本生成器真实输出", real, grid_to_pts(real), area)

    print(f"{'方案':<26}{'株数':>7}{'片数':>7}{'最大块':>8}{'平均块':>8}{'C-E R':>8}{'NN-CV':>8}   结论")
    print("-" * 92)
    for r in rows:
        if np.isnan(r[5]):
            verdict = "-"
        elif r[5] > 1.35:
            verdict = "规则排布（人工林/苗圃感）"
        elif r[5] > 1.10:
            verdict = "偏规则"
        elif r[5] > 0.90:
            verdict = "接近随机"
        else:
            verdict = "聚集 ✔ 树林的样子"
        print(f"{r[0]:<26}{r[1]:>7}{r[2]:>7}{r[3]:>8}{r[4]:>8.1f}{r[5]:>8.3f}{r[6]:>8.3f}   {verdict}")
    print("-" * 92)
    print("参照：R=1 完全随机；R=2.1491 完美六边形；实测成熟林分 R≈0.76~1.25")

    def cap(i, t1, t2):
        r = rows[i]
        return t1, f"{t2}  [R={r[5]:.2f} CV={r[6]:.2f}]" if not np.isnan(r[5]) else (t1, t2)

    panels = [
        (pois, "1. Poisson random (baseline)", "R~1 CV~0.5：完全随机，不成丛"),
        (spot_grid, "2. Turing spots, centres as trees", "R>1.3 CV~0.07：等间距等大小"),
        (masked_grid, "3. Turing spots x suitability", "有分区，但斑距仍然单一"),
        (lab_grid, "4. Turing labyrinth (stripes)", "条纹：虎皮/斑马纹，不是树（R 不适用）"),
        (thomas, "5. Textbook Thomas process", "子点独立散布：在格子上不成块（平均块~2）"),
        (overthin, "6. Over-thinning (counter-example)", "自疏过头：又被拉回人工林"),
        (shipped, "7. place_clumps (this project)", "丛内按距离填充的密实块 = 真树林观感"),
        (real, "8. This generator's real output", "当前代码真实产物（160x160）"),
    ]
    labs = [cap(0, panels[0][1], panels[0][2]), cap(1, panels[1][1], panels[1][2]),
            cap(2, panels[2][1], panels[2][2]), panels[3][1:],
            cap(4, panels[4][1], panels[4][2]), cap(5, panels[5][1], panels[5][2]),
            cap(6, panels[6][1], panels[6][2]), cap(7, panels[7][1], panels[7][2])]
    scale, gap, lab_h, cols = 3, 10, 32, 4
    pw, ph = N * scale, N * scale + lab_h
    rowsn = (len(panels) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * pw + (cols - 1) * gap, rowsn * ph + (rowsn - 1) * gap),
                       (238, 238, 238))
    for n, ((mask, _t1, _t2), (t1, t2)) in enumerate(zip(panels, labs)):
        p = Image.new("RGB", (pw, ph), (255, 255, 255))
        p.paste(render(mask, bg=(elig if n >= 4 else None), scale=scale), (0, lab_h))
        d = ImageDraw.Draw(p)
        d.text((6, 4), t1, fill=(20, 20, 20))
        d.text((6, 17), t2, fill=(95, 95, 95))
        canvas.paste(p, ((n % cols) * (pw + gap), (n // cols) * (ph + gap)))
    canvas.save(OUT)
    print("\n对比图 ->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
