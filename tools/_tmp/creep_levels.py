# -*- coding: utf-8 -*-
"""从游戏 MPQ 的 Units/UnitBalance.slk 抽野怪等级表（level 字段），
只保留 camp_templates.py 里用到的 id，导出 tools/creep_levels.py。

优先级：war3.mpq < War3x.mpq < War3Patch.mpq（后覆盖前）。
用 mpyq 直接读（MPQEditor 对被游戏锁住的 MPQ 静默失败，不用它）；
游戏开着时 MPQ 只锁写、读没问题，若仍打不开就先复制一份。
"""
import os
import re
import shutil
import sys

import mpyq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))   # 游戏根（war3.mpq 所在）
sys.path.insert(0, os.path.join(HERE, ".."))
from camp_templates import CAMP_TEMPLATES  # noqa: E402

TMP = os.path.join(HERE, "lvlslk")
os.makedirs(TMP, exist_ok=True)


def parse_slk(text):
    """最简 SLK 解析（稀疏格式：X/Y 省略时沿用上一个值）。
    返回 {第一列 unitID: {列名: 值}}。"""
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
    first_col = next((x for x, n in name_by_x.items()
                      if n in ("unit", "unitID", "unitBalanceID")), None)
    out = {}
    for y, cells in rows.items():
        if y == 1:
            continue
        uid = cells.get(first_col)
        if uid and re.match(r"^[A-Za-z0-9_]{4}$", uid):
            out[uid] = {name_by_x.get(x, f"col{x}"): v for x, v in cells.items()}
    return out


def load_unitdata(mpq_name):
    """读一个游戏 MPQ 的 Units/UnitData.slk → {id: {列: 值}}，打不开就复制一份再读。"""
    src = os.path.join(ROOT, mpq_name)
    a = None
    try:
        a = mpyq.MPQArchive(src)
        data = a.read_file(r"Units\UnitBalance.slk")
    except Exception as e:  # noqa: BLE001
        data = None
        print(f"{mpq_name}: 直读失败（{e}），复制一份再读")
    finally:
        try:
            if a is not None:
                a.close()
        except Exception:  # noqa: BLE001
            pass
    if data is None:
        cpy = os.path.join(TMP, "copy_" + mpq_name)
        if not os.path.exists(cpy):
            shutil.copy2(src, cpy)
        a = mpyq.MPQArchive(cpy)
        data = a.read_file(r"Units\UnitBalance.slk")
        try:
            a.close()
        except Exception:  # noqa: BLE001
            pass
    if data is None:
        return {}
    return parse_slk(data.decode("utf-8", "replace"))


def main():
    merged = {}
    for mpq in ("war3.mpq", "War3x.mpq", "War3Patch.mpq"):
        try:
            tab = load_unitdata(mpq)
        except Exception as e:  # noqa: BLE001
            print(f"{mpq}: 读取失败 {e}")
            continue
        n = 0
        for uid, cells in tab.items():
            if "level" in cells and re.match(r"^\d+$", cells["level"]):
                merged[uid] = int(cells["level"])
                n += 1
        print(f"{mpq}: 解析 {len(tab)} 行，带 lvl 的 {n} 条（累计 {len(merged)}）")

    need = sorted({k for c, _w in CAMP_TEMPLATES for k in c})
    lv = {}
    miss = []
    for uid in need:
        if uid in merged:
            lv[uid] = merged[uid]
        else:
            miss.append(uid)
    # 大文件副本用完即删（自产物）
    for f in os.listdir(TMP):
        if f.startswith("copy_"):
            os.remove(os.path.join(TMP, f))
    print(f"\n模板用到 {len(need)} 种 id，取到等级 {len(lv)} 种，缺失 {len(miss)}：{miss}")
    from collections import Counter
    print("等级分布:", dict(sorted(Counter(lv.values()).items())))
    out = os.path.join(HERE, "..", "creep_levels.py")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write('"""野怪 id → 等级（游戏 Units/UnitBalance.slk 的 level 字段实测），\n')
        f.write("由 tools/_tmp/creep_levels.py 从 war3.mpq / War3x.mpq / War3Patch.mpq 导出。\n")
        f.write('只收录 camp_templates.py 里用到的 id。"""\n\n')
        f.write("CREEP_LVL = {\n")
        for uid in sorted(lv):
            f.write(f'    "{uid}": {lv[uid]},\n')
        f.write("}\n")
    print(f"导出 → {os.path.normpath(out)}")
    for uid in sorted(lv, key=lambda k: -lv[k]):
        print(f"   lv{lv[uid]:>2}  {uid}")


if __name__ == "__main__":
    main()
