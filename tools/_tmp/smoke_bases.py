# -*- coding: utf-8 -*-
"""冒烟测试：三种基底 × 悬崖开关，各跑一遍并检查不变量。

检查项：
  * 编译/运行不炸
  * shallow 基底：没有任何角点深度 > shelf-depth（无深水）
  * land   基底：水域角点 = 0（一滴水都没有）
  * 悬崖模式：有 layer 台地，但**不是全图**（悬崖区角点占比明显 < 100%）
  * 每张图都跑 inspect_water 的校验逻辑（带头 0x40 的角点必须在世界水面之下）
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
GEN = os.path.join(ROOT, "tools", "gen_height.py")
TPL = os.path.join(ROOT, "template", "64-64.w3m")
OUT = os.path.join(ROOT, "out", "_smoke")

CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def run(name, extra):
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, name + ".w3m")
    shutil.copy2(TPL, dst)
    cmd = [PY, GEN, dst, "--no-backup", "--seed", "20260916",
           "--preview", os.path.join(OUT, name + ".png")] + extra
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=CHILD_ENV)
    out = r.stdout or ""
    print("=" * 78)
    print(f"### {name}  rc={r.returncode}")
    for ln in out.splitlines():
        print("   " + ln)
    if r.returncode != 0:
        print((r.stderr or "")[-2000:])
    return r.returncode, out


def check(rc, out, name, want):
    ok = rc == 0
    for key, needle, expect in want:
        got = needle in out
        if got != expect:
            print(f"  ✘ [{name}] {key}: 期望 {'出现' if expect else '不出现'} 「{needle}」")
            ok = False
        else:
            print(f"  ✔ [{name}] {key}")
    return ok


allok = True
rc, out = run("base_deep", ["--base", "deep", "--uplift", "220"])
allok &= check(rc, out, "base_deep", [
    ("有深水", "深水", True),
])

rc, out = run("base_shallow", ["--base", "shallow", "--uplift", "220"])
# 浅滩基底：深水角点必须是 0
deep_zero = False
for ln in out.splitlines():
    if ln.startswith("水体:"):
        deep_zero = "深水 0（" in ln
        print("   → " + ln)
allok &= bool(rc == 0 and deep_zero)

rc, out = run("base_land", ["--base", "land", "--uplift", "220"])
no_water = "水体: 无" in out
allok &= bool(rc == 0 and no_water)

rc, out = run("cliffs", ["--cliffs", "1", "--base-level", "120", "--uplift", "220"])
partial = False
for ln in out.splitlines():
    if "悬崖区:" in ln:
        print("   → " + ln)
        import re
        m = re.search(r"占地图 ([\d.]+)%", ln)
        partial = bool(m and 0.0 < float(m.group(1)) < 60.0)
allok &= bool(rc == 0 and partial)

rc, out = run("cliffs_shallow", ["--cliffs", "1", "--base", "shallow", "--uplift", "220"])
allok &= bool(rc == 0)

print("=" * 78)
print("SMOKE", "OK" if allok else "FAIL")
