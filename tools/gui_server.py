# -*- coding: utf-8 -*-
"""随机地图生成器 —— 图形界面（纯标准库，零依赖）。

为什么不用 tkinter：本机两个 Python（托管 3.13.12 与默认 venv）都没有编译 tk/tcl，
`import tkinter` 直接 ModuleNotFoundError，装 tcl/tk 比这个界面本身还折腾。
所以改用「标准库 http.server 起一个本机服务 + 浏览器当窗口」：
  优点：不需要任何第三方库；能直接显示生成的预览图；参数改完一键生成。
  安全性：只监听 127.0.0.1，只允许读取 out/ 目录下的文件。

用法:
  python gui_server.py            # 起服务并自动打开浏览器
  python gui_server.py --port 8800 --no-browser
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))


def force_utf8_stdout():
    """管道/重定向时标准输出统一 UTF-8，控制台保留原编码（中文才显示得对）。理由见 gen_height.py。"""
    for s in (sys.stdout, sys.stderr):
        try:
            if s.isatty():
                s.reconfigure(errors="replace")
            else:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


force_utf8_stdout()
ROOT = os.path.dirname(HERE)
TEMPLATE_DIR = os.path.join(ROOT, "template")
OUT_DIR = os.path.join(ROOT, "out")
PY = sys.executable
RANDOM_MAP = os.path.join(HERE, "random_map.py")

JOBS = {}
_job_seq = [0]
_job_lock = threading.Lock()

# 生成器里的合法层号：水面占 layer_min-1，陆地占 layer_min..layer_max，上限 14
LAYER_MAX = 14


# --------------------------------------------------------------------------
# 模板发现
# --------------------------------------------------------------------------
def list_templates():
    out = []
    for d in (TEMPLATE_DIR, ROOT):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith((".w3m", ".w3x", ".w3n")):
                continue
            if fn.startswith(("_", ".")):          # 跳过临时产物
                continue
            p = os.path.join(d, fn)
            size = os.path.getsize(p)
            # 从文件名读尺寸，如 128-128.w3m → 128x128
            m = re.match(r"^(\d+)-(\d+)", fn)
            note = ""
            if m:
                note = f"{m.group(1)}×{m.group(2)}"
            if fn.lower().endswith(".w3x") and m and int(m.group(1)) >= 224:
                note += "  ⚠ 1.31+ 产物，1.27a 的 WE 可能打不开"
            out.append({
                "path": os.path.relpath(p, ROOT).replace("\\", "/"),
                "name": fn,
                "note": note,
                "size": size,
                "dir": "template" if d == TEMPLATE_DIR else "根目录",
            })
    return out


def parse_log(text):
    """从生成器日志里抠出几条给界面做徽章的关键结论。"""
    info = {}
    m = re.search(r"模式: (\S+)", text)
    if m:
        info["mode"] = m.group(1)
    m = re.search(r"高度层区间: (\d+)~(\d+) 层", text)
    if m:
        info["layer"] = f"{m.group(1)} ~ {m.group(2)} 层"
    m = re.search(r"连片度: (\d+) 片，最大 (\d+) 格，平均 ([\d.]+) 格", text)
    if m:
        info["blob"] = f"连片 {m.group(1)} 片 / 最大 {m.group(2)} 格 / 平均 {m.group(3)}"
    m = re.search(r"种树 (\d+) 棵", text)
    if m:
        info["trees"] = int(m.group(1))
    m = re.search(r"斜坡: (\d+) 条", text)
    if m:
        info["ramps"] = int(m.group(1))
    if ("每座岛内部都走得通 ✔" in text or "岛内处处可走 ✔" in text):
        info["conn"] = "ok"
    elif "被崖壁切断 ✘" in text:
        info["conn"] = "bad"
    m = re.search(r"完成 → (.+)", text)
    if m:
        info["out"] = m.group(1).strip()
    return info


def run_job(job_id, params):
    job = JOBS[job_id]

    def emit(line):
        job["log"].append(line)

    try:
        tpl = params["template"]
        tpl_abs = tpl if os.path.isabs(tpl) else os.path.join(ROOT, tpl)
        if not os.path.exists(tpl_abs):
            raise FileNotFoundError(f"找不到模板: {tpl_abs}")
        os.makedirs(OUT_DIR, exist_ok=True)

        seed = params.get("seed")
        if params.get("random_seed") or seed in (None, ""):
            seed = int(time.time() * 1000) % 1000000
        seed = int(seed)

        name = (params.get("outname") or "").strip()
        if not name:
            name = f"rand_{seed}"
        name = re.sub(r"[\\/:*?\"<>|]", "_", name)
        if not name.lower().endswith((".w3x", ".w3m")):
            name += ".w3x"
        out_abs = os.path.join(OUT_DIR, name)
        prefix = os.path.splitext(out_abs)[0]

        cmd = [PY, RANDOM_MAP, "--template", tpl_abs, "--out", out_abs,
               "--seed", str(seed),
               "--preview-prefix", prefix]

        def add(k, v):
            cmd.extend(["--" + k, str(v)])

        # 第 1 步：地形基底与水面
        add("water", params.get("water", 0.30))
        if params.get("base", "auto") != "auto":
            add("base", params["base"])
        add("mountain", params.get("mountain", "fbm"))
        add("uplift", params.get("uplift", 220))
        add("ridge", params.get("ridge", 0.6))
        add("warp", params.get("warp", 8))
        add("max-relief", params.get("max_relief", 512))
        add("shelf-depth", params.get("shelf_depth", 128))
        # 第 2 步：悬崖（可选）
        add("cliffs", 1 if str(params.get("cliffs", 0)) in ("1", "true", "True") else 0)
        add("cliff-area", params.get("cliff_area", 0.15))
        add("cliff-size", params.get("cliff_size", 26))
        add("cliff-layers", params.get("cliff_layers", 3))
        add("cliff-feather", params.get("cliff_feather", 4))
        add("layer-min", params.get("layer_min", 2))
        add("layer-max", params.get("layer_max", 5))
        add("raise", params.get("raise", 75))
        add("lower", params.get("lower", 75))
        add("rough", params.get("rough", 12))
        add("blob", params.get("blob", 28))
        add("grain", params.get("grain", 2.5))
        add("ledge", params.get("ledge", 0))
        add("flat", params.get("flat", 0.15))
        add("flat-size", params.get("flat_size", 20))
        add("water-relief", params.get("water_relief", 0.5))
        add("shore-width", params.get("shore_width", 3))
        add("shore-shallow", params.get("shore_shallow", 0))
        add("height-step", params.get("height_step", 4))
        add("freq", params.get("freq", 1.6))
        add("boundary", params.get("boundary", "ring"))
        add("ramps", params.get("ramps", "auto"))
        if str(params.get("ramp_force", 1)) in ("1", "true", "True"):
            add("ramp-force", 1)
        else:
            add("ramp-force", 0)
        # 第 3 步：树木（可选）
        if str(params.get("trees", 1)) not in ("1", "true", "True"):
            add("trees", 0)
        add("density", params.get("density", 0.18))
        add("forest-share", params.get("forest_share", 0.32))
        add("forest-size", params.get("forest_size", 170))
        add("clump-size", params.get("clump_size", 11))
        add("clump-radius", params.get("clump_radius", 3.0))
        add("clump-gap", params.get("clump_gap", 1.5))
        add("clump-bias", params.get("clump_bias", 0.55))
        add("scatter", params.get("scatter", 0.035))
        add("scatter-size", params.get("scatter_size", 1.5))
        add("edge-forest", params.get("edge_forest", 0.55))
        add("edge-band", params.get("edge_band", 14))
        add("tree-freq", params.get("tree_freq", 2.2))

        emit(f"$ 模板 {os.path.basename(tpl_abs)} → {name}  (seed={seed})")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env=env,
                                cwd=ROOT, bufsize=1)
        buf = []
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            # 生成器外层会整段 print(stderr) 可能带 ANSI，直接原样显示
            emit(line)
            buf.append(line)
        proc.wait()
        text = "\n".join(buf)
        info = parse_log(text)

        if proc.returncode != 0:
            job["status"] = "error"
            job["error"] = f"生成器退出码 {proc.returncode}"
            return

        previews = []
        for suff in ("_terrain.png", "_trees.png"):
            p = prefix + suff
            if os.path.exists(p):
                previews.append(os.path.relpath(p, OUT_DIR).replace("\\", "/"))
        info["previews"] = previews
        info["out_abs"] = out_abs
        info["seed"] = seed
        job["result"] = info
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = f"{type(e).__name__}: {e}"
    finally:
        job["end"] = time.time()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "AutoMapGUI"

    def log_message(self, *a):        # 静音，别刷控制台
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif u.path == "/api/state":
            self._json({
                "templates": list_templates(),
                "out_dir": OUT_DIR,
                "root": ROOT,
                "layer_max": LAYER_MAX,
            })
        elif u.path == "/api/job":
            jid = (q.get("id") or [""])[0]
            job = JOBS.get(jid)
            if not job:
                self._json({"error": "no such job"}, 404)
            else:
                self._json({k: job.get(k) for k in
                            ("status", "log", "result", "error", "start", "end")})
        elif u.path == "/preview":
            rel = (q.get("p") or [""])[0]
            p = os.path.normpath(os.path.join(OUT_DIR, rel))
            if not p.startswith(os.path.normpath(OUT_DIR)) or not os.path.exists(p):
                self._json({"error": "not found"}, 404)
            else:
                self._send(200, open(p, "rb").read(), "image/png")
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            params = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:  # noqa: BLE001
            params = {}

        if u.path == "/api/generate":
            with _job_lock:
                _job_seq[0] += 1
                jid = str(_job_seq[0])
            JOBS[jid] = {"status": "running", "log": [], "start": time.time(),
                         "result": None, "error": None, "end": None}
            # 只留最近 8 个任务，别把内存堆满
            if len(JOBS) > 8:
                for k in sorted(JOBS, key=lambda x: int(x))[:-8]:
                    JOBS.pop(k, None)
            threading.Thread(target=run_job, args=(jid, params), daemon=True).start()
            self._json({"job": jid})
        elif u.path == "/api/open":
            path = (params.get("path") or "").strip()
            try:
                if path and os.path.exists(path):
                    if os.path.isfile(path):
                        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                    else:
                        subprocess.Popen(["explorer", os.path.normpath(path)])
                    self._json({"ok": True})
                else:
                    self._json({"ok": False, "error": "路径不存在"}, 404)
            except Exception as e:  # noqa: BLE001
                self._json({"ok": False, "error": str(e)}, 500)
        else:
            self._json({"error": "not found"}, 404)


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>魔兽随机地图生成器</title>
<style>
  :root{
    --bg:#12161d; --panel:#1a2029; --panel2:#212936; --line:#2c3542;
    --fg:#e6ebf2; --dim:#8f9bab; --accent:#4da3ff; --accent2:#2f7fd6;
    --ok:#3fbf7f; --bad:#ef6b6b; --warn:#e8b34a;
    --radius:10px;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.5 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
  header{padding:16px 22px;border-bottom:1px solid var(--line);
    display:flex;align-items:baseline;gap:14px;background:var(--panel)}
  h1{font-size:17px;margin:0;font-weight:600;letter-spacing:.3px}
  header .sub{color:var(--dim);font-size:12px}
  .wrap{display:grid;grid-template-columns:390px 1fr;gap:16px;padding:16px;align-items:start}
  @media (max-width:1080px){.wrap{grid-template-columns:1fr}}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
    padding:14px 16px;margin-bottom:16px}
  .panel h2{font-size:13px;margin:0 0 12px;color:var(--dim);font-weight:600;
    text-transform:uppercase;letter-spacing:.8px}
  .sub2{font-size:11.5px;color:var(--accent);font-weight:600;letter-spacing:.4px;
    margin:16px 0 2px;padding-bottom:4px;border-bottom:1px dashed var(--line)}
  .sub2:first-of-type{margin-top:4px}
  label{display:block;font-size:12px;color:var(--dim);margin:10px 0 4px}
  input,select{width:100%;background:var(--panel2);border:1px solid var(--line);
    color:var(--fg);border-radius:7px;padding:7px 9px;font-size:13px;outline:none}
  input:focus,select:focus{border-color:var(--accent)}
  input[type=range]{padding:0;height:22px;background:transparent;border:none}
  .row{display:flex;gap:10px}
  .row>div{flex:1;min-width:0}
  .hint{font-size:11px;color:var(--dim);margin-top:5px;line-height:1.45}
  .hint b{color:var(--accent)}
  .chk{display:flex;align-items:center;gap:8px;margin-top:10px;font-size:12.5px;color:var(--dim)}
  .chk input{width:auto}
  button{background:var(--accent);color:#06111f;border:none;border-radius:8px;
    padding:9px 14px;font-size:13.5px;font-weight:600;cursor:pointer}
  button:hover{background:#62b0ff}
  button:disabled{opacity:.45;cursor:default}
  button.ghost{background:transparent;border:1px solid var(--line);color:var(--fg);font-weight:500}
  button.ghost:hover{background:var(--panel2)}
  #go{width:100%;padding:12px;font-size:15px;margin-top:6px}
  .badges{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
  .badge{background:var(--panel2);border:1px solid var(--line);border-radius:999px;
    padding:4px 11px;font-size:12px;color:var(--dim)}
  .badge b{color:var(--fg);font-weight:600}
  .badge.ok{border-color:#2c6c4d;color:#a6e6c4}
  .badge.bad{border-color:#7a3636;color:#ffb3b3}
  .shots{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media (max-width:760px){.shots{grid-template-columns:1fr}}
  .shot{background:var(--panel2);border:1px solid var(--line);border-radius:8px;
    padding:8px;text-align:center;min-height:120px;
    display:flex;flex-direction:column;justify-content:center;align-items:center}
  .shot img{width:100%;border-radius:5px;display:block;image-rendering:pixelated}
  .shot .cap{font-size:11px;color:var(--dim);margin-top:6px}
  pre{background:#0c1016;border:1px solid var(--line);border-radius:8px;padding:12px;
    font-size:12px;line-height:1.55;max-height:430px;overflow:auto;margin:0;
    white-space:pre-wrap;word-break:break-all;font-family:Consolas,"Courier New",monospace}
  .spin{display:inline-block;width:12px;height:12px;border:2px solid var(--line);
    border-top-color:var(--accent);border-radius:50%;animation:s .8s linear infinite}
  @keyframes s{to{transform:rotate(360deg)}}
  .warnbar{background:#3a2c12;border:1px solid #6b5320;color:#ffd98a;border-radius:8px;
    padding:9px 12px;font-size:12px;margin-bottom:12px}
  /* 参数说明浮层：鼠标悬停任意带 data-tip 的参数名就弹出来 */
  label.tip{cursor:help}
  label.tip .q{display:inline-block;width:13px;height:13px;line-height:12px;text-align:center;
    border-radius:50%;background:var(--panel2);border:1px solid var(--line);color:var(--dim);
    font-size:9px;margin-left:5px;vertical-align:1px;font-weight:600}
  label.tip:hover{color:var(--fg)}
  label.tip:hover .q{border-color:var(--accent);color:var(--accent);background:#16283c}
  #tipbox{position:fixed;z-index:99;max-width:330px;background:#0b0f15;
    border:1px solid var(--accent2);border-radius:9px;padding:10px 12px;
    font-size:11.5px;line-height:1.55;color:var(--fg);
    box-shadow:0 10px 30px rgba(0,0,0,.55);pointer-events:none;display:none}
  #tipbox b{color:var(--accent)}
  #tipbox .tt{display:block;color:var(--accent);font-weight:600;margin-bottom:4px;font-size:12px}
</style>
</head>
<body>
<header>
  <h1>魔兽随机地图生成器</h1>
  <span class="sub">第 1 步 地形基底 → 第 2 步 悬崖（可选） → 第 3 步 树木（可选） → .w3x（WE 可直接打开）</span>
</header>

<div class="wrap">
  <!-- 左：参数 -->
  <div>
    <div class="panel">
      <h2>模板与输出</h2>
      <label class="tip" data-tip="<span class='tt'>模板地图</span>决定地图尺寸和地表贴图（树种也会按模板自动识别）。<br>只有 <b>64/96/128/160/192</b> 的 .w3m 是 1.27a 原生；224/256 的 .w3x 是 1.31+ 产物，1.27a 的 WE 可能打不开。<br>生成时<b>只替换地形与树木</b>，模板的其余内容原样保留。">模板地图<span class="q">?</span></label>
      <select id="template"></select>
      <div class="hint" id="tplHint"></div>
      <label class="tip" data-tip="<span class='tt'>输出文件名</span>生成的地图存到 <b>out/</b> 目录。<br>留空则自动用 rand_&lt;种子&gt;.w3x。">输出文件名<span class="q">?</span></label>
      <input id="outname" placeholder="留空 = rand_&lt;种子&gt;.w3x">
      <div class="row">
        <div>
          <label class="tip" data-tip="<span class='tt'>随机种子</span><b>同一个种子 + 同一套参数 = 一模一样的地图</b>（可复现）；换个种子就是一张全新地形。">随机种子<span class="q">?</span></label>
          <input id="seed" type="number" value="20260915">
        </div>
        <div style="flex:0 0 92px;display:flex;align-items:flex-end">
          <button class="ghost" style="width:100%" onclick="rollSeed()">换一个</button>
        </div>
      </div>
      <div class="chk"><input type="checkbox" id="randSeed"><label for="randSeed" style="margin:0"
        title="勾上后忽略上面的种子，每次点生成都随机取一个">每次生成都用随机种子</label></div>
      <label class="tip" data-tip="<span class='tt'>地图边界标记</span>WE 里给地图外圈打的「不可通行」标记。<br><b>ring</b> = 只留最外一圈（整张地图都能玩）<br><b>none</b> = 全清（可玩区顶到地图边）<br><b>keep</b> = 沿用模板自带的边框">地图边界标记<span class="q">?</span></label>
      <select id="boundary">
        <option value="ring" selected>ring — 只留最外一圈（整张可玩）</option>
        <option value="none">none — 全清</option>
        <option value="keep">keep — 沿用模板边框</option>
      </select>
    </div>

    <div class="panel">
      <h2>第 1 步 · 地形与水面（连续起伏，无悬崖）</h2>
      <div class="hint" style="margin:0 0 10px">这一栏做出来的全是<strong>圆滑的接触面</strong>：
        山脉抬升 + 地表起伏都不会产生层差，近战单位处处可走。想要崖壁去第 2 步。</div>

      <div class="sub2">初始地面与山脉</div>
      <label class="tip" data-tip="<span class='tt'>初始地面</span>整张图的基准高度（相对水面）。<br>选 <b>按水域占比自动</b> 时水面按占比反解、精确可控；选了其余任何一项，<b>水面恒为 0</b>，水域占比改由「初始地面 + 山脉抬升」自然决定（占比滑条失效）。">初始地面<span class="q">?</span></label>
      <select id="base">
        <option value="auto" selected>按水域占比自动（推荐，可精确控制水域）</option>
        <option value="land">纯陆地（0）— 一滴水都没有</option>
        <option value="shallow">浅滩（水底压平 128 WE = 1 整层）— 水浅到能直接走过去，无深水</option>
        <option value="deep">深水（-384）— 深浅水都有 → 只有山脊露出水面（群岛 / 大湖）</option>
      </select>
      <label class="tip" data-tip="<span class='tt'>山脉算法</span><b>fbm</b> = 圆润丘陵团块，最像官方对战图<br><b>ridged</b> = 有明显山脊线，更像真实山脉<br><b>warped</b> = 域扭曲，山体走向自然弯曲">山脉算法<span class="q">?</span></label>
      <select id="mountain">
        <option value="fbm" selected>fbm — 圆润丘陵团块（最像官方对战图）</option>
        <option value="ridged">ridged — 有明显山脊线（更像真实山脉）</option>
        <option value="warped">warped — 域扭曲（山体走向自然弯曲）</option>
      </select>
      <label class="tip" data-tip="<span class='tt'>山脉抬升</span>整张图山体的<b>整体高度幅度</b>（WE，1 整层 = 128）。<br>越大山越高、陆地与水面落差越大；<b>0 = 几乎没山</b>。<br>它管大尺度山体，和下面「地表起伏」那一栏<b>叠加</b>。">山脉抬升 <span id="upV">220</span> WE<span class="q">?</span></label>
      <input id="uplift" type="range" min="0" max="600" step="10" value="220">
      <div id="ridgeRow"><label class="tip" data-tip="<span class='tt'>山脊锐度</span>只对 <b>ridged</b> 生效。<br>越大山脊越尖、越像刀刃；越小越圆润。">山脊锐度（ridged） <span id="rdV">0.60</span><span class="q">?</span></label>
      <input id="ridge" type="range" min="0" max="2" step="0.05" value="0.6"></div>
      <div id="warpRow"><label class="tip" data-tip="<span class='tt'>扭曲强度</span>只对 <b>warped</b> 生效。<br>越大山脉走向扭曲越厉害（单位：格）。">扭曲强度（warped，格） <span id="wpV">8</span><span class="q">?</span></label>
      <input id="warp" type="range" min="0" max="30" step="1" value="8"></div>

      <div class="sub2">地表起伏（应用高度）</div>
      <label class="tip" data-tip="<span class='tt'>隆起</span>地面<b>向上</b>鼓包的幅度。<br>和「山脉抬升」叠加，管山体上的细节起伏。官方对战图参考值 ≈ <b>70</b>。">隆起（地面向上鼓包） <span id="raV">75</span><span class="q">?</span></label>
      <input id="raise" type="range" min="0" max="120" step="5" value="75">
      <label class="tip" data-tip="<span class='tt'>凹陷</span>地面<b>向下</b>凹坑的幅度。<br>和「隆起」一起决定起伏的上下幅度。官方对战图参考值 ≈ <b>70</b>。">凹陷（地面向下凹坑） <span id="loV">75</span><span class="q">?</span></label>
      <input id="lower" type="range" min="0" max="120" step="5" value="75">
      <label class="tip" data-tip="<span class='tt'>凹凸不平</span>表面<b>颗粒感</b>（小块凹凸）的强度。<br>官方地图的噪波笔刷本身很轻，参考值 ≈ <b>10</b>。">凹凸不平（表面颗粒感） <span id="rgV">12</span><span class="q">?</span></label>
      <input id="rough" type="range" min="0" max="60" step="2" value="12">
      <label class="tip" data-tip="<span class='tt'>起伏团块尺寸</span>起伏的<b>空间尺度</b>（格）。<br>越大起伏越「大块」越平缓；越小越细碎。">起伏团块尺寸（格） <span id="blV">28</span><span class="q">?</span></label>
      <input id="blob" type="range" min="8" max="80" step="2" value="28">
      <label class="tip" data-tip="<span class='tt'>颗粒尺寸</span>最小的起伏颗粒大小（格）。<br>越小越细密；太小时细节会被引擎的高度量化吃掉。">颗粒尺寸（格） <span id="grV">2.5</span><span class="q">?</span></label>
      <input id="grain" type="range" min="1.5" max="12" step="0.5" value="2.5">
      <label class="tip" data-tip="<span class='tt'>台阶高度</span>把连续起伏<b>量化成台阶</b>的高度（WE）。<br><b>0 = 完全连续圆滑</b>（近战单位处处可走）；调大就会出现等高平台，像官方图那样相邻角点大量等高。">台阶高度（0 = 连续起伏） <span id="lgV">0</span><span class="q">?</span></label>
      <input id="ledge" type="range" min="0" max="90" step="5" value="0">
      <label class="tip" data-tip="<span class='tt'>平整区域占比</span>完全没有起伏的<b>平地块</b>占地图的比例。<br>用来留出建基地、摆建筑的地方。">平整区域占比（完全没有起伏的地面） <span id="flV">15%</span><span class="q">?</span></label>
      <input id="flat" type="range" min="0" max="0.6" step="0.01" value="0.15">
      <label class="tip" data-tip="<span class='tt'>平整区域团块尺寸</span>每块平地的尺寸（格）。<br>越大越适合摆大基地，越小越零碎。">平整区域团块尺寸（格） <span id="fsV">20</span><span class="q">?</span></label>
      <input id="flatSize" type="range" min="6" max="60" step="1" value="20">
      <div class="hint">幅度单位 = WE 高度条上的格数（一整层 = 128），
        和上面的「山脉抬升」<strong>叠加</strong>：抬升管大尺度山体，这三项管山体上的细节。
        官方对战图参考：隆起/凹陷 ≈ 70，凹凸不平 ≈ 10（噪波笔刷本身很轻），
        相邻角点有 36%~64% 完全等高 —— 那是「台阶」的效果，调大它就能复现。<br>
        平整区域 = 把起伏整体压平的一块块地（建基地、摆建筑用）</div>

      <div class="sub2">水面</div>
      <label class="tip" data-tip="<span class='tt'>水域占比</span><b>只有「初始地面 = 按水域占比自动」时生效</b>。<br>水面高度按这个比例反解，所以能精确控制水域多少。<br>选了别的初始地面后这个滑条失效（水面恒为 0）。">水域占比 <span id="wtV">30%</span><span class="q">?</span></label>
      <input id="water" type="range" min="0" max="0.7" step="0.01" value="0.30">
      <label class="tip" data-tip="<span class='tt'>振幅上限</span>最高点与最低点的<b>落差上限</b>（WE）。<br>用软裁剪实现，不会把山顶切成平顶；官方实测能到 1536。">振幅上限（落差不超过这么多） <span id="mrV">512</span> WE<span class="q">?</span></label>
      <input id="maxRelief" type="range" min="128" max="1536" step="32" value="512">
      <label class="tip" data-tip="<span class='tt'>水底深度下限</span>水底最浅不会高于这个深度（WE）。<br><b>WE 只在「地形低于水面 ≥ 1 个整层（128 WE）」时才画水面</b>，更浅的水下会被当干地渲染（看着像陆地）。<br>所以别调到 128 以下。">水底深度下限 <span id="sdV">128</span> WE<span class="q">?</span></label>
      <input id="shelfDepth" type="range" min="128" max="256" step="8" value="128">
      <label class="tip" data-tip="<span class='tt'>水下起伏</span>水下地形的起伏 = 陆地起伏 × 这个系数。<br><b>0 = 水底完全压平</b>；1.5 = 比陆地还崎岖。">水下起伏（× 陆地起伏） <span id="wrV">0.50</span><span class="q">?</span></label>
      <input id="waterRelief" type="range" min="0" max="1.5" step="0.05" value="0.5">
      <label class="tip" data-tip="<span class='tt'>岸线缓坡宽度</span>水从岸边往湖心<b>加深</b>要走几格。<br>官方 40 张有水的对战图实测：离岸 <b>1/2/3 格的水深中位 = 68/114/128 WE</b> —— <b>岸边是一条缓坡浅滩</b>，不是一步踩到底。<br>我们旧行为是「一步到 128 的平底」，岸线因此是一道 <b>169 WE 的硬台阶</b>（陆 +41 → 水 −128），看着像被刀切的浴缸边。<br><b>0 = 关掉</b>（回到一步到底）">岸线缓坡宽度（水从岸边加深要走几格） <span id="swV">3</span> 格<span class="q">?</span></label>
      <input id="shoreWidth" type="range" min="0" max="10" step="1" value="3">
      <label class="tip" data-tip="<span class='tt'>岸线浅滩深度</span>紧贴岸那一排水底的目标深度（WE）。<br><b>0 = 自动取「水底深度下限」的 53%</b>（128 → <b>68</b>，正是官方实测的离岸第 1 格中位）。<br>调小 → 岸边更浅更缓；调大 → 更接近一步到底。必须小于「水底深度下限」。<br>⚠️ 这一段会被 WE 画成<b>浅水</b>（颜色更亮），官方有水的图约 <b>41%</b> 的水角点都在这个范围内">岸线浅滩深度（0 = 自动 68） <span id="ssV2">0（自动）</span><span class="q">?</span></label>
      <input id="shoreShallow" type="range" min="0" max="120" step="4" value="0">
      <div class="hint" id="baseHint">选「按水域占比自动」时水面按占比反解，精确可控；
        选某个初始地面后水面恒为 0，水域占比由「初始地面 + 山脉抬升」自然决定（占比滑条失效）。
        振幅上限用软裁剪，不会把山顶切成平顶；官方实测能到 1536 WE。
        <strong>水底深度下限：WE 只在「地形低于水面 ≥ 1 个整层（128 WE）」时才画水面</strong>，
        更浅的水下地形会被当干地渲染（看着像陆地）→ 所有水角点都会被兜到这个深度以上；
        <strong>浅滩基底</strong>的水底就直接压平在这个深度（128 = 1 整层 = 引擎认的浅水）。
        超过它算深水，只影响日志与预览配色。
        <strong>岸线缓坡</strong>：官方 40 张有水的图实测「离岸 1/2/3 格水深中位 = 68/114/128 WE」
        —— 岸边是<b>缓坡浅滩</b>，第 3 格才到全深；我们旧行为是一步到 128 的平底，
        岸线会变成一道 169 WE 的硬台阶（像浴缸边）。勾掉（宽度调 0）就回到旧行为。</div>
    </div>

    <div class="panel">
      <h2>第 2 步 · 悬崖（可选）</h2>
      <div class="chk"><input type="checkbox" id="cliffs">
        <label for="cliffs" style="margin:0"
          title="只在几小块区域里生成台地 + 崖壁；其余地面照旧连续起伏。不勾 = 全图零悬崖、近战单位处处可走">生成悬崖（<strong>只在几小块区域</strong>里生成台地 + 崖壁；
          其余地面照旧连续起伏，不勾 = 全图零悬崖）</label></div>
      <div id="cliffBody">
      <div class="sub2">悬崖区形状</div>
      <label class="tip" data-tip="<span class='tt'>悬崖区占陆地的比例</span>有多少比例的陆地会被抬成带崖壁的台地。<br>越小越像「点缀」；越大越像高原。">悬崖区占陆地的比例 <span id="caV">15%</span><span class="q">?</span></label>
      <input id="cliffArea" type="range" min="0.02" max="0.6" step="0.01" value="0.15">
      <label class="tip" data-tip="<span class='tt'>悬崖区团块尺寸</span>每块悬崖区的尺寸（格）。<br>越大台地越成片；越小越零散。">悬崖区团块尺寸（格） <span id="czV">26</span><span class="q">?</span></label>
      <input id="cliffSize" type="range" min="8" max="80" step="2" value="26">
      <label class="tip" data-tip="<span class='tt'>最高抬几层</span>台地比水面最多高几层（1 层 = 128 WE 的一个台阶）。<br>最终还受「最高层」限制。">最高抬几层（1 层 = 128 WE 的一个台阶） <span id="clV">3</span><span class="q">?</span></label>
      <input id="cliffLayers" type="range" min="1" max="6" step="1" value="3">
      <label class="tip" data-tip="<span class='tt'>外围羽化宽度</span>崖壁脚下一圈<b>平地</b>的宽度（格）。<br>太窄会让崖壁直接贴着水面或别的崖壁，WE 里容易看到错乱的崖面。">外围羽化宽度（格，崖壁脚下的一圈平地） <span id="cfV">4</span><span class="q">?</span></label>
      <input id="cliffFeather" type="range" min="1" max="12" step="1" value="4">
      <div class="hint">低频场挑出几大块区域做层量化 → 台地拔地而起，外围一圈羽化平整，
        落差严格等于 128 × 层差（WE 才不会渲出错乱崖壁）。台地最高受「最高层」限制。
        区域越靠水越不会被选中（台地不下水）。</div>

      <div class="sub2">悬崖区内的层与斜坡</div>
      <div class="row">
        <div>
          <label class="tip" data-tip="<span class='tt'>水面所在层</span>水面与普通地面所在的层号。<br>WE = (层号-2)×128，一般保持 <b>2</b>。">水面所在层（最低层）<span class="q">?</span></label>
          <input id="layerMin" type="number" min="1" max="13" step="1" value="2">
        </div>
        <div>
          <label class="tip" data-tip="<span class='tt'>最高层</span>台地最高能到第几层 = 限制悬崖高度。<br>不能超过 14（再高 WE 会崩）。">最高层（限制台地高度）<span class="q">?</span></label>
          <input id="layerMax" type="number" min="2" max="14" step="1" value="5">
        </div>
      </div>
      <div class="hint" id="layerHint"></div>
      <label class="tip" data-tip="<span class='tt'>斜坡</span><b>auto</b> = 按连通性自动刻斜坡（推荐）—— 保证每座岛内部都走得通。<br><b>0</b> = 不刻（台地之间的崖壁会彻底切断通行）。<br>刻出来的坡面高度会逐角点复制两侧台地的地面，<b>不会凹陷成沟</b>。">斜坡<span class="q">?</span></label>
      <select id="ramps">
        <option value="auto" selected>auto — 按连通性自动刻（推荐）</option>
        <option value="0">0 — 不刻斜坡</option>
      </select>
      <div class="chk"><input type="checkbox" id="rampForce" checked>
        <label for="rampForce" style="margin:0"
          title="找不到合适的垂直崖壁开坡时，就地整形硬刻一条出来，保证连通性">找不到齐整崖段时就地整形也要刻出来</label></div>
      <div class="hint">深浅水只靠 groundHeight 的落差表达、<strong>不换 layer</strong>
        （换 layer 会在水下多出崖壁，浅水处还可能露出来）；水色深浅由引擎按实际深度渲染。
        不勾悬崖时这一整栏无效</div>
      </div>
    </div>

    <div class="panel">
      <h2>第 3 步 · 树木（可选）</h2>
      <div class="chk"><input type="checkbox" id="trees" checked>
        <label for="trees" style="margin:0"
          title="大林 + 小林丛 + 散株三层播种，模仿官方对战图的自然林观感。不勾 = 完全不撒树">撒树（大林 + 小林丛 + 散株，天然林观感）</label></div>
      <div id="treeBody">
      <div class="hint" style="margin:0 0 8px">撒树复刻了 <strong>43 张官方 1.27a 对战图</strong>的实测结构：
        中位密度 <strong>12%</strong>、连片块数/树数 <strong>0.092</strong>、最大连片块 <strong>205 格</strong>、
        约 1/3 的树在 ≥100 格的大林里、一半的「块」是孤立单株。</div>
      <label class="tip" data-tip="<span class='tt'>总体密度</span>树占可种格子的比例。<br>官方 1.27a 对战图实测 <b>8%~19%（中位 12%）</b>。<br>调太高会密不透风，调太低就没有林地资源。">总体密度 <span id="dnV">18%</span><span class="q">?</span></label>
      <input id="density" type="range" min="0.02" max="0.4" step="0.01" value="0.18">
      <label class="tip" data-tip="<span class='tt'>大林占比（骨架）</span>多少比例的树交给<b>大块成片林</b>。<br>官方图里约 <b>1/3</b> 的树在 ≥100 格的大林里。<br>调大 → 更成片；<b>0 = 全打散成小丛</b>。">大林占比（成片林的骨架） <span id="fs2V">32%</span><span class="q">?</span></label>
      <input id="forestShare" type="range" min="0" max="0.8" step="0.05" value="0.32">
      <label class="tip" data-tip="<span class='tt'>大林尺寸</span>单块大林的<b>中位面积</b>（格）。<br>官方最大连片块中位约 <b>205 格</b>。调大会出现更大的森林。">大林尺寸（格，中位） <span id="fzV">170</span><span class="q">?</span></label>
      <input id="forestSize" type="range" min="60" max="500" step="10" value="170">
      <label class="tip" data-tip="<span class='tt'>每丛株数（中位）</span>小林丛的中位株数。<br>实际株数按<b>对数正态抖动</b>：多数 4~15 株，偶尔出现几十株的。<br>调大 → 块更大、块数更少。">每丛株数（中位） <span id="csV">11</span><span class="q">?</span></label>
      <input id="clumpSize" type="range" min="3" max="60" step="1" value="11">
      <label class="tip" data-tip="<span class='tt'>丛半径</span><b>中位丛</b>的半径（格）。<br>更大的丛半径按 sqrt(株数) 等比放大，所以各尺寸的丛疏密一致。">丛半径（格） <span id="crV">3.0</span><span class="q">?</span></label>
      <input id="clumpRadius" type="range" min="1.5" max="10" step="0.5" value="3">
      <label class="tip" data-tip="<span class='tt'>丛间距</span>丛与丛之间留出的<b>最小空隙</b>（格）。<br>调小 → 丛会粘成一大片；调大 → 一颗颗孤立，斑点感变强。">丛间距（格，丛与丛之间的空地） <span id="cgV">1.5</span><span class="q">?</span></label>
      <input id="clumpGap" type="range" min="0" max="6" step="0.5" value="1.5">
      <label class="tip" data-tip="<span class='tt'>丛林偏好</span>丛心有多偏向<b>森林场高</b>的地方。<br><b>0</b> = 全图均匀撒；<b>1</b> = 只长在森林场最高处（更集中成片）。">丛林偏好（丛心偏往森林区的程度） <span id="cbV">0.55</span><span class="q">?</span></label>
      <input id="clumpBias" type="range" min="0" max="1" step="0.05" value="0.55">
      <label class="tip" data-tip="<span class='tt'>丛外散树</span>不在丛里的<b>零星树</b>占全部树的比例。<br>会优先落在森林场低的空旷地（空旷的原野上零散几棵，像真地图）。<br>⚠️ 这些树也会<b>成小团</b>撒（见下一条），不是一粒一粒。">丛外散树 <span id="scV">3.5%</span><span class="q">?</span></label>
      <input id="scatter" type="range" min="0" max="0.15" step="0.005" value="0.035">
      <label class="tip" data-tip="<span class='tt'>散树每团株数</span>「丛外散树」每团<b>中位几株</b>（在对数正态上抖动）。<br>这些树挤在一个 3×3 窗口里，所以必然互相贴着。<br>官方实测：<b>2 格内连一棵邻树都没有的树只占 0.1%</b>；<br>调到 <b>1</b> 就退化成「一粒一粒单独撒」，0.1% 会飙到 1.8%，<br>满地图都是胡椒点 —— 这正是「树像斑点一样分散」的根源。">散树每团株数（成团程度） <span id="ssV">1.5</span><span class="q">?</span></label>
      <input id="scatterSize" type="range" min="1" max="8" step="0.5" value="1.5">
      <label class="tip" data-tip="<span class='tt'>边界林带</span>官方对战图的树<b>大半贴在「地图边 / 岸线 / 崖脚」</b>形成粗林带，内部才是零散小簇。<br>这个值越高越集中在边界成带；<b>0</b> = 完全靠森林场（容易变成全图均匀斑点）。">边界林带（贴边成带的强度） <span id="efV">55%</span><span class="q">?</span></label>
      <input id="edgeForest" type="range" min="0" max="1" step="0.05" value="0.55">
      <label class="tip" data-tip="<span class='tt'>边界林带宽度</span>林带从边界往里延伸多宽（格）。<br>越大 → 边缘那圈森林越厚。">边界林带宽度（格） <span id="ebV">14</span><span class="q">?</span></label>
      <input id="edgeBand" type="range" min="4" max="40" step="1" value="14">
      </div>
    </div>
  </div>

  <!-- 右：结果 -->
  <div>
    <div class="panel">
      <button id="go">一键生成地图</button>
      <div class="hint" id="statusHint" style="margin-top:8px"></div>
    </div>
    <div class="panel">
      <h2>结果</h2>
      <div class="badges" id="badges"><span class="badge">还没有生成</span></div>
      <div class="shots">
        <div class="shot" id="shotT"><span class="cap">地形预览（红=高地 黄=斜坡 蓝=水）</span></div>
        <div class="shot" id="shotR"><span class="cap">树丛预览</span></div>
      </div>
      <div class="row" style="margin-top:12px">
        <div><button class="ghost" id="btnFolder" style="width:100%">打开输出目录</button></div>
        <div><button class="ghost" id="btnLocate" style="width:100%">在资源管理器中定位地图</button></div>
      </div>
    </div>
    <div class="panel">
      <h2>生成日志</h2>
      <pre id="log">等待生成…</pre>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let templates = [], currentOut = null, lastJob = null, timer = null;

const sliders = [
  ["uplift","upV",v=>v],
  ["ridge","rdV",v=>v.toFixed(2)],
  ["warp","wpV",v=>v],
  ["water","wtV",v=>Math.round(v*100)+"%"],
  ["maxRelief","mrV",v=>v],
  ["shelfDepth","sdV",v=>v],
  ["cliffArea","caV",v=>Math.round(v*100)+"%"],
  ["cliffSize","czV",v=>v],
  ["cliffLayers","clV",v=>v],
  ["cliffFeather","cfV",v=>v],
  ["raise","raV",v=>v],
  ["lower","loV",v=>v],
  ["rough","rgV",v=>v],
  ["blob","blV",v=>v],
  ["grain","grV",v=>v.toFixed(1)],
  ["ledge","lgV",v=>v],
  ["flat","flV",v=>Math.round(v*100)+"%"],
  ["flatSize","fsV",v=>v],
  ["waterRelief","wrV",v=>v.toFixed(2)],
  ["shoreWidth","swV",v=>v],
  ["shoreShallow","ssV2",v=>(+v>0? v : "0（自动）")],
  ["density","dnV",v=>Math.round(v*100)+"%"],
  ["forestShare","fs2V",v=>Math.round(v*100)+"%"],
  ["forestSize","fzV",v=>v],
  ["clumpSize","csV",v=>v],
  ["clumpRadius","crV",v=>v.toFixed(1)],
  ["clumpGap","cgV",v=>v.toFixed(1)],
  ["clumpBias","cbV",v=>v.toFixed(2)],
  ["scatter","scV",v=>(v*100).toFixed(1)+"%"],
  ["scatterSize","ssV",v=>v.toFixed(1)],
  ["edgeForest","efV",v=>Math.round(v*100)+"%"],
  ["edgeBand","ebV",v=>v],
];
sliders.forEach(([id,out,f])=>{
  const el=$(id);
  const upd=()=>$(out).textContent=f(parseFloat(el.value));
  el.addEventListener("input",upd); upd();
});

// ---- 参数说明浮层：鼠标移到参数名（带 data-tip）上就弹出它影响什么 ----
const TIP = document.createElement("div");
TIP.id = "tipbox";
document.body.appendChild(TIP);
function hideTip(){ TIP.style.display = "none"; }
function placeTip(x, y){
  const pad = 16, w = TIP.offsetWidth, h = TIP.offsetHeight;
  let L = x + pad, T = y + pad;
  if (L + w > innerWidth - 8)  L = Math.max(8, x - w - pad);
  if (T + h > innerHeight - 8) T = Math.max(8, y - h - pad);
  TIP.style.left = L + "px";
  TIP.style.top = T + "px";
}
document.addEventListener("mouseover", e=>{
  const el = e.target.closest ? e.target.closest("[data-tip]") : null;
  if (!el){ hideTip(); return; }
  TIP.innerHTML = el.getAttribute("data-tip");
  TIP.style.display = "block";
  placeTip(e.clientX, e.clientY);
});
document.addEventListener("mousemove", e=>{
  if (TIP.style.display === "block") placeTip(e.clientX, e.clientY);
});
document.addEventListener("mouseout", e=>{
  const el = e.target.closest ? e.target.closest("[data-tip]") : null;
  if (el) hideTip();
});
window.addEventListener("scroll", hideTip, true);

function syncMode(){
  const base=$("base").value, mnt=$("mountain").value, cl=$("cliffs").checked;
  $("water").disabled = base!=="auto";
  $("ridgeRow").style.display = mnt==="ridged" ? "" : "none";
  $("warpRow").style.display = mnt==="warped" ? "" : "none";
  document.querySelectorAll("#cliffBody input,#cliffBody select")
    .forEach(e=>e.disabled=!cl);
  document.querySelectorAll("#treeBody input,#treeBody select")
    .forEach(e=>e.disabled=!$("trees").checked);
  const BASE_TXT = {
    auto:"水面按占比反解，精确可控；换一个初始地面则水面恒为 0，水域占比由「初始地面 + 山脉抬升」自然决定",
    land:"<b>纯陆地</b>：整块地形抬到水面之上 → <b>一滴水都没有</b>（占比滑条失效）",
    shallow:"<b>浅滩</b>：水底整片压平到「水底深度下限」（默认 128 WE = 1 整层）→ <b>没有深水</b>，水浅到能直接走过去（占比滑条失效）",
    deep:"<b>深水</b>：正常水域，深浅水都有；-384 WE 很低，只有山脊露出水面 → 群岛 / 大湖（占比滑条失效）",
  };
  $("baseHint").innerHTML = BASE_TXT[base] || BASE_TXT.auto;
}
["base","mountain","cliffs","trees"].forEach(id=>$(id).addEventListener("input",syncMode));
syncMode();

function layerInfo(){
  const a=parseInt($("layerMin").value||"2"), b=parseInt($("layerMax").value||"5");
  const n=b-a+1;
  if(!(b>a)){ $("layerHint").innerHTML='<b style="color:var(--bad)">最高层必须大于最低层</b>'; return; }
  if(b>14){ $("layerHint").innerHTML='<b style="color:var(--bad)">最高层不能超过 14</b>'; return; }
  $("layerHint").innerHTML =
    `水面与普通地面都在第 <b>${a}</b> 层（WE ${(a-2)*128}）；悬崖区最高抬到第 <b>${b}</b> 层`+
    `（WE ${(b-2)*128}），最多 <b>${n-1}</b> 级台阶、每级 128`;
}
["layerMin","layerMax"].forEach(id=>$(id).addEventListener("input",layerInfo));

async function boot(){
  const s = await (await fetch("/api/state")).json();
  templates = s.templates;
  const sel=$("template");
  sel.innerHTML = templates.map((t,i)=>
    `<option value="${t.path}">${t.name}${t.note?"  —  "+t.note:""}</option>`).join("");
  const show=()=>{ const t=templates[sel.selectedIndex];
    $("tplHint").textContent = t? `${t.dir} / ${t.path}　${(t.size/1024).toFixed(0)} KB` : ""; };
  sel.addEventListener("change",show); show();
  layerInfo();
}
boot();

function rollSeed(){ $("seed").value = Math.floor(Math.random()*999999); }

function setBusy(b){
  $("go").disabled=b;
  $("go").textContent = b ? "生成中…" : "一键生成地图";
  $("statusHint").innerHTML = b ? '<span class="spin"></span> 正在跑随机地形 → 刻斜坡 → 撒树…' : "";
}

function params(){
  return {
    template:$("template").value,
    outname:$("outname").value,
    seed:$("seed").value,
    random_seed:$("randSeed").checked,
    // 第 1 步
    base:$("base").value,
    mountain:$("mountain").value,
    uplift:+$("uplift").value,
    ridge:+$("ridge").value,
    warp:+$("warp").value,
    water:+$("water").value,
    max_relief:+$("maxRelief").value,
    shelf_depth:+$("shelfDepth").value,
    // 第 2 步
    cliffs:$("cliffs").checked?1:0,
    cliff_area:+$("cliffArea").value,
    cliff_size:+$("cliffSize").value,
    cliff_layers:+$("cliffLayers").value,
    cliff_feather:+$("cliffFeather").value,
    layer_min:+$("layerMin").value, layer_max:+$("layerMax").value,
    ramps:$("ramps").value,
    ramp_force:$("rampForce").checked?1:0,
    water_relief:+$("waterRelief").value,
    shore_width:+$("shoreWidth").value,
    shore_shallow:+$("shoreShallow").value,
    boundary:$("boundary").value,
    // 地表起伏
    raise:+$("raise").value,
    lower:+$("lower").value,
    rough:+$("rough").value,
    blob:+$("blob").value,
    grain:+$("grain").value,
    ledge:+$("ledge").value,
    flat:+$("flat").value,
    flat_size:+$("flatSize").value,
    // 第 3 步
    trees:$("trees").checked?1:0,
    density:+$("density").value,
    forest_share:+$("forestShare").value,
    forest_size:+$("forestSize").value,
    clump_size:+$("clumpSize").value,
    clump_radius:+$("clumpRadius").value,
    clump_gap:+$("clumpGap").value,
    scatter_size:+$("scatterSize").value,
    clump_bias:+$("clumpBias").value,
    scatter:+$("scatter").value,
    edge_forest:+$("edgeForest").value,
    edge_band:+$("edgeBand").value,
  };
}

async function gen(){
  setBusy(true);
  $("log").textContent = "";
  $("badges").innerHTML = '<span class="badge">生成中…</span>';
  const r = await (await fetch("/api/generate",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify(params())})).json();
  lastJob = r.job;
  clearInterval(timer);
  timer = setInterval(()=>poll(r.job), 400);
}
$("go").onclick = gen;

async function poll(id){
  const j = await (await fetch("/api/job?id="+id)).json();
  if(j.log) $("log").textContent = j.log.join("\n");
  $("log").scrollTop = $("log").scrollHeight;
  if(j.status === "running") return;
  clearInterval(timer); setBusy(false);
  if(j.status === "error"){
    $("badges").innerHTML = `<span class="badge bad">失败：${j.error||"未知错误"}</span>`;
    return;
  }
  const R = j.result || {};
  currentOut = R.out_abs || null;
  const b = [];
  if(R.conn === "ok") b.push('<span class="badge ok">连通性 ✔ 每座岛都走得通</span>');
  else if(R.conn === "bad") b.push('<span class="badge bad">连通性 ✘ 有岛被崖壁切断</span>');
  if(R.mode) b.push(`<span class="badge">${R.mode}</span>`);
  if(R.layer) b.push(`<span class="badge">高度层 <b>${R.layer}</b></span>`);
  if(R.ramps !== undefined) b.push(`<span class="badge">斜坡 <b>${R.ramps}</b> 条</span>`);
  if(R.trees !== undefined) b.push(`<span class="badge">树 <b>${R.trees}</b> 棵</span>`);
  if(R.blob) b.push(`<span class="badge">${R.blob}</span>`);
  if(R.seed !== undefined) b.push(`<span class="badge">种子 <b>${R.seed}</b></span>`);
  $("badges").innerHTML = b.join("") || '<span class="badge">完成</span>';
  const shots = R.previews || [];
  $("shotT").innerHTML = shots[0]
    ? `<img src="/preview?p=${encodeURIComponent(shots[0])}&t=${Date.now()}"><span class="cap">地形预览（红=高地 黄=斜坡 蓝=水）</span>`
    : '<span class="cap">无地形预览</span>';
  $("shotR").innerHTML = shots[1]
    ? `<img src="/preview?p=${encodeURIComponent(shots[1])}&t=${Date.now()}"><span class="cap">树丛预览（绿色，块与块之间留了空地）</span>`
    : '<span class="cap">无树丛预览</span>';
}

async function openPath(p){
  await fetch("/api/open",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({path:p})});
}
$("btnFolder").onclick = async ()=>{
  const s = await (await fetch("/api/state")).json(); openPath(s.out_dir);
};
$("btnLocate").onclick = ()=> currentOut ? openPath(currentOut) : alert("先生成一张地图");
</script>
</body>
</html>
"""


def main():
    argv = sys.argv[1:]
    port = 8770
    open_browser = True
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        elif a == "--no-browser":
            open_browser = False

    os.makedirs(OUT_DIR, exist_ok=True)
    srv = None
    for p in range(port, port + 30):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        print("没有可用端口，尝试 --port 换一个起始端口")
        return 1

    url = f"http://127.0.0.1:{port}/"
    print(f"随机地图生成器界面已就绪: {url}")
    print("（关掉这个窗口就停止服务；生成的地图在 out/ 目录）")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
