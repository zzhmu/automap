# -*- coding: utf-8 -*-
"""纯规则/噪声版随机地形生成器 —— 写高度、悬崖、水面到 war3map.w3e。

字段标定结论（见 tools/inspect_w3e.py 的实测验证）:
  v11 每角点 7 字节:
    u16 groundHeight                基准 8192 (ground zero)
    u16 waterHeight | 0x4000         0x4000 = boundary flag 1
    u8  flags<<4 | groundTexture     0x10 ramp / 0x20 blight / 0x40 water / 0x80 boundary2
    u8  groundVariation<<3 | cliffVariation
    u8  cliffTexture<<4 | layerHeight
  WE 显示高度 = (groundHeight - 8192 + (layer - 2) * 512) / 4
    → 层零位 = 2，每层 = 512 原始单位；layer 上限 14，写 15 会崩

用法:
  python gen_height.py <map.w3x> [选项]
常用选项:
  --out <路径>        另存为新地图（默认原地改，先备份）
  --no-backup         跳过备份（调用方自己已经复制过模板时用，避免堆积无用 .bak）
  --seed 12345        随机种子
  --freq 1.6          噪声基础频率，越小地形越大块
  --layer-min 2       水面所在的层（WE 每条层线 = 128 高度单位，合法范围 0~14）。
                      水陆同层，所以它同时是整张地面层和悬崖抬升的基准
  --layer-max 5       允许的最高层（留空时 = layer-min + layers - 1）—— 现在只用来
                      限制悬崖最多能抬几层
  --layers 4          允许的层数（等价于 layer-max = layer-min + layers - 1）
  --smooth 2          3x3 众数滤波次数，抹平悬崖区毛边；0=关闭
  --water 0.30        水域占地比例（只在没给 --base / --water-level 时生效）
  --octaves / --level-bias / --min-plateau
                      旧参数，2026-09-16 起**已失效**（保留只为兼容旧命令行，不再影响结果）
三步式生成（2026-09-16 新增，见 doc/三步地形生成方案.md）:
  --cliffs 0          0 = 不生成悬崖（默认）：全图同一个层值，落差全放在 groundHeight 里
                      → 零悬崖、连绵起伏、近战单位处处可走
                      1 = 只在地图上的**几小块区域**里生成悬崖（其余地面照旧连续起伏）。
                      悬崖区 = 一片拔地而起的台地，外围一圈羽化平整，层差 = 落差/128
  --base land         初始地面：deep(-384) / shallow(-128) / land(0)，单位是 WE 高度、
                      相对水面，负 = 水下。给了它 → 水面恒为 0，水域占比由「初始地面 +
                      山脉抬升」自然决定（不再受 --water 约束）
                        deep    = 正常水域，深水浅水都有
                        shallow = 浅滩：水底整片压平到 --shelf-depth（默认 128 WE = 1 个整层）
                                  → 全是能走过去的浅水，没有深水
                        land    = 纯陆地：整块抬到水面之上 → 一滴水都没有
  --base-level -200   直接指定初始地面高度（WE），覆盖 --base
  --uplift 220        山脉抬升幅度（WE，σ；mountain_field 已归一到单位标准差）
  --mountain fbm      山脉算法：fbm（默认，圆润丘陵团块）/ ridged（有明显山脊线）/
                      warped（域扭曲，山体走向自然弯曲）
  --ridge 0.6         ridged 模式的山脊锐度
  --warp 8.0          warped 模式的扭曲强度（格）
  --mountain-octaves 4 山脉算法八度数（单层模式没有量化，可以比 --octaves 细）
  --water-level -50   绝对水面（WE），给了就覆盖 --water
  --shelf-depth 128   水底深度下限（WE）。🔴 2026-09-16 实测：**引擎只在「地形低于水面
                      ≥1 个整层(128 WE)」时才渲染水面**，浅于此的水下地形会被当干地画出来
                      （探针图 out/probe_water_depth.w3x：96 WE 无水、128 WE 有水，与 layer 无关）。
                      所以：① 所有水角点的深度都被兜到 ≥ 它；② shallow 基底的水底就压平在这个深度；
                      ③ 深度 > 它算「深水」（仅用于日志/预览配色）。别调到 128 以下。
  --max-relief 512    相对水面高度的振幅上限（WE，软裁剪 tanh，不会切出平顶）
                      官方实测能到 1536，想要更壮观就调大
  --trees 1           0 = 不撒树（random_map.py 会跳过 add_doodads 这一步）
  --world-clamp 0     世界高度安全钳制。实测 45 张官方图的最低角点恰好 -256.0 WE
                      （= layer 0 的世界基准 (0-2)*128），无一越界；最高 1536。
                      1 = 打开：单层模式自动抬高整图层号（纯垂直平移，不改任何坡度形态），
                      再把越界角点压回边界（⚠️ 这个**会把最深的水底削平**）。
                      0 = 默认，完全不干预地形，只在越界时打印一行警告。
                      ⚠️ 实测：开了它并不能解决「WE 里改地形闪退」，所以默认关。
悬崖区的形状（只在 --cliffs 1 时有意义）:
  --cliff-area 0.15   悬崖区占陆地的比例（低频场取高分位 → 天然是几大块，不是碎点）
  --cliff-size 26     悬崖区团块尺寸（格）
  --cliff-layers 3    悬崖区最高抬几层（1 层 = 128 WE = 一个悬崖台阶）
  --cliff-feather 4   悬崖区外围羽化平整的宽度（格）—— 崖壁脚下的一圈平地
应用高度（对应 WE 地形面板的「应用高度」那一栏，都是同一个台地内部的起伏，
不会变成悬崖。幅度单位统一是 WE 高度单位 = WE 高度条上的 1 格；一整层 = 128）:
  --raise 75          隆起：地面向上鼓包的幅度（σ，单位 WE 高度）
  --lower 75          凹陷：地面向下凹坑的幅度（σ）
  --rough 12          凹凸不平：表面颗粒感的幅度（σ，WE 的噪波笔刷就是这个量级）
  --blob 28           隆起/凹陷的团块尺寸（格，越大越是整片丘陵）
  --grain 2.5         凹凸不平的颗粒尺寸（格，越小越细碎）
  --ledge 0           台阶高度（WE 高度单位）：>0 时把宏观起伏量化成"平坦面 + 陡坎"，
                      对应 WE 的「高原/阶梯」笔刷；官方对战图 36%~64% 的相邻角点完全
                      等高就是这个原因。0 = 保持连续起伏（默认，观感最自然）
  --height-step 4     高度量化步长（原始单位）：4 = 1 WE 单位，与 WE 笔刷粒度一致
  --relief 0.35       旧参数（单位：层），等价于 --raise/--lower = relief×128，保留兼容
  --shade-exag 10     预览图的山体阴影垂直夸张倍数（只影响预览，不影响地图）
平整区域（对应 WE 的「平整」笔刷，让一部分地面彻底没有起伏）:
  --flat 0.15         平整区域占地图的比例，0 = 关闭
  --flat-size 20      平整区域的团块尺寸（格）
水体（实测官方对战图的水深全是整层的倍数，最常见 1 层，其次 2 层，少数 4 层。
      深浅水只靠 groundHeight 的落差表达、不换 layer —— 换 layer 会在水下多出崖壁；
      水色深浅由引擎按实际深度渲染）:
  --water-relief 0.5  水下起伏 = 陆地起伏 × 该比例（自动裁到水底不会冒出水面）
  --shore-width 3     岸线缓坡跨几格（0 = 关闭）。官方 40 张有水的图实测：离岸 1/2/3 格
                      的水深中位数 = 68/114/128 WE —— 岸边是缓坡浅滩，第 3 格才到全深。
                      我们旧行为是「一步踩到 --shelf-depth 的平底」（128/128/128），
                      岸线因此是一道 169 WE 的硬台阶（看着像浴缸边）
  --shore-shallow 0   紧贴岸那排水底的目标深度（WE），0 = 自动取 --shelf-depth 的 53%
                      （128 → 68，对齐官方离岸第 1 格中位数）。必须小于 --shelf-depth
  --ramps auto        斜坡：auto=按连通性自动刻（默认）；0=关闭；N=最多 N 条
  --ramp-run 4        每条斜坡沿崖壁方向的瓦片数（官方长边集中在 5~8 条角点线）
  --ramp-force 1      1=找不到齐整崖段时把 5 条角点线就地整形（默认，斜着走的锯齿崖
                      也能刻出斜坡）；0=只接受本来就齐整的位置（会更常跳过）
  --cliff-texture auto 崖壁贴图索引（auto = 纹理集里第 2 套，官方地图的通用做法；
                      官方空模板里是 15 = 未指定）。整张图统一，不逐角点随机
  --min-plateau 0     小于该面积（格）的台地并入邻居，0=关闭（默认关）
  --min-island 32     小于该面积（格）的陆地碎岛并入水，0=关闭
  --min-lake 16       小于该面积（格）且不贴边的内陆水塘填平，0=关闭
  --max-jump 2        相邻角点允许的最大层差（官方地图存在 2 层崖）
  --boundary ring     地图边界标记（0x80 与 0x4000 这两个位是同一概念的两份拷贝，
                      带它 = 地图外，寻路可走率 0%）：
                        ring = 只留最外一圈（默认，整张地图可玩）
                        none = 全清
                        keep = 沿用模板边框（WE 自建的空模板用它标出游玩区之外的留白，
                               官方对战图如 LostTemple 则盖了 40% 的角点）
  --preview p.png     同时输出地形预览图
示例:
  python gen_height.py ../generated/rand1.w3x --seed 42 --water 0.28 --preview ../preview.png
"""
import heapq
import os
import shutil
import struct
import subprocess
import sys
import time
from collections import Counter, deque
from datetime import datetime

import numpy as np
from PIL import Image


def force_utf8_stdout():
    """管道/重定向时把标准输出统一成 UTF-8；直接开在控制台时保留控制台编码。

    不这么做会连环炸：
      1. 子进程 print 中文时按系统区域设置编码（中文 Windows = cp936），父进程若按
         另一种编码解码 → UnicodeDecodeError，而且它发生在 subprocess 的读取线程里，
         父进程只会看到 r.stdout 是 None，接着 AttributeError，看起来完全不知所云。
      2. ✔ ✘ 这类字符**不在 GBK 字符集里**，cp936 下直接 print 就 UnicodeEncodeError。
    所以：进管道的输出一律 UTF-8（调用方按 UTF-8 解），人看的控制台保留原编码但
    把编码不了的字符替换掉，绝不因为一个符号把整次生成搞崩。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            if s.isatty():
                s.reconfigure(errors="replace")
            else:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


force_utf8_stdout()

HERE = os.path.dirname(os.path.abspath(__file__))

GROUND_ZERO = 8192
LAYER_ZERO = 2          # 层编号的零位
LAYER_STEP = 512        # 每层 = 512 原始单位
MAX_LAYER = 14          # 15 非法
WATER_FLAG = 0x40
RAMP_FLAG = 0x10
BLIGHT_FLAG = 0x20
BOUNDARY2_FLAG = 0x80   # flags 里的「地图边界外」标记（实测：带它的瓦片可走率 0%）
BOUNDARY_BIT = 0x4000   # waterHeight 里的「地图边界外」标记（同一个概念的另一份拷贝）
WATER_LEVEL = 8192      # 水面基准（默认层区间 layer_min=2 时的世界高度 = GROUND_ZERO）

# 初始地面预设 / WE 崩溃防护用的世界高度合法区间。
# 实测 45 张官方对战图（tools/_tmp/diag_we_crash.py）：
#   * 最低角点恰好卡在 **-256.0**，且**没有一张图有任何角点低于它** —— 这正是
#     layer 0 的世界基准 (0-2)*128，是地形高度的硬地板，不是巧合。
#   * 最高 1536.0（= layer 14 的基准）。
# 越界后 WE 能打开也能显示，但一编辑地形就闪退。
WORLD_MIN_WE = -256.0
WORLD_MAX_WE = 1536.0

# 第 1 步「初始地面」的预设：相对水面的高度，单位 WE 高度单位（负 = 水下）。
# 给了 --base 就走「绝对水面」模式：水面恒为 0，水域占比由「初始地面 + 抬升」自然决定。
#
# 语义（2026-09-16 用户重新定义）：
#   deep    -384 深水基底：正常生成，有深水也有浅水
#   shallow -128 浅滩基底：水浅到**陆地单位能直接走过去** → 整片水域都不能是深水
#   land       0 纯陆地基底：整块抬到水面之上 → **一滴水都没有**
BASE_PRESETS = {"deep": -384.0, "shallow": -128.0, "land": 0.0}


def default_exe():
    """定位随项目自带的 ../bin/MPQEditor.exe（不依赖外部目录）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(here, "..", "bin", "MPQEditor.exe"))
    return p if os.path.exists(p) else "MPQEditor.exe"


def read_header(data):
    pos = 8
    tileset = chr(data[pos]); pos += 1
    custom = struct.unpack_from("<I", data, pos)[0]; pos += 4
    n_ground = struct.unpack_from("<I", data, pos)[0]; pos += 4
    ground = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace") for i in range(n_ground)]
    pos += 4 * n_ground
    n_cliff = struct.unpack_from("<I", data, pos)[0]; pos += 4
    cliff = [data[pos + 4 * i:pos + 4 * i + 4].decode("ascii", "replace") for i in range(n_cliff)]
    pos += 4 * n_cliff
    w = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    h = struct.unpack_from("<I", data, pos)[0] - 1; pos += 4
    pos += 8
    return {"version": struct.unpack_from("<I", data, 4)[0], "tileset": tileset,
            "custom": custom, "ground": ground, "cliff": cliff,
            "width": w, "height": h, "header": pos}


def value_noise(nprng, shape, cells, warp=None):
    """一块 cells x cells 的随机格点，双线性插值 + 多个八度叠加成 fBm。

    两个细节都是为了消除伪影：
      1. 插值权重用 smoothstep（3w²-2w³）而不是线性 —— 线性插值在格线上留折痕，
         多层八度叠起来就是一片 45° 的"砂纸斜纹"。
      2. 格点相位随机偏移 —— 格点数与角点数整除时（比如 129 角点配 65 格点），
         噪声节点刚好落在每个像素上，会渲染出规则的点阵/棋盘。相位一随机就散了。

    warp = (wy, wx)：域扭曲用的位移场（单位 = 格点坐标）。让它按另一层噪声去偏移
    采样坐标，山体走向就会自然弯曲，不再是各向同性的圆团。
    """
    rows, cols = shape
    gw = max(2, int(cells) + 1)
    gh = gw
    grid = nprng.random((gh, gw), dtype=np.float32)
    oy, ox = nprng.random(2).astype(np.float32)
    ys = np.linspace(0, gh - 1, rows, dtype=np.float32)[:, None] + oy
    xs = np.linspace(0, gw - 1, cols, dtype=np.float32)[None, :] + ox
    if warp is not None:
        ys = ys + np.asarray(warp[0], dtype=np.float32)
        xs = xs + np.asarray(warp[1], dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    wy = ys - y0
    wx = xs - x0
    y0 = np.mod(y0, gh); y1 = np.mod(y0 + 1, gh)
    x0 = np.mod(x0, gw); x1 = np.mod(x0 + 1, gw)
    wy = wy * wy * (3.0 - 2.0 * wy)
    wx = wx * wx * (3.0 - 2.0 * wx)
    top = grid[y0, x0] * (1 - wx) + grid[y0, x1] * wx
    bot = grid[y1, x0] * (1 - wx) + grid[y1, x1] * wx
    return top * (1 - wy) + bot * wy


def fbm(nprng, shape, freq, octaves=5, gain=0.5, lacunarity=2.0, warp=None):
    """分形布朗运动，返回任意实数范围的二维数组。

    八度一旦细过「一个角点一格」就停：再细的内容在角点网格上直接混叠成假图案
    （规则点阵/棋盘），不是细节。
    """
    out = np.zeros(shape, dtype=np.float32)
    nyq = float(min(shape))
    amp, norm, f = 1.0, 0.0, freq
    for _ in range(octaves):
        if f > nyq:
            break
        out += amp * value_noise(nprng, shape, f, warp=warp)
        norm += amp
        amp *= gain
        f *= lacunarity
    return out / norm if norm > 0 else out


def unit_normalize(a):
    """把任意场归一到「零均值 + 单位标准差」，好让幅度参数直接写成 WE 高度单位。"""
    a = a.astype(np.float32)
    a = a - a.mean()
    s = float(a.std())
    return (a / s) if s > 1e-6 else a


def ridged_multifractal(nprng, shape, freq, octaves=4, gain=0.5, lacunarity=2.0,
                        sharpness=0.6):
    """Ridged multifractal：`1-|noise|` 反复叠加 → 有明显的山脊线。

    每一层先把噪声折成脊（`1 - |2v-1|`），再用上一层的脊值当权重（上一轮是脊的
    地方这一轮才继续叠加细节），所以细节会沿山脊生长，而不是均匀铺满整张图。
    sharpness 越大脊越尖。
    ⚠️ 官方对战图实测是「大片平坦面 + 1 WE 量化的陡坎」，不是连续山坡 —— 这个算法
    出来的是**更像真实山脉、更不像官方对战图**的观感，想要官方味就保持 fbm + --ledge。
    """
    out = np.zeros(shape, dtype=np.float32)
    nyq = float(min(shape))
    amp, norm, f = 1.0, 0.0, freq
    w = np.ones(shape, dtype=np.float32)
    for _ in range(octaves):
        if f > nyq:
            break
        v = value_noise(nprng, shape, f)
        n = 1.0 - np.abs(v * 2.0 - 1.0)
        n = np.power(n, 1.0 + 2.0 * max(0.0, sharpness))
        out += w * n * amp
        norm += amp
        w = np.clip(n * (1.0 + sharpness), 0.0, 1.0)
        amp *= gain
        f *= lacunarity
    return unit_normalize(out / norm if norm > 0 else out)


def warped_fbm(nprng, shape, freq, octaves=4, warp_tiles=8.0, gain=0.5,
               lacunarity=2.0):
    """域扭曲 fBm：用一层低频噪声去位移另一层的采样坐标。

    单位换算：value_noise 把 cols 个像素映射到约 cells 个格点单位，所以
    1 像素 = cells/cols 格点单位 → 想位移 warp_tiles 个像素就乘 freq/cols。
    """
    rows, cols = shape
    wc = noise_cells(cols, max(6.0, warp_tiles * 2.5))
    fy = unit_noise(nprng, shape, wc, octaves=2)
    fx = unit_noise(nprng, shape, wc, octaves=2)
    scale = freq / max(1.0, float(cols))
    return unit_normalize(fbm(nprng, shape, freq, octaves=octaves, gain=gain,
                              lacunarity=lacunarity,
                              warp=(fy * warp_tiles * scale,
                                    fx * warp_tiles * scale)).astype(np.float32))


def mountain_field(nprng, shape, kind, cols, freq=1.6, octaves=4, ridge=0.6,
                   warp=8.0):
    """第 1 步的「山脉算法」：返回一个零均值、单位标准差的连续高度场。"""
    kind = (kind or "fbm").lower()
    if kind == "ridged":
        return ridged_multifractal(nprng, shape, freq, octaves=octaves,
                                   sharpness=ridge)
    if kind == "warped":
        return warped_fbm(nprng, shape, freq, octaves=octaves, warp_tiles=warp)
    return unit_noise(nprng, shape, freq, octaves=octaves)


def soft_clip(a, limit):
    """把振幅软压到 ±limit（tanh），保留单调性 —— 硬截断会把山顶切成平顶。"""
    limit = max(1e-6, float(limit))
    return limit * np.tanh(a.astype(np.float32) / limit)


def box_blur(a, r):
    """可分离盒式模糊，r = 半径（格）。用来求「大尺度地面高度」—— 悬崖区要从它
    上面拔地而起，所以这个基准必须跟得上大地形的走向，不能是个全局常数。"""
    a = a.astype(np.float32)
    r = int(r)
    if r <= 0:
        return a
    k = 2 * r + 1
    for ax in (0, 1):
        pad = [(r, r) if i == ax else (0, 0) for i in range(a.ndim)]
        p = np.pad(a, pad, mode="edge")
        c = np.concatenate([np.zeros_like(np.take(p, [0], axis=ax).cumsum(axis=ax)),
                            np.cumsum(p, axis=ax)], axis=ax)
        n = a.shape[ax]
        lo = np.take(c, range(0, n), axis=ax)
        hi = np.take(c, range(k, n + k), axis=ax)
        a = (hi - lo) / float(k)
    return a


def fill_band_fine(fine, layer, band, radius=8, win=4):
    """把坡带（`band`）角点的高度填成「**同层号、且朝台地那一侧**的地面高度」。

    为什么必须同层号：世界高度 = fine/4 + 128×(layer-2)，层号本身贡献一级台阶。
    坡带里 layer 高的那条角点线，就该站在上一级台地的地面上；layer 低的那两条线
    就该站在下一级台地的地面上。这样坡面**恰好**从下台地升到上台地，
    落差 = 128×层差 = 一整个台阶，跟 WE 渲染斜坡的方式一致（官方 BootyBay 实测）。
    ⚠️ 不能改成「邻域不分层号一起平均」：那样坡带会拿两个台地高度的中间值，
       上层线比它该贴的台地低一截、下层线又高出一截，坡面中段还会鼓包。

    为什么取源必须**朝台地那一侧**：坡带是「垂直崖壁的一条带」。沿坡带**切线**方向
    （也就是沿着崖壁往两边）看出去的普通地面，是崖壁上下的地面本身 —— 它的高度
    跟坡带该站的高度毫无关系，而且常常正是地形陡降的地方。实测 seed=777 站点 #5：
    坡带中间那条线在切线上挨着一片低 70~90 WE 的地面，若按「最近邻」取源就会把
    坡面中段拽下去，凹成一个「先下后上」的 V 形沟。

    方向怎么定 —— **局部 PCA**：取该角点 `win` 格邻域内的坡带角点，主轴就是坡带的
    切线，法线 = 主轴转 90°；再用「层号高的角点在法线正侧」定出朝向，于是
      低层线 → 朝法线负侧（下坡台地）；高层线 → 朝法线正侧（上坡台地）。
    ⚠️ 两个坑都踩过：
      * 别用「整条坡带连通簇算一根法线」—— 多条斜坡会连成一片（实测 `验收_局部悬崖`
        有一块 21 个瓦片把几条坡连在一起），簇级法线对不上（站点 #16 偏差 85~127 WE）；
      * 方向必须**吸附到 8 邻域里的一个**、位移严格沿着它走。用「点积 ≥ 阈值」的话，
        坡带中间那条线的正对面就是坡带自己，最先命中的同层号地面往往是斜向的切向地面
        （seed=777 站点 #5 中间线被拽低 42 WE）。

    返回 (filled_fine, ok)；ok = 成功填上的掩码（没填上的由调用方兜底）。
    """
    H, W = fine.shape
    out = fine.astype(np.float32).copy()
    ok = np.zeros_like(band, dtype=bool)
    if not band.any():
        return out, ok
    nbr = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    cells = list(zip(*[a.tolist() for a in np.nonzero(band)]))
    pts = np.array(cells, dtype=np.float64)
    lays = np.array([int(layer[r, c]) for r, c in cells], dtype=np.int32)
    for i, (r0, c0) in enumerate(cells):
        L = int(lays[i])
        # 1) 局部 PCA 求坡带法线，并定向到「高层在正侧」
        dd = np.maximum(np.abs(pts[:, 0] - r0), np.abs(pts[:, 1] - c0))
        sel = dd <= win
        nrm = None
        if int(sel.sum()) >= 3:
            q = pts[sel]
            cen = q - q.mean(axis=0)
            w_, v_ = np.linalg.eigh(cen.T @ cen)
            tan = v_[:, int(np.argmax(w_))]
            n = np.array([-tan[1], tan[0]])
            ls = lays[sel]
            hi_l, lo_l = int(ls.max()), int(ls.min())
            if hi_l > lo_l:
                proj = q[:, 0] * n[0] + q[:, 1] * n[1]
                if proj[ls == hi_l].mean() < proj[ls == lo_l].mean():
                    n = -n
                nrm = -n if L == lo_l else n     # 低层线朝下坡、高层线朝上坡
        # 2) 吸附到 8 邻域方向，沿严格直线找同层号的非坡带角点
        dirv = None
        if nrm is not None:
            nn = float(np.hypot(nrm[0], nrm[1]))
            if nn > 1e-6:
                uy, ux = nrm[0] / nn, nrm[1] / nn
                best, bd = (0, 0), -2.0
                for dy, dx in nbr:
                    d = (uy * dy + ux * dx) / float(np.hypot(dy, dx))
                    if d > bd:
                        bd, best = d, (dy, dx)
                dirv = best
        src = []
        if dirv is not None:
            for k in range(1, radius + 1):
                nr, nc = r0 + dirv[0] * k, c0 + dirv[1] * k
                if not (0 <= nr < H and 0 <= nc < W):
                    break
                if band[nr, nc] or int(layer[nr, nc]) != L:
                    continue
                src = [float(fine[nr, nc])]
                break
        if not src:
            # 兜底：整条坡带同层 / 严格方向上够不着 → 收任意方向的同层号地面
            for k in range(1, radius + 1):
                for dy, dx in nbr:
                    nr, nc = r0 + dy * k, c0 + dx * k
                    if not (0 <= nr < H and 0 <= nc < W):
                        continue
                    if band[nr, nc] or int(layer[nr, nc]) != L:
                        continue
                    src.append(float(fine[nr, nc]))
                if src:
                    break
        if src:
            out[r0, c0] = float(np.mean(src))
            ok[r0, c0] = True
    return out, ok



def dist_outside(mask, cap=64):
    """多源 BFS：每个非 mask 格到最近 mask 格的格数距离（mask 内 = 0）。"""
    d = np.where(mask, 0, cap + 1).astype(np.int32)
    front = mask.copy()
    for step in range(1, cap + 1):
        nb = np.zeros_like(front)
        nb[1:, :] |= front[:-1, :]
        nb[:-1, :] |= front[1:, :]
        nb[:, 1:] |= front[:, :-1]
        nb[:, :-1] |= front[:, 1:]
        new = nb & ~front
        if not new.any():
            break
        d[new] = step
        front |= new
    return d


def cliff_mask(nprng, shape, land, area, size, cols, smooth=2, min_area=24,
               solid=None):
    """在陆地上挑若干块成片区域当「悬崖区」。

    低频场取高分位 → 天然是几大块而不是碎点；众数滤波抹掉毛边；最后清掉过小的块。
    land 之外的（水域）一律排除 —— 悬崖长在水里没有意义，而且会破坏层差与落差
    的对应关系。

    最后一步**填洞**（2026-09-16 加，见下）：把被遮罩围住的整块干燥陆地并进遮罩。
    返回 (遮罩, 填掉的洞数)。
    """
    f = unit_noise(nprng, shape, noise_cells(cols, max(4.0, size)), octaves=2)
    if not land.any():
        return np.zeros(shape, dtype=bool), 0
    thr = float(np.percentile(f[land], (1.0 - min(0.95, max(0.0, area))) * 100.0))
    m = land & (f >= thr)
    if smooth > 0:
        m = mode_filter(m.astype(np.int32), passes=smooth, values=2) > 0
    m = m & land
    # 🔴 悬崖区不许贴到地图边（留 3 格）：一旦贴边，一道悬崖臂就可能把地图边缘的
    # 一条地面**切下来**（实测 seed=93014：右侧 2 列 × 13 行、25 格基准层地面被
    # 一道 2 级崖壁隔开）。那片地面在基底层上，撤台地撤不掉它，1 级斜坡也跨不过去
    # → 连通性自检必然报「有 1 座岛被崖壁切断」。留出一圈空地后，地图最外圈永远是
    # 连通的「基底层相框」，任何非遮罩地面都能绕出去。
    mg = 3
    if mg > 0:
        m[:mg, :] = False
        m[-mg:, :] = False
        m[:, :mg] = False
        m[:, -mg:] = False
    if min_area > 0:
        lab, n = _components(m)
        for i in range(n):
            sel = lab == i
            if sel.sum() < min_area:
                m[sel] = False

    # 🔴 填洞：遮罩里的「洞」（一块不属于遮罩、又被遮罩围住的地）必须并进遮罩。
    # 不填的话它会保持基准层（layer = layer_min），而四周的台地比它高 2 级以上
    # → 1 级斜坡跨不过这堵墙 → 变成一块**上不去的小坑**（实测 seed=93014：25 格）。
    # 而且「撤台地」兜底也救不了它：撤台地只处理 layer > 基准层的地块，它正好在
    # 基准层上，撤不动。
    # ⚠️ 洞里**带水**的不能填 —— 台地会把 H_we 抬到水面之上，那片水会直接消失。
    n_holes = 0
    if solid is None:
        solid = land
    if m.any() and not m.all():
        lab2, n2 = _components(~m)
        edge = set()
        for arr in (lab2[0, :], lab2[-1, :], lab2[:, 0], lab2[:, -1]):
            edge |= {int(v) for v in np.unique(arr) if v >= 0}
        for i in range(n2):
            if i in edge:              # 通到地图边 → 不是洞，是外面的地
                continue
            sel = lab2 == i
            if not bool(solid[sel].all()):
                continue               # 洞里带水：不能抬
            m[sel] = True
            n_holes += 1
    return m, n_holes


def _lipschitz_levels(k, mask, max_steps):
    """把台地级数场 k 约束成「相邻格最多差 1 级」（遮罩外一律视为 0 级）。

    为什么必须做（2026-09-16 加）：原来遮罩边界处的落差 = 128×k，k 可以是 2 甚至 3
    —— 那就是一堵 **2~3 级**的崖壁。可 WE 的斜坡一次只能跨 1 级（官方 293 条斜坡里
    只有 1 条是 2 级），所以边界旁那些基准层的地面（一片浅滩、一个贴着崖脚的小平台、
    甚至一格）就**爬不上去**，连通性自检必然报「有 1 座岛被崖壁切断」；而「撤台地」
    兜底也救不了它们（它们本来就在基准层上，没有层可撤）。

    约束后：遮罩最外一圈最多 1 级、第二圈最多 2 级 …… 台地就像台阶一样从边界
    一级一级爬上去，任何一圈与它外面那一圈都只差 1 级 → 斜坡一定能盖、能走。
    这是**只降不升**的传播，不会把地面抬得更高。
    """
    kk = np.where(mask, k, 0.0).astype(np.float32)
    for _ in range(int(max_steps) + 1):
        prev = kk.copy()
        for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
            nb = np.zeros_like(kk)
            if axis == 0:
                if shift > 0:
                    nb[1:, :] = kk[:-1, :]
                else:
                    nb[:-1, :] = kk[1:, :]
            else:
                if shift > 0:
                    nb[:, 1:] = kk[:, :-1]
                else:
                    nb[:, :-1] = kk[:, 1:]
            kk = np.minimum(kk, nb + 1.0)
        if not (kk < prev - 1e-6).any():
            break
    return np.where(mask, np.clip(kk, 1.0, max(1.0, float(max_steps))), 0.0)


def apply_terraces(H, mask, layer_min, plane_layer, blur_r, feather,
                   max_steps, ref=0.0):
    """在 mask 内把连续高度场切成整层台地（层差 = 崖壁），mask 外保持连续起伏。

    ⚠️ 关键不变量：**层差 ΔL 必须严格对应 128*ΔL 的真实落差**，否则 WE 会渲出
    高度对不上的错乱崖壁。所以：
      * mask 内：台地面 = Hgap + 128*k，层号 = layer_min + k
      * mask 外紧贴的一圈：地形被羽化拉平到 Hgap，层号 = layer_min
      → 边界处落差正好 128*ΔL，层差正好 ΔL ✔
      * 而 ΔL 由 `_lipschitz_levels` 约束成「相邻格最多差 1 级」，所以**每一圈台阶
        都只差 1 级** —— 边界处 ΔL 恒为 1，斜坡能盖、地面能走 ✔

    台阶级数 `k = round((Hgap - ref)/128) + 1`：**地形越高台地越高**。
    `ref` 是低地基准（外面传陆地高度的低分位）。+1 保证 mask 内每格至少抬 1 层，
    所以一块台地永远比它周围那圈羽化平地高。用 Hgap 而不是「Hgap 与更细模糊的差」，
    是因为后者只反映小尺度起伏（σ 几十 WE），除以 128 后四舍五入恒为 0 →
    `--cliff-layers` 形同虚设、所有台地都是 1 层。用 Hgap 才有「山里的台地更高」。
    返回 (新高度场, 层号数组, 级数 k)。
    """
    Hgap = box_blur(H, blur_r)
    k = np.clip(np.round((Hgap - float(ref)) / 128.0) + 1.0, 1.0,
                max(1.0, float(max_steps)))
    if mask.any():
        k = _lipschitz_levels(k, mask, max_steps)
    d = dist_outside(mask, cap=max(2, int(feather) + 2))
    w = np.clip((feather + 1.0 - d) / max(1e-6, float(feather)), 0.0, 1.0)
    w = np.where(mask, 0.0, w)                 # 羽化只作用在 mask 外面
    H_out = H * (1.0 - w) + Hgap * w           # 悬崖区外围 → 一圈围着崖壁的平地
    H_in = Hgap + 128.0 * k
    H_new = np.where(mask, H_in, H_out).astype(np.float32)
    layer = np.where(mask, layer_min + np.rint(k).astype(np.int16),
                     np.full(H.shape, layer_min, dtype=np.int16)).astype(np.int16)
    return H_new, layer, k


def hills_clean_regions(H, min_island=32, min_lake=16):
    """单层连续模式下清碎岛碎塘 —— 没有「层」可换，只能直接改高度。

    碎岛 → 翻到水面下（沉掉）；内陆小水塘 → 翻到水面上（填成小丘）。
    幅度取原绝对值并至少 12 WE，避免出现「刚好贴着水面」的暧昧地形。
    H 是相对水面的高度（WE），就地返回修改后的副本。
    """
    H = H.copy()
    land = H >= 0.0
    n_i = n_l = 0
    if min_island > 0:
        lab, n = _components(land)
        for i in range(n):
            m = lab == i
            if m.sum() < min_island:
                H[m] = -np.clip(np.abs(H[m]), 12.0, None)
                n_i += 1
        land = H >= 0.0
    if min_lake > 0:
        lab, n = _components(~land)
        edge = np.zeros_like(land)
        edge[0, :] = edge[-1, :] = True
        edge[:, 0] = edge[:, -1] = True
        ocean = set(int(v) for v in np.unique(lab[(~land) & edge]) if v >= 0)
        for i in range(n):
            m = lab == i
            if m.sum() >= min_lake or i in ocean:
                continue
            H[m] = np.clip(np.abs(H[m]), 12.0, None)
            n_l += 1
    return H, n_i, n_l


def apply_base_semantics(H, base_mode, shelf_depth):
    """把「初始地面」的语义强加到连续高度场 H 上（H = 相对水面的高度，单位 WE）。

    2026-09-16 用户对基底重新定义：
      * shallow（浅滩）：水浅到**陆地单位能直接走过去** → 整片水域都不许有深水。
      * land（纯陆地）：**一滴水都没有** → 整块抬到水面之上；抬升保形状。

    🔴 2026-09-16 第三轮实测纠错（关键）：shallow 原来是把水深**按比例压缩**，结果
    水深中位数被压到 27 WE —— 而引擎只在「地形低于水面 ≥ 1 个整层(128 WE)」时才渲染
    水面（探针图 out/probe_water_depth.w3x 实测：96 WE 无水、128 WE 有水，与 layer 无关）。
    于是整片浅水在 WE 里被当干地画，用户看到的是「纯陆地」。
    现在改成**把水底整体压到一个平面**（深度恒 = shelf_depth）—— 这也正是官方地图的
    样子（水底是整层台阶，81~98% 的水角点深度恰好是 128 的整数倍）。

    这个函数要在「叠加应用高度之前」和「之后」各调用一次：起伏会把水底推深，
    也会把陆地重新压到水面以下。返回新的 H（不修改入参）。
    """
    H = H.astype(np.float32)
    if base_mode == "shallow" and shelf_depth > 0:
        # 水角点（H < 0）一律压到 -shelf_depth：形状（水域范围）不变，深度变成均匀浅水。
        H = np.where(H < 0.0, -float(shelf_depth), H)
    elif base_mode == "land":
        m = float(H.min())
        if m < 1.0:
            H = H - m + 1.0                        # 最低点也留在水面之上
    return H


def unit_noise(nprng, shape, freq, **kw):
    """fBm 归一到「零均值 + 单位标准差」。

    这样「应用高度」的几个参数可以直接写成 WE 高度单位（--raise 70 = 鼓包处大约
    高出 70 格），跟 WE 高度条上的数字对得上；也不会因为改了尺度参数整个幅度就跑偏。
    """
    f = fbm(nprng, shape, freq, **kw).astype(np.float32)
    f = f - f.mean()
    s = float(f.std())
    return (f / s) if s > 1e-6 else f


def noise_cells(cols, size_tiles):
    """把「特征尺寸（格）」换算成 value_noise 的 cells 参数。

    value_noise 是在整张图上铺 int(cells)+1 个随机格点再做双线性插值，所以
    格点间距 ≈ cols / cells → 想要 size_tiles 格宽的起伏，就传 cells = cols/size。
    这样参数与地图尺寸无关：128 图上「28 格团块」和 256 图上「28 格团块」一样大。
    """
    return max(1.0, cols / max(1.0, float(size_tiles)))


def box_mean5(a):
    """5x5 边缘保形滑动均值（累积和实现，比卷积快）。"""
    k = 5
    pad = k // 2
    p = np.pad(a.astype(np.float32), pad, mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    R, C = a.shape
    s = (c[k:k + R, k:k + C] - c[0:R, k:k + C]
         - c[k:k + R, 0:C] + c[0:R, 0:C])
    return s / (k * k)


def shore_distance(is_water, cap=64):
    """每个水格到最近陆地的格数（多源 BFS，向量化膨胀，超过 cap 记 cap）。

    用来切「浅水岸带 / 深水区」：离岸近的是浅水，远的是深水，这样湖心深、岸边浅，
    跟真实水体一致（官方地图没有一条等宽的浅水描边）。
    """
    rows, cols = is_water.shape
    d = np.full((rows, cols), cap, dtype=np.int16)
    d[~is_water] = 0
    cur = ~is_water
    step = 0
    while cur.any() and step < cap:
        step += 1
        nxt = np.zeros_like(cur)
        nxt[1:, :] |= cur[:-1, :]
        nxt[:-1, :] |= cur[1:, :]
        nxt[:, 1:] |= cur[:, :-1]
        nxt[:, :-1] |= cur[:, 1:]
        nxt &= is_water & (d == cap)
        if not nxt.any():
            break
        d[nxt] = step
        cur = nxt
    return d


def relief_stats(fine, mask):
    """实测这块起伏场「低频(隆起/凹陷) / 高频(凹凸不平)」的 σ（单位 WE 高度）.

    口径与 tools/_tmp/analyze_height.py 一致：先换成 WE 高度单位，再用 5x5 均值
    把 5 格以上尺度算作低频、剩下的算高频。mask = 要统计的角点。
    """
    h = fine.astype(np.float32) / 4.0
    low = box_mean5(h)
    high = h - low
    sel = mask
    if sel.sum() < 50:
        sel = np.ones_like(mask)
    return (float(h[sel].std()), float(low[sel].std()), float(high[sel].std()))


def hillshade(height, az_deg=315.0, alt_deg=45.0, exag=10.0):
    """把高度场画成山体阴影（0~1 灰度），用来直观看出隆起/凹陷/颗粒感。

    exag 是垂直夸张倍数：真实比例下（1 格 = 128 世界单位，而起伏只有几十）
    阴影几乎全是平的，看不出东西，所以要放大。
    """
    az = np.deg2rad(90.0 - az_deg)
    alt = np.deg2rad(alt_deg)
    gy, gx = np.gradient(height.astype(np.float32) * exag)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    return np.clip(np.sin(alt) * np.sin(slope)
                   + np.cos(alt) * np.cos(slope) * np.cos(az - aspect), 0.0, 1.0)


def limit_neighbor_jump(layer, max_jump=1, passes=8):
    """WE 渲染相邻层落差过大会出异常 tearing，这里把相邻层差压到 max_jump 以内。"""
    rows, cols = layer.shape
    for _ in range(passes):
        changed = False
        for dy, dx in ((0, 1), (1, 0)):
            a = layer[:, :-1] if dx else layer[:-1, :]
            b = layer[:, 1:] if dx else layer[1:, :]
            diff = b - a
            over = np.abs(diff) > max_jump
            if not over.any():
                continue
            changed = True
            step = (np.abs(diff) - max_jump) / 2.0
            step = np.ceil(step) * np.sign(diff)
            if dx:
                layer[:, :-1] = np.where(over, (a + step).astype(np.int16), a)
                layer[:, 1:] = np.where(over, (b - step).astype(np.int16), b)
            else:
                layer[:-1, :] = np.where(over, (a + step).astype(np.int16), a)
                layer[1:, :] = np.where(over, (b - step).astype(np.int16), b)
        layer[:] = np.clip(layer, 0, MAX_LAYER)
        if not changed:
            break
    return layer


def _components(mask):
    """4 连通区域标记，返回 (label 数组, 区域数)，label=-1 表示不属于 mask。"""
    R, C = mask.shape
    lab = np.full((R, C), -1, dtype=np.int32)
    cur = 0
    for r in range(R):
        for c in range(C):
            if not mask[r, c] or lab[r, c] >= 0:
                continue
            lab[r, c] = cur
            stack = [(r, c)]
            while stack:
                y, x = stack.pop()
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < R and 0 <= nx < C and mask[ny, nx] and lab[ny, nx] < 0:
                        lab[ny, nx] = cur
                        stack.append((ny, nx))
            cur += 1
    return lab, cur


def _tile_derivatives(layer, is_water):
    """返回每个瓦片的 (层差, 梯度方向, 跳变线索引, 干燥)。索引均为自顶向下排布。"""
    a = layer[:-1, :-1]; b = layer[:-1, 1:]
    c_ = layer[1:, :-1]; d = layer[1:, 1:]
    spread = (np.maximum(np.maximum(a, b), np.maximum(c_, d))
              - np.minimum(np.minimum(a, b), np.minimum(c_, d)))
    di = np.abs(a - b) + np.abs(c_ - d)
    dj = np.abs(a - c_) + np.abs(b - d)
    grad = np.where(spread == 0, 0, np.where(di >= dj, 1, 2)).astype(np.int8)
    rows_g = np.arange(spread.shape[0])[:, None]
    cols_g = np.arange(spread.shape[1])[None, :]
    line = np.where(grad == 1,
                    cols_g + np.where(a < b, 0, 1),
                    rows_g + np.where(a < c_, 0, 1)).astype(np.int32)
    dry = ~(is_water[:-1, :-1] | is_water[:-1, 1:] | is_water[1:, :-1] | is_water[1:, 1:])
    return spread, grad, line, dry


def _shift(A, dy, dx):
    """把 A 整体平移 (dy, dx)，出界部分填 -1（用于众数滤波取邻域）。"""
    R, C = A.shape
    out = np.full((R, C), -1, dtype=A.dtype)
    ys0, ys1 = max(0, -dy), min(R, R - dy)
    yd0, yd1 = max(0, dy), min(R, R + dy)
    xs0, xs1 = max(0, -dx), min(C, C - dx)
    xd0, xd1 = max(0, dx), min(C, C + dx)
    out[yd0:yd1, xd0:xd1] = A[ys0:ys1, xs0:xs1]
    return out


def mode_filter(code, passes=2, values=16):
    """3x3 众数滤波，平局时保留原值。

    量化后的层场在阈值附近会被高频噪声打出「单角点毛刺」，把台地切成几十块
    肉眼看不见的小台阶；这一步把它们抹平，是台地能连成大片的关键。
    """
    L = code.astype(np.int32)
    R, C = L.shape
    rr = np.arange(R)[:, None]
    cc = np.arange(C)[None, :]
    for _ in range(passes):
        cnt = np.zeros((values, R, C), dtype=np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                S = _shift(L, -dy, -dx)
                m = S >= 0
                for v in range(values):
                    cnt[v] += (S == v) & m
        cnt[L, rr, cc] += 1          # 原值加一票 → 平局时保持不动
        L = np.argmax(cnt, axis=0).astype(np.int32)
    return L


def _multi_dijkstra(lab, passable, wmap):
    """多源 Dijkstra：每块台地的所有瓦片都是 0 距离源点，向外扩张。

    返回 (dist, owner, prev)。扩张到收敛后，相邻两瓦片 owner 不同的地方就是两块
    台地之间最省的通道口 —— 这等价于在「台地邻接图」上跑 Prim，一趟搞定。
    """
    H, W = lab.shape
    INF = np.int32(1 << 28)
    dist = np.full((H, W), INF, dtype=np.int32)
    owner = np.full((H, W), -1, dtype=np.int32)
    prev = np.full((H, W), -1, dtype=np.int32)
    pq = []
    for r, c in zip(*np.nonzero(lab >= 0)):
        dist[r, c] = 0
        owner[r, c] = lab[r, c]
        heapq.heappush(pq, (0, r * W + c))
    while pq:
        d, i = heapq.heappop(pq)
        r, c = divmod(i, W)
        if d > dist[r, c]:
            continue
        o = owner[r, c]
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if nr < 0 or nr >= H or nc < 0 or nc >= W or not passable[nr, nc]:
                continue
            nd = d + int(wmap[nr, nc])
            if nd < dist[nr, nc]:
                dist[nr, nc] = nd
                owner[nr, nc] = o
                prev[nr, nc] = i
                heapq.heappush(pq, (nd, nr * W + nc))
    return dist, owner, prev


def _plateau_levels(lab, nlab, layer):
    """每块台地（四角同层的连通平地）的层位 —— 取该块里平地的众数。"""
    lv = np.zeros(max(nlab, 1), dtype=np.int16)
    for k in range(nlab):
        m = lab == k
        if m.any():
            vals, cnt = np.unique(layer[:-1, :-1][m], return_counts=True)
            lv[k] = int(vals[np.argmax(cnt)])
    return lv


def _stamp_ramp(layer, is_water, ramp, ramp_band, u, v, lv_u, lv_v, run, margin,
                trace=None, force=True, max_jump=2):
    """在相邻瓦片 u / v（分属层位 lv_u / lv_v 的两块台地）之间盖一条 WE 合法斜坡。

    几何规则来自官方 51 张地图 / 3116 个 ramp 瓦片的实测（tools/diag_ramp.py）：
      * 斜坡是「垂直于崖壁 2 个瓦片厚」的一条带：
          瓦片 A（低侧基地）四角全在低层、四角全带 ramp 位；
          瓦片 B（台阶瓦片）2 角低 + 2 角高、四角全带 ramp 位；
        沿崖壁方向延续若干瓦片（官方长边集中在 5~8 条角点线）。
      * ramp 位只打 3 条角点线 = {高侧线, 共享线, 低侧线}，即 2 低 + 1 高。
        R 连块垂直于崖壁的厚度主导值就是 3（252/356）。
      * ramp 位绝不往高侧多给：官方「纯平地-高侧基地」只有 39/5346。
      * 层差恒为 1（Counter({1: 293, 2: 1})）。
      * cliffVariation 与斜坡无关（ramp 与普通崖壁取值分布几乎一致）→ 不用管。

    真正的几何是 **5 条角点线 / 4 个瓦片**（设低侧在左，层位记 lo < hi）：

        线:  L0=lo   L1=lo   L2=lo   L3=hi   L4=hi
        瓦片:    T0      T1      T2      T3
              平平   平平    台阶    平平
              (低侧翼) (基地) (台阶)  (高侧翼)

    T1/T2 是带 ramp 位的两块；T0/T3 是「翼」——它们必须是**平地**，否则斜坡
    两端接不上台地：低侧翼若成了崖壁瓦片，基地就悬空；高侧翼同理。
    早期实现只校验 L1/L3 两条线、不管翼，于是盖出来的斜坡有一头接不到台地，
    连通性自检就会报「有 1 座岛被崖壁切断」——症状像连通算法的问题，其实是几何没盖全。

    实现：
      1. 沿崖壁滑动 run+1 格，先找一段 5 条线**本来就全对**的位置（不动地形）；
      2. 找不到就「整形」：只要那 5 条线上的角点当前都还在 {lo, hi} 之内、且改动后
         相邻角点层差不超过 max_jump，就把 5 条线直接压成 lo/lo/lo/hi/hi。
         官方地图上的崖壁是 WE 刷出来的、天然齐整；我们的噪声地形常常是斜着走的
         锯齿崖（每两行错开一列），任何长度上都找不到齐整段，只能就地整形。

    返回 True/False。成功时 layer / ramp / ramp_band 已被就地修改。
    """
    def fail(msg):
        if trace is not None:
            trace.append(msg)
        return False

    rows, cols = layer.shape
    r, c = u
    r2, c2 = v
    dr, dc = r2 - r, c2 - c
    if abs(dr) + abs(dc) != 1 or lv_u == lv_v:
        return fail("不相邻或同层")
    hi, lo = max(lv_u, lv_v), min(lv_u, lv_v)
    if hi - lo != 1:
        return fail(f"层差 {hi - lo} ≠ 1")
    u_is_hi = lv_u == hi

    # 沿「垂直于崖壁」的轴：u 的外围线、共享线、v 的外围线，三条依次相邻
    if dc:
        axis = 0
        far_u = c if dc > 0 else c + 1
        shared = c + 1 if dc > 0 else c
        far_v = c + 2 if dc > 0 else c - 1
        n_perp, n_along = cols, rows
        base = r
    else:
        axis = 1
        far_u = r if dr > 0 else r + 1
        shared = r + 1 if dr > 0 else r
        far_v = r + 2 if dr > 0 else r - 1
        n_perp, n_along = rows, cols
        base = c

    far_hi = far_u if u_is_hi else far_v
    far_lo = far_v if u_is_hi else far_u
    dir_hi = 1 if far_hi > shared else -1
    dir_lo = 1 if far_lo > shared else -1
    out_hi = far_hi + dir_hi
    out_lo = far_lo + dir_lo
    p_lo, p_hi = min(out_lo, out_hi), max(out_lo, out_hi)
    if p_lo < margin or p_hi > n_perp - 1 - margin:
        return fail(f"贴边 (角点线 {p_lo}..{p_hi}, 需 ≥{margin})")

    def cell(a, p):
        return (a, p) if axis == 0 else (p, a)

    # 5 条角点线的目标层位：低侧 3 条全 lo，高侧 2 条全 hi
    want = ((out_lo, lo), (far_lo, lo), (shared, lo), (far_hi, hi), (out_hi, hi))
    want_of = dict(want)
    band = (far_lo, shared, far_hi)          # ramp 位只打这 3 条（官方口径）

    offsets = (0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6)
    reasons = []
    forced = None
    for off in offsets:
        a0 = base - run // 2 + off
        a1 = a0 + run
        if abs(off) > run * 2 or a0 < margin or a1 > n_along - 1 - margin:
            continue
        clean = True          # 5 条线本来就全对
        legal = True          # 整形不越界：都在 {lo,hi} 内、邻居层差也够近
        bad = None
        for a in range(a0, a1 + 1):
            for p in range(p_lo, p_hi + 1):
                rr, cc = cell(a, p)
                if is_water[rr, cc]:
                    clean = legal = False
                    bad = f"off{off:+d}@a{a}: 角点线 {p} 带水"
                    break
                cur = int(layer[rr, cc])
                if cur == want_of[p]:
                    continue
                # ⚠️ 这条角点线已经被**别的斜坡**占了、层位又跟我们要的不一样 →
                # 再盖下去就是把两条斜坡叠在一起。实测（seed=70259 / base=land）：
                # 两条互相垂直的斜坡交叉、或第二遍补刻在旧斜坡上平移 1 格重刻，
                # 交叉瓦片的四角会出现 3 个层值（如 4,4,2,3）→ 既不是台阶也不是
                # 基地，WE 渲出来的坡是坏的。这种情况直接放弃这个落点。
                # （层位恰好一致的重复盖章是幂等的，允许。）
                if ramp[rr, cc]:
                    clean = legal = False
                    bad = (f"off{off:+d}@a{a}: 角点线 {p} 已被既有斜坡占用"
                           f"（层位 {cur} ≠ 目标 {want_of[p]}）")
                    break
                clean = False
                if cur != lo and cur != hi:
                    legal = False
                    bad = f"off{off:+d}@a{a}: 角点线 {p} 层位={cur} 不在 {{{lo},{hi}}} 内"
                    break
                for na, np_ in ((a - 1, p), (a + 1, p),
                                (a, p - 1), (a, p + 1)):
                    if na < 0 or na >= n_along or np_ < 0 or np_ >= n_perp:
                        legal = False
                        break
                    nb = int(layer[cell(na, np_)])
                    if nb < lo - 1 or nb > hi + 1:
                        legal = False
                        bad = (f"off{off:+d}@a{a}: 整形会与邻格 {nb} 差超过 "
                               f"{max_jump} 层")
                        break
                if not legal:
                    break
            if not legal:
                break
        if clean:
            if _stamp_would_be_legal(layer, ramp, want, band, cell, a0, a1):
                return _commit(layer, ramp, ramp_band, want, band, cell, a0, a1,
                               mark=None)
            reasons.append(f"off{off:+d}: 邻域会留下非法斜坡瓦片")
            continue
        if not (force and legal):
            continue
        if not _stamp_would_be_legal(layer, ramp, want, band, cell, a0, a1):
            reasons.append(f"off{off:+d}: 邻域会留下非法斜坡瓦片")
            continue
        if forced is None:
            forced = (off, a0, a1)
        if bad:
            reasons.append(bad)
    if forced is not None:
        off, a0, a1 = forced
        return _commit(layer, ramp, ramp_band, want, band, cell, a0, a1, mark=off)
    return fail("; ".join(reasons[:3]) if reasons else "无可用偏移")


def _stamp_would_be_legal(layer, ramp, want, band, cell, a0, a1):
    """试算：按 want / band 盖下去之后，落点邻域会不会出现「非法斜坡瓦片」。

    非法 = 四角全带 ramp 位，但四角层位既不是全同层、也不是恰好差 1 级的台阶。

    为什么必须试算：两条斜坡的落点只要**挨着**（实测：一条横坡的列与另一条竖坡的
    列紧邻，或者补刻时在旧斜坡旁边平移 1 格再盖一条），中间那列瓦片的四角就会分别
    落在两条斜坡的 4 条不同角点线上，层位混成 3 个值（如 3,2,4,3；4,4,2,3）
    —— 既不是台阶也不是基地，WE 渲出来的坡是坏的。
    单纯的「落点是否重叠」判据抓不到这种**紧邻但不相交**的情况，所以这里直接按
    最终判据（每个瓦片要么是台阶、要么是基地）试算，不合格就换落点。
    """
    lines = [p for p, _ in want]
    band_set = set(band)
    p0, p1 = min(lines) - 2, max(lines) + 2     # 窗口多留 1 圈
    a0w, a1w = a0 - 2, a1 + 2
    lay = {}
    for p in range(p0, p1 + 1):
        for a in range(a0w, a1w + 1):
            rr, cc = cell(a, p)
            lay[(p, a)] = int(layer[rr, cc])
    for p, t in want:                            # 5 条角点线压到目标层位
        for a in range(a0, a1 + 1):
            lay[(p, a)] = int(t)
    marked = set()
    for p in range(p0, p1 + 1):
        for a in range(a0w, a1w + 1):
            rr, cc = cell(a, p)
            if ramp[rr, cc]:
                marked.add((p, a))
    for p in band_set:                           # 中间 3 条线打 ramp 位
        for a in range(a0, a1 + 1):
            marked.add((p, a))
    for p in range(p0, p1):
        for a in range(a0w, a1w):
            corners = ((p, a), (p + 1, a), (p, a + 1), (p + 1, a + 1))
            if not all(c in marked for c in corners):
                continue
            q = sorted(set(lay[c] for c in corners))
            if len(q) == 1 or (len(q) == 2 and q[1] - q[0] == 1):
                continue                              # 基地 / 台阶：合法
            return False
    return True


def _commit(layer, ramp, ramp_band, want, band, cell, a0, a1, mark=None):
    """把 5 条角点线压成 want 的目标层位，并给中间 3 条打 ramp 位、抹平起伏。"""
    for a in range(a0, a1 + 1):
        for p, t in want:
            rr, cc = cell(a, p)
            layer[rr, cc] = t
    for a in range(a0, a1 + 1):
        for p in band:
            rr, cc = cell(a, p)
            ramp[rr, cc] = True
            ramp_band[rr, cc] = True
    return True



def carve_ramps(layer, is_water, max_ramps=None, cliff_cost=6, cand_cap=0,
                edge_cost=8, edge_band=2, run=4, margin=2, max_jump=2, force=True,
                prev_ramps=None):
    """按连通性需要刻斜坡，保证每块台地都有通道。

    做法:
      1. 每块台地（四角同层的连通平地）是一个节点；
      2. 多源 Dijkstra 向外扩张（穿过崖壁的代价高、贴地图边更贵），得到台地邻接图；
      3. 在邻接图上跑 Kruskal 最小生成树，确定「连通哪几对台地、从哪个口子过」；
      4. 在每个选中的口子上「盖」一条 WE 合法斜坡（见 _stamp_ramp）。

    cand_cap: 每对台地最多试几个候选口子（0 = 不限）。**别调小**：Dijkstra 最省的
    那几个口子恰好落在崖壁最薄最碎的「尖角」上（两块台地只在一个锯齿点相碰），
    那里高侧台地厚度不足，盖不上官方几何的斜坡；而真正齐整的崖段往往排在后面。
    实测 128x128 图：上限 8 → 有一对台地的 8 个最省口子全废、整岛被切断；
    上限 ≥16 才能选到合格口子。默认不限，靠「成功即 break」自然收口。

    返回 (ramp, layer, ramp_band, info)。注意 **layer 会被就地修改**：
    盖章时要压下共享角点线，而连通性自检必须用改完之后的层位。

    prev_ramps: 上一遍已经刻好的 (ramp, ramp_band)。主流程会刻两遍（第二遍用**最终**的
    is_water 复查后补刻），第二遍必须把第一遍的结果传进来 —— 否则它以为地图上
    一条斜坡都没有，会在同一个崖壁上**再刻一条平移 1 格的重叠斜坡**，两条叠在
    一起就会产出「四角三个层值」的非法斜坡瓦片（实测 seed=70259 就是这么来的）。
    ⚠️ 别把这个参数叫 `prev`：下面 `_multi_dijkstra` 的第三个返回值也叫 prev，
    解包时会把它覆盖掉（曾踩过，症状是 ramp 变成 1 维、盖斜坡时 index error）。
    """
    spread, grad, line, dry = _tile_derivatives(layer, is_water)
    H, W = spread.shape
    # 只要「四角都不带水」就算通路：崖壁瓦片也能走（代价高而已）。
    # 早先这里加了 spread<=2 的门槛，会漏掉相邻角点层差 2 造成的 spread=3/4 瓦片，
    # 把同一座岛上的两块台地误判成「互不相邻」→ 那座岛永远补不上斜坡。
    passable = dry
    flat = (spread == 0) & dry
    lab, nlab = _components(flat)
    empty = np.zeros(layer.shape, dtype=bool)
    if nlab <= 1 or (lab < 0).all():
        return empty, layer, empty, {
            "components": int(nlab), "ramps": 0, "candidates": 0, "skipped": 0}

    # 代价图：平地便宜、崖壁贵；贴地图边再贵一点（不禁止，只在别无选择时才走边）
    wmap = np.where(flat, 1, cliff_cost).astype(np.int32)
    b = max(0, int(edge_band))
    if b and H > 2 * b and W > 2 * b:
        wmap[:b, :] += edge_cost
        wmap[-b:, :] += edge_cost
        wmap[:, :b] += edge_cost
        wmap[:, -b:] += edge_cost

    dist, owner, _bfs_prev = _multi_dijkstra(lab, passable, wmap)
    plevel = _plateau_levels(lab, nlab, layer)

    # 候选口子条目 = (权重, 低侧瓦片索引, 高侧瓦片索引, 低侧层位, 高侧层位)。
    # 显式带上两个层位，别在盖章时再从 key 反推 —— key 是排序过的 owner 对，
    # 跟 u/v 的先后顺序无关，反推会把「谁高谁低」搞反、几何整个镜像。
    def add(pair_lists, o1, o2, w, u, v, lu, lv):
        if o1 < 0 or o2 < 0 or o1 == o2:
            return
        pair_lists.setdefault((min(o1, o2), max(o1, o2)), []).append((w, u, v, lu, lv))

    def owner_at(rr, cc):
        if 0 <= rr < H and 0 <= cc < W:
            return int(owner[rr, cc])
        return -1

    # 口子来源①（首选）：直接读「崖壁瓦片」的层位跳变方向。
    # 斜坡是垂直于崖壁的一条带，所以带的方向必须跟真实崖壁垂直。只按「相邻瓦片
    # owner 不同」找口子（来源②）会翻车：那种相邻只是 Dijkstra 的分界，在锯齿崖上
    # 常常**跟崖壁走向平行**，盖出来的带会横切台地、把台地拦腰切断（切下来的碎块
    # 就成了连不上的孤岛）。这里从一个 spread==1 的崖壁瓦片反推：四角谁低谁高就
    # 知道墙在哪条角点线上、低侧/高侧瓦片各是谁 —— 带的方向天然正确。
    # 台地身份用「墙外侧再一格」的瓦片 owner 去认（2u-v / 2v-u），不能用 u/v 自己
    # 的 owner：崖壁瓦片常被判给高侧那块台地，那样两边 owner 相同、口子直接被丢掉。
    cliff_mouths = {}
    for r in range(H):
        for c in range(W):
            a = layer[r, c]; b = layer[r, c + 1]
            cc = layer[r + 1, c]; d = layer[r + 1, c + 1]
            lo = min(a, b, cc, d); hi = max(a, b, cc, d)
            if hi - lo != 1:
                continue
            if is_water[r, c] or is_water[r, c + 1] or is_water[r + 1, c] or is_water[r + 1, c + 1]:
                continue
            u = v = None
            if a == cc and b == d and a != b:            # 墙沿列方向
                u, v = ((r, c), (r, c + 1)) if a == lo else ((r, c + 1), (r, c))
            elif a == b and cc == d and a != cc:         # 墙沿行方向
                u, v = ((r, c), (r + 1, c)) if a == lo else ((r + 1, c), (r, c))
            if u is None:
                continue                                  # 对角跳变，带方向不明确
            # 崖壁瓦片可以在最后一行/列，但「墙外侧那一格」的瓦片必须真实存在
            if not (0 <= u[0] < H and 0 <= u[1] < W
                    and 0 <= v[0] < H and 0 <= v[1] < W):
                continue
            o1 = owner_at(2 * u[0] - v[0], 2 * u[1] - v[1])
            o2 = owner_at(2 * v[0] - u[0], 2 * v[1] - u[1])
            if o1 < 0:
                o1 = int(owner[u])
            if o2 < 0:
                o2 = int(owner[v])
            add(cliff_mouths, o1, o2, int(dist[u]) + int(dist[v]),
                u[0] * W + u[1], v[0] * W + v[1], lo, hi)

    # 口子来源②（兜底）：相邻瓦片 owner 不同。方向不一定对，只在来源①给不出
    # 口子时才用（否则这一对台地就完全连不上了）。
    adj_mouths = {}
    for r in range(H):
        for c in range(W):
            o = int(owner[r, c])
            if o < 0:
                continue
            for nr, nc in ((r + 1, c), (r, c + 1)):
                if nr >= H or nc >= W:
                    continue
                o2 = int(owner[nr, nc])
                if o2 < 0 or o2 == o:
                    continue
                add(adj_mouths, o, o2, int(dist[r, c]) + int(dist[nr, nc]),
                    r * W + c, nr * W + nc, int(plevel[o]), int(plevel[o2]))

    cand = {}
    for k, lst in adj_mouths.items():
        cand[k] = sorted(cliff_mouths.get(k, [])) + sorted(lst)
    for k, lst in cliff_mouths.items():
        if k not in cand:
            cand[k] = sorted(lst)
    if cand_cap:
        for lst in cand.values():
            del lst[cand_cap:]

    parent = list(range(nlab))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ramp = (np.zeros(layer.shape, dtype=bool) if prev_ramps is None
            else prev_ramps[0].copy())
    ramp_band = (np.zeros(layer.shape, dtype=bool) if prev_ramps is None
                 else prev_ramps[1].copy())

    # 已经「走得到」的台地对：不用再刻斜坡。
    # 第二遍补刻时 ramp 里已经有第一遍的斜坡，但**台地**（四角同层的平地）仍然是各自
    # 一块 —— 只看 flat 连通块的话，每一对台地都显得还没连通，于是第二遍会把已经
    # 连上的台地对**再刻一遍**（刻在别的口子上）→ 斜坡数量翻倍，还容易和旧斜坡打架。
    # 这里先用「平地 | 既有斜坡瓦片」算一遍可走连通块，凡是两块台地已经在一块里的
    # 就标记为已完成。
    done = set()
    if ramp.any():
        all4_prev = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
        wlab0, _ = _components(flat | all4_prev)

        def wlab_at(rr, cc):
            if 0 <= rr < H and 0 <= cc < W:
                return int(wlab0[rr, cc])
            return -1

        for key, lst in cand.items():
            for _w, u, v, _lu, _lv in lst:
                ur, uc = divmod(u, W)
                vr, vc = divmod(v, W)
                # 墙外侧再一格才是台地本体（与上面认台地身份同一个口径）
                lab_a = wlab_at(2 * ur - vr, 2 * uc - vc)
                lab_b = wlab_at(2 * vr - ur, 2 * vc - uc)
                if lab_a >= 0 and lab_a == lab_b:
                    done.add(key)
                    break

    carved = 0
    skipped = 0
    for key, lst in sorted(cand.items(), key=lambda kv: kv[1][0][0]):
        if key in done or find(key[0]) == find(key[1]):
            continue
        lv1, lv2 = int(plevel[key[0]]), int(plevel[key[1]])
        if abs(lv1 - lv2) != 1:          # 官方斜坡层差恒为 1，跨 2 层的口子不盖
            skipped += 1
            continue
        stamped = False
        # 优先「不动地形就能盖」的口子，找不到齐整崖段才允许整形。
        # 整形会改动 5 条角点线上的角点，在台地又窄又碎的地方容易把台地拦腰切断
        # （切下来的碎块就成了连不上的孤岛），所以能不整形就不整形。
        for rr in (run, max(2, run - 1), max(2, run - 2)):
            for fc in ((True, False) if force else (False,)):
                for _, u, v, lu, lv in lst:
                    r, c = divmod(u, W)
                    r2, c2 = divmod(v, W)
                    if _stamp_ramp(layer, is_water, ramp, ramp_band,
                                   (r, c), (r2, c2), lu, lv, rr, margin,
                                   force=fc, max_jump=max_jump):
                        stamped = True
                        break
                if stamped:
                    break
            if stamped:
                break
        if not stamped:                  # 整段崖壁都不齐整，这一对台地这次连不上
            skipped += 1
            continue
        parent[find(key[0])] = find(key[1])
        carved += 1
        if max_ramps is not None and carved >= max_ramps:
            break
    return ramp, layer, ramp_band, {
        "components": int(nlab), "ramps": carved,
        "candidates": len(cand), "skipped": skipped}


def clean_regions(code, min_island=32, min_lake=16):
    """清理碎岛碎塘:

      * 面积 < min_island 的陆地碎岛 → 并入水（贴地图边界的照样清，那里本来就不可达）；
      * 面积 < min_lake 且**不贴**地图边界的内陆水塘 → 填成邻域最常见的陆地高度
        （贴边的水域当成海，不动）。
    """
    code = code.copy()
    R, C = code.shape
    changed_i = changed_w = 0

    def border_components(mask, lab, n):
        """返回与地图最外圈相接的连通块编号集合。"""
        edge = np.zeros_like(mask)
        edge[0, :] = edge[-1, :] = True
        edge[:, 0] = edge[:, -1] = True
        hit = lab[mask & edge]
        return set(int(v) for v in np.unique(hit) if v >= 0)

    if min_island > 0:
        lab, n = _components(code > 0)
        for i in range(n):
            m = lab == i
            if m.sum() < min_island:
                code[m] = 0
                changed_i += 1

    if min_lake > 0:
        lab, n = _components(code == 0)
        ocean = border_components(code == 0, lab, n)
        for i in range(n):
            m = lab == i
            if m.sum() >= min_lake or i in ocean:
                continue
            vals = []
            ys, xs = np.nonzero(m)
            for y, x in zip(ys, xs):
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < R and 0 <= nx < C and code[ny, nx] > 0:
                        vals.append(int(code[ny, nx]))
            if not vals:
                continue
            code[m] = int(np.bincount(np.array(vals)).argmax())
            changed_w += 1
    return code, changed_i, changed_w


def connectivity_report(layer, is_water, ramp):
    """逐个陆地岛检查「岛内可走区域是否连成一体」。

    注意不能拿「陆地连通块数」和「可走连通块数」直接比：前者把崖壁瓦片也算进去，
    口径不同永远不可能相等。正确判据是——对每个陆地岛，落在它里面的可走瓦片
    只能属于同一个可走连通块。
    返回 (陆地岛数, 可走连通块数, 被崖壁切断的岛数)。
    """
    spread, grad, line, dry = _tile_derivatives(layer, is_water)
    flat = (spread == 0) & dry
    all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
    walk = flat | all4
    ilab, n_island = _components(dry)
    wlab, n_walk = _components(walk)
    bad = 0
    for i in range(n_island):
        labels = np.unique(wlab[(ilab == i) & walk])
        labels = labels[labels >= 0]
        if labels.size > 1:
            bad += 1
    return int(n_island), int(n_walk), int(bad)


def _cand_levels(layer, ys, xs):
    """碎块周围（紧邻角点）出现过的层位，按出现次数降序 —— 合并目标候选。"""
    seen, vals = set(), []
    rows, cols = layer.shape
    for y, x in zip(ys, xs):
        for yy, xx in ((y, x), (y, x + 1), (y + 1, x), (y + 1, x + 1)):
            for ny, nx in ((yy - 1, xx), (yy + 1, xx), (yy, xx - 1), (yy, xx + 1)):
                if 0 <= ny < rows and 0 <= nx < cols and (ny, nx) not in seen:
                    seen.add((ny, nx))
                    vals.append(int(layer[ny, nx]))
    if not vals:
        return []
    v, c = np.unique(np.array(vals), return_counts=True)
    return [int(v[k]) for k in np.argsort(-c)]


def _local_merge_ok(layer, is_water, ramp, keep, ys, xs, tgt, max_jump):
    """在局部窗口里试算：把碎块压到 tgt 后，层差不超标且碎块能接上主块。"""
    r0 = max(0, int(ys.min()) - 2)
    r1 = min(layer.shape[0], int(ys.max()) + 5)
    c0 = max(0, int(xs.min()) - 2)
    c1 = min(layer.shape[1], int(xs.max()) + 5)
    sub = layer[r0:r1, c0:c1].copy()
    ys2, xs2 = ys - r0, xs - c0
    for y, x in zip(ys2, xs2):
        sub[y, x] = sub[y, x + 1] = sub[y + 1, x] = sub[y + 1, x + 1] = tgt
    # 只看改动点附近的层差：窗口里本来就有别处的崖壁，全窗口取最大值会误判
    for y, x in zip(ys2, xs2):
        for yy, xx in ((y, x), (y, x + 1), (y + 1, x), (y + 1, x + 1)):
            for ny, nx in ((yy - 1, xx), (yy + 1, xx), (yy, xx - 1), (yy, xx + 1)):
                if 0 <= ny < sub.shape[0] and 0 <= nx < sub.shape[1]:
                    if abs(int(sub[ny, nx]) - tgt) > max_jump:
                        return False
    water = is_water[r0:r1, c0:c1]
    rsub = ramp[r0:r1, c0:c1]
    spread = (np.maximum(np.maximum(sub[:-1, :-1], sub[:-1, 1:]),
                         np.maximum(sub[1:, :-1], sub[1:, 1:]))
              - np.minimum(np.minimum(sub[:-1, :-1], sub[:-1, 1:]),
                           np.minimum(sub[1:, :-1], sub[1:, 1:])))
    dry_t = ~(water[:-1, :-1] | water[:-1, 1:] | water[1:, :-1] | water[1:, 1:])
    walk_t = ((spread == 0) & dry_t) | (rsub[:-1, :-1] & rsub[:-1, 1:]
                                        & rsub[1:, :-1] & rsub[1:, 1:])
    keep_t = keep[r0:r1 - 1, c0:c1 - 1]
    # 从碎块往外泛洪，看能不能碰到主块
    H, W = walk_t.shape
    seen = np.zeros_like(walk_t, dtype=bool)
    stack = [(int(ys2[0]), int(xs2[0]))]
    if not walk_t[stack[0]]:
        return False
    seen[stack[0]] = True
    while stack:
        y, x = stack.pop()
        if keep_t[y, x]:
            return True
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < H and 0 <= nx < W and walk_t[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                stack.append((ny, nx))
    return False


def merge_orphan_flats(layer, is_water, ramp, min_area=24, max_jump=2, rounds=6):
    """把被斜坡端头切下来的「孤立小块可走平地」并进同岛的主可走块。

    刻斜坡要在崖壁上压出 5 条整齐角点线，斜坡两个端头必然切出新崖壁；如果端头
    原本是一片平地，就会被切下一小块（几格）孤立出来。这种碎片在 WE 里就是几格
    上不去的台地，留着既难看又让连通性自检一直报「有 1 座岛被崖壁切断」。
    做法：逐岛取面积最大的可走块为主块，其余 <= min_area 的纯平地碎块，按邻接
    角点出现过的层位逐个试算（局部泛洪确认真能接上主块）后整体压过去。
    含 ramp 位的碎块属于斜坡本体，不动。返回合并掉的碎块数，layer 就地修改。
    """
    merged = 0
    for _ in range(rounds):
        spread, grad, line, dry = _tile_derivatives(layer, is_water)
        flat = (spread == 0) & dry
        all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
        walk = flat | all4
        ilab, n_isl = _components(dry)
        wlab, n_walk = _components(walk)
        did = 0
        for i in range(n_isl):
            m_isl = ilab == i
            ws = [int(v) for v in np.unique(wlab[m_isl & walk]) if v >= 0]
            if len(ws) <= 1:
                continue
            sizes = {w: int(((wlab == w) & m_isl).sum()) for w in ws}
            main = max(sizes, key=sizes.get)
            if sizes[main] < min_area * 3:
                continue                      # 岛上没有明显的主块，不动
            keep = wlab == main
            for w in ws:
                if w == main or sizes[w] > min_area or sizes[w] * 4 >= sizes[main]:
                    continue
                m = wlab == w
                ys, xs = np.nonzero(m)
                if not flat[ys, xs].all():
                    continue                  # 含 ramp 位 → 是斜坡的一部分
                for tgt in _cand_levels(layer, ys, xs):
                    if _local_merge_ok(layer, is_water, ramp, keep, ys, xs,
                                       tgt, max_jump):
                        for y, x in zip(ys, xs):
                            layer[y, x] = layer[y, x + 1] = tgt
                            layer[y + 1, x] = layer[y + 1, x + 1] = tgt
                        did += 1
                        break
        merged += did
        if did == 0:
            break
    return merged


def ramp_report(layer, ramp):
    """斜坡几何自检：把 ramp 角点按连通块分组，核对是否符合官方几何。

    官方基准（51 张官方地图 / 3116 个 ramp 瓦片）：
      * 垂直于崖壁的厚度 = 3 条角点线（252/356 块），即 2 个瓦片；
      * 瓦片构成 = 1 个「四角全低」的基地瓦片 + 1 个「2 低 2 高」的台阶瓦片，
        且两者四角全带 ramp 位；
      * 层差恒为 1。
    这里返回若干行文本，供主流程打印。
    """
    H, W = ramp.shape
    seen = np.zeros_like(ramp, dtype=bool)
    blocks = []
    for r0 in range(H):
        for c0 in range(W):
            if not ramp[r0, c0] or seen[r0, c0]:
                continue
            stack = [(r0, c0)]
            seen[r0, c0] = True
            n = 0
            rmin = rmax = r0
            cmin = cmax = c0
            while stack:
                r, c = stack.pop()
                n += 1
                rmin, rmax = min(rmin, r), max(rmax, r)
                cmin, cmax = cmin, max(cmax, c)
                for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= nr < H and 0 <= nc < W and ramp[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        stack.append((nr, nc))
            blocks.append((n, rmax - rmin + 1, cmax - cmin + 1))
    if not blocks:
        return ["斜坡几何自检: 无斜坡"]
    thick = Counter(min(bw, bh) for _, bw, bh in blocks)
    # 瓦片构成核对
    step = flat_low = flat_high = other = 0
    for r in range(H - 1):
        for c in range(W - 1):
            q = (layer[r, c], layer[r, c + 1], layer[r + 1, c], layer[r + 1, c + 1])
            if not (ramp[r, c] and ramp[r, c + 1] and ramp[r + 1, c] and ramp[r + 1, c + 1]):
                continue
            u = sorted(set(q))
            if len(u) == 1:
                flat_low += 1
            elif len(u) == 2 and u[1] - u[0] == 1 and q.count(u[0]) == 2:
                step += 1
            elif len(u) == 2 and u[1] - u[0] == 1:
                flat_high += 1
            else:
                other += 1
    # 「厚度 = 3」这一条是官方**网格对齐**崖壁的统计主导值，只有 252/356。
    # 现在悬崖区是噪声形状的锯齿边界（2026-09-16 改成局部悬崖后），两条斜坡很容易
    # 连成一块、包围盒就不是正方 → 厚度偏离属于观感差异，不是错误。
    # 真正的不变量只有一条：**不能出现「既不是台阶也不是基地」的非法瓦片**。
    ok = (other == 0)
    return [
        f"斜坡几何自检: {len(blocks)} 块  {'✔ 没有非法瓦片' if ok else '✘ 有非法瓦片'}",
        f"  垂直崖壁厚度分布(角点线数): {dict(sorted(thick.items()))}"
        f"   ← 官方主导值 3（偏离 = 多条斜坡连成一片，观感差异，非错误）",
        f"  瓦片构成: 台阶(2低2高) {step} / 四角全低基地 {flat_low}"
        f" / 四角全高 {flat_high} / 其他(非法) {other}",
    ]


def drop_unreachable_terraces(layer, is_water, ramp, H_we, plane_layer,
                              max_rounds=4):
    """把「上不去」的台地整块撤掉 —— 台地靠斜坡才走得上去，而 carve_ramps 在噪声
    形状的锯齿崖上不保证 100% 成功；剩下的台地在游戏里就是「看得见、上不去」的废地。

    判据沿用 connectivity_report 那套「可走瓦片块」口径：每座陆地岛里最大的可走
    区域是主地形，其余可走块就是够不着的台地。撤掉 = layer 拉回水面层 + 高度减掉
    128×层差（正好还原成没造悬崖之前的连续高度）→ 变成普通可走地形，通行性最好。

    撤掉一块可能让别的块变可达，所以最多迭代 max_rounds 轮。
    返回 (H_we, layer, is_water, ramp, 撤掉的块数)。
    """
    dropped = 0
    for _ in range(max_rounds):
        spread, grad, line, dry = _tile_derivatives(layer, is_water)
        flat = (spread == 0) & dry
        all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
        walk = flat | all4
        ilab, n_island = _components(dry)
        wlab, n_walk = _components(walk)
        need = np.zeros(walk.shape, dtype=bool)
        found = False
        for i in range(n_island):
            # ⚠️ ilab / wlab / walk 都是**瓦片级**（(rows-1, cols-1)），不需要再做
            #    四角与运算 —— 再降一次维就和 walk 对不上了。
            m = (ilab == i) & walk
            if not m.any():
                continue
            labs = np.unique(wlab[m])
            labs = labs[labs >= 0]
            if labs.size <= 1:
                continue
            found = True
            sizes = sorted(((int(np.count_nonzero(wlab == L)), int(L)) for L in labs),
                           reverse=True)
            for _, L in sizes[1:]:                 # 最大的那块留作主地形
                need |= (wlab == L) & walk
        if not found or not need.any():
            break
        corner = np.zeros(layer.shape, dtype=bool)
        corner[:-1, :-1] |= need
        corner[:-1, 1:] |= need
        corner[1:, :-1] |= need
        corner[1:, 1:] |= need
        delta = layer.astype(np.int32) - int(plane_layer)
        sel = corner & (delta > 0)
        if not sel.any():
            break
        H_we = H_we - np.where(sel, (delta * 128.0).astype(np.float32), 0.0)
        layer = np.where(sel, np.int16(plane_layer), layer).astype(np.int16)
        ramp = np.where(corner, False, ramp)
        is_water = H_we < 0.0
        dropped += 1
    return H_we, layer, is_water, ramp, dropped


def _illegal_ramp_count(layer, ramp):
    """数「非法斜坡瓦片」：四角全带 ramp 位、但四角层位既不是全同层、也不是差 1 级的台阶。

    在瓦片级向量化算：`spread = max - min > 1` 就是非法（spread 只可能是 0/1 时一定合法，
    因为 max-min ≤ 1 只允许 2 个取值）。与 `ramp_report` 的 `other` 判据同源。
    """
    all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
    if not all4.any():
        return 0
    a = layer[:-1, :-1]; b = layer[:-1, 1:]
    c_ = layer[1:, :-1]; d = layer[1:, 1:]
    mx = np.maximum(np.maximum(a, b), np.maximum(c_, d))
    mn = np.minimum(np.minimum(a, b), np.minimum(c_, d))
    return int((all4 & (mx - mn > 1)).sum())


def drill_ramps_for_connectivity(layer, is_water, ramp, max_rounds=4,
                                 max_path=48):
    """连通性硬兜底：把分隔两块可走区域的**崖壁瓦片**直接改成斜坡瓦片。

    为什么需要它：carve_ramps 在噪声形状的锯齿崖上不保证 100% 成功，漏掉的地方会
    出现「一座陆地岛被崖壁切成两半」—— 游戏里就是「看得见、过不去」。这里完全不依赖
    斜坡算法，而是用 0-1 BFS（可走瓦片代价 0 / 崖壁瓦片代价 1）从每座岛**最大的**
    可走块出发，找到通往其余可走块的最便宜路径，把路径上的崖壁瓦片四角都打上 0x10。
    斜坡瓦片按定义可走 → 两块立刻接通。

    代价：那几格是从崖壁上硬开出来的一个坡（观感略生硬），但比「过不去」好得多。

    🔴 只从**层差恰好 1** 的崖壁瓦片开坡（`spread == 1`）。层差 ≥2 的崖壁开出来的是
    「四角只有 2 个层值、却差 2 级」的非法斜坡瓦片（实测 seed=93014/93562/92329），
    WE 渲出来的坡是坏的，也过不去。1 级斜坡跨不过 2 级崖壁 —— 这种台地本来就上不去，
    交给主流程后面的「撤台地」兜底，而不是硬开一个坏坡。
    返回 (ramp, 开的坡瓦片数, 被迫放弃的位置数)。
    """
    rows, cols = layer.shape
    R, C = rows - 1, cols - 1
    opened = 0
    reverted = 0
    for _ in range(max_rounds):
        spread, grad, line, dry = _tile_derivatives(layer, is_water)
        flat = (spread == 0) & dry
        all4 = ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:]
        walk = flat | all4
        drillable = dry & ~walk & (spread == 1)      # 只能开 1 级坡
        ilab, n_island = _components(dry)
        wlab, n_walk = _components(walk)
        changed = False
        for i in range(n_island):
            m = (ilab == i) & walk
            if not m.any():
                continue
            labs = np.unique(wlab[m])
            labs = labs[labs >= 0]
            if labs.size <= 1:
                continue
            sizes = sorted(((int(np.count_nonzero(wlab == L)), int(L)) for L in labs),
                           reverse=True)
            # 0-1 BFS：起点 = 最大的可走块
            INF = 1 << 30
            dist = np.full((R, C), INF, dtype=np.int32)
            par = np.full((R, C), -1, dtype=np.int64)
            dq = deque()
            sy, sx = np.nonzero((wlab == sizes[0][1]) & walk)
            for y, x in zip(sy.tolist(), sx.tolist()):
                dist[y, x] = 0
                dq.append((y, x))
            while dq:
                y, x = dq.popleft()
                d = dist[y, x]
                if d >= max_path:
                    continue
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if not (0 <= ny < R and 0 <= nx < C):
                        continue
                    if not (walk[ny, nx] or drillable[ny, nx]):
                        continue          # 水格 / 2 级崖壁：穿不过去
                    nd = d + (0 if walk[ny, nx] else 1)
                    if nd < dist[ny, nx]:
                        dist[ny, nx] = nd
                        par[ny, nx] = y * C + x
                        if walk[ny, nx]:
                            dq.appendleft((ny, nx))
                        else:
                            dq.append((ny, nx))
            for _, L in sizes[1:]:
                ty, tx = np.nonzero((wlab == L) & walk)
                ty, tx = ty.tolist(), tx.tolist()
                if not ty:
                    continue
                k = int(np.argmin([dist[y, x] for y, x in zip(ty, tx)]))
                cy, cx = ty[k], tx[k]
                if dist[cy, cx] >= INF:
                    continue                         # 实在够不着（路径太长）
                # 回溯，把路径上的崖壁瓦片改成斜坡瓦片
                guard = 0
                placed = False
                while dist[cy, cx] > 0 and guard <= max_path:
                    guard += 1
                    p = par[cy, cx]
                    if p < 0:
                        break
                    py, px = divmod(int(p), C)
                    if drillable[cy, cx]:
                        before = _illegal_ramp_count(layer, ramp)
                        ramp[cy, cx] = ramp[cy, cx + 1] = True
                        ramp[cy + 1, cx] = ramp[cy + 1, cx + 1] = True
                        if _illegal_ramp_count(layer, ramp) > before:
                            # 这个坡会把邻域里别的瓦片变成非法斜坡 → 撤销
                            ramp[cy, cx] = ramp[cy, cx + 1] = False
                            ramp[cy + 1, cx] = ramp[cy + 1, cx + 1] = False
                            reverted += 1
                        else:
                            opened += 1
                            placed = True
                    cy, cx = py, px
                changed = changed or placed
        if not changed:
            break
    return ramp, opened, reverted


def tile_layer(layer):
    """每个瓦片取四角均值取整，作为该瓦片的层值。"""
    a = layer[:-1, :-1].astype(np.int32); b = layer[:-1, 1:].astype(np.int32)
    c = layer[1:, :-1].astype(np.int32); d = layer[1:, 1:].astype(np.int32)
    return ((a + b + c + d + 2) // 4).astype(np.int16)


def despeckle_layers(layer, min_area=8, passes=3, max_jump=1):
    """把过小的台地并进相邻台地，减少碎斑；返回 (新 layer, 合并次数)。"""
    layer = layer.copy()
    merged = 0
    for _ in range(passes):
        tl = tile_layer(layer)
        H, W = tl.shape
        lab = np.full((H, W), -1, dtype=np.int32)
        cur = 0
        comps = []
        for r in range(H):
            for c in range(W):
                if lab[r, c] >= 0:
                    continue
                v = tl[r, c]
                stack = [(r, c)]
                lab[r, c] = cur
                cells = []
                while stack:
                    y, x = stack.pop()
                    cells.append((y, x))
                    for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                        if 0 <= ny < H and 0 <= nx < W and lab[ny, nx] < 0 and tl[ny, nx] == v:
                            lab[ny, nx] = cur
                            stack.append((ny, nx))
                comps.append((v, cells))
                cur += 1
        changed = False
        for v, cells in comps:
            if len(cells) >= min_area:
                continue
            # 统计相邻台地的层值，取最常见的并进去
            near = []
            for y, x in cells:
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < H and 0 <= nx < W and tl[ny, nx] != v:
                        near.append(int(tl[ny, nx]))
            if not near:
                continue
            target = int(np.bincount(np.array(near)).argmax())
            for y, x in cells:
                layer[y:y + 2, x:x + 2] = target
            merged += 1
            changed = True
        if changed:
            layer = limit_neighbor_jump(layer, max_jump=max_jump)
        if not changed:
            break
    return layer, merged


def make_tmp(name):
    """给本次运行开一个干净且独占的临时目录。

    用「父目录尽力清空 + 本次唯一子目录」而不是复用固定目录：
      - 唯一子目录 → 永远不会有上次残留的文件被当成新数据（MPQ 提取失败时最容易踩）
      - 父目录尽力清空 → 正常环境下临时文件不会越积越多
      - 删除被拦下来（安全软件 / 系统删除保护）时不影响本次生成，也不影响正确性
    """
    parent = os.path.join(HERE, "_tmp", name)
    try:
        if os.path.exists(parent):
            shutil.rmtree(parent, ignore_errors=True)
    except BaseException:
        pass
    tmp = os.path.join(parent, "r%d_%d" % (os.getpid(), int(time.time() * 1000) % 100000))
    os.makedirs(tmp, exist_ok=True)
    return tmp


def drop_tmp(tmp):
    """收尾清理，纯尽力而为 —— 失败绝不能影响已经写好的地图。"""
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except BaseException:
        pass


def main():
    args = []
    opts = {}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k, sep, v = a[2:].partition("=")
            if sep:
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]
                i += 1
            else:
                opts[k] = True
        else:
            args.append(a)
        i += 1

    if not args:
        print(__doc__)
        return 1
    map_path = args[0]
    seed = int(opts.get("seed", 20260915))
    freq = float(opts.get("freq", 1.6))
    # 高度层区间：地形（含水面之上的全部陆地台地）只占 [layer_min, layer_max] 这几层。
    # WE 里每上/下一层线 = 128 高度单位，所以层区间直接决定「悬崖能爬多高」。
    layer_min = int(opts.get("layer-min", LAYER_ZERO))
    levels = int(opts.get("layers", 4))
    layer_max = int(opts.get("layer-max", layer_min + levels - 1))
    water_frac = float(opts.get("water", 0.30))
    octaves = int(opts.get("octaves", 2))
    max_jump = int(opts.get("max-jump", 2))
    smooth = int(opts.get("smooth", 2))
    level_bias = float(opts.get("level-bias", 2.0))
    ramps_opt = str(opts.get("ramps", "auto"))
    ramp_run = int(opts.get("ramp-run", 4))
    ramp_force = str(opts.get("ramp-force", "1")) not in ("0", "false", "no")
    cliff_tex_opt = str(opts.get("cliff-texture", "auto"))
    boundary_mode = str(opts.get("boundary", "ring")).lower()
    exe = opts.get("exe") or default_exe()
    preview = opts.get("preview")
    out_path = opts.get("out")

    if not (0 <= water_frac < 1):
        print("--water 必须在 [0, 1) 之间")
        return 1
    if level_bias <= 0:
        print("--level-bias 必须大于 0（1=各层等面积，越大越低平）")
        return 1
    if ramp_run < 1:
        print("--ramp-run 至少为 1（斜坡沿崖壁方向的瓦片数）")
        return 1
    if boundary_mode not in ("ring", "none", "keep"):
        print("--boundary 只能是 ring（默认，只留最外一圈）/ none（全清）/ keep（保留模板）")
        return 1
    if layer_min < 1:
        print("--layer-min 至少为 1（水面就画在这一层，层号 0 会把整张图压到 -256 以下）")
        return 1
    if layer_max < layer_min:
        print(f"--layer-max({layer_max}) 不能小于 --layer-min({layer_min})")
        return 1
    if layer_max > MAX_LAYER:
        print(f"最高层 {layer_max} 超过合法上限 {MAX_LAYER}，请调小 --layer-max")
        return 1
    nlev = layer_max - layer_min + 1     # 留给悬崖的层数（只影响 --cliffs 1 时能抬几层）
    # 注：水面**不再**单独占一层（水陆同层，岸边没有落差），所以没有 water_layer 了。

    # ---- 三步式生成的新开关 ----
    # 默认「关」：默认出无悬崖的连绵丘陵，对近战友好；想要官方对战图风格再勾上。
    cliffs = str(opts.get("cliffs", "0")) not in ("0", "false", "no")
    base_opt = str(opts.get("base", "")).strip().lower()
    base_level_opt = opts.get("base-level")
    if base_level_opt is not None and base_level_opt is not True:
        base = float(base_level_opt)
        base_desc = f"自定义 {base:g}"
        abs_plane = True          # 给了初始地面 → 水面恒为 0（base 就是「相对水面」的高度）
    elif base_opt and base_opt in BASE_PRESETS:
        base = BASE_PRESETS[base_opt]
        base_desc = f"{base_opt}（{base:g} WE）"
        abs_plane = True
    elif base_opt and base_opt not in BASE_PRESETS:
        print(f"--base 只能是 {' / '.join(BASE_PRESETS)}（或用 --base-level 直接给数值）"
              + ("；flat 已改名 land = 纯陆地" if base_opt == "flat" else ""))
        return 1
    else:
        base = 0.0
        base_desc = "未指定（占比模式）"
        abs_plane = False         # 没给初始地面 → 走占比模式，用分位数反解水面
    uplift = float(opts.get("uplift", 220.0))
    mountain = str(opts.get("mountain", "fbm")).strip().lower()
    if mountain not in ("fbm", "ridged", "warped"):
        print("--mountain 只能是 fbm / ridged / warped")
        return 1
    ridge = float(opts.get("ridge", 0.6))
    warp = float(opts.get("warp", 8.0))
    mountain_oct = max(1, int(opts.get("mountain-octaves", 4)))
    max_relief = float(opts.get("max-relief", 512.0))
    if max_relief <= 0:
        print("--max-relief 必须大于 0（单层模式下相对水面高度的振幅上限，WE）")
        return 1
    water_level_opt = opts.get("water-level")
    # 水底深度下限 / 浅深分界（WE）。默认 128 = 1 个整层 —— 引擎认水的下限，
    # 调到 128 以下水在 WE 里就看不见了（实测见 --shelf-depth 的说明）。
    shelf_depth = max(0.0, float(opts.get("shelf-depth", 128.0)))
    world_clamp = str(opts.get("world-clamp", "0")) not in ("0", "false", "no")

    tmp = make_tmp("genheight")

    target = map_path
    if out_path:
        shutil.copy2(map_path, out_path)
        target = out_path
        print(f"已复制模板到 {out_path}")
    elif opts.get("no-backup"):
        pass                                   # 调用方（random_map）已经自己复制过模板了，
                                               # 再给这份副本做备份纯属堆垃圾
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(os.path.dirname(HERE), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup = os.path.join(backup_dir, f"{os.path.basename(map_path)}.{stamp}.bak")
        shutil.copy2(map_path, backup)
        print(f"备份原图: {backup}")
        # 顺手清掉同名旧备份，只留最近 100 个：跑上千次实验也不会把目录撑爆
        try:
            stem = os.path.basename(map_path) + "."
            olds = sorted(f for f in os.listdir(backup_dir)
                          if f.startswith(stem) and f.endswith(".bak"))
            for f in olds[:-100]:
                os.remove(os.path.join(backup_dir, f))
        except BaseException:
            pass

    # 1. 取出来
    subprocess.run([exe, "extract", target, "war3map.w3e", tmp, "/fp"],
                   capture_output=True, timeout=120)
    w3e_path = os.path.join(tmp, "war3map.w3e")
    if not os.path.exists(w3e_path):
        print("提取 war3map.w3e 失败")
        return 1

    data = bytearray(open(w3e_path, "rb").read())
    if data[:4] != b"W3E!":
        print("不是 w3e 文件")
        return 1
    info = read_header(data)
    W, H, HS = info["width"], info["height"], info["header"]
    rows, cols = H + 1, W + 1
    size = len(data) - HS
    per = size // (rows * cols)
    if per != 7:
        print(f"该文件每角点 {per} 字节，本脚本只支持 v11 (7 字节)")
        return 1
    print(f"{os.path.basename(target)}: {W}x{H}  角点 {cols}x{rows}  v{info['version']}  "
          f"tileset={info['tileset']}  cliff={info['cliff']}")

    nprng = np.random.default_rng(seed)

    # 2. 噪声 → 高度场
    # cliffs=1 → 「层量化」的原有路径：连续场切成整层台阶 → 台地 + 崖壁 + 斜坡
    # cliffs=0 → 「单层连续」的新路径：全图一个层值，落差全放在 gh 里 → 零悬崖
    min_island = int(opts.get("min-island", 32))
    min_lake = int(opts.get("min-lake", 16))
    # 水面所在层：悬崖模式就是 layer_min；单层模式可能被「世界高度地板」抬高（见下）
    plane_layer = int(layer_min)
    # ===== 第 1 步：地形基底 → 连续高度场（相对水面，单位 WE）=====
    # 两种模式共用，悬崖不再是「另一种生成逻辑」，而是第 2 步的一个后处理
    # —— 这正是方案书 §7 修正 3 要的结构。
    field = mountain_field(nprng, (rows, cols), mountain, cols, freq=freq,
                           octaves=mountain_oct, ridge=ridge, warp=warp)
    H_we = (base + uplift * field).astype(np.float32)

    # 水面：绝对高度 / 初始地面 / 占比，三选一
    if water_level_opt is not None and water_level_opt is not True:
        plane_h = float(water_level_opt)
        wmode = f"绝对水面 {plane_h:g} WE"
    elif abs_plane:
        plane_h = 0.0
        wmode = f"由初始地面决定（{base_desc} → 水面 = 0），水域占比随地形自然变化"
    else:
        plane_h = float(np.percentile(H_we, water_frac * 100.0))
        wmode = f"占比 {water_frac * 100:.0f}%（反解水面 = {plane_h:+.0f} WE）"
    H_we = H_we - plane_h
    H_we = soft_clip(H_we, max_relief)
    is_water = H_we < 0.0

    # 清碎岛碎塘：连续场没有「层」可换，只能直接改高度
    if min_island > 0 or min_lake > 0:
        H_we, n_island_fix, n_lake_fix = hills_clean_regions(
            H_we, min_island=min_island, min_lake=min_lake)
        if n_island_fix or n_lake_fix:
            print(f"清理碎块: 沉掉 {n_island_fix} 座小岛, 填平 {n_lake_fix} 个小水塘")
        is_water = H_we < 0.0

    # 初始地面的语义（2026-09-16 用户重新定义）：
    #   shallow = 陆地单位能走过去的浅滩 → 水里不能有深水，整片水域都压到浅水阈值以内
    #   land    = 纯陆地 → 一滴水都没有
    before_deep = -float(H_we.min())
    H_we = apply_base_semantics(H_we, base_opt, shelf_depth)
    is_water = H_we < 0.0
    if base_opt == "shallow":
        print(f"      浅滩基底: 水底压平到 {shelf_depth:.0f} WE（原最深 {before_deep:.0f}）"
              f" —— 整片水域都是能走过去的浅水，且深到引擎会渲染水面，没有深水")
    elif base_opt == "land":
        print("      纯陆地基底: 整块抬到水面之上 → 全图没有水")

    code = np.where(is_water, 0, 1).astype(np.int32)
    nlev = 1
    layer = np.full((rows, cols), layer_min, dtype=np.int16)
    ramp = np.zeros((rows, cols), dtype=bool)
    ramp_band = np.zeros((rows, cols), dtype=bool)

    # ===== 第 2 步：悬崖（可选）—— 只在若干小块区域里做层量化 =====
    # 不勾 = 全图一个层值，落差全放在 gh 里 → 零悬崖，连绵起伏，近战友好。
    if not cliffs:
        plane_layer = int(layer_min)
        ramp_info = {"components": 1, "ramps": 0, "candidates": 0,
                     "skipped": 0, "disabled": True}
        print(f"模式: 单层连续（零悬崖）  初始地面 {base_desc} / 山脉 {mountain} / "
              f"抬升 {uplift:g} WE / 振幅上限 {max_relief:g} WE")
        print(f"      水面: {wmode}")
    else:
        # 只在「若干个小块区域」里做层量化 —— 用户 2026-09-16 需求：勾了悬崖也不是
        # 全图崖壁，而是几片台地拔地而起，其余地面保持连续起伏。
        cliff_area = min(0.95, max(0.02, float(opts.get("cliff-area", 0.15))))
        cliff_size = max(4.0, float(opts.get("cliff-size", 26.0)))
        # 台阶级数不能超过 --max-jump（否则下面的 limit_neighbor_jump 会改 layer 而
        # 不改高度，「层差 = 落差/128」这个不变量就破了），也不能顶出 MAX_LAYER。
        cliff_layers = max(1, min(int(opts.get("cliff-layers", 3)),
                                  int(opts.get("max-jump", 2)),
                                  MAX_LAYER - int(layer_min),
                                  max(1, int(layer_max) - int(layer_min))))
        cliff_feather = max(1.0, float(opts.get("cliff-feather", 4.0)))
        blur_r = max(2, int(round(cliff_size / 4.0)))
        # 离水太近的地方不长台地 —— 台地的基准面是平滑高度 Hgap，岸边 Hgap 可能已经
        # 在水面以下，台地就会泡在水里（水角点跟 layer 的对应关系也会变得别扭）。
        cliff_land = (~is_water) & (H_we > 32.0)
        cmask, n_holes = cliff_mask(nprng, (rows, cols), cliff_land, cliff_area,
                                    cliff_size, cols, smooth=max(1, smooth),
                                    min_area=min_island, solid=~is_water)
        # 台地的基准高度：陆地高度的低分位（低地），级数按「台地比低地高多少层」算
        _lh = H_we[cliff_land]
        cliff_ref = float(np.percentile(_lh, 15)) if _lh.size > 50 else 0.0
        H_we, layer, ksteps = apply_terraces(
            H_we, cmask, layer_min, layer_min, blur_r, cliff_feather, cliff_layers,
            ref=cliff_ref)
        is_water = H_we < 0.0
        n_terr = int(len(np.unique(layer[cmask]))) if cmask.any() else 0
        print(f"模式: 局部悬崖  初始地面 {base_desc} / 山脉 {mountain} / "
              f"抬升 {uplift:g} WE")
        print(f"      水面: {wmode}")
        print(f"      悬崖区: {int(cmask.sum())} 角点（占地图 "
              f"{cmask.sum() * 100.0 / (rows * cols):.1f}%）→ {n_terr} 级台地"
              f"，最高抬 {int(np.nanmax(ksteps[cmask])) if cmask.any() else 0} 层"
              f"（每级 128 WE，外围一圈羽化平整，落差 = 层差 ✔）；"
              f"其余地面保持连续起伏，零崖壁"
              + (f"　填掉遮罩内的洞 {n_holes} 处（不填会变成上不去的浅坑）"
                 if n_holes else ""))
        if ramps_opt == "0":
            ramp_info = {"components": 0, "ramps": 0, "candidates": 0,
                         "disabled": True}
        else:
            limit = None if ramps_opt == "auto" else int(ramps_opt)
            ramp, layer, ramp_band, ramp_info = carve_ramps(
                layer, is_water, max_ramps=limit, run=ramp_run, max_jump=max_jump,
                force=ramp_force)
            if ramp_info.get("ramps"):
                n_fix = merge_orphan_flats(layer, is_water, ramp,
                                           min_area=int(opts.get("orphan-area", 24)),
                                           max_jump=max_jump)
                if n_fix:
                    print(f"      斜坡收尾: 合并 {n_fix} 块被斜坡端头切断的孤立平地")
        plane_layer = int(layer_min)
    # ---- 应用高度：隆起 / 凹陷 / 凹凸不平 ----
    # 这三项合成的是「同一台地内部」的起伏（layer 不变，所以不会变成悬崖），
    # 对应 WE 地形面板的「应用高度」笔刷：
    #   低频场 → 隆起（正的半边）/ 凹陷（负的半边）：大尺度的鼓包与凹坑，地形"性格"
    #   高频场 → 凹凸不平：表面颗粒感，避免整片地像一块塑料板
    # 幅度单位 = WE 高度单位（1 单位 = 高度条上 1 格 = 4 原始单位；一整层 = 128）。
    # 官方对战图实测（tools/_tmp/analyze_height.py）：低频 σ 典型 ≈ 70、
    # 高频 σ 典型 ≈ 32、两者合计的台地内残差 σ 典型 ≈ 87。
    raise_amp = float(opts.get("raise", 75.0))
    lower_amp = float(opts.get("lower", 75.0))
    rough_amp = float(opts.get("rough", 12.0))
    blob = float(opts.get("blob", 28.0))     # 隆起/凹陷团块尺寸（格）
    grain = float(opts.get("grain", 2.5))    # 凹凸不平颗粒尺寸（格）
    if "relief" in opts and opts["relief"] is not True:
        # 旧参数兼容：relief 的单位是「层」，1 层 = 128 WE 高度单位
        r = float(opts["relief"]) * 128.0
        raise_amp = lower_amp = r
    # 幅度封顶：超过一整层（128），鼓起来的部分就扎进上一层的崖壁里了
    CAP = 120.0
    if max(raise_amp, lower_amp, rough_amp) > CAP:
        over = [n for n, v in (("--raise", raise_amp), ("--lower", lower_amp),
                               ("--rough", rough_amp)) if v > CAP]
        print(f"注意：{'、'.join(over)} 超过一整层（128），已压到 {CAP:.0f}，"
              f"再大会穿进上层崖壁")
        raise_amp, lower_amp, rough_amp = (min(raise_amp, CAP), min(lower_amp, CAP),
                                           min(rough_amp, CAP))

    lf = unit_noise(nprng, (rows, cols), noise_cells(cols, blob), octaves=3)
    bell = np.where(lf > 0, lf * raise_amp, lf * lower_amp)   # 上半 隆起 / 下半 凹陷
    hf = unit_noise(nprng, (rows, cols), noise_cells(cols, grain),
                    octaves=int(opts.get("rough-octaves", 3)),
                    gain=float(opts.get("rough-gain", 0.6)))
    macro = bell * 4.0                         # WE 高度单位 → 原始单位
    # 台阶化：官方对战图的地面其实是「大片平坦面 + 陡坎」（实测 36%~64% 的相邻角点完全
    # 等高），不是处处连续的坡。把宏观起伏量化到 ledge 高的台阶就得到这个观感，
    # 对应 WE 里「高原/阶梯」笔刷。0 = 保持连续。
    # 只量化宏观起伏：细颗粒（凹凸不平）要叠在台阶之上，一起量化会被台阶吃掉。
    ledge = float(opts.get("ledge", 0.0))
    if ledge > 0:
        step_raw = max(1.0, ledge * 4.0)
        macro = np.round(macro / step_raw) * step_raw
    fine = macro + hf * rough_amp * 4.0        # WE 高度单位 → 原始单位

    # ---- 平整区域：留一些完全没有隆起/凹陷的地方 ----
    # 对应 WE 的「平整」笔刷。拿一块低频场取分位当"平整场"，核心区把起伏乘 0，
    # 边缘用一段斜坡过渡（硬边界看起来像被刀切的）。
    flat_frac = float(opts.get("flat", 0.15))
    flat_peak = 0.0
    wflat = np.ones_like(is_water, dtype=np.float32)
    if flat_frac > 0:
        flat_size = float(opts.get("flat-size", 20.0))
        ff = unit_noise(nprng, (rows, cols), noise_cells(cols, flat_size), octaves=2)
        # 稍微偏向低层：官方地图的平整区大多是平原，不会长在高台地上 → 低层 ff 更小
        ff = ff - 0.35 * (1.0 - code.astype(np.float32) / max(1.0, nlev))
        frac = min(0.9, flat_frac)
        thr = float(np.percentile(ff, frac * 100.0))          # 最低的那 frac 比例变平整
        span = max(1e-6, float(ff.max()) - thr)
        wflat = np.clip((ff - thr) / (span * 0.25), 0.0, 1.0).astype(np.float32)
        fine = fine * wflat
        flat_peak = float(np.mean(wflat < 0.05)) * 100.0

    # ---- 水下起伏：按 --water-relief 缩一档，别让水底跟陆地一样粗糙 ----
    # 官方地图的水底都是平滑的，但也不能是一块塑料板。向上要留 1/4 层安全边，
    # 免得把水底顶出水面变成一串小岛（那样 is_water 会跟实际渲染对不上）。
    guard = LAYER_STEP // 4
    wrelief = max(0.0, float(opts.get("water-relief", 0.5)))
    if is_water.any() and wrelief < 1.0:
        cap_w = max(0.0, (shelf_depth * 4.0 if shelf_depth > 0 else LAYER_STEP) - guard)
        fine = np.where(is_water, np.minimum(fine * wrelief, cap_w), fine)

    # ---- 把「应用高度」的起伏并回连续高度场，再编码成 (layer, gh) ----
    H_we = H_we + fine.astype(np.float32) / 4.0
    # 平整区域：连续模式没有台地可削平，就整块向「陆地平均高度」压平。
    # 不能压向 0 —— 那会把平整区按在水面上，变成一片分不清是水还是地的滩涂。
    # ⚠️ 悬崖模式不做宏观压平：台地面的高度必须严格等于 Hgap+128k，
    #    一压平就破坏了「层差 = 落差/128」这个不变量，崖壁会渲错。
    if flat_frac > 0 and not cliffs:
        land_now = H_we >= 0.0
        tgt = float(H_we[land_now].mean()) if land_now.any() else 0.0
        w = np.where(is_water, 1.0, wflat).astype(np.float32)
        H_we = H_we * w + np.float32(tgt) * (1.0 - w)
    # ⚠️ 悬崖模式同样不能 soft_clip：软裁剪会把台阶高度压缩成非 128 的倍数。
    if not cliffs:
        H_we = soft_clip(H_we, max_relief)
        # 世界高度地板（可选）：world = H_we + (L-2)*128 必须 ≥ -256（layer 0 的基准）。
        # 抬高整图层号 = 把整张图垂直平移，相对水面的关系一点没变，**坡度形态不受影响**。
        L_need = 2 + int(np.ceil((WORLD_MIN_WE - float(H_we.min())) / 128.0))
        L_need = max(int(layer_min), L_need, 0)
        if L_need > MAX_LAYER:
            L_need = MAX_LAYER
        if not world_clamp:
            L_need = int(layer_min)
        if L_need != int(layer_min):
            print(f"      抬高整图到第 {L_need} 层（原 {layer_min}）："
                  f"最深的角点 {float(H_we.min()):.0f} WE，在第 {layer_min} 层会跌破 "
                  f"世界高度下限 {WORLD_MIN_WE:.0f}（官方 45 张图无一越界）")
            layer[:] = L_need
        plane_layer = L_need
    # 起伏会把水底推深、也会把陆地压回水面以下 —— 基线语义在这里再兜一次
    H_we = apply_base_semantics(H_we, base_opt, shelf_depth)
    is_water = H_we < 0.0

    # ---- 斜坡补刻：台地边界是噪声形状，锯齿崖很常见，第一遍 carve_ramps 常会漏掉
    # 一两块台地 → 那块台地就成了上不去的孤岛。这里用**最终**的 is_water 复查一遍，
    # 还断着就再扫一次候选崖段补刻（第一遍用过的崖段已被标掉，第二遍看到的是剩下的）。
    if cliffs and ramps_opt != "0" and ramp_info.get("ramps"):
        n_iso = connectivity_report(layer, is_water, ramp)[2]
        if n_iso:
            r2, l2, z2, info2 = carve_ramps(
                layer, is_water, max_ramps=None, run=ramp_run,
                max_jump=max_jump,                 force=ramp_force,
                prev_ramps=(ramp, ramp_band))
            if info2.get("ramps"):
                ramp, layer, ramp_band = r2, l2, z2
                n_fix2 = merge_orphan_flats(layer, is_water, ramp,
                                            min_area=int(opts.get("orphan-area", 24)),
                                            max_jump=max_jump)
                n_iso2 = connectivity_report(layer, is_water, ramp)[2]
                # 日志里报的是「总共和刻了几条」，所以两遍要合并统计
                _tot = int(ramp_info.get("ramps", 0)) + int(info2.get("ramps", 0))
                ramp_info = dict(info2)
                ramp_info["ramps"] = _tot
                print(f"      补刻斜坡: 还有 {n_iso} 座岛被崖壁切断 → 又刻了 "
                      f"{info2['ramps']} 条（候选 {info2.get('candidates', 0)} 处）"
                      + (f"，合并 {n_fix2} 块孤立平地" if n_fix2 else "")
                      + f"　→ 剩余 {n_iso2} 座")

    # ---- 兜底：补刻完还够不着的台地整块撤掉 ----
    # 哪怕 carve_ramps 全失败也不能留「看得见上不去」的孤岛 —— 撤掉就是普通连续地形，
    # 通行性 100%。这是硬保证，不依赖斜坡算法在锯齿崖上的成功率。
    if cliffs:
        H_we, layer, is_water, ramp, n_drop = drop_unreachable_terraces(
            layer, is_water, ramp, H_we, plane_layer)
        if n_drop:
            print(f"      撤掉够不着的台地: {n_drop} 块（没有斜坡能接上 → 拉回连续地形，"
                  f"避免「看得见上不去」；这些地方就没有崖壁了）")
        # 最后的硬保证：还有岛被切成两半，就从崖壁上直接开一条坡出来
        ramp, n_drill, n_rej = drill_ramps_for_connectivity(layer, is_water, ramp)
        if n_drill or n_rej:
            n_iso = connectivity_report(layer, is_water, ramp)[2]
            print(f"      兜底开坡: 从崖壁上直接开 {n_drill} 个坡瓦片接通被切断的岛"
                  + (f"（放弃 {n_rej} 处，会留下非法斜坡瓦片）" if n_rej else "")
                  + f"　→ 剩余 {n_iso} 座不通")
        # 兜底 ③：开坡只跨得了 1 级崖壁（跨 2 级会开出非法斜坡瓦片，见 drill 的说明）。
        # 剩下那些挡着 2 级崖壁、1 级斜坡上不去的台地再撤一轮 —— 宁可少一块台地，
        # 也不要留「看得见上不去」的孤岛。
        H_we, layer, is_water, ramp, n_drop2 = drop_unreachable_terraces(
            layer, is_water, ramp, H_we, plane_layer)
        if n_drop2:
            n_iso = connectivity_report(layer, is_water, ramp)[2]
            print(f"      撤掉够不着的台地(二轮): {n_drop2} 块"
                  f"（挡路的只剩 2 级崖壁，1 级斜坡跨不过去）　→ 剩余 {n_iso} 座不通")
    # ---- 🔴 水底深度下限：让水真的能被引擎画出来（2026-09-16 第三轮实测）----
    # 引擎只在「地形低于水面 ≥ 1 个整层(128 WE)」时才把它渲染成水面；浅于此的水下地形
    # 会被当**干地**画。探针图 out/probe_water_depth.w3x 实测：gh 下沉 4/32/96 WE 都看不到
    # 水，128 WE 就有水，而且**跟 layer 无关**（同层 gh 下沉一样成立）。
    # 所以这里给所有水角点兜一个深度下限，否则浅水会在 WE 里「隐形」、整张图看着像纯陆地。
    # ⚠️ 必须放在 drop_unreachable_terraces / drill_ramps 之后 —— 那两个会改 H_we（陆地）。
    if shelf_depth > 0 and is_water.any():
        n_raised = int((is_water & (-H_we < float(shelf_depth))).sum())
        H_we = np.where(is_water, np.minimum(H_we, -float(shelf_depth)), H_we)
        if n_raised:
            print(f"      水底深度下限: {n_raised} 个水角点原来浅于 {shelf_depth:g} WE"
                  f"（引擎会把它们当干地画）→ 已压到 {shelf_depth:g} WE")

    # ---- 岸线缓坡（浅滩）：水域在离岸几格内逐格加深，别一步踩到底 ----
    # 🔴 2026-09-16 新增，起因：用户「感觉陆地和水衔接的地方没有那么自然，坡度小一些更好」。
    # 官方 40 张有水的对战图实测（tools/_tmp/shore_depth_profile.py，口径 = 该图 waterHeight
    # 众数当水面平面、depth = 平面高度 − 角点世界高度）：
    #     离岸 1 / 2 / 3 格的水深中位数 = 68 / 114 / 128 WE
    #     —— 岸边是一条**缓坡浅滩**，要到第 3 格才到全深；
    #     40 张图里「水深 < 128 的水角点」占比中位数 41%（Riverrun 57%、BloodvenomFalls 72%）。
    # 而我们的水是「一步踩到 shelf_depth 的平底」（128 / 128 / 128），于是岸线成了一道
    # 169 WE 的硬台阶（陆 +41 → 水 −128）、水下是一条等深的沟 —— WE 里看就是「浴缸边」，
    # 这正是「衔接不自然」的来源。
    # 做法：离岸 k 格的水底抬到浅滩剖面 target(k) 上（只**抬浅**，绝不把水顶出水面）。
    #     剖面形状抄官方那三个数：k=1 → shore_s，k=shore_w → shelf_depth，中间用
    #     (1−t)² 二次曲线 —— 代进 68/128、w=3 时 k=2 正好 ≈113，与官方 114 吻合。
    # ⚠️ 只动**水角点**的高度：陆地一个数都没改，所以「层差 = 落差/128」这个悬崖不变量
    #     不受影响（水角点永远不是台地，不会被 apply_terraces / carve_ramps 碰）。
    # --shore-width 0 = 关闭，退化成旧的「一步到 shelf_depth」。
    shore_w = int(opts.get("shore-width", 3) or 0)
    shore_s = float(opts.get("shore-shallow", 0) or 0)
    if shore_s <= 0:
        shore_s = float(shelf_depth) * 0.53      # 128 → 68，对齐官方离岸第 1 格中位数
    # shore_prof = 每个角点的「最小水深目标」（WE）：选中的岸边水角点走浅滩剖面，
    # 其余 = shelf_depth。下面「量化后的水角点深度兜底」必须复用同一张表，
    # 否则那道 `fine ≤ -4×shelf_depth` 的强制钳制会把这里刚抬上去的浅滩又抹平。
    shore_prof = None
    if shelf_depth > 0 and is_water.any() and shore_w > 0 and 0 < shore_s < shelf_depth:
        _d = shore_distance(is_water, cap=shore_w + 1).astype(np.float32)
        sel = is_water & (_d >= 1.0) & (_d <= float(shore_w))
        if sel.any():
            t = np.clip((_d - 1.0) / max(1.0, float(shore_w - 1)), 0.0, 1.0)
            prof = float(shelf_depth) - (float(shelf_depth) - shore_s) * (1.0 - t) ** 2
            shore_prof = np.where(sel, prof, float(shelf_depth)).astype(np.float32)
            _before = float(H_we[sel].mean())
            H_we = np.where(sel, np.maximum(H_we, -prof), H_we)
            print(f"      岸线缓坡: 离岸 {shore_w} 格内的水底抬成浅滩剖面"
                  f"（岸线 {shore_s:.0f} → 全深 {shelf_depth:g} WE）"
                  f"{int(sel.sum())} 个角点，岸边水底平均抬浅 "
                  f"{float(H_we[sel].mean()) - _before:.0f} WE"
                  f"（官方实测离岸 1/2/3 格 = 68/114/128）")

    # 世界高度 → (layer, gh)：层内偏移 = H_we - (layer - 水面层)*128。
    # 这个式子保证「世界高度 = H_we + (水面层-2)*128，与 layer 无关」——
    # 台地靠 layer 抬起来，gh 就自动少掉 128k，所以台阶面照旧平滑。
    fine = (H_we - (layer.astype(np.float32) - plane_layer) * 128.0) * 4.0

    # ---- 水体：浅水 / 深水 ----
    # 水面高度 = 水面层的世界基准（默认 layer_min=2 → gh 8192）；官方对战图的水深全是
    # 整层的倍数，最常见 1 层（=128 WE 高度单位），其次 2 层，少数深达 4 层。
    # ⚠️ 深浅水一律**只靠 groundHeight 的落差**表达，不换 layer：
    #    layer 一换，水下就多出一道崖壁（浅水处可能露出来，岸边也平白多一圈落差），
    #    而引擎本来就按「地形相对水面的深度」渲染水色（越深越暗）。交给它即可。
    plane_raw = GROUND_ZERO + (plane_layer - LAYER_ZERO) * LAYER_STEP   # 水面世界高度
    # 深水 = 比 shelf_depth 再深（shelf_depth 默认就是 1 个整层，所以「深水」= 2 层以上）。
    # epsilon 是给 shallow 基底的平底（恰好 = shelf_depth）留的，别让浮点误差把它算成深水。
    deep_water = (is_water & ((-H_we) > shelf_depth + 0.5)
                  if shelf_depth > 0 else np.zeros_like(is_water))
    land_only = ~is_water

    # 斜坡瓦片：坡面必须**贴住两侧台地的实际地面**，不能按到「层基准线」。
    # 🔴 这里曾经写的是 `fine = 0`（= 把坡面按到层基准线，世界高度 = 128×(layer-2)）。
    #    理由是「斜坡不能带起伏，否则是搓板路」—— 起伏是去掉了，可层基准线离台地面
    #    差了整整一个 Hgap：台地世界高度 = Hgap + 128×k，而 Hgap 是几十~几百 WE 的
    #    宏观地形高度。于是坡面直接沉到紧邻台地**下面 400~500 WE**（实测 seed=777：
    #    坡面 128~256，紧邻台地 550~620），在 WE 里就是一条「凹到地心」的深沟；
    #    用户报的就是这个。
    #    官方图（BootyBay 站点 r30~32）的坡面是**贴着**两侧台地地面的：上层角点线在
    #    上一级台地的高度上、下两层线在下一级台地的高度上。
    # 做法：坡带角点的 fine 用「**同一层号**的邻近非坡带角点」的 fine 填进去（见
    #    fill_band_fine）。台地与坡外地面（除坡带本身）的 fine 恒等于 4×Hgap ——
    #    因为世界高度 = fine/4 + 128×(layer-2)，层号已经把 128k 抬掉了 ——
    #    所以「同层号最近邻」填出来的高度天然就**等于它所连接的那一级台地地面**，
    #    坡面落差正好 = 128×层差 = 一整个台阶，跟 WE 渲染斜坡的方式一致。
    #    而且填的是邻近真实地面高度 → 自带地形起伏，不会搓板也不会鼓包。
    # 兜底：极个别角点附近没有同层号的普通地面（坡带贴着地图边角等），
    #    用邻域加权平均顶上，保证一定填满、不会留 0（= 层基准线 = 深沟）。
    if ramp_band.any():
        rr = max(1, int(opts.get("ramp-smooth", 2)))
        nb = ~ramp_band
        num = box_blur(np.where(nb, fine, 0.0).astype(np.float32), rr)
        den = box_blur(nb.astype(np.float32), rr)
        fallback = np.where(den > 1e-6, num / np.where(den > 1e-6, den, 1.0),
                            fine.astype(np.float32))
        filled, ok = fill_band_fine(fine, layer, ramp_band,
                                   radius=max(2, int(opts.get("ramp-reach", 8))))
        fine = np.where(ramp_band, np.where(ok, filled, fallback),
                        fine.astype(np.float32))
    # 高度量化到 1 WE 单位（= 4 原始单位），与 WE 笔刷的粒度一致：实测官方地图
    # （如 GolemsInTheMist）台地内残差的取值全是 4 的倍数。照做才像手刷出来的地形。
    hstep = max(1, int(opts.get("height-step", 4)))
    if hstep > 1:
        fine = (np.round(fine.astype(np.float32) / hstep) * hstep).astype(np.int16)

    # 水陆分界靠「gh 相对水面层的高低」表达，而量化（hstep 一档）会把分界线附近的
    # 角点四舍五入到水面的错误一侧 → 校验会报「水会画穿」。量化之后统一强制一次。
    # ⚠️ 判据必须换算成**世界高度**：世界高度 = fine/4 + (layer - 水面层)*128，
    #    所以层号比水面层高 k 级的角点，它的 fine 要低到 -512k 才真的沉进水里。
    #    只写 fine < 0 是不够的 —— 那会让台地上的水角点反而高过水面。
    # ⚠️ 水角点同时还要「够深」：量化会把水底四舍五入到 hstep 的倍数（hstep=6 时
    #    128 WE 会变成 127.5），低于 128 引擎就不画水了 → 这里连深度下限一起兜住。
    #    ⚠️ 但**岸边浅滩要按 shore_prof 放宽**（见上「岸线缓坡」）—— 一刀切 4×shelf_depth
    #       会把浅滩又抹平，等于白做。
    layer_over = (layer.astype(np.float32) - plane_layer) * 512.0
    if shelf_depth > 0:
        need = (shore_prof * 4.0 if shore_prof is not None
                else np.float32(float(shelf_depth) * 4.0))
    else:
        need = np.float32(0.0)
    water_need = np.maximum(np.float32(hstep), need)
    water_max_fine = -layer_over - water_need      # 水角点：世界高度 ≤ -max(hstep, 4*shelf_depth)/4
    land_min_fine = -layer_over + float(hstep)     # 陆地角点：世界高度 ≥ +hstep/4
    fine = np.where(is_water, np.minimum(fine, water_max_fine),
                    np.maximum(fine, land_min_fine))

    # ---- WE 崩溃防护（默认关）：世界高度必须落在官方图从未越过的区间内 ----
    # 45 张官方图实测：最低角点恰好 -256（layer 0 基准），最高 1536，**无一越界**。
    # 越界后 WE 能打开、能显示，但一编辑地形就闪退。实测打开它并不能解决那个闪退，
    # 而且它**会把最深的水底削平**、也限制坡度形态，所以默认完全不动地形。
    if world_clamp:
        world_now = (fine.astype(np.float32) / 4.0
                     + (layer.astype(np.float32) - LAYER_ZERO) * 128.0)
        bad = (world_now < WORLD_MIN_WE) | (world_now > WORLD_MAX_WE)
        n_bad = int(bad.sum())
        if n_bad:
            wc = np.clip(world_now, WORLD_MIN_WE, WORLD_MAX_WE)
            fine = (np.round(
                (wc - (layer.astype(np.float32) - LAYER_ZERO) * 128.0) * 4.0 / hstep
            ) * hstep).astype(np.int16)
            # 钳制有可能把分界附近的角点推到水面另一侧，所以再确认一次
            fine = np.where(is_water, np.minimum(fine, water_max_fine),
                            np.maximum(fine, land_min_fine))
            print(f"安全钳制: {n_bad} 个角点跌出世界高度区间 "
                  f"[{WORLD_MIN_WE:g}, {WORLD_MAX_WE:g}] WE → 已压回边界"
                  f"（最低 {float(world_now.min()):.0f} → {float(wc.min()):.0f}）")

    # 起伏指标只在「非平整区的陆地」上统计：平整区本来就没有起伏，算进去会把
    # 官方的基准值带偏，看不出隆起/凹陷到底调对没有。
    meas = land_only & (wflat >= 0.95) if flat_frac > 0 else land_only
    tot_s, low_s, high_s = relief_stats(fine, meas)
    tail = "，不含平整区" if flat_frac > 0 else ""
    print(f"应用高度: 隆起 σ={raise_amp:.0f}  凹陷 σ={lower_amp:.0f}  "
          f"凹凸不平 σ={rough_amp:.0f}（WE 高度单位）"
          f"　团块 {blob:g} 格 / 颗粒 {grain:g} 格"
          + (f" / 台阶 {ledge:g}" if ledge > 0 else ""))
    print(f"      实测层内起伏(陆地{tail}): 合计 σ={tot_s:.0f}  低频 σ={low_s:.0f}  "
          f"高频 σ={high_s:.0f}   ← 官方对战图典型 87 / 70 / 32")
    if flat_frac > 0:
        print(f"平整区域: 约 {flat_peak:.1f}% 的陆地完全没有隆起/凹陷"
              f"（团块 {float(opts.get('flat-size', 20.0)):g} 格）")
    if is_water.any():
        depth = -H_we[is_water]
        n_sh = int((is_water & ~deep_water).sum())
        n_dp = int(deep_water.sum())
        _shore = (f"；离岸 {shore_w} 格内是缓坡浅滩（{shore_s:.0f} → {shelf_depth:g} WE，"
                  f"官方实测 68/114/128）" if shore_prof is not None else
                  "；岸边是一步到底的平底（岸线落差 = 水底深度）")
        print(f"水体: 浅水 {n_sh} 角点（深度 ≤ {shelf_depth:g} WE）/ 深水 {n_dp}"
              f"（> {shelf_depth:g} WE，最深 {depth.max() / 128:.1f} 层）"
              f"；最深 {depth.max():.0f} WE，中位 {np.median(depth):.0f} WE"
              f"　水陆同层（不出崖壁）{_shore}")
        # ⚠️ 起伏要按**世界高度**算：水角点可能落在不同层上（台地脚伸进水里），
        #    此时 fine（层内偏移）天然不同，直接对 fine 求 σ 会把层差误算成起伏。
        w_world = (fine.astype(np.float32) / 4.0
                   + (layer.astype(np.float32) - LAYER_ZERO) * 128.0)
        print(f"      水下起伏: σ≈{float(np.std(w_world[is_water])):.0f} WE"
              f"（陆地的 {wrelief * 100:.0f}%）"
              + ("　← 浅滩基底水底压平，没有起伏" if base_opt == "shallow" else ""))
    else:
        print("水体: 无（整张图一滴水都没有）")

    # 悬崖贴图：官方地图整张图用同一套（LostTemple 全是 index 1 = CLgr），
    # 而 WE 新建的空模板是 15（未指定）。逐角点随机是错的，会让崖壁贴图忽明忽暗。
    n_cliff = max(1, len(info["cliff"]))
    if cliff_tex_opt == "auto":
        cliff_tex = 1 if n_cliff >= 2 else 0
    else:
        cliff_tex = int(cliff_tex_opt) % max(1, min(n_cliff, 16))
    cliff_texture = np.full((rows, cols), cliff_tex, dtype=np.uint8)
    # 悬崖变体：官方实测的分布（0 占 45%，4 占 29%，1 占 18%，其余零星）。
    # 这个字段与斜坡无关（ramp 与普通崖壁分布几乎一致），纯粹是外观。
    cliff_variation = nprng.choice(
        8, size=(rows, cols),
        p=[0.45, 0.18, 0.018, 0.003, 0.29, 0.036, 0.018, 0.005]).astype(np.uint8)
    ground_variation = nprng.integers(0, 32, size=(rows, cols), dtype=np.uint8)

    # 3. 逐角点写回
    water_corners = 0
    blight_kept = 0
    tpl_b1 = tpl_b2 = 0          # 模板自带的两种边界标记数量（只统计，用于日志）
    for cy in range(rows):
        file_row = rows - 1 - cy      # 文件自下而上存行，图像第 0 行是地图顶部
        base = HS + file_row * cols * per
        for cx in range(cols):
            off = base + cx * per
            gh = GROUND_ZERO + int(fine[cy, cx])
            # 水面高度：必须跟着 layer_min 走。写死 8192 的话，一旦把最低层抬高
            # （例如 --layer-min 6），水面就落到地形下面，整张图一滴水都看不到。
            wh = plane_raw
            # 模板自带的 0x80(flags) / 0x4000(waterHeight) 是「地图边界外」标记：
            # 带它的瓦片寻路可走率 0%。LostTemple 拿它盖了 40% 的角点（真正的地图外框），
            # WE 自建的空模板则用它标出「游玩区之外的留白边框」。
            # 我们要的是整张可玩地图，所以默认整图清零、只在最外一圈补回（boundary=ring）。
            # 唯一保留的原有标记是 blight（枯地）。
            orig_flags = data[off + 4]
            orig_b1 = struct.unpack_from("<H", data, off + 2)[0] & BOUNDARY_BIT
            flags = orig_flags & BLIGHT_FLAG
            if orig_flags & BLIGHT_FLAG:
                blight_kept += 1
            if orig_flags & BOUNDARY2_FLAG:
                tpl_b2 += 1
            if orig_b1:
                tpl_b1 += 1
            if ramp[cy, cx]:
                flags |= RAMP_FLAG
            if is_water[cy, cx]:
                flags |= WATER_FLAG
                water_corners += 1
            edge = cy in (0, rows - 1) or cx in (0, cols - 1)
            if boundary_mode == "keep":
                # 保留模板自己的边框：0x4000 原样留着，并把 0x80 同步到同一批角点
                # （实测这两个位是同一个「地图外」概念的两份拷贝，必须一致）。
                boundary = orig_b1
                if boundary:
                    flags |= BOUNDARY2_FLAG
            elif boundary_mode == "none":
                boundary = 0
            else:                                    # ring（默认）
                boundary = BOUNDARY_BIT if edge else 0
                if edge:
                    flags |= BOUNDARY2_FLAG
            tex = data[off + 4] & 0x0F

            struct.pack_into("<H", data, off, max(0, min(0xFFFF, gh)))
            struct.pack_into("<H", data, off + 2, (wh & 0x3FFF) | boundary)
            data[off + 4] = (flags & 0xF0) | tex
            data[off + 5] = ((int(ground_variation[cy, cx]) & 0x1F) << 3) | (int(cliff_variation[cy, cx]) & 0x07)
            data[off + 6] = ((int(cliff_texture[cy, cx]) & 0x0F) << 4) | (int(layer[cy, cx]) & 0x0F)

    new_w3e = os.path.join(tmp, "war3map.w3e.new")
    open(new_w3e, "wb").write(bytes(data))

    # 4. 预览图
    if preview:
        img = np.zeros((rows, cols, 3), dtype=np.uint8)
        # 悬崖模式按「层」上色（能看出台地）；单层模式层值恒定，改按相对水面的高度上色
        lv = layer.astype(np.float32) if cliffs else fine.astype(np.float32) / 4.0
        lo = float(lv.min())
        hi = float(lv.max())
        hi = lo + 1.0 if hi <= lo else hi
        t = (lv - lo) / (hi - lo)
        img[:, :, 0] = (90 + 140 * t).astype(np.uint8)
        img[:, :, 1] = (70 + 150 * t).astype(np.uint8)
        img[:, :, 2] = (40 + 110 * t).astype(np.uint8)
        # 叠一层山体阴影：不然「隆起/凹陷/凹凸不平」在纯色块上看不出来
        h_we = fine.astype(np.float32) / 4.0 + (layer.astype(np.float32) - LAYER_ZERO) * 128.0
        sh = 0.42 + 0.58 * hillshade(h_we, exag=float(opts.get("shade-exag", 10.0)))
        img = np.clip(img.astype(np.float32) * sh[:, :, None], 0, 255).astype(np.uint8)
        # 水面也叠一层柔和的阴影，否则「水下隆起/凹陷」在预览图上完全看不出来
        sh_soft = 0.55 + 0.45 * hillshade(h_we, exag=float(opts.get("shade-exag", 10.0)))
        for wm, wcol in ((is_water & ~deep_water, (60, 130, 210)),   # 浅水
                         (deep_water, (20, 60, 150))):               # 深水（更暗，和游戏里一致）
            if wm.any():
                c = np.array(wcol, dtype=np.float32)[None, :]
                img[wm] = np.clip(sh_soft[wm][:, None] * c, 0, 255).astype(np.uint8)
        ramp_tile = (ramp[:-1, :-1] & ramp[:-1, 1:] & ramp[1:, :-1] & ramp[1:, 1:])
        img[:-1, :-1][ramp_tile] = (230, 170, 40)
        # 放大 4 倍：和撒树预览同尺寸，界面里并排显示时不会一个糊一个清
        Image.fromarray(img).resize((cols * 4, rows * 4), Image.NEAREST).save(preview)
        print(f"预览图: {preview}"
              f"（已叠山体阴影；水色浅=浅水 深=深水，隆起/凹陷/颗粒感可直接看出来）")

    # 5. 塞回 MPQ
    subprocess.run([exe, "add", target, new_w3e, "war3map.w3e"],
                   capture_output=True, timeout=120)

    unique_layers = np.unique(layer)
    if cliffs:
        l_lo, l_hi = int(unique_layers.min()), int(unique_layers.max())
        print(f"高度层区间: {l_lo}~{l_hi} 层"
              f"（世界基准 {(l_lo - LAYER_ZERO) * 128:.0f} ~ "
              f"{(l_hi - LAYER_ZERO) * 128:.0f}，共 {l_hi - l_lo + 1} 级台阶，"
              f"每级 128；水面在第 {plane_layer} 层）")
        print(f"层分布: { {int(v): int(np.count_nonzero(layer == v)) for v in unique_layers} }")
        print(f"      悬崖区之外一律第 {plane_layer} 层：连续起伏、零崖壁，且与水面同层")
    else:
        print(f"高度层: 全图统一第 {plane_layer} 层（世界基准 "
              f"{(plane_layer - LAYER_ZERO) * 128:.0f}）"
              f"　落差全在 groundHeight 里：世界高度 "
              f"{(plane_layer - LAYER_ZERO) * 128 + (int(fine.min()) / 4.0):.0f} ~ "
              f"{(plane_layer - LAYER_ZERO) * 128 + (int(fine.max()) / 4.0):.0f}"
              f"（相对水面 {int(fine.min()) / 4.0:.0f} ~ {int(fine.max()) / 4.0:.0f}）")
    print(f"水域角点: {water_corners} ({water_corners * 100.0 / (rows * cols):.1f}%)")
    n_edge = 2 * cols + 2 * rows - 4
    _bnd_desc = {
        "ring": f"只留最外一圈（{n_edge} 角点）",
        "none": "全清（整张地图无边界位）",
        "keep": f"沿用模板边框（0x4000 共 {tpl_b1} 角点，0x80 已同步）",
    }[boundary_mode]
    print(f"边界标记: {boundary_mode} → {_bnd_desc}"
          f"   模板原有 0x4000={tpl_b1} / 0x80={tpl_b2} 角点"
          f"   保留枯地: {blight_kept} 角点")
    n_island, n_walk, n_bad = connectivity_report(layer, is_water, ramp)
    if cliffs:
        print(f"斜坡: {ramp_info.get('ramps', 0)} 条 (台地 {ramp_info.get('components', 0)} 块, "
              f"候选崖边 {ramp_info.get('candidates', 0)} 处"
              + (f", 跳过 {ramp_info['skipped']} 处" if ramp_info.get("skipped") else "") + ")")
        for line in ramp_report(layer, ramp):
            print("      " + line)
        print(f"连通性自检: 陆地岛 {n_island} 块 / 可走连通块 {n_walk} 块  → "
              + ("每座岛内部都走得通 ✔" if n_bad == 0 else f"有 {n_bad} 座岛被崖壁切断 ✘"))
    else:
        print("斜坡: 0 条（单层模式没有层差，也就没有崖壁，不需要斜坡）")
        print(f"连通性自检: 全图同一层值，无层差可挡路 → "
              f"陆地岛 {n_island} 块，岛内处处可走 ✔（近战友好）")
    print(f"完成: {target}")
    if not opts.get("keep-temp"):
        drop_tmp(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
