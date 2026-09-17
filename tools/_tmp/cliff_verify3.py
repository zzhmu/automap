# -*- coding: utf-8 -*-
"""mpyq 直接读（listfile 可能缺失）；试标准路径 + (listfile)。"""
import mpyq, os, shutil, tempfile

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"
for mpq_name in ("war3.mpq", "War3x.mpq"):
    path = GAME + mpq_name
    tmp = None
    try:
        a = mpyq.MPQArchive(path)
    except Exception:
        tmp = tempfile.mktemp(suffix=".mpq")
        shutil.copy2(path, tmp)
        a = mpyq.MPQArchive(tmp)
    for fn in ("Units\\CliffTypes.slk", "Units/CliffTypes.slk",
               "UI\\CliffTypes.slk", "CliffTypes.slk",
               "Units\\TerrainArt\\CliffTypes.slk"):
        try:
            data = a.read_file(fn)
        except Exception as e:
            data = None
        if data:
            print(mpq_name, "HIT:", fn, len(data), "字节")
            break
    else:
        lf = None
        try:
            lf = a.read_file("(listfile)")
        except Exception:
            pass
        if lf:
            txt = lf.decode("utf-8", "replace")
            hits = [ln for ln in txt.splitlines() if "cliff" in ln.lower()]
            print(mpq_name, "listfile cliff:", hits[:10])
        else:
            print(mpq_name, "无 listfile")
