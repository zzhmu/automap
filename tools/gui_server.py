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
    if "每座岛内部都走得通 ✔" in text:
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

        # 地形
        add("water", params.get("water", 0.30))
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
        add("shelf", params.get("shelf", 3))
        add("deep", params.get("deep", 1))
        add("water-relief", params.get("water_relief", 0.5))
        add("level-bias", params.get("level_bias", 2.0))
        add("freq", params.get("freq", 1.6))
        add("boundary", params.get("boundary", "ring"))
        add("ramps", params.get("ramps", "auto"))
        if str(params.get("ramp_force", 1)) in ("1", "true", "True"):
            add("ramp-force", 1)
        else:
            add("ramp-force", 0)
        # 树
        add("density", params.get("density", 0.35))
        add("clump-size", params.get("clump_size", 26))
        add("clump-radius", params.get("clump_radius", 4.5))
        add("clump-gap", params.get("clump_gap", 2.1))
        add("clump-bias", params.get("clump_bias", 0.55))
        add("scatter", params.get("scatter", 0.015))

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
</style>
</head>
<body>
<header>
  <h1>魔兽随机地图生成器</h1>
  <span class="sub">模板 → 随机地形 + 悬崖 + 斜坡 + 树丛 → .w3x（WE 可直接打开）</span>
</header>

<div class="wrap">
  <!-- 左：参数 -->
  <div>
    <div class="panel">
      <h2>模板与输出</h2>
      <label>模板地图</label>
      <select id="template"></select>
      <div class="hint" id="tplHint"></div>
      <label>输出文件名</label>
      <input id="outname" placeholder="留空 = rand_&lt;种子&gt;.w3x">
      <div class="row">
        <div>
          <label>随机种子</label>
          <input id="seed" type="number" value="20260915">
        </div>
        <div style="flex:0 0 92px;display:flex;align-items:flex-end">
          <button class="ghost" style="width:100%" onclick="rollSeed()">换一个</button>
        </div>
      </div>
      <div class="chk"><input type="checkbox" id="randSeed"><label for="randSeed" style="margin:0">
        每次生成都用随机种子</label></div>
    </div>

    <div class="panel">
      <h2>悬崖高度范围</h2>
      <div class="row">
        <div>
          <label>最低层</label>
          <input id="layerMin" type="number" min="1" max="13" step="1" value="2">
        </div>
        <div>
          <label>最高层</label>
          <input id="layerMax" type="number" min="2" max="14" step="1" value="5">
        </div>
      </div>
      <div class="hint" id="layerHint"></div>
      <label>台地分布偏置 <span id="lbV">2.0</span></label>
      <input id="levelBias" type="range" min="0.6" max="5" step="0.1" value="2.0">
      <div class="hint">1 = 各层地面积均等（马赛克感）；越大越低平，越像真地图</div>
    </div>

    <div class="panel">
      <h2>应用高度</h2>
      <label>隆起（地面向上鼓包） <span id="raV">75</span></label>
      <input id="raise" type="range" min="0" max="120" step="5" value="75">
      <label>凹陷（地面向下凹坑） <span id="loV">75</span></label>
      <input id="lower" type="range" min="0" max="120" step="5" value="75">
      <label>凹凸不平（表面颗粒感） <span id="rgV">12</span></label>
      <input id="rough" type="range" min="0" max="60" step="2" value="12">
      <label>起伏团块尺寸（格） <span id="blV">28</span></label>
      <input id="blob" type="range" min="8" max="80" step="2" value="28">
      <label>颗粒尺寸（格） <span id="grV">2.5</span></label>
      <input id="grain" type="range" min="1.5" max="12" step="0.5" value="2.5">
      <label>台阶高度（0 = 连续起伏） <span id="lgV">0</span></label>
      <input id="ledge" type="range" min="0" max="90" step="5" value="0">
      <label>平整区域占比（完全没有起伏的地面） <span id="flV">15%</span></label>
      <input id="flat" type="range" min="0" max="0.6" step="0.01" value="0.15">
      <label>平整区域团块尺寸（格） <span id="fsV">20</span></label>
      <input id="flatSize" type="range" min="6" max="60" step="1" value="20">
      <div class="hint">幅度单位 = WE 高度条上的格数（一整层 = 128），三个幅度全调 0 就是一块大平地。
        官方对战图参考：隆起/凹陷 ≈ 70，凹凸不平 ≈ 10（噪波笔刷本身很轻），
        相邻角点有 36%~64% 完全等高 —— 那是「台阶」的效果，调大它就能复现。<br>
        平整区域 = 把隆起/凹陷整体压平的一块块地（建基地、摆建筑用），占比按陆地面积算</div>
    </div>

    <div class="panel">
      <h2>水域与斜坡</h2>
      <label>水域占比 <span id="wtV">30%</span></label>
      <input id="water" type="range" min="0" max="0.7" step="0.01" value="0.30">
      <label>浅水岸带宽度（格） <span id="shV">3</span></label>
      <input id="shelf" type="range" min="0" max="12" step="0.5" value="3">
      <label>深水再深几层 <span id="dpV">1</span></label>
      <input id="deep" type="range" min="0" max="4" step="1" value="1">
      <label>水下起伏（× 陆地起伏） <span id="wrV">0.50</span></label>
      <input id="waterRelief" type="range" min="0" max="1.5" step="0.05" value="0.5">
      <div class="hint">水面 = 最低陆地层的顶面。浅水是贴着岸的一圈（离岸 ≤ 岸带宽度），
        之外自动降到深水；水下照常按陆地起伏成比例起伏，但会被裁到永不冒出水面。
        深水调 0 = 全图只有一种水深</div>
      <label>地图边界标记</label>
      <select id="boundary">
        <option value="ring" selected>ring — 只留最外一圈（整张可玩）</option>
        <option value="none">none — 全清</option>
        <option value="keep">keep — 沿用模板边框</option>
      </select>
      <label>斜坡</label>
      <select id="ramps">
        <option value="auto" selected>auto — 按连通性自动刻</option>
        <option value="0">0 — 不刻斜坡</option>
      </select>
      <div class="chk"><input type="checkbox" id="rampForce" checked>
        <label for="rampForce" style="margin:0">找不到齐整崖段时就地整形也要刻出来</label></div>
    </div>

    <div class="panel">
      <h2>树木分布</h2>
      <label>总体密度 <span id="dnV">35%</span></label>
      <input id="density" type="range" min="0.05" max="0.6" step="0.01" value="0.35">
      <label>每丛株数 <span id="csV">26</span></label>
      <input id="clumpSize" type="range" min="4" max="90" step="1" value="26">
      <label>丛半径（格） <span id="crV">4.5</span></label>
      <input id="clumpRadius" type="range" min="1.5" max="12" step="0.5" value="4.5">
      <label>丛间距（× 半径） <span id="cgV">2.1</span></label>
      <input id="clumpGap" type="range" min="1" max="5" step="0.1" value="2.1">
      <label>丛林偏好（丛心偏往森林区的程度） <span id="cbV">0.55</span></label>
      <input id="clumpBias" type="range" min="0" max="1" step="0.05" value="0.55">
      <label>丛外散树 <span id="scV">1.5%</span></label>
      <input id="scatter" type="range" min="0" max="0.08" step="0.005" value="0.015">
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
  ["levelBias","lbV",v=>v.toFixed(1)],
  ["raise","raV",v=>v],
  ["lower","loV",v=>v],
  ["rough","rgV",v=>v],
  ["blob","blV",v=>v],
  ["grain","grV",v=>v.toFixed(1)],
  ["ledge","lgV",v=>v],
  ["flat","flV",v=>Math.round(v*100)+"%"],
  ["flatSize","fsV",v=>v],
  ["water","wtV",v=>Math.round(v*100)+"%"],
  ["shelf","shV",v=>v.toFixed(1).replace(/\.0$/,"")],
  ["deep","dpV",v=>v],
  ["waterRelief","wrV",v=>v.toFixed(2)],
  ["density","dnV",v=>Math.round(v*100)+"%"],
  ["clumpSize","csV",v=>v],
  ["clumpRadius","crV",v=>v],
  ["clumpGap","cgV",v=>v.toFixed(1)],
  ["clumpBias","cbV",v=>v.toFixed(2)],
  ["scatter","scV",v=>(v*100).toFixed(1)+"%"],
];
sliders.forEach(([id,out,f])=>{
  const el=$(id);
  const upd=()=>$(out).textContent=f(parseFloat(el.value));
  el.addEventListener("input",upd); upd();
});

function layerInfo(){
  const a=parseInt($("layerMin").value||"2"), b=parseInt($("layerMax").value||"5");
  const n=b-a+1;
  if(!(b>a)){ $("layerHint").innerHTML='<b style="color:var(--bad)">最高层必须大于最低层</b>'; return; }
  if(b>14){ $("layerHint").innerHTML='<b style="color:var(--bad)">最高层不能超过 14</b>'; return; }
  $("layerHint").innerHTML =
    `共 <b>${n}</b> 级台阶，WE 高度 <b>${(a-2)*128}</b> ~ <b>${(b-2)*128}</b>`+
    `　（每级 128，水面自动落在第 ${a-1} 层）`;
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
    layer_min:+$("layerMin").value, layer_max:+$("layerMax").value,
    level_bias:+$("levelBias").value,
    raise:+$("raise").value,
    lower:+$("lower").value,
    rough:+$("rough").value,
    blob:+$("blob").value,
    grain:+$("grain").value,
    ledge:+$("ledge").value,
    flat:+$("flat").value,
    flat_size:+$("flatSize").value,
    water:+$("water").value,
    shelf:+$("shelf").value,
    deep:+$("deep").value,
    water_relief:+$("waterRelief").value,
    boundary:$("boundary").value,
    ramps:$("ramps").value,
    ramp_force:$("rampForce").checked?1:0,
    density:+$("density").value,
    clump_size:+$("clumpSize").value,
    clump_radius:+$("clumpRadius").value,
    clump_gap:+$("clumpGap").value,
    clump_bias:+$("clumpBias").value,
    scatter:+$("scatter").value,
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
