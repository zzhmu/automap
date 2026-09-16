# -*- coding: utf-8 -*-
"""宽种子回归扫描：3 种基底 × 40 个种子，直接跑 gen_height（不经 GUI），
统计「非法斜坡瓦片 / 被崖壁切断 / 撤台地 / 兜底开坡」四类信号的出现次数。

GUI 全链路已在 tools/_tmp/gui_stress.py 里验过（24/24 硬通过）；这里只是把种子面
铺开，确认这次斜坡重叠修复不是只修好了那几个种子。

用法: python tools/_tmp/ramp_sweep.py [每组合种子数]
"""
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
TMP = os.path.join(ROOT, "out", "_sweep")
os.makedirs(TMP, exist_ok=True)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
TPL = os.path.join(ROOT, "template", "128-128.w3m")
EXE = os.path.join(ROOT, "bin", "MPQEditor.exe")

BASE_ARGS = [
    "--water", "0.30", "--mountain", "fbm", "--uplift", "220", "--ridge", "0.6",
    "--warp", "8", "--max-relief", "512", "--shelf-depth", "128",
    "--cliffs", "1", "--cliff-area", "0.15", "--cliff-size", "26",
    "--cliff-layers", "3", "--cliff-feather", "4",
    "--layer-min", "2", "--layer-max", "5",
    "--raise", "75", "--lower", "75", "--rough", "12", "--blob", "28",
    "--grain", "2.5", "--ledge", "0", "--flat", "0.15", "--flat-size", "20",
    "--water-relief", "0.5", "--height-step", "4", "--freq", "1.6",
    "--boundary", "ring", "--ramps", "auto", "--ramp-force", "1",
    "--trees", "0", "--density", "0.35",
]
COMBOS = [("shallow", ["--base", "shallow"]),
          ("land", ["--base", "land"]),
          ("auto", [])]
env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

flag_illegal = re.compile(r"✘ 有非法瓦片")
flag_cut = re.compile(r"被崖壁切断 ✘")
flag_drop = re.compile(r"撤掉够不着的台地: (\d+) 块")
flag_drill = re.compile(r"兜底开坡: 从崖壁上直接开 (\d+) 个坡瓦片")

summary = {}
for mode, extra in COMBOS:
    bad = []
    stats = Counter()
    ramps = []
    for k in range(N):
        seed = 90000 + k * 137
        out = os.path.join(TMP, f"sw_{mode}_{seed}.w3x")
        shutil.copyfile(TPL, out)
        cmd = [PY, os.path.join(ROOT, "tools", "gen_height.py"), out, "--seed", str(seed),
               "--exe", EXE] + BASE_ARGS + extra
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, cwd=ROOT)
        body = (r.stdout or "") + (r.stderr or "")
        why = []
        if flag_illegal.search(body):
            why.append("illegal")
        if flag_cut.search(body):
            why.append("cut")
        if r.returncode != 0:
            why.append(f"rc={r.returncode}")
        m = re.search(r"^斜坡: (\d+) 条", body, re.M)
        if m:
            ramps.append(int(m.group(1)))
        m = flag_drop.search(body)
        if m:
            stats["drop"] += int(m.group(1))
        m = flag_drill.search(body)
        if m:
            stats["drill"] += int(m.group(1))
        if "斜坡几何自检: 无斜坡" in body:
            stats["noramp"] += 1
        if why:
            bad.append((seed, why))
            print(f"  !! {mode} seed={seed} {why}")
            for ln in body.splitlines():
                if "✘" in ln:
                    print("       " + ln.strip())
        # 注：不在这里删 out 文件 —— 循环内删除会被环境的安全策略拦下并中断整个扫描。
        # 产物留在 out/_sweep/ 里，扫完自己清理即可。
    summary[mode] = {
        "hard_fail": f"{len(bad)}/{N}",
        "ramps": (f"min {min(ramps)} / avg {sum(ramps)/len(ramps):.1f} / max {max(ramps)}"
                  if ramps else "-"),
        "drop": stats["drop"], "drill": stats["drill"], "no_ramp": stats["noramp"],
    }
    print(f"{mode}: 硬失败 {len(bad)}/{N}　斜坡 {summary[mode]['ramps']}"
          f"　累计撤台地 {stats['drop']} 块 / 兜底开坡 {stats['drill']} 瓦片")
print("=" * 60)
for k, v in summary.items():
    print(k, v)
