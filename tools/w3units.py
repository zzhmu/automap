# -*- coding: utf-8 -*-
"""war3mapUnits.doo（单位 / 中立建筑 / 出生点）的顺序读写 —— 解析到文件尾零误差。

格式（v7.9，实测自 1.27a 全部原生对战图 + 自造空模板，全部「顺序解析到文件尾零误差」）:

    文件头 16 字节: "W3do" + u32 version + u32 subversion + u32 n_units

    每条记录（v7）:
      p+0   id(4)          p+36 flags(u8)   0x1=可通行? 0x2=常用值
      p+4   variation(i32) p+37 owner(i32)  0..11=玩家槽 12=中立敌对 15=中立被动
      p+8   x,y,z(f32×3)   p+41 未知(u16)
      p+20  angle(f32)     p+43 hp(i32)     -1 = 用默认值
      p+24  scaleXYZ(3×f32) p+47 mana(i32)
      p+51  n_sets(i32) → 每个集合: n_items(i32) + n_items×(itemId4, chance i32)
      掉落之后:
        gold(i32)  targetAcquisition(f32)  heroLevel(i32)
        n_inv(i32) + n_inv×(slot i32, itemId4)
        n_ab(i32)  + n_ab×(abilityId4, autocast i32, level i32)
        randomFlag(i32) —— 后面跟着的「随机单位/物品」条件数据，长度随取值变:
            -1 → 0 个 i32（出生点 sloc 属于这种）
             0 → 1 个 i32（值 0/1，绝大多数普通单位属于这种）
             1 → 2 个 i32（如 TranquilPaths 的 uDNR）
             2 → 单个物品集: n_items(i32) + n_items×(itemId4, chance i32)
        尾部固定三字段: customColor(i32)  waygate(i32)  creationNumber(i32)

    v8.11（1.31+ 编辑器 / TFT 官方图）的差别 —— **flags 仍然是 1 字节**（实测
    (2)Circumvention.w3x 第一条 ngol：52=0x02 flags，53..56=15 owner），前缀同样 51 字节；
    只有 subversion>=11 才多两个字段：mana 之后 itemTablePointer(i32=-1)、
    heroLevel 之后 英雄三围 str/agi/int(3×i32)。模板用 v7，解 v8 是为了读 TFT 图做统计。

用法见文件末尾 self-test:  python w3units.py <map.w3x|units.doo>
"""
import struct

MAGIC = b"W3do"

P_ID, P_VAR, P_XYZ, P_ANG, P_SCALE, P_FLAGS, P_OWNER = 0, 4, 8, 20, 24, 36, 37
P_UNK, P_HP, P_MANA, P_SETS, FIXED = 41, 43, 47, 51, 51      # 前缀固定 51 字节


class Unit:
    """一条单位记录。未列出的字段统一存放在 raw_tail，保证重写时原样保留。"""

    __slots__ = ("id", "variation", "x", "y", "z", "angle", "scale", "flags",
                 "owner", "unk", "hp", "mana", "sets", "gold", "tacq", "hero_level",
                 "inv", "ab", "random_flag", "random_extra", "random_items",
                 "custom_color", "waygate", "creation", "size", "raw",
                 "item_table", "hero_stats")

    #: 新建记录的默认值 —— 与官方图里中立建筑的字段众数一致
    #: （实测 43 张 1.27a + 113 张 TFT 官方图：flags=2 owner=15 hp=-1 mana=-1
    #:   tacq=-1.0 heroLevel=1 customColor=-1 waygate=-1 scale=1）
    DEFAULTS = {
        "variation": 0, "scale": (1.0, 1.0, 1.0), "flags": 2, "unk": 0,
        "hp": -1, "mana": -1, "sets": [], "gold": 0, "tacq": -1.0,
        "hero_level": 1, "inv": [], "ab": [], "random_flag": 0,
        "random_extra": [1], "random_items": [], "custom_color": -1,
        "waygate": -1, "creation": 0, "item_table": -1, "hero_stats": None,
        "size": None, "raw": None, "owner": 15,
    }

    def __init__(self, **kw):
        for k in self.__slots__:
            if k not in kw:
                kw[k] = self.DEFAULTS.get(k)
        for k, v in kw.items():
            setattr(self, k, v)

    def is_building(self):
        return bool(self.id) and self.id[0] in "no"

    def __repr__(self):
        return (f"<Unit {self.id} owner={self.owner} "
                f"({self.x:.0f},{self.y:.0f},{self.z:.1f}) gold={self.gold} "
                f"size={self.size}>")


def _read_sets(data, p):
    """读一份掉落表。返回 (sets, 新位置)。数量异常时按 0 处理，避免解析崩掉。"""
    n_sets, = struct.unpack_from("<i", data, p)
    p += 4
    sets = []
    if not (0 <= n_sets < 16):
        n_sets = 0
    for _ in range(n_sets):
        n_it, = struct.unpack_from("<i", data, p)
        p += 4
        if not (0 <= n_it < 16) or p + 8 * n_it > len(data):
            p -= 4
            break
        its = []
        for _ in range(n_it):
            its.append((data[p:p + 4].decode("ascii", "replace"),
                        struct.unpack_from("<i", data, p + 4)[0]))
            p += 8
        sets.append(its)
    return sets, p


def _size_sets(sets):
    return 4 + sum(4 + 8 * len(s) for s in sets)


def parse(data):
    """顺序解析整个文件。返回 (version, subversion, [Unit...], 结束偏移)。

    结束偏移必须 == len(data)，否则说明格式假设不对（self-test 会报出来）。
    """
    if data[:4] != MAGIC:
        raise ValueError("不是 W3do 文件")
    ver, sub, cnt = struct.unpack_from("<III", data, 4)
    v8 = ver >= 8
    is11 = v8 and sub >= 11
    p = 16
    out = []
    for _ in range(cnt):
        st = p
        u = Unit()
        u.id = data[p:p + 4].decode("ascii", "replace")
        u.variation, = struct.unpack_from("<i", data, p + P_VAR)
        u.x, u.y, u.z = struct.unpack_from("<3f", data, p + P_XYZ)
        u.angle, = struct.unpack_from("<f", data, p + P_ANG)
        u.scale = struct.unpack_from("<3f", data, p + P_SCALE)
        u.flags = data[p + P_FLAGS]
        u.owner, = struct.unpack_from("<i", data, p + P_OWNER)
        u.unk, = struct.unpack_from("<H", data, p + P_UNK)
        u.hp, = struct.unpack_from("<i", data, p + P_HP)
        u.mana, = struct.unpack_from("<i", data, p + P_MANA)
        p += FIXED
        if is11:
            u.item_table, = struct.unpack_from("<i", data, p); p += 4
        u.sets, p = _read_sets(data, p)
        u.gold, = struct.unpack_from("<i", data, p); p += 4
        u.tacq, = struct.unpack_from("<f", data, p); p += 4
        u.hero_level, = struct.unpack_from("<i", data, p); p += 4
        if is11:
            u.hero_stats = struct.unpack_from("<3i", data, p); p += 12
        n_inv, = struct.unpack_from("<i", data, p); p += 4
        u.inv = []
        for _ in range(n_inv if 0 <= n_inv < 64 and p + 8 * n_inv <= len(data) else 0):
            slot, = struct.unpack_from("<i", data, p)
            u.inv.append((slot, data[p + 4:p + 8].decode("ascii", "replace")))
            p += 8
        n_ab, = struct.unpack_from("<i", data, p); p += 4
        u.ab = []
        for _ in range(n_ab if 0 <= n_ab < 64 and p + 12 * n_ab <= len(data) else 0):
            aid = data[p:p + 4].decode("ascii", "replace")
            auto, lvl = struct.unpack_from("<ii", data, p + 4)
            u.ab.append((aid, auto, lvl))
            p += 12
        u.random_flag, = struct.unpack_from("<i", data, p); p += 4
        u.random_extra = []
        if u.random_flag in (0, 1):
            for _ in range(1 if u.random_flag == 0 else 2):
                u.random_extra.append(struct.unpack_from("<i", data, p)[0]); p += 4
        elif u.random_flag == 2:
            n_it, = struct.unpack_from("<i", data, p); p += 4
            u.random_items = []
            for _ in range(n_it if 0 < n_it < 64 else 0):
                u.random_items.append((data[p:p + 4].decode("ascii", "replace"),
                                       struct.unpack_from("<i", data, p + 4)[0]))
                p += 8
        u.custom_color, = struct.unpack_from("<i", data, p); p += 4
        u.waygate, = struct.unpack_from("<i", data, p); p += 4
        u.creation, = struct.unpack_from("<i", data, p); p += 4
        u.size = p - st
        u.raw = data[st:p]
        out.append(u)
    return ver, sub, out, p


def dump(u, use_raw=True, ver=7, sub=9):
    """把一条记录序列化回字节。

    use_raw=True（默认）：解析出来的记录原样吐回原始字节 —— 重写文件时，凡是没被
    我们改过的记录都能保证逐字节不变。改动字段后请自行 `u.raw = None`。
    """
    if use_raw and u.raw is not None:
        return u.raw
    is11 = ver >= 8 and sub >= 11
    b = bytearray()
    b += u.id.encode("ascii", "replace")[:4].ljust(4, b"\x00")
    b += struct.pack("<i", u.variation)
    b += struct.pack("<3f", u.x, u.y, u.z)
    b += struct.pack("<f", u.angle)
    b += struct.pack("<3f", *u.scale)
    b += bytes([u.flags & 0xFF])
    b += struct.pack("<i", u.owner)
    b += struct.pack("<H", u.unk & 0xFFFF)
    b += struct.pack("<ii", u.hp, u.mana)
    if is11:
        b += struct.pack("<i", u.item_table)
    b += struct.pack("<i", len(u.sets))
    for s in u.sets:
        b += struct.pack("<i", len(s))
        for iid, chance in s:
            b += iid.encode("ascii", "replace")[:4].ljust(4, b"\x00")
            b += struct.pack("<i", chance)
    b += struct.pack("<i", u.gold)
    b += struct.pack("<f", u.tacq)
    b += struct.pack("<i", u.hero_level)
    if is11:
        b += struct.pack("<3i", *(u.hero_stats or (0, 0, 0)))
    b += struct.pack("<i", len(u.inv))
    for slot, iid in u.inv:
        b += struct.pack("<i", slot)
        b += iid.encode("ascii", "replace")[:4].ljust(4, b"\x00")
    b += struct.pack("<i", len(u.ab))
    for aid, auto, lvl in u.ab:
        b += aid.encode("ascii", "replace")[:4].ljust(4, b"\x00")
        b += struct.pack("<ii", auto, lvl)
    b += struct.pack("<i", u.random_flag)
    if u.random_flag in (0, 1):
        for v in (u.random_extra or []):
            b += struct.pack("<i", v)
    elif u.random_flag == 2:
        b += struct.pack("<i", len(u.random_items))
        for iid, chance in u.random_items:
            b += iid.encode("ascii", "replace")[:4].ljust(4, b"\x00")
            b += struct.pack("<i", chance)
    b += struct.pack("<iii", u.custom_color, u.waygate, u.creation)
    return bytes(b)


def build(units, ver=7, sub=9, use_raw=True):
    out = bytearray()
    out += MAGIC
    out += struct.pack("<III", ver, sub, len(units))
    for u in units:
        out += dump(u, use_raw=use_raw, ver=ver, sub=sub)
    return bytes(out)


# --------------------------------------------------------------------------
# self-test: 对给定地图/文件解析并回写，检查「回写字节 == 原字节」且「解析到文件尾」
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import subprocess
    import sys

    HERE = os.path.dirname(os.path.abspath(__file__))
    EXE = os.path.normpath(os.path.join(HERE, "..", "bin", "MPQEditor.exe"))
    TMP = os.path.join(HERE, "_tmp", "w3units")
    os.makedirs(TMP, exist_ok=True)

    bad = 0
    for path in sys.argv[1:]:
        if path.lower().endswith(".doo"):
            data = open(path, "rb").read()
        else:
            dst = os.path.join(TMP, "war3mapUnits.doo")
            if os.path.exists(dst):
                os.remove(dst)
            subprocess.run([EXE, "extract", path, "war3mapUnits.doo", TMP, "/fp"],
                           capture_output=True, timeout=180)
            if not os.path.exists(dst):
                print(f"{os.path.basename(path)}: 无 units.doo")
                continue
            data = open(dst, "rb").read()
        name = os.path.basename(path)
        try:
            ver, sub, units, end = parse(data)
        except Exception as e:
            print(f"✘ {name}: {e}")
            bad += 1
            continue
        ok_end = (end == len(data))
        ok_round = (build(units, ver, sub, use_raw=False) == data)
        ok_raw = (build(units, ver, sub, use_raw=True) == data)
        if ok_end and ok_round:
            print(f"✔ {name}: v{ver}.{sub} {len(units)} 条  解析到尾 & 语义回写逐字节一致")
        elif ok_end:
            print(f"△ {name}: v{ver}.{sub} {len(units)} 条  解析到尾 ✔  原始字节回写 ✔ "
                  f" 语义回写 ✘（有字段值被规范化，见下）")
            a, b = build(units, ver, sub, use_raw=False), data
            d = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
            print(f"    首处差异 @ {d}: 原 {b[d:d + 12].hex(' ')} → 新 {a[d:d + 12].hex(' ')}")
        else:
            bad += 1
            print(f"✘ {name}: v{ver}.{sub} {len(units)} 条  解析结束 {end}/{len(data)} ✘  "
                  f"原始字节回写 {'✔' if ok_raw else '✘'}  语义回写 {'✔' if ok_round else '✘'}")
    print(f"\n{'全部通过' if bad == 0 else f'{bad} 个文件未通过'}")
