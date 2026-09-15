# -*- coding: utf-8 -*-
"""盘点地图 MPQ 里的文件清单（对模板和生成图做对比用）。

用法: python inspect_mpq.py <map.w3x|w3m> [--exe 路径] [--dir 输出目录]
原理：MPQEditor 的 list 在本机不输出到 stdout，改为用 extract + 通配符提取全部文件，
再列出目录内容与大小。
"""
import os
import shutil
import subprocess
import sys


def default_exe():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def main():
    args, opts, i = [], {}, 0
    argv = sys.argv[1:]
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k, sep, v = a[2:].partition("=")
            if sep:
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]; i += 1
            else:
                opts[k] = True
        else:
            args.append(a)
        i += 1
    if not args:
        print(__doc__)
        return 1
    map_path = args[0]
    exe = opts.get("exe") or default_exe()
    safe = os.path.splitext(os.path.basename(map_path))[0].replace("(", "").replace(")", "")
    out = opts.get("dir") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "_tmp", "mpq_" + safe)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    subprocess.run([exe, "extract", map_path, "*", out, "/fp"],
                   capture_output=True, timeout=300)

    files = []
    for root, _, names in os.walk(out):
        for n in names:
            p = os.path.join(root, n)
            files.append((os.path.relpath(p, out).replace("\\", "/"),
                          os.path.getsize(p)))
    files.sort()
    print(f"===== {os.path.basename(map_path)}：共 {len(files)} 个文件 =====")
    for name, size in files:
        print(f"  {size:>9}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
