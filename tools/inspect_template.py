# -*- coding: utf-8 -*-
"""体检模板地图：尺寸 / 地形纹理集 / 游玩区 / 玩家槽位 / 单位 / 装饰物。

用法: python inspect_template.py <目录或地图...> [--exe 路径]

关注点（生成器只覆盖 war3map.w3e 与 war3map.doo，所以模板里
其余文件必须「干净」）：
  * 有没有 war3mapUnits.doo —— 有几条、都是什么（应该只有 sloc 出生点或干脆没有）
  * war3map.doo 里有多少装饰物（应该为 0，否则会和生成器铺的树打架）
  * 地形纹理集（groundTexture 列表）——生成器不改纹理，模板的纹理就是成品纹理
  * w3i 里的玩家槽位 / 游玩区尺寸 —— 决定 sloc 该摆在哪
"""
import os
import struct
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))

TILESET = {
    "A": "Ashenvale 灰谷", "B": "Barrens 贫瘠之地", "C": "Felwood 费伍德",
    "D": "Dalaran 达拉然", "F": "Lordaeron Fall 洛丹伦(秋)", "G": "Underground 地下",
    "I": "Icecrown 冰冠", "J": "Dalaran Ruins 达拉然废墟", "K": "Outland 外域",
    "L": "Lordaeron Summer 洛丹伦(夏)", "N": "Northrend 诺森德", "O": "Outland",
    "Q": "Village Fall 村庄(秋)", "V": "Village 村庄", "W": "Village Winter 村庄(冬)",
    "X": "Cityscape 城市", "Y": "Sunken Ruins 沉没废墟", "Z": "Dalaran Ruins",
}


def default_exe():
    p = os.path.join(ROOT, "bin", "MPQEditor.exe")
    return p if os.path.exists(p) else "MPQEditor.exe"


def strip_str(buf, pos=0):
    """读一个 NUL 结尾字符串（w3i 用：先读一串到 \\0）。"""
    end = buf.index(b"\x00", pos)
    return buf[pos:end].decode("utf-8", "replace"), end + 1


def parse_w3i(data):
    pos = 0
    fmt, = struct.unpack_from("<i", data, pos); pos += 4
    mapver, = struct.unpack_from("<i", data, pos); pos += 4
    editver, = struct.unpack_from("<i", data, pos); pos += 4
    name, pos = strip_str(data, pos)
    author, pos = strip_str(data, pos)
    desc, pos = strip_str(data, pos)
    rec, pos = strip_str(data, pos)
    pos += 8 * 4          # camera bounds 8 floats
    pos += 4 * 4          # bounds complements 4 ints
    pw, = struct.unpack_from("<i", data, pos); pos += 4
    ph, = struct.unpack_from("<i", data, pos); pos += 4
    flags, = struct.unpack_from("<i", data, pos); pos += 4
    tileset = chr(data[pos])
    return {"fmt": fmt, "mapver": mapver, "editver": editver, "name": name,
            "author": author, "desc": desc, "playable": (pw, ph),
            "flags": flags, "tileset": tileset}


def parse_w3e_header(data):
    pos = 8
    tileset = chr(data[pos]); pos += 1
    custom, = struct.unpack_from("<I", data, pos); pos += 4
    n, = struct.unpack_from("<I", data, pos); pos += 4
    tset = [data[pos + 4 * k:pos + 4 * k + 4].decode("ascii", "replace")
            for k in range(n)]; pos += 4 * n
    n2, = struct.unpack_from("<I", data, pos); pos += 4
    cset = [data[pos + 4 * k:pos + 4 * k + 4].decode("ascii", "replace")
            for k in range(n2)]; pos += 4 * n2
    w, = struct.unpack_from("<I", data, pos); pos += 4
    h, = struct.unpack_from("<I", data, pos); pos += 4
    ox, oy = struct.unpack_from("<2f", data, pos); pos += 8
    return {"ver": struct.unpack_from("<I", data, 4)[0], "tileset": tileset,
            "custom": custom, "tiles": tset, "cliffs": cset,
            "W": w - 1, "H": h - 1, "HS": pos, "ox": ox, "oy": oy}


def parse_w3i_players(data):
    """w3i 里玩家段不易稳解析，这里只做一个弱校验：返回值可能是 None。"""
    try:
        pos = 0
        pos += 12
        for _ in range(4):
            _, pos = strip_str(data, pos)
        pos += 8 * 4 + 4 * 4 + 4 * 3 + 1
        pos += 4 * 4 + 4 + 4
        n, = struct.unpack_from("<i", data, pos); pos += 4
        return n if 0 < n <= 24 else None
    except Exception:
        return None


def doo_count(data, rec_len=42):
    if len(data) < 16:
        return None
    magic, ver, sub, count = struct.unpack_from("<4sIII", data, 0)
    return count


def units_summary(data):
    if len(data) < 16:
        return None
    magic, ver, sub, count = struct.unpack_from("<4sIII", data, 0)
    ids = Counter()
    # 保守扫描：只找连续可打印的 4 字节 id 且其后坐标合理
    for p in range(16, len(data) - 91):
        b = data[p:p + 4]
        if b in (b"sloc", b"ngol", b"stwp", b"nwgt"):
            ids[b.decode()] += 1
    if count == 0:
        return {"count": 0, "ids": {}}
    return {"count": count, "ids": dict(ids)}


def inspect(map_path, exe):
    tmp = os.path.join(HERE, "_tmp", "tpl")
    os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(tmp):
        try:
            os.remove(os.path.join(tmp, f))
        except OSError:
            pass
    subprocess.run([exe, "extract", map_path, "*", tmp, "/fp"],
                   capture_output=True, timeout=300)
    got = sorted(os.listdir(tmp))
    print(f"\n===== {os.path.basename(map_path)}  ({os.path.getsize(map_path)} 字节) =====")
    print(f"  含 {len(got)} 个文件: {', '.join(got)}")

    w3i_p = os.path.join(tmp, "war3map.w3i")
    if os.path.exists(w3i_p):
        d = open(w3i_p, "rb").read()
        i = parse_w3i(d)
        np_ = parse_w3i_players(d)
        print(f"  w3i v{i['fmt']}: 名称={i['name']!r}  作者={i['author']!r}")
        print(f"       纹理集 = '{i['tileset']}' {TILESET.get(i['tileset'], '?')}"
              f"   游玩区 {i['playable'][0]}x{i['playable'][1]}"
              f"   玩家数(粗解)={np_}")
    w3e_p = os.path.join(tmp, "war3map.w3e")
    if os.path.exists(w3e_p):
        d = open(w3e_p, "rb").read()
        e = parse_w3e_header(d)
        print(f"  w3e v{e['ver']}: 纹理集 '{e['tileset']}' {TILESET.get(e['tileset'], '?')}"
              f"   网格 {e['W']}x{e['H']} 瓦片")
        print(f"       地面纹理 {len(e['tiles'])} 种: {e['tiles']}")
        print(f"       悬崖纹理 {len(e['cliffs'])} 种")
        gh = set(); ly = set(); fl = set()
        for k in range(e["HS"], len(d) - 6, 7):
            h, = struct.unpack_from("<H", d, k)
            gh.add(h); ly.add(d[k + 4] & 0x0F); fl.add(d[k + 6])
        print(f"       高度种类={len(gh)} 层位种类={len(ly)} 标志位={sorted(fl)}"
              f"  地面高度={sorted(gh)[:4]}{'...' if len(gh) > 4 else ''}"
              f"  {'✔ 完全平坦' if len(gh) == 1 and len(ly) == 1 else '← 有起伏'}")
    doo_p = os.path.join(tmp, "war3map.doo")
    if os.path.exists(doo_p):
        d = open(doo_p, "rb").read()
        print(f"  war3map.doo: 声明 {doo_count(d)} 条装饰物"
              f"  {'✔ 空' if doo_count(d) == 0 else '✘ 非空'}")
    else:
        print("  war3map.doo: 不存在（生成器会新建）")
    u_p = os.path.join(tmp, "war3mapUnits.doo")
    if os.path.exists(u_p):
        d = open(u_p, "rb").read()
        s = units_summary(d)
        print(f"  war3mapUnits.doo: 声明 {s['count']} 条"
              f"  识别到的关键 id: {s['ids']}"
              f"  {'✔ 空' if s['count'] == 0 else '← 注意：有残留单位'}")
    else:
        print("  war3mapUnits.doo: 不存在（生成器会新建）")


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
        print(__doc__); return 1
    exe = opts.get("exe") or default_exe()
    targets = []
    for a in args:
        if os.path.isdir(a):
            for f in sorted(os.listdir(a)):
                if f.lower().endswith((".w3x", ".w3m")):
                    targets.append(os.path.join(a, f))
        else:
            targets.append(a)
    for t in targets:
        inspect(t, exe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
