# -*- coding: utf-8 -*-
"""走 GUI 全链路重新生成 `out/验收_*.w3x`（用户熟悉的验收图）。

参数组合与 GUI 左栏默认值一致；`base` 三选一 + `cliffs` 开关。
用法: python tools/_tmp/accept_maps.py
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
PORT = 8788
BASE = f"http://127.0.0.1:{PORT}"

CASES = [
    ("验收_局部悬崖", {"base": "auto", "cliffs": 1, "ramps": "auto", "seed": 20260916}),
    ("验收_纯陆地", {"base": "land", "cliffs": 0, "seed": 20260916}),
    ("验收_浅滩无深水", {"base": "shallow", "cliffs": 0, "seed": 20260916}),
]

DEFAULTS = {"water": 0.30, "mountain": "fbm", "uplift": 220, "ridge": 0.6,
            "warp": 8, "max_relief": 512, "shelf_depth": 128, "layer_min": 2,
            "layer_max": 5, "cliff_area": 0.15, "cliff_size": 26,
            "cliff_layers": 3, "cliff_feather": 4, "ramps": "auto",
            "ramp_force": 1, "water_relief": 0.5, "height_step": 4,
            "boundary": "ring", "raise": 75, "lower": 75, "rough": 12,
            "blob": 28, "grain": 2.5, "ledge": 0, "flat": 0.15, "flat_size": 20,
            "freq": 1.6, "random_seed": False, "density": 0.35}


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
    for _ in range(80):
        try:
            st = get("/api/state")
            break
        except Exception:
            time.sleep(0.25)
    else:
        print("服务没起来")
        sys.exit(1)
    tpl = st["templates"][0]["path"]
    for name, extra in CASES:
        p = dict(DEFAULTS)
        p["template"] = tpl
        p["outname"] = name
        p.update(extra)
        jid = post("/api/generate", p)["job"]
        for _ in range(900):
            j = get("/api/job?id=" + jid)
            if j["status"] != "running":
                break
            time.sleep(0.4)
        print("=" * 78)
        print(f"### {name}  status={j['status']}  err={j.get('error')}")
        for ln in (j.get("log") or []):
            if any(k in ln for k in ("斜坡", "连通", "悬崖区", "水域角点", "水体",
                                     "树", "完成", "✘", "水面", "层分布")):
                print("   " + ln.strip())
finally:
    srv.terminate()
