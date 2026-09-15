# -*- coding: utf-8 -*-
"""一键生成随机魔兽地图：随机地形（高度/悬崖/水） + 算法撒树 → 可直接用 WE 打开。

用法:
  python random_map.py --template <模板地图> --out <输出地图> [选项]
示例:
  python random_map.py --template "..\\..\\Maps\\(2)Harrow.w3m" \\
      --out ../generated_random/random_42.w3x --seed 42 --water 0.28 --density 0.35

参数全部透传给两个子步骤:
  --seed / --freq / --layers / --layer-min / --layer-max / --octaves / --smooth / --level-bias
  --water / --ramps / --ramp-run / --ramp-force / --max-jump
  --raise / --lower / --rough / --blob / --grain / --ledge   → 应用高度
  --flat / --flat-size                                  → 平整区域
  --shelf / --deep / --water-relief                     → 浅水 / 深水 / 水下起伏
  --min-plateau / --min-island / --min-lake / --boundary   → gen_height.py
  --density / --clump-size / --clump-radius / --clump-gap / --scatter / --clump-bias
  --tree-id / --slope-tol                              → add_doodads.py
  --exe（可选，默认自动定位 ../bin/MPQEditor.exe） / --preview-prefix
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# 两个子步骤一律按 UTF-8 输出（它们自己也会强制），这里再把环境钉死，
# 免得继承到 cp936 之类的区域设置又出编码问题。
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def force_utf8_stdout():
    """管道/重定向时标准输出统一 UTF-8，控制台保留原编码。理由同 gen_height.py。"""
    for s in (sys.stdout, sys.stderr):
        try:
            if s.isatty():
                s.reconfigure(errors="replace")
            else:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


force_utf8_stdout()


def run_child(cmd, timeout=600):
    """跑一个子步骤并把它的输出原样转出来，返回退出码。

    必须显式写 encoding：text=True 不指定编码时，Python 按系统区域设置解码
    （中文 Windows = cp936），而子步骤是按 UTF-8 输出中文的。
    解码失败还会发生在 subprocess 的读取线程里 → r.stdout 变成 None →
    后面 strip() 抛 AttributeError，报错信息完全指不到真正的原因。
    """
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=CHILD_ENV, timeout=timeout)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if out:
        print(out)
    if r.returncode and err:
        print(err)
    return r.returncode


def parse_opts(argv):
    args, opts, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k, sep, v = a[2:].partition("=")
            if sep:
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]; i += 1
            else:
                opts[k] = True
        else:
            args.append(a)
        i += 1
    return args, opts


def main():
    args, opts = parse_opts(sys.argv[1:])
    template = opts.get("template")
    out = opts.get("out")
    if not template or not out:
        print(__doc__)
        return 1
    exe = opts.get("exe")
    exe_args = ["--exe", exe] if exe else []
    seed = str(opts.get("seed", 20260915))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    shutil.copy2(template, out)
    print(f"[1/2] 随机地形 ← {os.path.basename(template)}")
    prefix = opts.get("preview-prefix", os.path.splitext(out)[0])

    height_cmd = [PY, os.path.join(HERE, "gen_height.py"), out] + exe_args + [
                  "--no-backup",
                  "--seed", seed,
                  "--water", str(opts.get("water", 0.30)),
                  "--freq", str(opts.get("freq", 1.6)),
                  "--layers", str(opts.get("layers", 4)),
                  "--layer-min", str(opts.get("layer-min", 2)),
                  "--octaves", str(opts.get("octaves", 2)),
                  "--smooth", str(opts.get("smooth", 2)),
                  "--level-bias", str(opts.get("level-bias", 2.0)),
                  "--raise", str(opts.get("raise", 75)),
                  "--lower", str(opts.get("lower", 75)),
                  "--rough", str(opts.get("rough", 12)),
                  "--blob", str(opts.get("blob", 28)),
                  "--grain", str(opts.get("grain", 2.5)),
                  "--ledge", str(opts.get("ledge", 0)),
                  "--flat", str(opts.get("flat", 0.15)),
                  "--flat-size", str(opts.get("flat-size", 20)),
                  "--shelf", str(opts.get("shelf", 3)),
                  "--deep", str(opts.get("deep", 1)),
                  "--water-relief", str(opts.get("water-relief", 0.5)),
                  "--ramps", str(opts.get("ramps", "auto")),
                  "--ramp-run", str(opts.get("ramp-run", 4)),
                  "--ramp-force", str(opts.get("ramp-force", 1)),
                  "--cliff-texture", str(opts.get("cliff-texture", "auto")),
                  "--max-jump", str(opts.get("max-jump", 2)),
                  "--min-plateau", str(opts.get("min-plateau", 0)),
                  "--min-island", str(opts.get("min-island", 32)),
                  "--min-lake", str(opts.get("min-lake", 16)),
                  "--boundary", str(opts.get("boundary", "ring")),
                  "--preview", prefix + "_terrain.png"]
    if opts.get("layer-max") is not None:
        height_cmd += ["--layer-max", str(opts["layer-max"])]
    rc = run_child(height_cmd)
    if rc:
        return rc

    print("[2/2] 撒树")
    tree_cmd = [PY, os.path.join(HERE, "add_doodads.py"), out] + exe_args + [
                "--no-backup",
                "--seed", seed,
                "--density", str(opts.get("density", 0.35)),
                "--clump-size", str(opts.get("clump-size", 26)),
                "--clump-radius", str(opts.get("clump-radius", 4.5)),
                "--clump-gap", str(opts.get("clump-gap", 2.1)),
                "--clump-bias", str(opts.get("clump-bias", 0.55)),
                "--scatter", str(opts.get("scatter", 0.015)),
                "--freq", str(opts.get("tree-freq", 3.0)),
                "--slope-tol", str(opts.get("slope-tol", 1)),
                "--preview", prefix + "_trees.png"]
    if opts.get("tree-id"):
        tree_cmd += ["--tree-id", str(opts["tree-id"])]
    rc = run_child(tree_cmd)
    if rc:
        return rc

    print(f"\n完成 → {out}")
    print(f"预览 → {prefix}_terrain.png / {prefix}_trees.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
