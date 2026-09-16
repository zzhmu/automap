# -*- coding: utf-8 -*-
"""把官方地图自带的 war3mapMap.blp（WE 生成的地形预览图）解出来。

这是**权威基准**：它就是 WE 渲染这张地图的样子，水在哪、浅水什么样，一目了然。
BLP1: "BLP1" + u32 compression(0=JPEG,1=palette) + u32 alphaBits/flags
      + u32 width + u32 height + u32 mipOffsets[16] + u32 mipSizes[16]
      JPEG 的话，数据段直接是 JPEG 流；调色板的话是 256*4 调色板 + 索引。

用法: python tools/_tmp/blp_preview.py "(9)Riverrun.w3m"
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

PUB = os.path.normpath(os.path.join(ROOT, ".."))
MAPS = os.path.join(PUB, "Maps")


def decode_blp(raw):
    if raw[:4] != b"BLP1":
        return None
    comp, flags, w, h = struct.unpack_from("<IIII", raw, 4)
    offs = struct.unpack_from("<16I", raw, 20)
    sizes = struct.unpack_from("<16I", raw, 84)
    data = raw[offs[0]: offs[0] + sizes[0]]
    if comp == 0:                                    # JPEG 内容
        i = data.find(b"\xff\xd8")
        from io import BytesIO
        im = Image.open(BytesIO(data[i:]))
        return im.convert("RGBA")
    if comp == 1:                                    # 256 色 + 索引
        pal = np.frombuffer(raw, np.uint8, count=1024,
                            offset=offs[0] + sizes[0] - 1024).reshape(256, 4)
        idx = np.frombuffer(raw, np.uint8, count=w * h,
                            offset=offs[0] + sizes[0]).reshape(h, w)
        # 索引数据在调色板之前，重新按官方布局取
        idx = np.frombuffer(data, np.uint8, count=w * h, offset=0).reshape(h, w)
        plt_off = offs[0] + w * h
        pal = np.frombuffer(raw, np.uint8, count=1024,
                            offset=plt_off).reshape(256, 4)
        rgb = pal[idx][:, :, :3].astype(np.uint8)
        return Image.fromarray(rgb[:, :, ::-1])
    return None


def main():
    maps = sys.argv[1:] or ["(9)Riverrun.w3m", "(4)MysticIsles.w3m",
                            "(8)BloodvenomFalls.w3m", "(4)LostTemple.w3m"]
    tmp = A.make_tmp("blp")
    tiles = []
    try:
        for fn in maps:
            p = fn if os.path.isabs(fn) else os.path.join(MAPS, fn)
            if not os.path.exists(p):
                print("缺", fn)
                continue
            for f in os.listdir(tmp):
                os.remove(os.path.join(tmp, f))
            subprocess.run([A.default_exe(), "extract", p, "war3mapMap.blp", tmp, "/fp"],
                           capture_output=True, timeout=240)
            q = os.path.join(tmp, "war3mapMap.blp")
            if not os.path.exists(q):
                print("无预览图", fn)
                continue
            raw = open(q, "rb").read()
            im = decode_blp(raw)
            if im is None:
                print("解不了", fn, raw[:16].hex())
                continue
            print(f"{fn}: {im.size} mode={im.mode}")
            im = im.convert("RGB")
            sc = max(1, 420 // max(im.size))
            im = im.resize((im.width * sc, im.height * sc), Image.NEAREST)
            tiles.append((fn, im))
    finally:
        A.drop_tmp(tmp)

    if not tiles:
        return
    pad, lab = 10, 22
    cw = max(t[1].width for t in tiles)
    ch = max(t[1].height for t in tiles)
    cols = min(2, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    from PIL import ImageDraw, ImageFont
    canvas = Image.new("RGB", (cols * (cw + pad) + pad,
                               rows * (ch + lab + pad) + pad), (245, 245, 240))
    try:
        f = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)
    except Exception:
        f = ImageFont.load_default()
    d = ImageDraw.Draw(canvas)
    for i, (name, im) in enumerate(tiles):
        px = pad + (i % cols) * (cw + pad)
        py = pad + (i // cols) * (ch + lab + pad)
        canvas.paste(im, (px, py))
        d.text((px + 4, py + ch + 3), name, fill=(20, 20, 20), font=f)
    out = os.path.join(ROOT, "out", "official_previews.png")
    canvas.save(out)
    print("saved", out, canvas.size)


main()
