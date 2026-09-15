# -*- coding: utf-8 -*-
"""扫描「应用高度」参数组合，用 analyze_height 的指标挑最像官方对战图的一组。

只跑 gen_height（不撒树），所以一轮几秒。
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import analyze_height as A   # noqa: E402

PY = sys.executable
TPL = os.path.join(ROOT, "template", "128-128.w3m")
WORK = os.path.join(HERE, "sweep")
os.makedirs(WORK, exist_ok=True)

# 官方典型值（tools/_tmp/analyze_height.py 全量扫描 157 张对战图得到）
TARGET = {"low": 69.74, "high": 31.85, "adj50": 5.5, "adj99": 89.0, "resid": 86.58}

# (grain, octaves, gain, rough)
CONFIGS = [
    (4, 3, 0.6, 55),
    (5, 3, 0.6, 55),
    (6, 3, 0.6, 55),
    (7, 3, 0.6, 55),
    (8, 3, 0.6, 55),
    (6, 2, 0.7, 55),
    (8, 2, 0.7, 55),
    (10, 2, 0.7, 55),
    (6, 3, 0.45, 60),
    (8, 3, 0.45, 60),
]


def run(cfg, seed=777):
    grain, oct_, gain, rough = cfg
    out = os.path.join(WORK, "s_%g_%d_%g.w3x" % (grain, oct_, gain))
    shutil.copy2(TPL, out)
    cmd = [PY, os.path.join(TOOLS, "gen_height.py"), out, "--seed", str(seed),
           "--ramps", "0", "--rough", str(rough), "--grain", str(grain),
           "--rough-octaves", str(oct_), "--rough-gain", str(gain)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if r.returncode:
        print("  gen 失败:", (r.stdout or "")[-300:], (r.stderr or "")[-300:])
        return None
    tmp = os.path.join(HERE, "sw_%d" % os.getpid())
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    return A.analyze(out, tmp, "s")


def main():
    if not os.path.exists(TPL):
        print("缺模板", TPL)
        return 1
    print(f"{'grain':>6} {'oct':>4} {'gain':>5} {'rough':>6} | "
          f"{'resid':>7} {'low':>7} {'high':>7} {'adj50':>7} {'adj99':>7}")
    print(f"{'-'*6} {'-'*4} {'-'*5} {'-'*6} | "
          f"{TARGET['resid']:>7.2f} {TARGET['low']:>7.2f} {TARGET['high']:>7.2f} "
          f"{TARGET['adj50']:>7.2f} {TARGET['adj99']:>7.2f}   ← 官方典型")
    best = None
    for cfg in CONFIGS:
        r = run(cfg)
        if r is None:
            continue
        score = (abs(r["low_std"] - TARGET["low"]) / TARGET["low"]
                 + abs(r["high_std"] - TARGET["high"]) / TARGET["high"]
                 + abs(r["adj_p50"] - TARGET["adj50"]) / TARGET["adj50"] * 1.5
                 + abs(r["adj_p99"] - TARGET["adj99"]) / TARGET["adj99"])
        print(f"{cfg[0]:>6} {cfg[1]:>4} {cfg[2]:>5} {cfg[3]:>6} | "
              f"{r['resid_std']:>7.2f} {r['low_std']:>7.2f} {r['high_std']:>7.2f} "
              f"{r['adj_p50']:>7.2f} {r['adj_p99']:>7.2f}   偏差={score:.3f}")
        if best is None or score < best[0]:
            best = (score, cfg, r)
    if best:
        print(f"\n最佳: grain={best[1][0]} octaves={best[1][1]} gain={best[1][2]} "
              f"rough={best[1][3]}  偏差={best[0]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
