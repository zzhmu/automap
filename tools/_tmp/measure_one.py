# -*- coding: utf-8 -*-
"""对单张地图跑 analyze_height 的指标（用来校准「应用高度」参数）。

用法: python measure_one.py <map.w3x> [<map2> ...]
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import analyze_height as A   # noqa: E402

KEYS = ("resid_std", "low_std", "high_std", "high_p99", "adj_p50", "adj_p99")


def main():
    for i, p in enumerate(sys.argv[1:]):
        tmp = os.path.join(HERE, "one_r%d_%d" % (os.getpid(), i))
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        r = A.analyze(os.path.abspath(p), tmp, os.path.basename(p))
        if r is None:
            print(f"{os.path.basename(p)}: 读不到 / 没有够大的台地")
            continue
        print(f"{r['name'][:30]:<30} {r['size']:>9}  台地 {r['plats']:>3} 块")
        print("    " + "  ".join(f"{k}={r[k]:.2f}" for k in KEYS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
