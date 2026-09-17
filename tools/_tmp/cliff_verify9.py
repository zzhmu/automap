# -*- coding: utf-8 -*-
"""列出 CliffTypes.slk 全部 cliffID + groundTile（不带 WANT 过滤），找实际 id 拼写。"""
import mpyq

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"

def parse(text):
    cols, rows, x, y = {}, {}, 0, 0
    for ln in text.splitlines():
        if not ln.startswith("C;"):
            continue
        xk = yk = kv = None
        for seg in ln[2:].split(";"):
            if seg:
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

a = mpyq.MPQArchive(GAME + "War3x.mpq")
rows = parse(a.read_file("TerrainArt\\CliffTypes.slk").decode("utf-8", "replace"))
for yy, r in sorted(rows.items()):
    print(f"  Y{yy:2d} id={r.get('cliffID','?'):6s} ground={r.get('groundTile','?'):6s} name={r.get('name','')}")
