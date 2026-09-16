# -*- coding: utf-8 -*-
"""验证「散树每团株数」旋钮的 GUI→random_map→add_doodads 全链路真的生效。

做法：同一个种子、同一套参数，只把 scatter_size 从 1.0 改到 2.5，
看生成日志里的「胡椒点」行是否按预期变化（iso2 单调下降、单株占块下降）。

用法: python tools/_tmp/gui_scatter_probe.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
GUI = os.path.join(ROOT, "tools", "gui_server.py")
PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"


def post(path, obj):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())


env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
srv = subprocess.Popen([PY, GUI, "--port", str(PORT), "--no-browser"],
                       cwd=ROOT, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True,
                       encoding="utf-8", errors="replace")
try:
    for _ in range(60):
        try:
            get("/api/state")
            break
        except Exception:
            time.sleep(0.25)
    else:
        print("服务没起来")
        sys.exit(1)

    st = get("/api/state")
    tpl = [t for t in st["templates"] if t["name"] == "160-160.w3m"]
    base = {"template": (tpl[0] if tpl else st["templates"][0])["path"],
            "base": "land", "cliffs": 0, "trees": 1, "seed": 20260916,
            "water": 0.30, "mountain": "fbm", "uplift": 220, "ridge": 0.6, "warp": 8,
            "max_relief": 512, "shelf_depth": 128, "layer_min": 2, "layer_max": 5,
            "cliff_area": 0.15, "cliff_size": 26, "cliff_layers": 3, "cliff_feather": 4,
            "ramps": "auto", "ramp_force": 1, "water_relief": 0.5, "height_step": 4,
            "boundary": "ring", "raise": 75, "lower": 75, "rough": 12, "blob": 28,
            "grain": 2.5, "ledge": 0, "flat": 0.15, "flat_size": 20, "freq": 1.6,
            "random_seed": False, "density": 0.18, "forest_share": 0.32,
            "forest_size": 170, "clump_size": 11, "clump_radius": 3.0, "clump_gap": 1.5,
            "clump_bias": 0.55, "scatter": 0.035, "edge_forest": 0.55, "edge_band": 14,
            "tree_freq": 2.2}

    print(f"{'scatter_size':>13}{'散株行':>46}{'胡椒点行':>60}")
    for ss in (1.0, 1.5, 2.5):
        p = dict(base, scatter_size=ss, outname=f"probe_ss{ss}")
        jid = post("/api/generate", p)["job"]
        j = None
        for _ in range(900):
            j = get("/api/job?id=" + jid)
            if j["status"] != "running":
                break
            time.sleep(0.5)
        lines = j.get("log") or []
        scatter = next((ln.strip() for ln in lines if "散株" in ln), "?")
        pepper = next((ln.strip() for ln in lines if "胡椒点" in ln), "?")
        print(f"{ss:>13}  {scatter}")
        print(f"{'':>13}  {pepper}")
        if j["status"] != "done":
            print("  !! status =", j["status"], j.get("error"))
finally:
    srv.terminate()
