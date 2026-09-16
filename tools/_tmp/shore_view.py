# -*- coding: utf-8 -*-
"""岸边局部放大对比图：官方图 vs 我们的图，同一个渲染口径。

渲染内容（每个角点 6 像素）：
  * 陆地：按「相对水面高度」上色 + 山体阴影
  * 水：按深度上色（浅=亮蓝，深=暗蓝）
  * 叠一层等高线（每 64 WE 一条）→ 能直接看出坡度疏密
用法: python tools/_tmp/shore_view.py
"""
import os
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import add_doodads as A  # noqa: E402

GROUND_ZERO, LAYER_STEP = 8192, 512
PXM = 6


def read_map(path, tmp):
    exe = A.default_exe()
    subprocess.run([exe, "extract", path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=180)
    p = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(p):
        return None
    w3e = open(p, "rb").read()
    _ts, W, H, HS = A.read_w3e_header(w3e)
    R, C = H + 1, W + 1
    gh = np.zeros((R, C), np.int32)
    layer = np.zeros((R, C), np.int32)
    water = np.zeros((R, C), bool)
    surf = np.zeros((R, C), np.float32)
    for r in range(R):
        for c in range(C):
            off = HS + (r * C + c) * 7
            g, whf, fb, _b5, b6 = struct.unpack_from("<HHBBB", w3e, off)
            gh[r, c] = g
            layer[r, c] = b6 & 0x0F
            water[r, c] = bool(fb & 0x40)
            surf[r, c] = ((whf & 0x3FFF) - GROUND_ZERO) / 4.0
    world = (gh - GROUND_ZERO + (layer - 2) * LAYER_STEP) / 4.0
    return world - surf, water, W, H


def shade(h, exag=1.6):
    gy, gx = np.gradient(h)
    nz = 1.0 / np.sqrt(1.0 + exag * exag * (gx * gx + gy * gy))
    lx, ly, lz = -0.5, 0.5, 0.7071
    return np.clip((-gx * exag * lx - gy * exag * ly + lz) * nz, 0.0, 1.0)


def render(h, water, y0, y1, x0, x1, title=""):
    sub_h = h[y0:y1, x0:x1]
    sub_w = water[y0:y1, x0:x1]
    lv = np.clip(sub_h, -512, 768)
    t = (lv + 512) / 1280.0
    img = np.zeros(sub_h.shape + (3,), np.float32)
    img[:, :, 0] = 70 + 170 * t
    img[:, :, 1] = 55 + 165 * t
    img[:, :, 2] = 35 + 120 * t
    img = img * (0.45 + 0.55 * shade(sub_h)[:, :, None])
    # 水：按深度上色
    dep = np.clip(-sub_h, 0, 512) / 512.0
    wimg = np.zeros(sub_h.shape + (3,), np.float32)
    wimg[:, :, 0] = 230 - 190 * dep
    wimg[:, :, 1] = 245 - 175 * dep
    wimg[:, :, 2] = 255 - 105 * dep
    img[sub_w] = wimg[sub_w] * 0.92
    # 等高线：每 64 WE 一条（坡度越陡线越密）
    step = 64.0
    bands = np.floor(sub_h / step).astype(np.int32)
    edge = np.zeros(sub_h.shape, bool)
    edge[:, 1:] |= bands[:, 1:] != bands[:, :-1]
    edge[1:, :] |= bands[1:, :] != bands[:-1, :]
    img[edge & ~sub_w] = np.array([25, 18, 12], np.float32)
    img = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(img[::-1]).resize(
        ((x1 - x0) * PXM, (y1 - y0) * PXM), Image.NEAREST)
    return im


def pick_window(water, size=44):
    """挑一个「水陆各占一些」的窗口：找水比例在 25%~60% 的行，取中间。"""
    H, W = water.shape
    best, bestscore = None, 1e9
    for y0 in range(0, H - size, 4):
        for x0 in range(0, W - size, 4):
            f = float(water[y0:y0 + size, x0:x0 + size].mean())
            s = abs(f - 0.42)
            if s < bestscore:
                bestscore, best = s, (y0, x0)
    return best


CASES = [
    ("官方 (4)LostTemple",
     r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps\(4)LostTemple.w3m", 0.30),
    ("官方 (6)DarkForest",
     r"Z:\Game\Warcraft III Frozen Throne 1.27a publish\Maps\(6)DarkForest.w3m", 0.42),
    ("我们 acc_auto", os.path.join(ROOT, "out", "acc_auto.w3x"), 0.42),
    ("我们 gui_cliffs", os.path.join(ROOT, "out", "gui_cliffs.w3x"), 0.42),
]

def main():
    tmp = A.make_tmp("shoreview")
    tiles = []
    size = 44
    try:
        for name, path, want in CASES:
            if not os.path.exists(path):
                print("缺", path)
                continue
            got = read_map(path, tmp)
            if got is None:
                print("读不到", path)
                continue
            h, water, W, H = got
            y0, x0 = pick_window(water, size)
            im = render(h, water, y0, y0 + size, x0, x0 + size)
            tiles.append((name, im))
            print(f"{name}: 窗口 y={y0} x={x0} 水占比 "
                  f"{water[y0:y0+size, x0:x0+size].mean()*100:.0f}%")
    finally:
        A.drop_tmp(tmp)

    if not tiles:
        return
    pad = 10
    lab = 22
    w = size_w = max(t[1].width for t in tiles)
    cell_h = max(t[1].height for t in tiles)
    canvas = Image.new("RGB", (w * 2 + pad * 3, (cell_h + lab) * 2 + pad * 3), (245, 245, 240))
    from PIL import ImageDraw, ImageFont
    try:
        f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)
    except Exception:
        f = ImageFont.load_default()
    d = ImageDraw.Draw(canvas)
    for i, (name, im) in enumerate(tiles[:4]):
        cx, cy = i % 2, i // 2
        px = pad + cx * (w + pad)
        py = pad + cy * (cell_h + lab + pad)
        canvas.paste(im, (px, py))
        d.text((px + 6, py + cell_h + 3), name, fill=(20, 20, 20), font=f)
    out = os.path.join(ROOT, "out", "shore_compare.png")
    canvas.save(out)
    print("saved", out, canvas.size)


if __name__ == "__main__":
    main()
