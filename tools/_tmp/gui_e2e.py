# -*- coding: utf-8 -*-
"""GUI 全链路验证（用户要求：参数组合必须在 GUI 上跑，不能用命令行默认参数代替）。

做法：起 gui_server（--no-browser）→ POST /api/generate 三组 → 轮询 /api/job → 校验产物。
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
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"

CASES = [
    ("gui_land", {"base": "land", "cliffs": 0, "trees": 0,
                  "outname": "gui_land", "seed": 4242}),
    ("gui_shallow", {"base": "shallow", "cliffs": 0, "trees": 0,
                     "outname": "gui_shallow", "seed": 4242}),
    ("gui_cliffs", {"base": "shallow", "cliffs": 1, "trees": 0,
                    "outname": "gui_cliffs", "seed": 4242}),
]


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
    # 等服务起来
    for _ in range(60):
        try:
            get("/api/state")
            break
        except Exception:
            time.sleep(0.25)
    else:
        print("服务没起来"); sys.exit(1)

    allok = True
    for name, extra in CASES:
        p = {"template": None, "water": 0.30, "mountain": "fbm", "uplift": 220,
             "ridge": 0.6, "warp": 8, "max_relief": 512, "shelf_depth": 128,
             "layer_min": 2, "layer_max": 5, "cliff_area": 0.15, "cliff_size": 26,
             "cliff_layers": 3, "cliff_feather": 4, "ramps": "auto",
             "ramp_force": 1, "water_relief": 0.5, "height_step": 4,
             "boundary": "ring", "raise": 75, "lower": 75, "rough": 12,
             "blob": 28, "grain": 2.5, "ledge": 0, "flat": 0.15, "flat_size": 20,
             "freq": 1.6, "random_seed": False, "density": 0.35}
        st = get("/api/state")
        p["template"] = st["templates"][0]["path"]
        p.update(extra)
        r = post("/api/generate", p)
        jid = r["job"]
        log = []
        for _ in range(600):
            j = get("/api/job?id=" + jid)
            log = j.get("log") or []
            if j["status"] != "running":
                break
            time.sleep(0.5)
        print("=" * 78)
        print(f"### {name}  status={j['status']}  err={j.get('error')}")
        for ln in log:
            print("   " + ln)
        ok = j["status"] in ("ok", "done")
        body = "\n".join(log)
        if name == "gui_land":
            ok &= "水体: 无" in body
        if name == "gui_shallow":
            ok &= "深水 0（" in body
        if name == "gui_cliffs":
            ok &= "悬崖区:" in body and "模式: 局部悬崖" in body
            ok &= "0 角点（占地图 0.0%）" not in body
        allok &= ok
        print(f"  -> {'OK' if ok else 'FAIL'}")

    # 对产物跑水体校验
    for f in ("gui_land.w3x", "gui_shallow.w3x", "gui_cliffs.w3x"):
        p = os.path.join(ROOT, "out", f)
        if not os.path.exists(p):
            print(f"  !! 缺少产物 {p}"); allok = False; continue
        rr = subprocess.run([PY, os.path.join(ROOT, "tools", "inspect_water.py"), p],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env)
        txt = rr.stdout or ""
        bad = "水会画穿" in txt
        print(f"  {f}: 水体验证 {'✘ 水会画穿' if bad else '✔'}")
        allok &= not bad
    print("=" * 78)
    print("GUI E2E", "OK" if allok else "FAIL")
finally:
    srv.terminate()
