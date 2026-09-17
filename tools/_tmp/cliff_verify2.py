# -*- coding: utf-8 -*-
"""列出各 MPQ 里含 Cliff 的文件路径，找对文件名。"""
import mpyq, os, shutil, tempfile

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"
for mpq_name in ("war3.mpq", "War3x.mpq", "War3Patch.mpq"):
    path = GAME + mpq_name
    tmp = None
    try:
        a = mpyq.MPQArchive(path)
    except Exception:
        tmp = tempfile.mktemp(suffix=".mpq")
        shutil.copy2(path, tmp)
        a = mpyq.MPQArchive(tmp)
    names = getattr(a, "names", None) or {}
    hits = [n for n in names if "cliff" in n.lower()]
    print(mpq_name, ":", hits[:12])
    if tmp:
        os.unlink(tmp)
