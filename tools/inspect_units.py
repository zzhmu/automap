# -*- coding: utf-8 -*-
"""解析 war3mapUnits.doo（地图单位/中立建筑/出生点），并把坐标对到地形上做体检。

用法: python inspect_units.py <map.w3x> [--exe 路径] [--dump 20]

记录前缀字段偏移（实测 LostTemple v7.9，逐条手工核对过）:
    p+0  id(4)          p+36 flags(1)
    p+4  variation(4)   p+37 owner(4)      ← 12=中立敌对(野怪) 15=中立被动 0..3=玩家槽位
    p+8  x,y,z(12)      p+41 未知(2)
    p+20 angle(4)       p+43 hp(4)  -1=用默认
    p+24 scaleXYZ(12)   p+47 mana(4)
    p+51 n_sets(4) → p+55 起 n_sets × [n_items(4) + n_items × (itemId4, chance4)]
    紧随掉落之后: gold(4) targetAcq(4) heroLevel(4) n_inv(4) n_ab(4) …
    尾部: 随机标记(4) 自定义颜色(4) waygate(4) creationNumber(4)

注意：变长记录的**长度公式没有完全定死**（部分记录的尾部比模型多 4 字节），
所以这里不用「顺序解析」，而是靠字段取值域扫描出记录开头，再按固定前缀偏移取字段。
我们需要的东西（id/坐标/owner/金矿/掉落）全在稳定前缀里，不受尾部歧义影响。
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


def read_w3e_header(data):
    pos = 8 + 1 + 4
    n = struct.unpack_from("<I", data, pos)[0]; pos += 4 + 4 * n
    n = struct.unpack_from("<I", data, pos)[0]; pos += 4 + 4 * n
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    return w, h, pos + 8


def load_terrain(path):
    data = open(path, "rb").read()
    W, H, HS = read_w3e_header(data)
    rows, cols = H + 1, W + 1
    per = (len(data) - HS) // (rows * cols)
    corner = np.zeros((rows, cols, 5), dtype=np.int32)
    for cy in range(rows):
        for cx in range(cols):
            off = HS + (cy * cols + cx) * per
            corner[cy, cx] = struct.unpack_from("<HHBBB", data, off)
    return {"W": W, "H": H, "rows": rows, "cols": cols, "corner": corner}


def terrain_at(t, x, y):
    """世界坐标 → (是否水, 是否悬崖瓦片, 是否边界外)。出界返回 None。"""
    W, H = t["W"], t["H"]
    fx = (x + W * 64.0) / 128.0 - 0.5
    fy = (y + H * 64.0) / 128.0 - 0.5
    i, j = int(np.floor(fx)), int(np.floor(fy))
    if not (0 <= i < t["cols"] - 1 and 0 <= j < t["rows"] - 1):
        return None
    quad = t["corner"][j:j + 2, i:i + 2]
    water = bool((quad[:, :, 2] & 0x40).any())
    boundary = bool((((quad[:, :, 2] >> 7) & 1) != 0).any()
                    or ((quad[:, :, 1] & 0x4000) != 0).any())
    layers = quad[:, :, 4] & 0x0F
    flat = bool((layers == layers[0, 0]).all())
    return water, (not flat), boundary


def terrain_z(t, x, y):
    """该点四角 WE 高度的均值（单位坐在地面上时应等于它）。"""
    W, H = t["W"], t["H"]
    fx = (x + W * 64.0) / 128.0 - 0.5
    fy = (y + H * 64.0) / 128.0 - 0.5
    i, j = int(np.floor(fx)), int(np.floor(fy))
    if not (0 <= i < t["cols"] - 1 and 0 <= j < t["rows"] - 1):
        return None
    c = t["corner"][j:j + 2, i:i + 2]
    gh = c[:, :, 0].astype(np.float64)
    ly = (c[:, :, 4] & 0x0F).astype(np.float64)
    return float(((gh - GROUND_ZERO + (ly - LAYER_ZERO) * LAYER_STEP) / 4.0).mean())


def _plausible_id(data, p):
    if p + 4 > len(data):
        return False
    b = data[p:p + 4]
    if b[0] not in b"nouehrsNOUEHRS":
        return False
    return all(48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 for c in b)


def scan_units(data, map_w=None, map_h=None):
    """扫描记录开头：不做顺序解析，靠字段取值域交叉验证。

    最有效的一条过滤是「坐标必须落在地图范围内」——随机字节凑出的假记录几乎
    不可能同时让 x/y 解成合法浮点、又恰好落在 [-W*64, W*64] 内。
    """
    xmax = (map_w * 64.0 + 1024.0) if map_w else 1e9
    ymax = (map_h * 64.0 + 1024.0) if map_h else 1e9
    cands = []
    for p in range(16, len(data) - 91):
        if not _plausible_id(data, p):
            continue
        var, = struct.unpack_from("<I", data, p + 4)
        flags = data[p + 36]
        owner, = struct.unpack_from("<i", data, p + 37)
        hp, = struct.unpack_from("<i", data, p + 43)
        if var > 64 or flags >= 0x10 or not (-1 <= owner <= 16):
            continue
        if not (hp == -1 or 0 <= hp <= 100000):
            continue
        x, y, z, ang = struct.unpack_from("<4f", data, p + 8)
        if abs(x) > xmax or abs(y) > ymax or not (-2000.0 < z < 2000.0):
            continue
        if not (abs(x) > 1e-6 or abs(y) > 1e-6):
            continue
        cands.append(p)
    out = []
    for p in cands:
        if out and p - out[-1] < 80:      # 最短记录 91 字节，靠太近的必是同一条的误判
            continue
        out.append(p)
    return out


def parse_at(data, starts):
    units = []
    for k, p in enumerate(starts):
        oid = data[p:p + 4].decode("ascii", "replace")
        var, x, y, z, ang, sx, sy, sz = struct.unpack_from("<I4f3f", data, p + 4)
        flags = data[p + 36]
        owner, = struct.unpack_from("<i", data, p + 37)
        hp, mana = struct.unpack_from("<ii", data, p + 43)
        n_sets, = struct.unpack_from("<i", data, p + 51)
        q = p + 55
        drops = []
        if 0 < n_sets < 16:
            for _ in range(n_sets):
                n_it, = struct.unpack_from("<i", data, q); q += 4
                if not (0 <= n_it < 16):
                    break
                for _ in range(n_it):
                    drops.append((data[q:q + 4].decode("ascii", "replace"),
                                  struct.unpack_from("<i", data, q + 4)[0]))
                    q += 8
        gold, = struct.unpack_from("<i", data, q)
        units.append({"id": oid, "var": var, "x": x, "y": y, "z": z, "owner": owner,
                      "gold": gold, "drops": drops, "hp": hp, "flags": flags,
                      "start": p, "size": (starts[k + 1] - p) if k + 1 < len(starts) else 0})
    return units


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
    dump = int(opts.get("dump", 0))
    tmp = os.path.join(HERE, "_tmp", "units")
    os.makedirs(tmp, exist_ok=True)
    w3e = os.path.join(tmp, "war3map.w3e")
    doo = os.path.join(tmp, "war3mapUnits.doo")
    for f in (w3e, doo):
        if os.path.exists(f):
            os.remove(f)
    subprocess.run([exe, "extract", map_path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=180)
    subprocess.run([exe, "extract", map_path, "war3mapUnits.doo", tmp, "/fp"],
                   capture_output=True, timeout=180)
    if not os.path.exists(doo):
        print("该地图没有 war3mapUnits.doo")
        return 0

    t = load_terrain(w3e)
    data = open(doo, "rb").read()
    magic, ver, sub, count = struct.unpack_from("<4sIII", data, 0)
    starts = scan_units(data, map_w=t["W"], map_h=t["H"])
    units = parse_at(data, starts)

    print(f"===== {os.path.basename(map_path)} =====")
    print(f"war3mapUnits.doo  v{ver}.{sub}  头部声明 {count} 条  文件 {len(data)} 字节")
    print(f"  扫描到 {len(units)} 条记录"
          + ("  ✔ 与头部声明一致" if len(units) == count else "  ✘ 与头部声明不一致"))
    sizes = [u["size"] for u in units if u["size"]]
    if sizes:
        print(f"  记录长度实测: 最小 {min(sizes)} / 最大 {max(sizes)} 字节"
              f"（说明长度公式尚未完全定死，见文件头注释）")

    print(f"\n单位类型: {dict(Counter(u['id'] for u in units).most_common(40))}")
    owners = Counter(u["owner"] for u in units)
    print(f"owner 分布: {dict(sorted(owners.items()))}")
    gold = [u for u in units if u["id"] == "ngol"]
    if gold:
        print(f"金矿(ngol): {len(gold)} 座  金量 "
              f"{sorted(set(u['gold'] for u in gold))}  "
              f"坐标 {[(int(u['x']), int(u['y'])) for u in gold]}")
    shops = [u for u in units if u["owner"] == 15 and u["id"] != "ngol"]
    if shops:
        print(f"其他中立建筑(owner=15): {dict(Counter(u['id'] for u in shops))}")

    bad = {"出界": [], "水里": [], "悬崖上": [], "边界外": []}
    zerr = []
    for u in units:
        info = terrain_at(t, u["x"], u["y"])
        zc = terrain_z(t, u["x"], u["y"])
        if zc is not None:
            zerr.append(abs(u["z"] - zc))
        if info is None:
            bad["出界"].append(u); continue
        water, cliff, boundary = info
        if water:
            bad["水里"].append(u)
        elif cliff:
            bad["悬崖上"].append(u)
        if boundary:
            bad["边界外"].append(u)
    n = len(units)
    print("\n落在当前地形上的体检:")
    for k, v in bad.items():
        detail = ", ".join(f"{u['id']}@{int(u['x'])},{int(u['y'])}" for u in v[:6])
        print(f"  {k:<6} {len(v):>3} / {n}  " + (detail + (" ..." if len(v) > 6 else "")
                                                  if v else "✔"))
    if zerr:
        zerr = np.array(zerr)
        print(f"  高度对账: 单位 z 与地形高度差  平均 {zerr.mean():.1f} / 最大 {zerr.max():.1f} "
              f"WE 单位（>8 的 {int((zerr > 8).sum())} 个）")
        print("    ← 模板自身应≈0；若在生成图上数值很大，说明这些单位是模板遗留、"
              "高度已经对不上了")

    if dump:
        print("\n明细:")
        for u in units[:dump]:
            info = terrain_at(t, u["x"], u["y"])
            tag = "出界" if info is None else ("水" if info[0] else
                                              ("崖" if info[1] else ("边界" if info[2] else "陆地")))
            print(f"  {u['id']} owner={u['owner']:<3} ({u['x']:>8.0f},{u['y']:>8.0f}) "
                  f"z={u['z']:>7.1f} gold={u['gold']:<6} {tag}"
                  + (f" 掉落={u['drops']}" if u["drops"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
