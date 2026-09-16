# -*- coding: utf-8 -*-
"""岸线缓坡 A/B 对比图（放大版）。

上排：官方两张，作为「自然岸线」的标尺
下排：我们同种子、只差 --shore-width 的前 / 后（**同一个窗口**）
每角点 12 px；陆地按相对水面高度上色 + 山体阴影；水按深度上色，且把 0~160 WE
这一段拉满对比度 —— 这样 68 WE 的浅滩和 128 WE 的全深一眼能分出来。
下方再画一条「离岸 k 格 × 水深中位」剖面曲线。
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
import shore_view as SV  # noqa: E402
import shore_depth_profile as DP  # noqa: E402

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")
SIZE, PXM, DEPCAP = 30, 12, 170.0

CASES = [
    ("官方 (4)LostTemple", os.path.join(MAPS, "(4)LostTemple.w3m")),
    ("官方 (4)MysticIsles", os.path.join(MAPS, "(4)MysticIsles.w3m")),
    ("我们：岸线缓坡 关", os.path.join(ROOT, "out", "shore_off.w3x")),
    ("我们：岸线缓坡 开", os.path.join(ROOT, "out", "shore_on.w3x")),
]


def shade(h, exag=1.6):
    gy, gx = np.gradient(h)
    nz = 1.0 / np.sqrt(1.0 + exag * exag * (gx * gx + gy * gy))
    return np.clip((-gx * exag * -0.5 - gy * exag * 0.5 + 0.7071) * nz, 0.0, 1.0)


def render(h, water, y0, y1, x0, x1):
    sh = h[y0:y1, x0:x1]
    sw = water[y0:y1, x0:x1]
    t = np.clip(sh, -512, 768) / 1280.0
    img = np.zeros(sh.shape + (3,), np.float32)
    img[:, :, 0] = 70 + 170 * t
    img[:, :, 1] = 55 + 165 * t
    img[:, :, 2] = 35 + 120 * t
    img = img * (0.45 + 0.55 * shade(sh)[:, :, None])
    dep = np.clip(-sh, 0, DEPCAP) / DEPCAP
    wi = np.zeros(sh.shape + (3,), np.float32)
    wi[:, :, 0] = 240 - 205 * dep
    wi[:, :, 1] = 250 - 190 * dep
    wi[:, :, 2] = 255 - 120 * dep
    img[sw] = wi[sw]
    bands = np.floor(sh / 64.0).astype(np.int32)
    e = np.zeros(sh.shape, bool)
    e[:, 1:] |= bands[:, 1:] != bands[:, :-1]
    e[1:, :] |= bands[1:, :] != bands[:-1, :]
    img[e] = np.array([25, 18, 12], np.float32)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)[::-1]).resize(
        ((x1 - x0) * PXM, (y1 - y0) * PXM), Image.NEAREST)


tmp = A.make_tmp("shoreab")
tiles, profs = [], []
prof_official = None
try:
    off = []
    for fn in ("(4)MysticIsles.w3m", "(9)Riverrun.w3m", "(8)Plaguelands.w3m",
               "(4)LostTemple.w3m", "(6)GnollWood.w3m", "(6)SwampOfSorrows.w3m",
               "(12)IceCrown.w3m", "(12)DustwallowKeys.w3m"):
        p = os.path.join(MAPS, fn)
        if os.path.exists(p):
            r = DP.prof(p, tmp, "o")
            if r:
                off.append(r["prof"])
    if off:
        prof_official = np.nanmedian(np.array(off, float), axis=0)
        print("官方剖面中位 k=1..10:", " ".join(f"{v:.0f}" for v in prof_official))

    ours_win = None
    for name, path in CASES:
        if not os.path.exists(path):
            print("缺", path)
            continue
        got = SV.read_map(path, tmp)
        if got is None:
            print("读不到", path)
            continue
        h, water, W, H = got
        if name.startswith("官方"):
            win = SV.pick_window(water, SIZE)
        else:
            if ours_win is None:
                ours_win = SV.pick_window(water, SIZE)
            win = ours_win
        y0, x0 = win
        tiles.append((name, render(h, water, y0, y0 + SIZE, x0, x0 + SIZE)))
        r = DP.prof(path, tmp, "x")
        profs.append((name, np.array(r["prof"], float) if r else np.full(10, np.nan)))
        print(f"{name}: 窗口 y={y0} x={x0}")
finally:
    A.drop_tmp(tmp)

if not tiles:
    sys.exit(0)

pad, lab, plot_h = 12, 24, 210
cw = max(t[1].width for t in tiles)
ch = max(t[1].height for t in tiles)
PW = 2 * (cw + pad) + pad
PH = 2 * (ch + lab + pad) + pad
canvas = Image.new("RGB", (PW, PH + plot_h + 34), (247, 246, 242))
try:
    f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 16)
    fs = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 13)
except Exception:
    f = fs = ImageFont.load_default()
d = ImageDraw.Draw(canvas)
for i, (name, im) in enumerate(tiles[:4]):
    px = pad + (i % 2) * (cw + pad)
    py = pad + (i // 2) * (ch + lab + pad)
    canvas.paste(im, (px, py))
    d.text((px + 6, py + ch + 4), name, fill=(20, 20, 20), font=f)

py0 = 2 * (ch + lab + pad) + pad
d.text((pad, py0 - 18), "离岸 k 格 × 水深中位（WE；线越靠下 = 水越深）",
       fill=(30, 30, 30), font=fs)
gx0, gy0, gw, gh = pad + 48, py0 + 8, PW - pad * 2 - 62, plot_h - 46
d.rectangle([gx0, gy0, gx0 + gw, gy0 + gh], outline=(190, 190, 185))
DMAX = 300.0
for v in (0, 50, 100, 150, 200, 250, 300):
    yy = gy0 + gh * v / DMAX
    d.line([gx0, yy, gx0 + gw, yy], fill=(228, 228, 222))
    d.text((gx0 - 42, yy - 8), f"{v}", fill=(90, 90, 90), font=fs)
for k in range(1, 11):
    xx = gx0 + gw * (k - 1) / 9.0
    d.text((xx - 4, gy0 + gh + 4), str(k), fill=(90, 90, 90), font=fs)

series = []
if prof_official is not None:
    series.append(("官方 8 图中位", prof_official, (205, 70, 45)))
for (nm, pr) in profs:
    series.append((nm, pr, {"关": (120, 120, 120), "开": (25, 150, 70)}.get(
        nm.split()[-1], (60, 110, 200))))
for nm, pr, c in series:
    pts = [(gx0 + gw * k / 9.0, gy0 + gh * min(pr[k], DMAX) / DMAX)
           for k in range(10) if not np.isnan(pr[k])]
    if len(pts) > 1:
        d.line(pts, fill=c, width=3)
        for px, py in pts:
            d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=c)
lx = gx0 + 4
for nm, pr, c in series:
    d.line([lx, py0 + plot_h - 12, lx + 18, py0 + plot_h - 12], fill=c, width=4)
    d.text((lx + 22, py0 + plot_h - 20), nm, fill=(40, 40, 40), font=fs)
    lx += 34 + int(d.textlength(nm, font=fs))

out = os.path.join(ROOT, "out", "shore_ab.png")
canvas.save(out)
print("saved", out, canvas.size)
