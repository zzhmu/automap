# -*- coding: utf-8 -*-
"""按用户在 GUI 里的真实路径，分别用三种「初始地面」生成一张图，把水情打出来。
（用户要求：参数组合必须在 GUI 上验证，不能拿命令行默认值代替。）

用法: python tools/_tmp/gui_base_probe.py
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
PORT = 8823
BASE_URL = f"http://127.0.0.1:{PORT}"
SEED = 7001

# GUI 前端默认值（tools/gui_server.py params() 里的默认）
GUI_DEFAULTS = {
    "water": 0.30, "mountain": "fbm", "uplift": 220, "ridge": 0.6, "warp": 8,
    "max_relief": 512, "shelf_depth": 128, "cliffs": 0, "cliff_area": 0.15,
    "cliff_size": 26, "cliff_layers": 3, "cliff_feather": 4, "layer_min": 2,
    "layer_max": 5, "raise": 75, "lower": 75, "rough": 12, "blob": 28,
    "grain": 2.5, "ledge": 0, "flat": 0.15, "flat_size": 20,
    "water_relief": 0.5, "height_step": 4, "freq": 1.6, "boundary": "ring",
    "ramps": "auto", "ramp_force": 1, "trees": 1, "density": 0.35,
    "clump_size": 26, "clump_radius": 4.5, "clump_gap": 2.1, "clump_bias": 0.55,
    "scatter": 0.015,
}


def post(path, obj):
    req = urllib.request.Request(BASE_URL + path, method="POST",
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE_URL + path, timeout=30).read())


env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
srv = subprocess.Popen([PY, GUI, "--port", str(PORT), "--no-browser"], cwd=ROOT,
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
try:
    for _ in range(60):
        try:
            st = get("/api/state")
            break
        except Exception:
            time.sleep(0.25)
    else:
        print("服务没起来")
        sys.exit(1)

    tpl = st["templates"][0]["path"]
    print(f"模板: {tpl}")
    for base in ("auto", "land", "shallow", "deep"):
        p = dict(GUI_DEFAULTS)
        p["base"] = base
        p["template"] = tpl
        p["outname"] = f"_probe_{base}"
        p["seed"] = SEED
        r = post("/api/generate", p)
        jid = r["job"]
        for _ in range(1200):
            j = get("/api/job?id=" + jid)
            if j["status"] != "running":
                break
            time.sleep(0.5)
        print("=" * 78)
        print(f"### base={base}  status={j['status']}")
        for ln in (j.get("log") or []):
            if any(k in ln for k in ("水体:", "模式:", "初始地面", "水面", "应用高度",
                                     "高度层区间", "斜坡:", "连通性")):
                print("   " + ln)
        out = os.path.join(ROOT, "out", f"_probe_{base}.w3x")
        if os.path.exists(out):
            rr = subprocess.run([PY, os.path.join(ROOT, "tools", "inspect_water.py"), out],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=env)
            for ln in (rr.stdout or "").splitlines():
                if any(k in ln for k in ("水角点", "水深 WE", "没有水", "水面世界高度")):
                    print("   " + ln.strip())
finally:
    srv.terminate()
