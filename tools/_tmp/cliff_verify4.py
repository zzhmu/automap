# -*- coding: utf-8 -*-
"""从 listfile 全量搜 TerrainArt/CliffTypes。"""
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
    lf = None
    try:
        lf = a.read_file("(listfile)")
    except Exception:
        pass
    if lf:
        txt = lf.decode("utf-8", "replace")
        hits = [ln for ln in txt.splitlines()
                if "clifftype" in ln.lower() or ("terrainart" in ln.lower() and ".slk" in ln.lower())]
        print(mpq_name, ":", hits[:15])
    else:
        print(mpq_name, ": 无 listfile")
