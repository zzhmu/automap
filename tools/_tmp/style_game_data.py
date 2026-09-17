# -*- coding: utf-8 -*-
"""从游戏 MPQ 提取「地图风格(tileset)」的数据口径：
  1. TerrainArt/Terrain.slk  → 每个 tileset 的地面纹理表（w3e 里纹理索引 0..8 对应谁）
  2. Units/UnitData.slk      → 每个野怪 id 的 tilesets 字段（官方标注这只怪用在哪些风格）
  3. Doodads/Doodads.slk     → 每个风格的树模型（name 带 Tree 的装饰物）
合并优先级：war3.mpq < War3x.mpq < War3Patch.mpq。
"""
import os
import re
import sys

import mpyq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, ".."))


def parse_slk(text):
    """通用 SLK 解析（稀疏格式，X/Y 省略沿用上一格）→ {首列值: {列名: 值}}。"""
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
    name_by_x = rows.get(1, {})
    first_col = min(name_by_x) if name_by_x else None
    out = {}
    for y, cells in rows.items():
        if y == 1:
            continue
        uid = cells.get(first_col)
        if uid and re.match(r"^[A-Za-z0-9_]{1,4}$", uid):
            out[uid] = {name_by_x.get(x, f"col{x}"): v for x, v in cells.items()}
    return out


def load(mpyqs, inner):
    merged = {}
    for mpq in mpyqs:
        try:
            a = mpyq.MPQArchive(os.path.join(ROOT, mpq))
            data = a.read_file(inner)
        except Exception as e:  # noqa: BLE001
            print(f"  ({mpq}: {e})")
            continue
        if data is None:
            continue
        merged.update(parse_slk(data.decode("utf-8", "replace")))
    return merged


def main():
    MPQS = ("war3.mpq", "War3x.mpq", "War3Patch.mpq")

    print("===== 1. Terrain.slk：tileset → 地面纹理 =====")
    terr = load(MPQS, r"TerrainArt\Terrain.slk")
    if terr:
        some = next(iter(terr.values()))
        print("列名:", sorted(some.keys()))
        for ts, row in sorted(terr.items()):
            tex = {k: v for k, v in row.items() if re.match(r"tex\d", k)}
            print(f"  {ts}: {tex}")

    print("\n===== 2. UnitData.slk：野怪 id → tilesets 标注 =====")
    ud = load(MPQS, r"Units\UnitData.slk")
    from camp_templates import CAMP_TEMPLATES
    need = {k for c, _w in CAMP_TEMPLATES for k in c}
    per_ts = {}
    for uid, row in sorted(ud.items()):
        tss = row.get("tilesets", "")
        if uid in need or uid.startswith("nmr"):
            for ch in tss:
                per_ts.setdefault(ch, []).append(uid)
    for ch in sorted(per_ts):
        print(f"  {ch}: {sorted(per_ts[ch])}")
    print("  （模板野怪无 tilesets 标注的）:",
          sorted(k for k in need
                 if not any(k in v for v in (r.get("tilesets", "") for r in ud.values()
                                             if k == next(iter([k]))))) if False else
          sorted(k for k in need if k not in {u for v in per_ts.values() for u in v}))

    print("\n===== 3. Doodads.slk：每风格的树模型 =====")
    dd = load(MPQS, r"Doodads\Doodads.slk")
    trees = {}
    for did, row in dd.items():
        nm = row.get("name", "")
        if "Tree" not in nm and "tree" not in nm:
            continue
        tss = row.get("tilesets", "")
        for ch in tss:
            trees.setdefault(ch, []).append((did, nm))
    for ch in sorted(trees):
        print(f"  {ch}: {trees[ch]}")


if __name__ == "__main__":
    main()
