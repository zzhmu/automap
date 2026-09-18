# -*- coding: utf-8 -*-
"""一键生成随机魔兽地图：随机地形（高度/悬崖/水） + 算法撒树 → 可直接用 WE 打开。

用法:
  python random_map.py --template <模板地图> --out <输出地图> [选项]
示例:
  python random_map.py --template "..\\..\\Maps\\(2)Harrow.w3m" \\
      --out ../generated_random/random_42.w3x --seed 42 --water 0.28 --density 0.18

三步式生成（新增，详见 doc/三步地形生成方案.md）:
  --cliffs 0           0 = 不生成悬崖（默认，单层连续，零悬崖）
                       1 = 只在几小块区域生成悬崖（台地 + 崖壁 + 斜坡），其余地方照旧连续
  --base deep|shallow|land   初始地面（相对水面的 WE 高度）；给了它 → 水面恒为 0，
                             水域占比由「初始地面 + 抬升」自然决定，不再受 --water 约束
                               deep    = 正常水域，深浅水都有
                               shallow = 浅滩：水底压平到 --shelf-depth（默认 128=1 整层），无深水
                               land    = 纯陆地：一滴水都没有
  --base-level -200    直接指定初始地面高度（WE），覆盖 --base
  --uplift 220         山脉抬升幅度（WE）
  --mountain fbm       山脉算法 fbm / ridged / warped
  --ridge 0.6 / --warp 8.0   ridged 的山脊锐度 / warped 的扭曲强度（格）
  --water-level -50    绝对水面（WE），给了就覆盖 --water
  --shelf-depth 128    水底深度下限（WE，<128 引擎不渲染水面）；也是深水判据
  --max-relief 512     相对水面高度的振幅上限（WE）
  --cliff-area 0.15 / --cliff-size 26 / --cliff-layers 3 / --cliff-feather 4 / --cliff-band 4
                       悬崖区的面积占比 / 团块尺寸 / 最高抬几层 / 外围羽化宽度
  --trees 0            0 = 不撒树（跳过 add_doodads 这一步）
  --buildings 0        0 = 不摆中立建筑（跳过 add_buildings 这一步）
  --style A,W,...      地图风格（tileset）：纹理/树/野怪池/雇佣兵营地跟随风格。
                       可多选（逗号分隔）→ 每次生成随机抽一种（一张图只能一种风格，
                       WE 格式决定）。可选：L 洛丹伦夏 W 洛丹伦冬 F 洛丹伦秋
                       A 灰谷 B 荒地 C 费尔伍德 N 诺森德 Y 城市。不给 = 跟随模板。
  --nb-<id> N          每种中立建筑的数量（0 = 不放）。可选的 id：
                         ngol 金矿(默认12) ngme 地精商店(2) ngad 地精实验室(1)
                         nmer 雇佣兵营地(1) nfoh 生命之泉(1) nmrk 市场(1) ntav 酒馆(1)
  --nb-min-dist 8      建筑之间的最小间距（格）
  --nb-edge 6          距地图边缘的最小格数
  --nb-flat-tol 1      建筑占地范围内的允许层差（0 = 必须完全同层）
  --nb-avoid-trees 1   建筑避开装饰物（树）
  --triggers 1         1 = 生成后注入触发器（改写 war3map.j，见 add_triggers.py）
  --msg "文本"          进图欢迎消息（配合 --msg-seconds 显示秒数，默认 8）
  --no-fog             关闭战争迷雾（全图可见）
  --revive-seconds N   英雄死亡 N 秒后自动在出生点复活
  --timed-msg "文本"    开局定时消息（--timed-msg-delay / --timed-msg-period / --timed-msg-times）
  --jass "代码"         注入自定义 Jass 顶层代码（或 --jass-file 文件；$VAR 占位符
                       用 --set-VAR 值 替换，可做参数化模板）
  --triggers-dir <dir> 触发器源码文件夹（默认 triggers/jass/，所有 .j 按文件名
                       排序拼接注入；none = 关闭文件夹注入）

参数全部透传给两个子步骤:
  --seed / --freq / --layers / --layer-min / --layer-max / --octaves / --smooth / --level-bias
  --water / --ramps / --ramp-run / --ramp-force / --max-jump
  --raise / --lower / --rough / --blob / --grain / --ledge   → 应用高度
  --flat / --flat-size                                  → 平整区域
  --water-relief / --height-step / --world-clamp         → 水体 / 量化 / 崩溃防护
  --min-plateau / --min-island / --min-lake / --boundary   → gen_height.py
  --density / --forest-share / --forest-size / --edge-forest / --edge-band
  --clump-size / --clump-radius / --clump-gap / --scatter / --scatter-size / --clump-bias / --tree-freq
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

sys.path.insert(0, HERE)
from tilesets import STYLES  # noqa: E402


def pick_style(opts, seed):
    """--style 支持多选（逗号分隔）：一张图只能一种风格 → 按种子随机抽一。

    同一 seed 下 main / run_buildings / run_creeps 各自调用都会抽到同一个值。
    """
    style = opts.get("style")
    if not style:
        return None
    import random as _random
    picks = [s.strip().upper() for s in str(style).split(",") if s.strip()]
    valid = [s for s in picks if s in STYLES]
    if not valid:
        print(f"⚠ 风格参数无效（{style}），忽略。可选：{','.join(STYLES)}")
        return None
    return _random.Random(int(seed)).choice(valid)


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


def run_triggers(opts, out, prefix, exe_args, seed):
    """第 5 步（可选）：触发器注入 —— 改写 war3map.j，给地图加游戏逻辑。"""
    if str(opts.get("triggers", "0")) in ("0", "false", "no"):
        return 0
    print("[5/5] 触发器")
    tg_cmd = [PY, os.path.join(HERE, "add_triggers.py"), out] + exe_args + ["--no-backup"]
    for k in ("msg", "msg-seconds", "timed-msg", "timed-msg-delay",
              "timed-msg-period", "timed-msg-times", "revive-seconds",
              "jass", "jass-file", "jass-dir"):
        v = opts.get(k)
        if v is not None:
            tg_cmd += ["--" + k, str(v)]
    for flag in ("no-fog", "leak-clean"):
        if str(opts.get(flag, "0")) not in ("0", "false", "no"):
            tg_cmd += ["--" + flag]
    return run_child(tg_cmd)


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
    chosen = pick_style(opts, int(seed))
    if chosen:
        print(f"地图风格: {STYLES[chosen]['name']}（{chosen}）"
              f"—— 纹理/树/野怪池/雇佣兵营地跟随该风格")
    print(f"[1/4] 随机地形 ← {os.path.basename(template)}")
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
                  "--water-relief", str(opts.get("water-relief", 0.5)),
                  "--height-step", str(opts.get("height-step", 4)),
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
    # 三步式生成：这几个参数给了才传，不给就用 gen_height 自己的默认
    for k, d in (("cliffs", "0"), ("uplift", 220), ("mountain", "fbm"),
                 ("ridge", 0.6), ("warp", 8.0), ("mountain-octaves", 4),
                 ("shelf-depth", 128), ("max-relief", 512), ("base", None),
                 ("base-level", None), ("water-level", None),
                 ("cliff-area", 0.15), ("cliff-size", 26),
                 ("cliff-layers", 3), ("cliff-feather", 4.0), ("cliff-band", 4),
                 ("shore-width", 3), ("shore-shallow", 0),
                 ("world-clamp", 0)):
        if opts.get(k) is not None:
            height_cmd += ["--" + k, str(opts[k])]
    if opts.get("layer-max") is not None:
        height_cmd += ["--layer-max", str(opts["layer-max"])]
    chosen_style = pick_style(opts, seed)
    if chosen_style:
        height_cmd += ["--style", chosen_style]
    rc = run_child(height_cmd)
    if rc:
        return rc

    # 第 3 步（可选）：撒树
    trees = str(opts.get("trees", "1")) not in ("0", "false", "no")
    if not trees:
        print("[2/3] 撒树 —— 已跳过（--trees 0）")
        return run_buildings(opts, out, prefix, exe_args, seed)

    print("[2/3] 撒树")
    tree_cmd = [PY, os.path.join(HERE, "add_doodads.py"), out] + exe_args + [
                "--no-backup",
                "--seed", seed,
                "--density", str(opts.get("density", 0.18)),
                "--forest-share", str(opts.get("forest-share", 0.32)),
                "--forest-size", str(opts.get("forest-size", 170)),
                "--clump-size", str(opts.get("clump-size", 11)),
                "--clump-radius", str(opts.get("clump-radius", 3.0)),
                "--clump-gap", str(opts.get("clump-gap", 1.5)),
                "--clump-bias", str(opts.get("clump-bias", 0.55)),
                "--scatter", str(opts.get("scatter", 0.035)),
                "--scatter-size", str(opts.get("scatter-size", 1.5)),
                "--edge-forest", str(opts.get("edge-forest", 0.55)),
                "--edge-band", str(opts.get("edge-band", 14)),
                "--freq", str(opts.get("tree-freq", 2.2)),
                "--slope-tol", str(opts.get("slope-tol", 1)),
                "--preview", prefix + "_trees.png"]
    if opts.get("tree-id"):
        tree_cmd += ["--tree-id", str(opts["tree-id"])]
    elif chosen_style:
        # 风格的官方树模型（覆盖「从模板学树」—— 模板里学到的永远是洛丹伦夏天的树）
        tree_cmd += ["--tree-id", STYLES[chosen_style]["tree"]]
    rc = run_child(tree_cmd)
    if rc:
        return rc

    rc = run_buildings(opts, out, prefix, exe_args, seed)
    if rc:
        return rc
    return run_creeps(opts, out, prefix, exe_args, seed)


def run_buildings(opts, out, prefix, exe_args, seed):
    """第 3 步（可选）：中立建筑。数量由 --nb-<id> 指定，0 = 该类不放。"""
    if str(opts.get("buildings", "1")) in ("0", "false", "no"):
        print("[3/3] 中立建筑 —— 已跳过（--buildings 0）")
        rc = run_triggers(opts, out, prefix, exe_args, seed)
        print(f"\n完成 → {out}")
        print(f"预览 → {prefix}_terrain.png / {prefix}_trees.png")
        return rc

    print("[3/3] 中立建筑")
    bld_cmd = [PY, os.path.join(HERE, "add_buildings.py"), out] + exe_args + [
              "--no-backup", "--seed", seed,
              "--min-dist", str(opts.get("nb-min-dist", 8)),
              "--edge", str(opts.get("nb-edge", 6)),
              "--flat-tol", str(opts.get("nb-flat-tol", 1)),
              "--gold", str(opts.get("nb-gold", 12500)),
              "--avoid-trees", str(opts.get("nb-avoid-trees", 1)),
              "--preview", prefix + "_buildings.png"]
    # 每种建筑的数量：GUI/命令行给了就传，没给就让 add_buildings 用自己的默认值
    for bid in ("ngol", "ngme", "ngad", "nmer", "nfoh", "nmrk", "ntav"):
        v = opts.get("nb-" + bid)
        if v is not None:
            bld_cmd += ["--" + bid, str(v)]
    for k, v in opts.items():            # 表外的自定义 id 也透传
        if k.startswith("nb-") and k[3:] not in (
                "ngol", "ngme", "ngad", "nmer", "nfoh", "nmrk", "ntav",
                "min-dist", "edge", "flat-tol", "gold", "avoid-trees", "style"):
            bld_cmd += ["--" + k[3:], str(v)]
    chosen_style = pick_style(opts, seed)
    if chosen_style:
        bld_cmd += ["--style", chosen_style]
    rc = run_child(bld_cmd)
    if rc:
        return rc
    return 0


def run_creeps(opts, out, prefix, exe_args, seed):
    """第 4 步（可选）：野怪。守建筑的野怪点 + 树林角落的野怪点 + 按等级掉落。"""
    if str(opts.get("creeps", "1")) in ("0", "false", "no"):
        print(f"[4/4] 野怪 —— 已跳过（--creeps 0）")
        rc = run_triggers(opts, out, prefix, exe_args, seed)
        print(f"\n完成 → {out}")
        print(f"预览 → {prefix}_terrain.png / {prefix}_trees.png / {prefix}_buildings.png")
        return rc

    print("[4/4] 野怪")
    cr_cmd = [PY, os.path.join(HERE, "add_creeps.py"), out] + exe_args + [
              "--no-backup", "--seed", seed,
              "--guard-share", str(opts.get("guard-share", 0.6)),
              "--forest-camps", str(opts.get("forest-camps", "auto")),
              "--camp-scale", str(opts.get("camp-scale", 1.0)),
              "--edge", str(opts.get("nb-edge", 6)),
              "--flat-tol", str(opts.get("nb-flat-tol", 1)),
              "--preview", prefix + "_creeps.png"]
    chosen_style = pick_style(opts, seed)
    if chosen_style:
        cr_cmd += ["--style", chosen_style]
    rc = run_child(cr_cmd)
    if rc:
        return rc

    rc = run_triggers(opts, out, prefix, exe_args, seed)
    if rc:
        return rc

    print(f"\n完成 → {out}")
    print(f"预览 → {prefix}_terrain.png / {prefix}_trees.png / "
          f"{prefix}_buildings.png / {prefix}_creeps.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
