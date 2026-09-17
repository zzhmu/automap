# -*- coding: utf-8 -*-
"""官方图按 tileset（地图风格字母，w3e 头第 5 字节）分组统计：
  - 每种风格的野怪窝构成（id 池 + 常见组合）
  - 雇佣兵营地变体 nmr0-9 各用在哪种风格
  - 树模型 id
输出到 style_map_stats.txt。
"""
import os
import struct
import subprocess
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import w3units  # noqa: E402
from add_doodads import parse_doo  # noqa: E402
from creep_stats import LINK, clusters  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
EXE = os.path.normpath(os.path.join(ROOT, "automap", "bin", "MPQEditor.exe"))
MAPS = os.path.join(ROOT, "Maps")
TMP = os.path.join(HERE, "tsstat")
os.makedirs(TMP, exist_ok=True)


def tileset_of(map_path):
    """抽 war3map.w3e 的头，返回 (tileset 字母, W, H)。"""
    for fn in ("war3map.w3e",):
        dst = os.path.join(TMP, "war3map.w3e")
        if os.path.exists(dst):
            os.remove(dst)
        subprocess.run([EXE, "extract", map_path, fn, TMP, "/fp"],
                       capture_output=True, timeout=180)
        if not os.path.exists(dst):
            return None, None, None
        head = open(dst, "rb").read(8)
        _ver, _ws, _hs, tileset = head[0:4], struct.unpack_from("<I", head, 4)[0], \
            struct.unpack_from("<I", head, 8)[0], chr(head[8])
        # 头结构: "W3E!" ver(4) tileset(1) ...
        return tileset, 0, 0


def main():
    stats = defaultdict(lambda: dict(maps=[], camps=Counter(), combos=Counter(),
                                     trees=Counter(), nmr=Counter(), bld=Counter()))
    for nm in sorted(f for f in os.listdir(MAPS) if f.endswith((".w3m", ".w3x"))):
        p = os.path.join(MAPS, nm)
        for fn in ("war3map.w3e", "war3mapUnits.doo", "war3map.doo"):
            dst = os.path.join(TMP, fn)
            if os.path.exists(dst):
                os.remove(dst)
            subprocess.run([EXE, "extract", p, fn, TMP, "/fp"],
                           capture_output=True, timeout=180)
        w3e = os.path.join(TMP, "war3map.w3e")
        if not os.path.exists(w3e):
            continue
        head = open(w3e, "rb").read(16)
        ts = chr(head[8])
        st = stats[ts]
        st["maps"].append(nm)

        doo_u = os.path.join(TMP, "war3mapUnits.doo")
        if os.path.exists(doo_u):
            _v, _s, units, _e = w3units.parse(open(doo_u, "rb").read())
            cre = [u for u in units if u.owner == 12]
            if cre:
                xs = np.array([u.x for u in cre])
                ys = np.array([u.y for u in cre])
                for grp in clusters(xs, ys):
                    comp = tuple(sorted(Counter(cre[i].id for i in grp).items()))
                    st["combos"][comp] += 1
                    for i in grp:
                        st["camps"][cre[i].id] += 1
            for u in units:
                if u.owner == 15 and u.id.startswith("nmr"):
                    st["nmr"][u.id] += 1
                elif u.owner == 15:
                    st["bld"][u.id] += 1

        doo_d = os.path.join(TMP, "war3map.doo")
        if os.path.exists(doo_d):
            _v, _s, recs, _t = parse_doo(open(doo_d, "rb").read())
            ids = Counter(r[0:4].decode("ascii", "replace") for r in recs
                          if len(r) >= 8)
            for k, v in ids.items():
                st["trees"][k] += v

    out = []
    for ts in sorted(stats):
        st = stats[ts]
        out.append(f"\n===== tileset {ts}（{len(st['maps'])} 张图："
                   f"{[m for m in st['maps']][:8]}{'...' if len(st['maps']) > 8 else ''}）")
        out.append(f"  野怪 id 池（出现次数 top40）: "
                   f"{dict(st['camps'].most_common(40))}")
        out.append(f"  树模型: {dict(st['trees'].most_common(8))}")
        out.append(f"  雇佣兵营地变体: {dict(st['nmr'].most_common())}")
        out.append(f"  其他中立建筑: {dict(st['bld'].most_common(10))}")
        out.append(f"  常见窝组合 top10:")
        for comp, w in st["combos"].most_common(10):
            out.append(f"    ×{w:<3} {dict(comp)}")
    txt = "\n".join(out)
    open(os.path.join(HERE, "style_map_stats.txt"), "w", encoding="utf-8").write(txt)
    print(txt[:6000])
    print(f"\n完整输出 → {os.path.join(HERE, 'style_map_stats.txt')}")


if __name__ == "__main__":
    main()
