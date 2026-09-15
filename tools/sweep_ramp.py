# -*- coding: utf-8 -*-
"""批量跑随机地图生成器，统计斜坡/连通性自检通过率与耗时。

用法: python sweep_ramp.py [--seeds 20] [--templates 64-64,96-96,...]
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
PY = sys.executable


def run_one(tpl, seed, extra=None):
    out = os.path.join(ROOT, "_tmp_sweep.w3x")
    tpath = os.path.join(ROOT, "template", tpl)
    if not os.path.splitext(tpath)[1]:
        tpath += ".w3m"                    # 允许只写 "128-128"，自动补扩展名
    cmd = [PY, os.path.join(HERE, "random_map.py"),
           "--template", tpath,
           "--out", out, "--seed", str(seed)]
    if extra:
        cmd += extra
    t0 = time.time()
    # 子进程 stdout 是管道时默认用系统 locale 编码（中文 Windows = cp936），
    # 强制它输出 utf-8，否则这里按 utf-8 解码会把中文全变成乱码、正则全部匹配失败。
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600, env=env)
    dt = time.time() - t0
    txt = (p.stdout or "") + (p.stderr or "")
    geoms = re.findall(r"斜坡几何自检: (\d+) 块\s+(✔|✘)([^\n]*)", txt)
    conn = re.search(r"连通性自检: 陆地岛 (\d+) 块 / 可走连通块 (\d+) 块\s+→ ([^\n]*)", txt)
    skip = re.search(r"斜坡: (\d+) 条 \(台地 (\d+) 块, 候选崖边 (\d+) 处(?:, 跳过 (\d+) 处)?\)", txt)
    plat = re.search(r"台地 (\d+) 块", txt)
    return {
        "rc": p.returncode, "dt": dt, "txt": txt,
        "geom_ok": bool(geoms) and all(g[1] == "✔" for g in geoms),
        "geom_n": sum(int(g[0]) for g in geoms),
        "conn_ok": bool(conn) and "✔" in conn.group(3),
        "conn_line": conn.group(0) if conn else "(无)",
        "islands": int(conn.group(1)) if conn else -1,
        "walks": int(conn.group(2)) if conn else -1,
        "ramps": int(skip.group(1)) if skip else -1,
        "plats": int(skip.group(2)) if skip else -1,
        "skipped": int(skip.group(4) or 0) if skip else -1,
    }


def main():
    opts = {}
    for i, a in enumerate(sys.argv):
        if a.startswith("--") and i + 1 < len(sys.argv):
            opts[a[2:]] = sys.argv[i + 1]
    nseed = int(opts.get("seeds", 20))
    tpls = (opts.get("templates", "64-64,96-96,128-128,160-160,192-192")).split(",")
    # 实测官方模板 224/256 是新编辑器 v25 格式，1.27a 不兼容，默认跳过
    bad = 0
    for tpl in tpls:
        line = []
        tmax = 0.0
        for s in range(nseed):
            r = run_one(tpl, 5000 + s)
            tmax = max(tmax, r["dt"])
            mark = "✔" if (r["conn_ok"] and r["geom_ok"]) else "✘"
            line.append(f"{mark}[岛{r['islands']}/走{r['walks']} 坡{r['ramps']}"
                        f"/台{r['plats']}/跳{r['skipped']}]")
            if not (r["conn_ok"] and r["geom_ok"]):
                bad += 1
                print(f"  !! {tpl} seed {5000 + s}: {r['conn_line']}")
                for ln in r["txt"].splitlines():
                    if "斜坡" in ln or "连通" in ln or "Traceback" in ln or "Error" in ln:
                        print("       " + ln.strip())
        print(f"{tpl:12s} 峰耗时 {tmax:5.1f}s  " + " ".join(line))
    print(f"\n失败 {bad} 例")
    return 0


if __name__ == "__main__":
    sys.exit(main())
