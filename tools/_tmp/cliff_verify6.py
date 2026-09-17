# -*- coding: utf-8 -*-
"""调试：打印 CliffTypes.slk 原始头部 + 首几行，看列名与值格式。"""
import mpyq, os, shutil, tempfile

GAME = u"Z:/Game/Warcraft III Frozen Throne 1.27a publish/"
a = mpyq.MPQArchive(GAME + "War3x.mpq")
data = a.read_file("TerrainArt\\CliffTypes.slk")
text = data.decode("utf-8", "replace")
lines = text.splitlines()
for ln in lines[:25]:
    print(ln)
