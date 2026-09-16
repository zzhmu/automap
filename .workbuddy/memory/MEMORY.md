# automap 项目记忆（精简版）

> 详细实测事实/脚本清单/算法细节 → 同目录 `详细知识库.md`；逐日记录 → `YYYY-MM-DD.md`。
> 本文件只放「绝不重犯的坑 + 常用旋钮」。

## 项目
- WC3 随机地图生成器（类红警2）：`gen_height.py` 生成地形 → 只覆盖 MPQ 内的 `war3map.w3e`
  + `war3map.doo`（树），其余 14 个文件与 `template/*.w3m` 逐字节相同。
- 模板只用 64/96/128/160/192 `.w3m`（1.27a 原生）；224/256 `.w3x` 是 1.31+ 产物。
  ⚠️ `template/*.w3m` 不可再生，动之前必须问。
- 分层：① 地形+装饰物 ② 中立建筑 ③ 野怪。后两层需**整文件重写** `war3mapUnits.doo`。

## 必背不变量
- `world(WE) = (gh-8192+(layer-2)*512)/4`；层基准 2，每层 512 原始 = 128 WE。
- **挡路的只有层差**；层内起伏再大也不挡路（官方实测同层瓦片高差 190 WE 仍 70% 可走）。
- **世界高度硬地板 -256 WE**（= layer0）。跌破 → 能开能显示，**一编辑地形就闪退**。
  用户已拍板**不修**，只在越界时打印一行警告。
- flags 高 4 位：`0x10` ramp / `0x20` blight / `0x40` water / `0x80` 边界外（**水不是 0x80**）；
  `0x80` 与 `waterHeight` 的 `0x4000` 是同一概念两份标记，必须一致。
- 水面高度读 `waterHeight` 低 14 位（高 2 位是边界位）—— 别用常量 8192、别靠 layer_min 推算。
  ⚠️ 它是**全图恒定的「水面平面」绝对 raw 高度**（官方图 99.7% 角点同值：Riverrun 9728、
  LostTemple 8192；我们 L2415 也写常量 `plane_raw`）。所以 `h = world − (wh&0x3FFF−8192)/4`
  才是「相对水面高度」。⚠️ 但 flag `0x40` **不等于** `h<0`：官方图里大量「打了水标记却在平面
  之上」的角点（TheCrucible 98%、BloodvenomFalls 74%）→ flag 只当「水体范围」，深度另算。
- w3e 行序自下而上；瓦片中心 `x=(i+0.5)*128-W*64`，`y=(j+0.5)*128-H*64`。

## 🔴 斜坡（ramp）
1. 斜坡 = 垂直崖壁的 **3 条角点线（2 瓦片厚）**，层差恒 1；带 ramp 位的瓦片四角 layer
   必须「全同层」或「恰好 2 低 2 高」，否则判非法。
2. **坡面高度必须逐角点贴住两侧台地** → `fill_band_fine()`：局部 PCA（窗口 4）求法线 →
   方向**吸附到 8 邻域** → 沿**严格直线**找**同层号**非坡带角点取值。
   ⚠️ 清零坡带 `fine` → 沉出 400~500 WE 深沟（用户实测「凹到地心」）。
   ⚠️ 不分层号平均 / 放宽成「点积 ≥ 阈值」/ 一条坡带只算一根簇级法线 → 取到沿坡带切向的低地形，
   拽出 V 形沟（实测偏差 42~127 WE）。
3. 连通性 = 四级防线（`carve_ramps` 两遍 + `drop_unreachable_terraces` +
   `drill_ramps_for_connectivity`）+ 多遍刻坡重叠守卫（`prev_ramps` /
   `_stamp_ramp` 占位 / `_stamp_would_be_legal` 试算 / `drill` 只在 `spread==1` 开坡且非法即撤销）。

## 🔴 撒树（`add_doodads.py`）
1. 目标来自 **43 张官方 1.27a 原生 `.w3m`** 实测：密度 12%、块数/树数 0.092、最大连片块 205 格、
   ≥100 块 4 个、树落大林 33%、孤立单株占块数 49%（**单株多 = 正常**）。
   ⚠️ 基准集只能用顶层 `.w3m`：FrozenThrone 下 `.w3x` 是 doo **v8**，`parse_doo` 只认 v7。
2. **官方图的树大半贴在「地图边 / 岸线 / 崖脚」成粗林带**，内部才零散小簇 —— 这是「像真地图」的关键。
   森林场必须含 `dist_transform(elig)` 的边界林带项，并乘沿边噪声把林带**打断**，
   否则整圈连成巨型块（实测最大块飙到 1000+）。
3. 三层：**大林**（`grow_region` 加权最短路生长；核间距按 `2.2×中位`）→ **小林丛**
   （株数对数正态 + 椭圆噪边；禁区半径 = `2×丛半径+空隙`）→ **散株**。不够只沿林缘外扩，
   **绝不随机撒孤立单株**。⚠️ 把 `grow_region` 改成「局部择优邻居」会顺林带长成长蛇成巨块。
   ⚠️ 窗口切片一律 `[x范围, y范围]`；`mgrid[y范围,x范围]` 得到转置掩码会圈错地方。
4. **胡椒点判据 = `iso2`（2 格邻域内一棵邻树都没有的树占比），官方 p50 只有 0.1%。**
   旧 `place_scatter` 按 `(1-森林场)` **逐格独立抽样** → `iso2` 1.8%（高 18 倍），
   视觉上就是「满地胡椒点」，用户原话「树像斑点一样分散」的真凶。
   修法：散株**也必须成团** —— 每个丛心只在自己 **3×3 窗口**内补 `--scatter-size`（默认 1.5）格，
   窗口小 → 必然互为 8 邻域 → `iso2` 归零；抖动到 1 的那一小撮才是官方那种真孤立单株。
   `--scatter-size 1.0` = 退化成旧行为（`iso2` 冲到官方 p90）。
5. ⚠️ **别用手挑的几张「典型图」当基准**。4 张精挑密林图量出「官方到大林格距中位 = 0」，
   43 张全量的 p50 其实是 **10** —— 差一个数量级，据此改过算法方向。基准一律跑全量 43 张。

## 🔴 岸线（陆 ↔ 水）
1. **差别在水下不在陆上**：陆侧剖面我们与官方几乎一样（离水 1~5 格平均高 官方 31/68/102/121/132
   vs 我们 41/70/93/110/125）。官方是**逐格加深的浅滩**：离岸 k=1/2/3 格水深中位
   **68 / 114 / 128 WE**；40 张有水的官方图「水深 <128 的水角点」占比中位 **41%**。
   我们旧行为是一步到 `--shelf-depth`(128) 的平底 → 岸线一道 169 WE 硬台阶（"浴缸边"）。
2. 实现 = `--shore-width 3`（0 关闭）/ `--shore-shallow 0`（= shelf_depth 的 53%，128→68），
   目标深度二次曲线 `shelf − (shelf−shore_s)·(1−t)²`，t=(k−1)/(w−1)（代进 68/128、w=3 → k=2=113，官方 114）。
   **只抬浅水角点、陆地一个数不碰** → 不破坏「层差 = 落差/128」（水角点永不是台地）。
3. ⚠️ 改 H_we **没用**：量化后还有一道「水角点强制深度兜底」`fine ≤ −4×shelf_depth`，
   会把浅滩抹平（A/B 两图只差 1 个角点就是这个）。必须让那道兜底读同一份 `shore_prof`。
4. ⚠️ 引擎「水深 <128 渲不渲水」**仍未 100% 定论**（探针说 ≥128 才画，官方却有 41% 更浅）。
   两种情形下缓坡观感都收敛到官方，所以按官方分布做是安全的。判据脚本
   `tools/_tmp/shore_depth_profile.py`（离岸 k×水深中位）是唯一的对照手段。

## 常用旋钮
- `--base deep|shallow|land|auto`（指定后水面恒为 0、`--water` 失效）：shallow 无深水，land 无水。
- `--cliffs 0/1`、`--cliff-area 0.15 / --cliff-size 26 / --cliff-layers 3 / --cliff-feather 4`、
  `--ramps auto|0|N`。
- 水体：`--water 0.30 / --shelf-depth 128 / --water-relief 0.5 /
  --shore-width 3 / --shore-shallow 0（0 = shelf_depth 的 53%）`。
  `--shore-width 0` = 回到旧的「一步到底」平底。
- 起伏：`--raise/--lower 75`、`--rough 12`、`--blob 28`、`--grain 2.5`、`--ledge 0`、`--height-step 4`。
- 树木：`--density 0.18 / --forest-share 0.32 / --forest-size 170 / --clump-size 11 /
  --clump-radius 3.0 / --clump-gap 1.5 / --scatter 0.035 / --scatter-size 1.5 /
  --edge-forest 0.55 / --edge-band 14 / --tree-freq 2.2`。`--clump-gap` 是**绝对空隙格数**。
  最大块偏高（282 vs 官方 205）时调 `--forest-size`（170→140 ⇒ ≈235）。
- 已**失效**（保留兼容）：`--octaves / --level-bias / --min-plateau / --shelf / --deep`。

## 工程约定
- **同一口径的指标只能有一份实现**：`add_doodads.forest_metrics` 是树林形态指标的唯一来源，
  GUI 日志 / `forest_sim` / `accept_forest` / `forest_official_stats` 全部调它。
  ⚠️ 各脚本自己抄一份的代价：`t & ~dilate(t,1)` —— 标准 dilate **含自身** → 孤立率**恒 0**，
  不报错、静默给出「官方 43 图孤立率全为 0」的荒谬结论（反向写法又恒 1，也被骗过一次）。
  正确的算子是 `add_doodads._neigh_any`（从全零 OR 位移副本、永不含 (0,0)）；
  语义由 `tools/_tmp/test_forest_metrics.py`（31 项小例子）钉死 —— **这类算子写错只能靠单测发现**。
- ⚠️ `gen_height.main()` 里 **`target` 是输出地图路径**，别拿它当局部变量名 —— 曾把浅滩剖面
  数组赋给 `target`，结果 `subprocess.run([exe,"add",target,...])` 崩在 `list2cmdline`
  （ndarray 当路径），报错完全指不到真因。
- ⚠️ 新增地形参数要**改三处**：`gen_height.py`（解析+实现）、`random_map.py` 的**透传白名单**
  （L152 那个 tuple，漏了会被静默丢弃）、`gui_server.py`（`add()` + HTML 滑条 + JS 映射表
  `["id","显示span",格式化]` + payload 四组）。**只改 gen_height 在 GUI 上不生效**。
- 管道一律 UTF-8（`✔✘` 不在 GBK 里，崩在 subprocess 读线程里报错完全指不到真因）；
  `subprocess.run(text=True)` 必须显式 `encoding="utf-8", errors="replace"`；读 `r.stdout` 前 `or ""`。
- 临时目录统一用 `make_tmp/drop_tmp`（裸 `rmtree`/`os.remove` 被沙箱拦截 → 图已生成但退出码 1）。
- `out/`、`backups/`、`tools/_tmp/` 里的自产物**直接删不问**；唯一例外 `template/*.w3m`。
  ⚠️ 但一次删 `tools/_tmp/` 下几百个 `make_tmp` 残留目录会被**批量删除守卫**拦（count>50），
  拦下就说明一句、别重试。
- GUI = `tools/gui_server.py`（8770 起 +1）+ 根目录 bat；**必须用带 numpy 的 venv python 启动**。
  参数组合验证**一律走 GUI**（前端默认值与透传逻辑与命令行不等价）。
  参数名带 `data-tip` + `?` 徽标 → 悬停弹 `#tipbox`（`position:fixed` + JS 跟随/翻转；
  不能用纯 CSS `::after`，会被面板裁掉），说明要写**官方实测参考值**。
- 截 GUI 图：本机有 **Edge**，`msedge.exe --headless=new --disable-gpu --virtual-time-budget=4000
  --window-size=1400,3500 --screenshot=o.png <url>`；截 tooltip 就 curl 页面 + 注入
  `dispatchEvent(new MouseEvent('mouseover'))`。（`agent-browser` 没装，不值得下 500MB Chromium。）
- 工作方式：先分析 → 用户确认 → 才改代码；格式以「解析到文件尾零误差」为验证标准。
