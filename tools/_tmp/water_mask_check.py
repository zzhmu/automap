# -*- coding: utf-8 -*-
"""判定：官方图里「水标记(0x40) 但深度 <128」的区域到底是什么？

把两个掩码叠在一起画：
    深蓝  = 水标记 且 depth >= 128   （按项目已知规则「引擎会渲成水」）
    浅黄  = 水标记 但 depth <  128   （按同一规则「引擎当干地画」）
    土黄  = 没有水标记
如果浅黄总是绕着深蓝形成一圈细边 → 官方确实留了一圈「湿滩」，规则成立；
如果浅黄是大块湖面 → 规则不成立，浅水其实是会渲成水的。

用法: python tools/_tmp/water_mask_check.py
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402
import shore_depth_profile as DP  # noqa: E402

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")

CASES = ["(9)Riverrun.w3m", "(4)LostTemple.w3m", "(4)MysticIsles.w3m",
         "(8)Plaguelands.w3m", "(6)SwampOfSorrows.w3m", "(8)BloodvenomFalls.w3m"]


def main():
    tmp = A.make_tmp("wmcheck")
    tiles = []
    try:
        for fn in CASES:
            p = os.path.join(MAPS, fn)
            if not os.path.exists(p):
                continue
            depth, water, outside, plane = DP.load2(p, tmp)
            if water.sum() < 50:
                continue
            H, W = depth.shape
            img = np.zeros((H, W, 3), np.uint8)
            img[:, :] = (176, 154, 104)                      # 土黄 = 陆
            dry = water & (depth < 128)
            wet = water & (depth >= 128)
            img[dry] = (250, 226, 128)                       # 浅黄 = 水标记但浅
            t = np.clip(depth, 0, 384) / 384.0
            base = np.stack([120 - 100 * t, 195 - 140 * t, 235 - 80 * t], -1)
            img[wet] = base[wet].astype(np.uint8)
            img[outside] = (60, 60, 60)
            sc = max(1, 900 // max(H, W))
            im = Image.fromarray(img[::-1]).resize((W * sc, H * sc), Image.NEAREST)
            tiles.append((f"{fn}  水标记{water.sum()}  其中<128 {dry.sum()} "
                          f"({dry.sum()*100.0/max(1,water.sum()):.0f}%)", im))
            print(tiles[-1][0])
    finally:
        A.drop_tmp(tmp)

    if not tiles:
        return
    pad, lab = 8, 20
    cw = max(t[1].width for t in tiles)
    ch = max(t[1].height for t in tiles)
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * (cw + pad) + pad,
                               rows * (ch + lab + pad) + pad), (245, 245, 240))
    try:
        f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 14)
    except Exception:
        f = ImageFont.load_default()
    d = ImageDraw.Draw(canvas)
    for i, (name, im) in enumerate(tiles):
        cx, cy = i % cols, i // cols
        px, py = pad + cx * (cw + pad), pad + cy * (ch + lab + pad)
        canvas.paste(im, (px, py))
        d.text((px + 4, py + ch + 2), name, fill=(20, 20, 20), font=f)
    out = os.path.join(ROOT, "out", "water_mask_check.png")
    canvas.save(out)
    print("saved", out, canvas.size)


main()
