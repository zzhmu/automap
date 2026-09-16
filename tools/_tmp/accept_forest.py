# -*- coding: utf-8 -*-
"""树林算法验收：走 GUI 全链路生成，再把产物的树掩码渲染出来 + 量连片指标。

用法: python tools/_tmp/accept_forest.py
"""
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "tools"))
import add_doodads as A  # noqa: E402

GUI = os.path.join(ROOT, "tools", "gui_server.py")
PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"

# 官方 43 张 1.27a 对战图 p50 目标（口径 = add_doodads.forest_metrics）：
# 见 tools/_tmp/foreststats_melee.txt
TGT = dict(dens=0.120, ratio=0.0924, max_sz=205, n100=4,
           frac100=0.332, lone=0.488, iso8=0.017, iso2=0.001, dmed=10.0, dnear=0.365)

CASES = [
    ("acc_land", {"base": "land", "cliffs": 0, "trees": 1, "seed": 20260916}),
    ("acc_cliffs", {"base": "shallow", "cliffs": 1, "trees": 1, "seed": 20260916}),
    ("acc_auto", {"base": "auto", "cliffs": 0, "trees": 1, "seed": 20260916}),
]


def post(path, obj):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())


def measure(w3x):
    """从产出的地图里量树掩码的连片指标（同 forest_official_stats 的口径）。"""
    tmp = A.make_tmp("accforest")
    exe = A.default_exe()
    for fn in ("war3map.w3e", "war3map.doo"):
        subprocess.run([exe, "extract", w3x, fn, tmp, "/fp"], capture_output=True, timeout=180)
    w3e = open(os.path.join(tmp, "war3map.w3e"), "rb").read()
    _ts, W, H, _HS = A.read_w3e_header(w3e)
    _v, _s, recs, _t = A.parse_doo(open(os.path.join(tmp, "war3map.doo"), "rb").read())
    ids = {}
    for r in recs:
        try:
            k = r[:4].decode("ascii")
            ids[k] = ids.get(k, 0) + 1
        except UnicodeDecodeError:
            pass
    if not ids:
        A.drop_tmp(tmp)
        return None
    tree_id = max(ids, key=ids.get)
    grid = np.zeros((W, H), dtype=bool)
    for r in recs:
        try:
            if r[:4].decode("ascii") != tree_id:
                continue
        except UnicodeDecodeError:
            continue
        x, y, _z = struct.unpack_from("<fff", r, 8)
        i = int(round((x + W * 64) / 128.0 - 0.5))
        j = int(round((y + H * 64) / 128.0 - 0.5))
        if 0 <= i < W and 0 <= j < H:
            grid[j, i] = True
    A.drop_tmp(tmp)
    if grid.sum() == 0:
        return None
    fm = A.forest_metrics(grid)     # 口径唯一来源
    out = os.path.join(ROOT, "out", os.path.splitext(os.path.basename(w3x))[0] + "_trees_big.png")
    img = np.full((H, W, 3), (214, 205, 175), dtype=np.uint8)
    img[grid] = (18, 78, 18)
    Image.fromarray(img[::-1]).resize((W * 3, H * 3), Image.NEAREST).save(out)
    fm["png"] = out
    return fm


def _blobs(mask):
    """（已弃用：统一走 A.forest_metrics）"""
    raise NotImplementedError("请用 add_doodads.forest_metrics")


env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
srv = subprocess.Popen([PY, GUI, "--port", str(PORT), "--no-browser"],
                       cwd=ROOT, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True,
                       encoding="utf-8", errors="replace")
rows = []
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

    for name, extra in CASES:
        p = {"template": None, "water": 0.30, "mountain": "fbm", "uplift": 220,
             "ridge": 0.6, "warp": 8, "max_relief": 512, "shelf_depth": 128,
             "layer_min": 2, "layer_max": 5, "cliff_area": 0.15, "cliff_size": 26,
             "cliff_layers": 3, "cliff_feather": 4, "ramps": "auto",
             "ramp_force": 1, "water_relief": 0.5, "height_step": 4,
             "boundary": "ring", "raise": 75, "lower": 75, "rough": 12,
             "blob": 28, "grain": 2.5, "ledge": 0, "flat": 0.15, "flat_size": 20,
             "freq": 1.6, "random_seed": False,
             "density": 0.18, "forest_share": 0.32, "forest_size": 170,
             "clump_size": 11, "clump_radius": 3.0, "clump_gap": 1.5,
             "clump_bias": 0.55, "scatter": 0.035, "scatter_size": 1.5,
             "edge_forest": 0.55,
             "edge_band": 14, "tree_freq": 2.2,
             "outname": name}
        p.update(extra)
        st = get("/api/state")
        tpl = [t for t in st["templates"] if t["name"] == "160-160.w3m"]
        p["template"] = (tpl[0] if tpl else st["templates"][0])["path"]
        r = post("/api/generate", p)
        jid = r["job"]
        for _ in range(900):
            j = get("/api/job?id=" + jid)
            if j["status"] != "running":
                break
            time.sleep(0.5)
        print("=" * 84)
        print(f"### {name}  status={j['status']}  err={j.get('error')}  "
              f"base={p.get('base')} cliffs={p.get('cliffs')}")
        for ln in (j.get("log") or []):
            if any(k in ln for k in ("可用格子", "大林 ", "散株", "连片度", "胡椒点", "种树",
                                     "水体", "初始地面", "深水基底", "浅滩基底",
                                     "纯陆地基底")):
                print("   " + ln)
        f = os.path.join(ROOT, "out", name + ".w3x")
        if os.path.exists(f):
            m = measure(f)
            if m:
                rows.append((name, m))
                print(f"   实测: 树{m['n']} 密度{m['dens']*100:.1f}% 块{m['n_blob']} "
                      f"最大{m['max_sz']} ≥100:{m['n_big']} 大林占比{m['frac_big']*100:.0f}% "
                      f"单株{m['lone']*100:.0f}% 块/树{m['ratio']:.3f} | "
                      f"iso8 {m['iso8']*100:.2f}% iso2 {m['iso2']*100:.2f}% "
                      f"大林距{m['dmed']:.0f} ≤3格{m['dnear']*100:.0f}% → {m['png']}")

    print("\n" + "=" * 96)
    if rows:
        # (forest_metrics 的键, 目标表的键, 显示名)
        hdr = [("dens", "dens", "密度"), ("ratio", "ratio", "块/树"),
               ("max_sz", "max_sz", "最大块"), ("n_big", "n100", "≥100块"),
               ("frac_big", "frac100", "大林占比"), ("lone", "lone", "单株占比"),
               ("iso8", "iso8", "iso8"), ("iso2", "iso2", "iso2"),
               ("dmed", "dmed", "大林距"), ("dnear", "dnear", "≤3格")]
        rows_out = []
        for key, tkey, lab in hdr:
            v = [m[key] for _, m in rows]
            rows_out.append(f"  我们 mean {lab:<8}{np.mean(v):>9.3f}   官方 p50 {TGT[tkey]:>8.3f}")
        half = (len(rows_out) + 1) // 2
        for i in range(half):
            left = rows_out[i]
            right = rows_out[i + half] if i + half < len(rows_out) else ""
            print(f"{left:<52}{right}")
finally:
    srv.terminate()
