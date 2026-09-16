# -*- coding: utf-8 -*-
"""树林「官方 vs 我们」并排对比图（纯读图拼贴，不改任何产物）。

上排 = 1.27a 原生官方对战图（render_official_trees.py 产出的树掩码 + 水面）
下排 = 我们 GUI 全链路验收产物（out/acc_*_trees_big.png，走 accept_forest.py）

输出 out/forest_compare.png
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "out")

TOP = [
    ("官方 Harrow", os.path.join(HERE, "(2)Harrow.w3m_trees.png")),
    ("官方 GnollWood", os.path.join(HERE, "(6)GnollWood.w3m_trees.png")),
    ("官方 DarkForest", os.path.join(HERE, "(6)DarkForest.w3m_trees.png")),
]
BOT = [
    ("我们 acc_land", os.path.join(OUT, "acc_land_trees_big.png")),
    ("我们 acc_auto", os.path.join(OUT, "acc_auto_trees_big.png")),
    ("我们 acc_cliffs", os.path.join(OUT, "acc_cliffs_trees_big.png")),
]

CELL = 300          # 每格图画布尺寸
PAD = 8
LABEL_H = 22
BG = (245, 245, 240)
FG = (20, 20, 20)


def font(sz):
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def load(path):
    if not os.path.exists(path):
        return None
    im = Image.open(path).convert("RGB")
    im.thumbnail((CELL, CELL), Image.NEAREST)
    return im


def tile(im):
    c = Image.new("RGB", (CELL, CELL), (230, 230, 225))
    if im is None:
        return c
    c.paste(im, ((CELL - im.width) // 2, (CELL - im.height) // 2))
    return c


def row(items):
    w = len(items) * CELL + (len(items) + 1) * PAD
    h = CELL + LABEL_H * 2 + PAD
    strip = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(strip)
    f = font(15)
    for i, (name, path) in enumerate(items):
        x = PAD + i * (CELL + PAD)
        im = load(path)
        strip.paste(tile(im), (x, PAD))
        if im is None:
            d.text((x + 8, PAD + 8), "缺图: " + os.path.basename(path), fill=(180, 30, 30), font=f)
        tb = d.textbbox((0, 0), name, font=f)
        d.text((x + (CELL - (tb[2] - tb[0])) // 2, PAD + CELL + 3), name, fill=FG, font=f)
    return strip


def main():
    r1 = row(TOP)
    r2 = row(BOT)
    W = max(r1.width, r2.width) + PAD * 2
    H = r1.height + r2.height + PAD
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(r1, (PAD, 0))
    canvas.paste(r2, (PAD, r1.height))
    out = os.path.join(OUT, "forest_compare.png")
    canvas.save(out)
    print("saved", out, canvas.size)


if __name__ == "__main__":
    main()
