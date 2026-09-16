# -*- coding: utf-8 -*-
"""画一张探针图的示意图（哪条带多深），方便在对话里对照。"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEPTHS = [4, 16, 32, 64, 96, 128, 160, 192, 256]
SCALE = 40
W = 512
H = 448
img = Image.new("RGB", (W, H), (58, 58, 62))
dr = ImageDraw.Draw(img)
band = W // len(DEPTHS)
for k, d in enumerate(DEPTHS):
    # 颜色随深度变深（浅水亮 → 深水暗）
    t = min(1.0, d / 256.0)
    col = (int(120 * (1 - t) + 18 * t), int(190 * (1 - t) + 58 * t), int(230 * (1 - t) + 150 * t))
    x0 = k * band + 2
    dr.rectangle([x0, 6, x0 + band - 6, H - 46], fill=col,
                 outline=(230, 230, 230), width=1)
    label = f"{d} WE\n{d / 128:.2f}层"
    dr.multiline_text((x0 + band // 2 - 16, H - 38), label, fill=(240, 240, 240),
                      align="center", spacing=2)
dr.text((8, H - 22), "每条水带 = 固定水深，陆地在各带之间（细灰缝）", fill=(220, 220, 220))
img.save(os.path.join(ROOT, "out", "probe_water_depth_示意图.png"))
print("ok")
