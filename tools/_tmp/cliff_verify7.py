# -*- coding: utf-8 -*-
"""正确解析 CliffTypes.slk（列名在第 1 行，行从 Y2 开始）。输出 16 个 id。"""
import mpyq, os, shutil, tempfile

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"
WANT = {"CLdi","CLgr","CWgr","CWsn","CFdi","CFgr","CAgr","CAdi",
        "CBde","CBgr","CCgr","CCdi","CNdi","CNsn","CYdi","CYsq"}

def parse(text):
    cols, rows, x, y = {}, {}, 0, 0
    for ln in text.splitlines():
        for seg in ln.split(";")[1:]:
            if not seg:
                continue
            k, v = seg[0], seg[1:]
            if k == "C":
                sub = v
                xk = yk = kv = None
                # 子段内再有 ; 分隔
                parts = (";" + v).split(";C")
                for pr in parts:
                    pr = pr.lstrip(";C")
                    if not pr:
                        continue
                    kk, vv = pr[0], pr[1:]
                    if kk == "X": xk = int(vv)
                    elif kk == "Y": yk = int(vv)
                    elif kk == "K": kv = vv
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
    for y, r in sorted(rows.items()):
        cid = (r.get("cliffID") or "").strip()
        if cid.upper() in WANT:
            print(f"  {cid:5s} groundTile={r.get('groundTile','?'):6s} upperTile={r.get('upperTile','?'):4s} name={r.get('name','')}")
            n += 1
    print(f"  命中 {n}/16")
