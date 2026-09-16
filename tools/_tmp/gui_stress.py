# -*- coding: utf-8 -*-
"""压力测试：GUI 全链路上跑多组 (基底 × 悬崖) × 多随机种子，统计失败率。

判定：
  * 连通性：「每座岛内部都走得通 ✔」
  * 斜坡几何：「全部符合官方几何」或「无斜坡」
  * 水体：inspect_water 不报「水会画穿」
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
GUI = os.path.join(ROOT, "tools", "gui_server.py")
PORT = 8811
BASE = f"http://127.0.0.1:{PORT}"
N = 8

COMBOS = [
    ("cliffs_shallow", {"base": "shallow", "cliffs": 1}),
    ("cliffs_land", {"base": "land", "cliffs": 1}),
    ("cliffs_auto", {"base": "auto", "cliffs": 1, "water": 0.30}),
]

DEFAULTS = {"water": 0.30, "mountain": "fbm", "uplift": 220, "ridge": 0.6,
            "warp": 8, "max_relief": 512, "shelf_depth": 128, "layer_min": 2,
            "layer_max": 5, "cliff_area": 0.15, "cliff_size": 26,
            "cliff_layers": 3, "cliff_feather": 4, "ramps": "auto",
            "ramp_force": 1, "water_relief": 0.5, "height_step": 4,
            "boundary": "ring", "raise": 75, "lower": 75, "rough": 12,
            "blob": 28, "grain": 2.5, "ledge": 0, "flat": 0.15, "flat_size": 20,
            "freq": 1.6, "random_seed": False, "density": 0.35, "trees": 0}


def post(path, obj):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())


env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
srv = subprocess.Popen([PY, GUI, "--port", str(PORT), "--no-browser"], cwd=ROOT,
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
try:
    for _ in range(60):
        try:
            st = get("/api/state"); break
        except Exception:
            time.sleep(0.25)
    tpl = st["templates"][0]["path"]
    good = {}
    for label, extra in COMBOS:
        g = 0
        for k in range(N):
            p = dict(DEFAULTS)
            p["template"] = tpl
            p["outname"] = f"st_{label}_{k}"
            p["seed"] = 70000 + k * 37
            p.update(extra)
            jid = post("/api/generate", p)["job"]
            for _ in range(600):
                j = get("/api/job?id=" + jid)
                if j["status"] != "running":
                    break
                time.sleep(0.4)
            body = "\n".join(j.get("log") or [])
            # 硬失败：连通性被切断 / 有非法斜坡瓦片 / 水体画穿
            why = []
            if j["status"] not in ("ok", "done"):
                why.append("rc")
            if "被崖壁切断 ✘" in body:
                why.append("conn")
            if "✘ 有非法瓦片" in body:
                why.append("ramp")
            rr = subprocess.run(
                [PY, os.path.join(ROOT, "tools", "inspect_water.py"),
                 os.path.join(ROOT, "out", f"st_{label}_{k}.w3x")],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=env)
            if "✘ 水会画穿" in (rr.stdout or ""):
                why.append("water")
            hard = bool(why)
            soft = ("✘" in body) and not hard
            if not hard:
                g += 1
            else:
                prog = re.search(r"悬崖区: \d+ 角点（占地图 [\d.]+%）", body)
                print(f"  !! {label} seed={p['seed']} 失败({'+'.join(why)})  "
                      f"{prog.group(0) if prog else ''}")
                for ln in body.splitlines():
                    if "✘" in ln:
                        print("       " + ln.strip())
            if soft:
                print(f"  ~~ {label} seed={p['seed']} 软提示: "
                      + " | ".join(l.strip() for l in body.splitlines() if "✘" in l))
        good[label] = f"{g}/{N}"
        print(f"{label}: {g}/{N} 硬通过")
    print("=" * 60)
    print("STRESS", good)
finally:
    srv.terminate()
