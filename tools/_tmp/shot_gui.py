# -*- coding: utf-8 -*-
"""起 GUI → Edge 无头截图 → 裁出「撒树参数面板」作为交付物 → 关服务。

用法: python tools/_tmp/shot_gui.py
输出: out/gui_tree_params.png
"""
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
PORT = 8803
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TALL = os.path.join(ROOT, "tools", "_tmp", "ui_full.png")
OUT = os.path.join(ROOT, "out", "gui_tree_params.png")

env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
srv = subprocess.Popen([PY, os.path.join(ROOT, "tools", "gui_server.py"),
                        "--port", str(PORT), "--no-browser"],
                       cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.STDOUT, text=True,
                       encoding="utf-8", errors="replace")
try:
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/state", timeout=3).read()
            break
        except Exception:
            time.sleep(0.25)
    else:
        print("服务没起来")
        sys.exit(1)
    print("GUI 已起，开始截图…")
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=760,6000", "--force-device-scale-factor=2",
                    f"--screenshot={TALL}", f"http://127.0.0.1:{PORT}/"],
                   capture_output=True, timeout=180)
    if not os.path.exists(TALL):
        print("截图没产出")
        sys.exit(1)
    from PIL import Image
    im = Image.open(TALL)
    w, h = im.size
    print("整页尺寸", im.size)
    im.crop((0, int(h * 0.40), w, int(h * 0.63))).save(OUT)
    print("已保存", OUT, Image.open(OUT).size)
finally:
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()
    print("服务已关")
