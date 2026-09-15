# -*- coding: utf-8 -*-
"""一次性可行性验证：能不能从零手写一个 war3mapUnits.doo。

验证三点:
  1. 「空文件」= 16 字节头(count=0) + 8 字节尾部，能否被解析器正确接受
  2. 用模板里已实测过的 sloc 记录 91 字节原样搬过来改 owner/坐标，能否被正确读出
  3. 两种情况塞回 MPQ 后地图仍能被 MPQEditor 正常读
"""
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
EXE = os.path.join(ROOT, "bin", "MPQEditor.exe")
SRC = os.path.join(HERE, "war3mapUnits.doo")


def build(count_header, records, tail):
    return struct.pack("<4sIII", b"W3do", 7, 9, count_header) + b"".join(records) + tail


def main():
    data = open(SRC, "rb").read()
    _, _, _, count = struct.unpack_from("<4sIII", data, 0)
    tail = data[-8:]
    print(f"源文件: count={count} 尾部={tail.hex()}")

    # sloc 记录 = 文件里第 0 条，91 字节（已手工核对过每一段）
    sloc = data[16:16 + 91]
    assert sloc[:4] == b"sloc" and len(sloc) == 91
    print(f"取到 sloc 模板记录 {len(sloc)} 字节")

    def patch(rec, owner, x, y, z):
        r = bytearray(rec)
        struct.pack_into("<i", r, 37, owner)      # p+37 owner
        struct.pack_into("<fff", r, 8, x, y, z)   # p+8 x,y,z
        return bytes(r)

    for name, blob, expect in (
        ("empty", build(0, [], tail), 0),
        ("one", build(1, [patch(sloc, 3, -1024.0, -3072.0, 128.0)], tail), 1),
        ("four", build(4, [patch(sloc, i, -3072.0 + i * 2048, 1024.0, 200.0)
                           for i in range(4)], tail), 4),
    ):
        out = os.path.join(HERE, f"units_{name}.doo")
        open(out, "wb").write(blob)
        print(f"写出 {out}: {len(blob)} 字节, 声明 count={expect}")
        # 塞回地图
        mpq = os.path.join(HERE, f"map_{name}.w3x")
        shutil.copy2(os.path.join(HERE, "utest.w3x"), mpq)
        subprocess.run([EXE, "add", mpq, out, "war3mapUnits.doo"],
                       capture_output=True, timeout=120)
        r = subprocess.run([sys.executable,
                            os.path.join(ROOT, "tools", "inspect_units.py"), mpq],
                           capture_output=True, text=True, timeout=180)
        head = "\n".join(r.stdout.splitlines()[1:8])
        print("  → 回读结果:")
        for line in head.splitlines():
            print("     " + line)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
