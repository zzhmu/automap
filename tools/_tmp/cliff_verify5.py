# -*- coding: utf-8 -*-
"""读 TerrainArt\\CliffTypes.slk，输出 16 个用到的悬崖 id 的 groundTile/comment。"""
import mpyq, os, shutil, tempfile

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"
WANT = {"CLdi","CLgr","CWgr","CWsn","CFdi","CFgr","CAgr","CAdi",
        "CBde","CBgr","CCgr","CCdi","CNdi","CNsn","CYdi","CYsq"}

def slk_rows(text):
    rows, cols, x, y = {}, {}, 0, 0
    for ln in text.splitlines():
        p = ln.rstrip("\n").split(";")
        if not p or not p[0]:
            continue
        op = p[0][1:2] if p[0].startswith("P") else p[0][:1]
        if not p[0] or p[0][0] not in "CBIPOEX":
            continue
        op = p[0][0]
        vals = []
        for seg in p[1:]:
            vals.append((seg[:1], seg[1:] if len(seg) > 1 else ""))
        if op == "C":
            xv = yv = kv = None
            for k, v in vals:
                if k == "X": xv = int(v)
                elif k == "Y": yv = int(v)
                elif k == "K": kv = v
            x = xv if xv else x
            y = yv if yv else y
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
    if not data:
        print(mpq_name, "读取失败")
        continue
    rows = slk_rows(data.decode("utf-8", "replace"))
    print(f"== {mpq_name}: {len(rows)} 个悬崖类型 ==")
    for y, r in sorted(rows.items()):
        cid = (r.get("cliffID") or r.get("CliffID") or "").strip()
        if cid.upper() in WANT:
            print(f"  {cid:5s} groundTile={r.get('groundTile','?'):6s} "
                  f"texDir={r.get('dirTEX','?'):6s} comment={r.get('comment','')}")
