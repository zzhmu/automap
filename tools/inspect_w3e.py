# -*- coding: utf-8 -*-
"""分析 w3e 角点字段与悬崖/高度的真实对应关系（只读，不改地图）。

用法: python inspect_w3e.py <map.w3x|map.w3m> [--exe MPQEditor路径]
输出: 各字段的分布、以及一个 8x8 采样区块的逐角点明细，用于确认
      groundHeight / layerHeight / cliffTexture / flags 的语义。
"""
import os
import struct
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))


def default_exe():
    """定位随项目自带的 ../bin/MPQEditor.exe（不依赖外部目录）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def read_header(data):
    pos = 8
    tileset = chr(data[pos]); pos += 1
    custom = struct.unpack_from("<I", data, pos)[0]; pos += 4
    n_ground = struct.unpack_from("<I", data, pos)[0]; pos += 4
    ground = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace") for i in range(n_ground)]
    pos += 4 * n_ground
    n_cliff = struct.unpack_from("<I", data, pos)[0]; pos += 4
    cliff = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace") for i in range(n_cliff)]
    pos += 4 * n_cliff
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return {"version": struct.unpack_from("<I", data, 4)[0], "tileset": tileset,
            "custom": custom, "ground": ground, "cliff": cliff,
            "width": w, "height": h, "header": pos}


def main():
    args = []
    opts = {}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k, sep, v = a[2:].partition("=")
            if sep:
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]
                i += 1
            else:
                opts[k] = True
        else:
            args.append(a)
        i += 1

    map_path = args[0]
    exe = opts.get("exe") or default_exe()
    tmp = os.path.join(HERE, "_tmp", "inspect")
    os.makedirs(tmp, exist_ok=True)
    out = os.path.join(tmp, "war3map.w3e")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([exe, "extract", map_path, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=120)
    if not os.path.exists(out):
        print("提取 war3map.w3e 失败")
        return 1

    data = open(out, "rb").read()
    assert data[:4] == b"W3E!"
    info = read_header(data)
    W, H, HS = info["width"], info["height"], info["header"]
    rows, cols = H + 1, W + 1
    print(f"{os.path.basename(map_path)}: {W}x{H}  角点 {cols}x{rows}  v{info['version']}  "
          f"tileset={info['tileset']}  custom={info['custom']}")
    print(f"ground 贴图: {info['ground']}")
    print(f"cliff 贴图: {info['cliff']}")

    gh_c, layer_c, clifftex_c, flag_c, var_c, water_c = (Counter() for _ in range(6))
    tex_c, ramp_c, blight_c, bnd_c = Counter(), Counter(), Counter(), Counter()
    corners = []
    for cy in range(rows):
        for cx in range(cols):
            off = HS + (cy * cols + cx) * 7
            gh, whf, fb, gv_cv, ct_lh = struct.unpack_from("<HHBBB", data, off)
            # 字段布局依据 Wartergen.Wc3Terrain/TerrainTranslator.cs:176-181
            corners.append((cx, cy, gh, whf & 0x3FFF, (whf & 0x4000) != 0,
                            (fb >> 7) & 1, (fb >> 6) & 1, (fb >> 4) & 3, fb & 0x0F,
                            gv_cv >> 3, gv_cv & 0x07, ct_lh >> 4, ct_lh & 0x0F))
    for c in corners:
        gh_c[c[2]] += 1
        layer_c[c[12]] += 1              # 索引 12 才是 layerHeight（11 是 cliffTexture）
        clifftex_c[(c[11], c[10])] += 1  # (cliffTexture, cliffVariation)
        flag_c[(c[5], c[6])] += 1        # (boundary2, water)
        var_c[c[9]] += 1                 # groundVariation
        tex_c[c[8]] += 1                 # groundTexture
        ramp_c[c[7] & 1] += 1            # flags bit4 = ramp (0x10)
        blight_c[(c[7] >> 1) & 1] += 1   # flags bit5 = blight (0x20)
        bnd_c[(c[4], c[5])] += 1         # (boundary1 in waterHeight, boundary2 in flags)
        if c[6]:
            water_c[c[3]] += 1

    def top(counter, n=12, fmt=str):
        return ", ".join(f"{fmt(k)}:{v}" for k, v in counter.most_common(n))

    print(f"\ngroundHeight 去重值 ({len(gh_c)} 种): {top(gh_c, 10)}")
    print(f"layerHeight  去重值 ({len(layer_c)} 种): {top(layer_c, 16)}")
    print(f"cliffTexture/cliffVariation 组合: {top(clifftex_c, 12)}")
    print(f"groundVariation 去重: {top(var_c, 8)}")
    print(f"groundTexture 去重: {top(tex_c, 12)}")
    print(f"ramp 标记(0/1): {top(ramp_c, 2)}   blight(0/1): {top(blight_c, 2)}")
    print(f"flags(boundary2, water): {top(flag_c, 8)}")
    print(f"边界(boundary1, boundary2): {top(bnd_c, 4)}")

    if water_c:
        print(f"waterHeight 去重: {top(water_c, 8)}")

    # 相邻角点 layerHeight 差值的分布 -> 确认悬崖是怎么涌现的
    diff = Counter()
    for cy in range(rows):
        for cx in range(cols):
            i = cy * cols + cx
            if cx + 1 < cols:
                diff[corners[i + 1][12] - corners[i][12]] += 1
            if cy + 1 < rows:
                diff[corners[i + cols][12] - corners[i][12]] += 1
    print(f"\n相邻角点 layerHeight 差值分布: {top(diff, 11)}")

    # 采样一段打印明细：从左上角起 8x8
    print("\n左上角 8x8 角点明细 (x,y,gh,layer,cliffTex,water,tex):")
    for cy in range(min(8, rows)):
        row = []
        for cx in range(min(8, cols)):
            c = corners[cy * cols + cx]
            row.append(f"({c[0]},{c[1]} gh={c[2]} L={c[11]} ct={c[10]} w={c[5]} t={c[8]})")
        print("  " + " ".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
