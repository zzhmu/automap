# -*- coding: utf-8 -*-
"""生成 tools/tilesets.py —— 8 种有官方图数据背书的地图风格：
  纹理表（Terrain.slk 行序 = w3e 索引序）+ convertTo 跨风格语义映射
  + 树模型 / 野怪 id 池 / 雇佣兵营地变体（45 张官方图实测，style_map_stats.txt）。
"""
import os
import re
import sys

import mpyq

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def parse_slk_ordered(text):
    cur_x = cur_y = 0
    rows = {}
    for line in text.splitlines():
        if not line.startswith("C;"):
            continue
        xm = re.search(r";X(\d+)", line)
        ym = re.search(r";Y(\d+)", line)
        km = re.search(r';K("(?:[^"]|"")*"|-?\d+)', line)
        if xm:
            cur_x = int(xm.group(1))
        if ym:
            cur_y = int(ym.group(1))
        if not (cur_x and cur_y) or not km:
            continue
        kv = km.group(1)
        if kv.startswith('"'):
            kv = kv[1:-1].replace('""', '"')
        rows.setdefault(cur_y, {})[cur_x] = kv
    h = rows.get(1, {})
    fc = min(h) if h else None
    out = []
    for y in sorted(rows):
        if y == 1:
            continue
        cells = rows[y]
        uid = cells.get(fc)
        if uid and re.match(r"^[A-Za-z0-9_]{1,4}$", uid):
            out.append((uid, {h.get(x, f"col{x}"): v for x, v in cells.items()}))
    return out


# 官方图实测（tools/_tmp/tileset_map_stats.py → style_map_stats.txt）
TREES = {"L": "LTlt", "A": "ATtr", "B": "BTtw", "C": "CTtr",
         "F": "FTlt", "N": "WTst", "W": "WTtw", "Y": "LTlt"}
TREES["F"] = "FTtw"
MERC = {"L": "nmer", "F": "nmer", "A": "nmr5", "B": "nmr4", "C": "nmr6",
        "N": "nmr7", "W": "nmr3", "Y": "nmr8"}
NAMES = {"L": "洛丹伦的夏天", "W": "洛丹伦的冬天", "F": "洛丹伦的秋天",
         "A": "灰谷", "B": "荒地", "C": "费尔伍德", "N": "诺森德", "Y": "城市"}
POOLS = {
    "L": ["nftr", "nftb", "ngno", "ngst", "nfsp", "ngnb", "nogr", "ngna",
          "ngns", "nfsh", "nomg", "nftt", "ngnw", "ngnv", "nogm", "nogl",
          "ngrk", "nftk", "nrdr", "nggr", "nrdk", "ntrt", "ntrh", "nrwm", "ntrg"],
    "A": ["nfrl", "nwlt", "nsts", "nltl", "ngrw", "ndtb", "nsty", "nfrs",
          "nstl", "nfrb", "nwlg", "ndth", "nfra", "nthl", "nsat", "nwld",
          "ngdk", "ndtr", "ndtt", "ndtw", "ngrd", "nsgt", "nspr", "nfre",
          "nsth", "nstw", "nssp", "ndtp", "nsbm"],
    "B": ["nqbh", "ncim", "ncea", "nrzm", "nbzw", "ncen", "ncer", "nowb",
          "nrzs", "nrzb", "nbzk", "nltl", "nrzg", "nspp", "nthl", "ncks",
          "nstw", "ncnk", "nhrh", "nhrr", "nbzd", "nhrq", "nowk", "nhrw",
          "nrzt", "nowe"],
    "C": ["nmfs", "nfel", "nsts", "nmmu", "nenp", "nstl", "nmpg", "nsth",
          "ninf", "nepl", "nfrl", "nssp", "nenc", "nsgt", "nsbm", "ngdk",
          "nthl", "ngrw", "nfrb", "nfrs", "ngrd", "nfrg", "nfre", "nbal",
          "nltl"],
    "F": ["nogr", "ngna", "nftb", "nogm", "nfsp", "ngst", "ngnw", "nomg",
          "ngns", "ngnv", "ngnb", "nftk", "nbdk", "nogl", "nftr", "nggr",
          "nbwm"],
    "N": ["nwen", "ngh1", "nitt", "nnwl", "nfrp", "nwwf", "nwnr", "nrvi",
          "nnwq", "nnwr", "nits", "nith", "nadw", "nnwa", "nitr", "nadk",
          "nwns", "nitw"],
    "W": ["nomg", "ngns", "nitr", "nitt", "ngnw", "ngna", "nadw", "nogr",
          "nftr", "nitw", "nith", "nadk", "nits", "nfsp", "nftb", "ngno",
          "ngrk", "ngst", "ngnv", "ngnb", "nfsh", "nogm", "nadr", "nftt",
          "nogl", "nggr", "nftk"],
    "Y": ["nass", "ngst", "ngrk", "nkog", "nkob", "nwzg", "nwzd", "nenf",
          "nkol", "nkot", "nbrg", "nrog", "nwzr", "nbld"],
}
STYLE_LETTERS = "LWFABCNY"


def main():
    a = mpyq.MPQArchive(os.path.normpath(
        os.path.join(HERE, "..", "..", "..", "War3x.mpq")))
    rows = parse_slk_ordered(a.read_file(r"TerrainArt\Terrain.slk")
                             .decode("utf-8", "replace"))
    crows = parse_slk_ordered(a.read_file(r"TerrainArt\CliffTypes.slk")
                              .decode("utf-8", "replace"))
    cliffs = {}    # letter -> [cliffID...]（CliffTypes.slk 行序 = w3e 悬崖索引序）
    for uid, row in crows:
        gt = row.get("groundTile", "")
        if re.match(r"^[A-Za-z]", gt):
            cliffs.setdefault(gt[0], []).append(uid)
    tex = {}       # letter -> [tileID...]（Terrain.slk 行序 = w3e 索引序）
    conv = {}      # tileID -> {letter: tileID}
    for uid, row in rows:
        ts = uid[0]
        tex.setdefault(ts, []).append(uid)
        if row.get("convertTo") and row["convertTo"] != "-":
            m = {}
            for t in row["convertTo"].split(","):
                t = t.strip()
                if re.match(r"^[A-Za-z]", t):
                    m[t[0]] = t
            conv[uid] = m
    # 校验：8 种风格的每个纹理都能映射到其他 7 种（语义对，靠 convertTo）
    missing = []
    for ts in STYLE_LETTERS:
        for t in tex.get(ts, []):
            for dst in STYLE_LETTERS:
                if dst == ts:
                    continue
                if len(t) > 1 and t not in conv:
                    missing.append((t, dst))
                elif len(t) == 1:
                    pass
                elif dst not in conv[t]:
                    missing.append((t, dst))
    if missing:
        print(f"⚠ convertTo 缺失映射 {len(missing)} 条（将按 comment 语义兜底）:")
        for t, d in missing[:12]:
            print("   ", t, "→", d)

    # convertTo 缺失的 4 条，按 comment 语义手工兜底（灰谷没有直接的对应项）
    EXTRA = {("Ldrg", "A"): "Adrg", ("Wsng", "A"): "Adrg",
             ("Fdrg", "A"): "Adrg", ("CAc2", "A"): "Adrt"}
    for (t, dst), v in EXTRA.items():
        conv.setdefault(t, {})[dst] = v
    out = os.path.join(HERE, "..", "tilesets.py")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write('"""地图风格（tileset）表 —— 全项目唯一数据源。\n\n')
        f.write("纹理表 = 游戏 TerrainArt/Terrain.slk 按行序（行序 = w3e 纹理索引序，\n")
        f.write("Ldrt/Ldro/Ldrg/Lrok/Lgrs/Lgrd = 0~5 已实证）；跨风格映射用 convertTo 列。\n")
        f.write("树/雇佣兵/野怪池 = 45 张官方 1.27a 对战图实测\n")
        f.write("（tools/_tmp/tileset_map_stats.py，见 style_map_stats.txt）。\n\n")
        f.write("⚠ 一张图只能一种风格（w3e 头一个 tileset 字母）；多选 = 生成时随机抽一。\n")
        f.write('由 tools/_tmp/gen_tilesets.py 生成。"""\n\n')
        f.write("STYLES = {\n")
        for ts in STYLE_LETTERS:
            f.write(f'    "{ts}": {{\n')
            f.write(f'        "name": "{NAMES[ts]}",\n')
            f.write(f'        "tree": "{TREES[ts]}",\n')
            f.write(f'        "merc": "{MERC[ts]}",\n')
            f.write(f'        "textures": {tex.get(ts, [])!r},\n')
            f.write(f'        "cliffs": {cliffs.get(ts, [])!r},\n')
            f.write(f'        "pool": {sorted(set(POOLS[ts]))!r},\n')
            f.write("    },\n")
        f.write("}\n\n")
        f.write("# tileID → {目标风格字母: tileID}（Terrain.slk convertTo 列，语义等价纹理）\n")
        f.write("CONVERT = {\n")
        for t in sorted(conv):
            f.write(f'    "{t}": {conv[t]!r},\n')
        f.write("}\n")
    print(f"导出 {len(STYLE_LETTERS)} 种风格 → {os.path.normpath(out)}")
    for ts in STYLE_LETTERS:
        print(f"  {ts} {NAMES[ts]:<8} 纹理{len(tex.get(ts, []))}  "
              f"树 {TREES[ts]:<5} 雇佣兵 {MERC[ts]:<5} 野怪池 {len(set(POOLS[ts]))} 种")


if __name__ == "__main__":
    main()
