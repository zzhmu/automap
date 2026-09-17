# -*- coding: utf-8 -*-
"""用 mpyq 读游戏 CliffTypes.slk，核实用到的 16 个悬崖 id 的 groundTile/comment。"""
import mpyq, os, re, shutil, tempfile

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"
WANT = {"CLdi","CLgr","CWgr","CWsn","CFdi","CFgr","CAgr","CAdi",
        "CBde","CBgr","CCgr","CCdi","CNdi","CNsn","CYdi","CYsq"}

def slk_rows(text):
    # 稀疏 SLK：X/Y 定位，继承上一行同列值
    rows, cols = {}, {}
    x = y = 0
    for ln in text.splitlines():
        p = ln.rstrip("\n").split(";")
        if not p or not p[0]:
            continue
        op = p[0][0] if p[0] else ""
        vals = []
        for seg in p[1:]:
            if len(seg) < 1:
                vals.append(("K", ""))
            else:
                vals.append((seg[0], seg[1:]))
        if op == "C":
            xv = yv = None
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
    return rows, cols

for mpq_name in ("war3.mpq", "War3x.mpq", "War3Patch.mpq"):
    path = GAME + mpq_name
    if not os.path.exists(path):
        continue
    tmp = None
    try:
        a = mpyq.MPQArchive(path)
    except Exception:
        tmp = tempfile.mktemp(suffix=".mpq")
        shutil.copy2(path, tmp)
        a = mpyq.MPQArchive(tmp)
    try:
        data = a.read_file("Units\\CliffTypes.slk") or a.read_file("Units/CliffTypes.slk")
    finally:
        pass  # mpyq 无 close
        if tmp:
            os.unlink(tmp)
    if not data:
        print(mpq_name, "-> 无 CliffTypes.slk")
        continue
    text = data.decode("utf-8", "replace")
    rows, cols = slk_rows(text)
    print(mpq_name, "->", len(rows), "行")
    for y, r in sorted(rows.items()):
        cid = r.get("cliffID") or r.get("CliffID") or ""
        if str(cid).upper() in WANT:
            print(f"  {cid:6s} groundTile={r.get('groundTile','?'):6s} dirTEX={r.get('dirTEX','?'):6s} comment={r.get('comment','')}")
    break
