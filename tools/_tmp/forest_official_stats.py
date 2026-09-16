# -*- coding: utf-8 -*-
"""量官方地图的「树林连片结构」—— 给撒树算法定目标值。

指标（都在瓦片网格上算，4 连通）：
  * 树的可种面积占比 = 树数 / (W*H)
  * 连片块数 n_blob、最大块 blob_max、各分位
  * 「大林块」数（≥100 / ≥300 格）与它们吃掉了多少树
  * 最大块的长宽比与 周长/面积（越大越参差、越不像圆斑）
  * 孤立单株占比

用法: python tools/_tmp/forest_official_stats.py [地图数上限]
"""
import os
import shutil
import struct
import subprocess
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402

MAPS = r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 335


def list_maps():
    """参数：地图文件 / 目录（不递归）/ 目录/**（递归）/ --w3m（只要 v7 .w3m）/ 空（= 全部）。

    注意：FrozenThrone 目录下的 .w3x 是 doo **v8**（记录布局不同），本项目 parse_doo
    只认 v7，量出来必然是垃圾 → 用 --w3m 只留 1.27a 原生 .w3m（顶层 44 张经典对战图）。
    """
    argv = [a for a in sys.argv[1:] if not a.replace(".", "").isdigit() and not a.startswith("--")]
    only_w3m = "--w3m" in sys.argv
    if not argv:
        roots = [(MAPS, True)]
    else:
        roots = []
        for a in argv:
            if a.lower().endswith((".w3x", ".w3m")):
                return [a]
            if a.endswith("/**"):
                roots.append((a[:-3], True))
            else:
                roots.append((a, False))
    out = []
    for root, rec in roots:
        if not os.path.isdir(root):
            continue
        if rec:
            for dirpath, _dirnames, filenames in os.walk(root):
                for f in filenames:
                    if f.lower().endswith((".w3x", ".w3m")):
                        out.append(os.path.join(dirpath, f))
        else:
            for f in os.listdir(root):
                if f.lower().endswith((".w3x", ".w3m")):
                    out.append(os.path.join(root, f))
    if only_w3m:
        out = [p for p in out if p.lower().endswith(".w3m")]
    return sorted(set(out))


def blobs(mask):
    """4 连通块（返回每块面积列表 + 最大块掩码）"""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    sizes = []
    best = None
    best_n = -1
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        stack = [(int(sy), int(sx))]
        seen[sy, sx] = True
        cells = []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        sizes.append(len(cells))
        if len(cells) > best_n:
            best_n = len(cells)
            best = cells
    m = np.zeros_like(mask, dtype=bool)
    if best:
        for y, x in best:
            m[y, x] = True
    return sizes, m


# metric_extra 已删除：指标统一走 A.forest_metrics（见 add_doodads.py）。


def one(path, tmp):
    exe = A.default_exe()
    for fn in ("war3map.w3e", "war3map.doo"):
        subprocess.run([exe, "extract", path, fn, tmp, "/fp"],
                       capture_output=True, timeout=180)
    p_w3e = os.path.join(tmp, "war3map.w3e")
    p_doo = os.path.join(tmp, "war3map.doo")
    if not os.path.exists(p_w3e) or not os.path.exists(p_doo):
        return None
    w3e = open(p_w3e, "rb").read()
    try:
        _tileset, W, H, _HS = A.read_w3e_header(w3e)
    except Exception:
        return None
    _ver, _sub, recs, _tail = A.parse_doo(open(p_doo, "rb").read())
    if not recs:
        return None
    ids = Counter()
    for r in recs:
        try:
            ids[r[:4].decode("ascii")] += 1
        except UnicodeDecodeError:
            pass
    if not ids:
        return None
    tree_id, n_tree = ids.most_common(1)[0]

    grid = np.zeros((H, W), dtype=bool)
    for r in recs:
        try:
            if r[:4].decode("ascii") != tree_id:
                continue
        except UnicodeDecodeError:
            continue
        x, y, _z = struct.unpack_from("<fff", r, 8)
        i = int(round((x + W * 64) / 128.0 - 0.5))
        j = int(round((y + H * 64) / 128.0 - 0.5))
        if 0 <= i < W and 0 <= j < H:
            grid[j, i] = True
    if grid.sum() == 0:
        return None
    sizes, big = blobs(grid)
    sz = np.sort(np.array(sizes))[::-1]
    n = grid.sum()
    # 最大块周长（4 邻接边界）/ 面积 → 参差程度；圆盘 ≈ 4/sqrt(pi*A) ≈ 2.26/sqrt(A)
    pad = np.pad(big, 1)
    perim = int((pad[1:-1, 1:-1] & ~pad[:-2, 1:-1]).sum()
                + (pad[1:-1, 1:-1] & ~pad[2:, 1:-1]).sum()
                + (pad[1:-1, 1:-1] & ~pad[1:-1, :-2]).sum()
                + (pad[1:-1, 1:-1] & ~pad[1:-1, 2:]).sum())
    ys, xs = np.nonzero(big)
    bbox_ar = 0.0
    if len(ys):
        hh = ys.max() - ys.min() + 1
        ww = xs.max() - xs.min() + 1
        bbox_ar = max(hh, ww) / max(1.0, min(hh, ww))
    total = int(n)
    # 指标口径统一走 add_doodads.forest_metrics（全项目唯一实现）。
    # 这里以前自己抄了一份孤立度/dilate 代码，把「dilate 含自身」的坑又踩了一遍，
    # 量出「43 张图孤立率全为 0」的假结论 —— 所以**别再本地再实现一遍**。
    fm = A.forest_metrics(grid)
    _lab, _sizes = A._blob_labels(grid)
    big_ids = [k + 1 for k, s in enumerate(_sizes) if s >= 100]
    big_ids_mask = np.isin(_lab, big_ids) if big_ids else np.zeros_like(grid)
    return dict(name=os.path.basename(path), W=W, H=H, tree_id=tree_id, trees=total,
                dens=total / float(W * H),
                n_blob=len(sizes), top5=[int(v) for v in sz[:5]],
                max_sz=int(sz[0]),
                n100=int((sz >= 100).sum()), n300=int((sz >= 300).sum()),
                frac100=float(sz[sz >= 100].sum()) / total,
                frac300=float(sz[sz >= 300].sum()) / total,
                lone=float((sz == 1).sum()) / max(1, len(sizes)),
                perim_ar=perim / float(max(1, int(sz[0]))),
                bbox_ar=float(bbox_ar),
                iso8=fm["iso8"], iso2=fm["iso2"], dmed=fm["dmed"],
                d3=fm["dnear"], inbig=fm["inbig"])


def main():
    maps = list_maps()[:LIMIT]
    tmp = A.make_tmp("foreststats")
    rows = []
    try:
        for k, p in enumerate(maps):
            try:
                r = one(p, tmp)
            except Exception as e:
                print(f"  !! {os.path.basename(p)}: {e}")
                continue
            if r:
                rows.append(r)
                print(f"[{k+1:>3}/{len(maps)}] {r['name'][:28]:<28} {r['W']}x{r['H']} "
                      f"树{r['trees']:>5} 密度{r['dens']*100:>4.1f}% 块{r['n_blob']:>4} "
                      f"最大{r['max_sz']:>5} top5={r['top5']} ≥100:{r['n100']:>3} "
                      f"≥300:{r['n300']:>3} 单株{r['lone']*100:>3.0f}%")
    finally:
        A.drop_tmp(tmp)

    if not rows:
        print("没有可用样本")
        return
    def stat(key):
        v = np.array([r[key] for r in rows], dtype=float)
        return v
    print("\n" + "=" * 100)
    print(f"样本 {len(rows)} 张")
    for key, label in [("dens", "树种密度"), ("n_blob", "连片块数"), ("max_sz", "最大块"),
                       ("n100", "≥100 格的块数"), ("n300", "≥300 格的块数"),
                       ("frac100", "树落在大林(≥100)的比例"),
                       ("frac300", "树落在 ≥300 块的比例"),
                       ("lone", "孤立单株比例"),
                       ("iso8", "★8邻域孤立株占树数"), ("iso2", "★2格内无树占树数"),
                       ("dmed", "★到大林格距中位"), ("d3", "★距大林≤3格占树数"),
                       ("perim_ar", "最大块 周长/面积"),
                       ("bbox_ar", "最大块 长宽比")]:
        v = stat(key)
        print(f"  {label:<24} p10={np.percentile(v,10):>8.3f}  p50={np.percentile(v,50):>8.3f}  "
              f"p90={np.percentile(v,90):>8.3f}  mean={v.mean():>8.3f}  max={v.max():>8.3f}")
    # 每 100 棵树对应多少块
    ratio = stat("n_blob") / np.maximum(1.0, stat("trees"))
    print(f"  {'块数/树数':<24} p10={np.percentile(ratio,10):>8.4f}  "
          f"p50={np.percentile(ratio,50):>8.4f}  p90={np.percentile(ratio,90):>8.4f}")


main()
