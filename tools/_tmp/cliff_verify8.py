# -*- coding: utf-8 -*-
"""最简解析：SLK 每行一条 C 记录（已从原始 dump 确认格式 C;Xn;[Yn;]K"value"）。"""
import mpyq, os, shutil, tempfile, re

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"
WANT = {"CLdi","CLgr","CWgr","CWsn","CFdi","CFgr","CAgr","CAdi",
        "CBde","CBgr","CCgr","CCdi","CNdi","CNsn","CYdi","CYsq"}

def parse(text):
    cols, rows, x, y = {}, {}, 0, 0
    for ln in text.splitlines():
        if not ln.startswith("C;"):
            continue
        xk = yk = kv = None
        for seg in ln[2:].split(";"):
            if len(seg) >= 1:
                k, v = seg[0], seg[1:]
                if k == "X": xk = int(v)
                elif k == "Y": yk = int(v)
                elif k == "K": kv = v
        x = xk if xk else x
        y = yk if yk else y
        if kv is not None:
            if y == 1:
                cols[x] = kv.strip('"')
            else:
                rows.setdefault(y, {})[cols.get(x, x)] = kv.strip('"')
    return rows

for mpq_name in ("war3.mpq", "War3x.mpq"):
    path = GAME + mpq_name
    tmp = None
    try:
        a = mpyq.MPQArchive(path)
    except Exception:
        tmp = tempfile.mktemp(suffix=".mpq")
        shutil.copy2(path, tmp)
        a = mpyq.MPQArchive(tmp)
    data = a.read_file("TerrainArt\\CliffTypes.slk")
    rows = parse(data.decode("utf-8", "replace"))
    print(f"== {mpq_name}: {len(rows)} 行 ==")
    n = 0
    for yy, r in sorted(rows.items()):
        cid = (r.get("cliffID") or "").strip()
        if cid.upper() in WANT:
            print(f"  {cid:5s} groundTile={r.get('groundTile','?'):6s} upperTile={r.get('upperTile','?'):4s} name={r.get('name','')}")
            n += 1
    print(f"  命中 {n}/16")
