# automap — 魔兽争霸 III 1.27a 随机地图生成器

从官方对战地图统计规律反推生成算法的 WC3 随机地图（melee map）生成器。
输入一张模板地图与随机种子，输出一张可直接游玩的完整地图：地形（分层台地 /
悬崖 / 斜坡 / 水域）、树林、中立建筑、野怪营地、掉落物，并支持 8 种
《魔兽争霸 III》地图风格（洛丹伦夏/冬、灰谷、荒地、费尔伍德、诺森德、城市等）。

所有生成规则都从 **43~45 张官方对战地图 + 游戏 SLK 数据** 实测统计得出，
而不是拍脑袋——脚本、统计结论与推导过程都保留在仓库里（`tools/_tmp/`、`doc/`）。

## 功能一览

| 层 | 脚本 | 内容 |
|---|---|---|
| ① 地形 | `tools/gen_height.py` | 分层台地 + 悬崖 + 斜坡（保证连通）+ 水域 + 岸线缓坡；地面纹理 / 悬崖贴图按语义分区涂刷 |
| ② 树林 | `tools/add_doodads.py` | 团簇树林 + 边界林带 + 胡椒散株，形态统计对齐官方图 |
| ③ 建筑 | `tools/add_buildings.py` | 金矿 / 市场等 7 类中立建筑，出生点修正，最小间距约束 |
| ④ 野怪 | `tools/add_creeps.py` | 守卫营地（金矿/商店/实验室 60% 带守卫）+ 林间营地；等级 1–10；等级 >6 必掉装备且掉落物等级跟随野怪等级 |
| 风格 | `tools/tilesets.py` | 8 风格 ×（地面纹理 / 悬崖 / 树模型 / 雇佣兵营地 / 野怪池），跨风格语义映射自动换肤 |

风格示例（同一张图的不同风格渲染，地形骨架相同）：

- **L 洛丹伦的夏天**：草底 + 暗草团块 + 泥斑 + 崖圈岩石
- **W 洛丹伦的冬天**：雪原 + 草斑，雪崖 / 草崖分区
- **N 诺森德**：冰面 / 雪 / 泥三分
- **A 灰谷**：8 种地面纹理自然混布

## 快速开始

```bat
:: Windows：双击 启动地图生成器.bat，或在命令行：
启动地图生成器.bat
```

浏览器打开 `http://127.0.0.1:8770`（若被占用自动 +1），界面上选模板、尺寸、
风格、参数，点生成即可。产物在 `out/`，复制到
`Warcraft III\Maps\Download\` 后可在游戏里直接游玩。

命令行方式（与 GUI 参数一致）：

```bash
cd tools
python random_map.py --template ../template/128-128.w3m --out ../out/my_map.w3x --seed 4242 --style A --cliffs 1
```

常用参数：

```text
--style A|W|F|B|C|N|Y|L   地图风格，可多选逗号分隔（每次随机抽一，同种子抽中固定）
--base deep|shallow|land  水域模式 / --water 0.30 水量
--cliffs 0|1              悬崖开关 / --ramps auto 斜坡
--density 0.18            树密度 / --forest-size 170 树林团簇尺度
--ngol 12 --ngme 2 ...    中立建筑数量（金矿/市场/…）
--guard-share 0.6         守卫营地比例 / --drops 1 掉落物
```

## 环境要求

- Python 3.8+，依赖：`numpy`、`Pillow`、`mpyq`（仅读取游戏 MPQ 时需要）

```bash
pip install numpy Pillow mpyq
```

- WC3 1.27a（生成物按 1.27a 原生格式校验；更高版本未测试）

## 模板地图（需自行提取）

受版权保护，仓库不带模板。任选一种：

1. **从你的游戏目录提取**（推荐）：用任意 MPQ 工具（如 Ladik's MPQ Editor）
   打开 `Warcraft III\Maps\` 下的官方地图（`(2)Harrow.w3m` 等），整体解包即可；
2. 把 5 张不同尺寸的官方 1.27a 对战地图放进 `template/` 并按
   `<宽>-<高>.w3m` 重命名（64/96/128/160/192），生成器按模板确定地图尺寸
   与出生点布局。

> 生成器只读模板的 `war3map.w3e` / `war3map.doo` / `war3mapUnits.doo` /
> `war3map.shd` 等文件，重写其中的地形与物件；不分发、不修改模板本体。

## 目录结构

```text
automap/
├── 启动地图生成器.bat      # GUI 入口
├── tools/
│   ├── random_map.py       # 编排器：①②③④ 依序执行
│   ├── gen_height.py       # 地形（含风格转换 apply_style / 纹理涂刷 paint_textures）
│   ├── add_doodads.py      # 树林
│   ├── add_buildings.py    # 中立建筑
│   ├── add_creeps.py       # 野怪 + 掉落
│   ├── tilesets.py         # 8 风格数据表（纹理/悬崖/树/野怪池 + 跨风格 CONVERT 语义映射）
│   ├── camp_templates.py   # 野怪营地组合模板（官方图统计）
│   ├── creep_levels.py     # 野怪等级表（UnitBalance.slk 导出）
│   ├── w3units.py          # war3mapUnits.doo / war3map.doo 读写库
│   ├── gui_server.py       # 本地 GUI（零依赖 HTTP 服务）
│   ├── inspect_*.py        # 体检器：单位落点 / 地形一致性 / MPQ 内容
│   └── _tmp/               # 统计与分析脚本（官方图实测数据来源，保留可复现）
├── doc/                    # 各子系统的方案书（含实测数据与推导）
├── template/               # （自备）官方模板地图
└── bin/                    # （自备）MPQEditor.exe 等
```

## 设计要点（为什么这样做）

- **一切以官方图为基准**：树的成团率、岸线坡宽、野怪守卫比例、掉落分布、
  建筑朝向（官方 2900+ 座中立建筑 owner=15 朝向全部 270°）都从官方图
  统计得出，统计脚本在 `tools/_tmp/` 可复现；
- **w3e 头部细节**：末尾 8 字节是地形原点世界偏移（标准 `-W*64/-H*64`），
  写错会导致物件相对地形整体偏移半个地图；
- **崖面一致化**：官方 16058 条崖面的贴图混合率为 0——整面崖壁必须一种
  贴图，逐角点独立选图会渲染出「半草半泥」花斑；
- **跨风格映射**：w3e 只存 tileset 字母 + 纹理索引。转换风格时按
  `Terrain.slk` 的 `convertTo` 列与 `CliffTypes.slk` 的 `groundTile` 列做
  语义映射（`Lgrs→Agrs/Wsnw/Nsnw`），不是简单换表。

## 已知限制

- 仅 1.27a 格式（w3m/w3x 无 `map.tga` 加密头路径）；Reforged 未测试；
- 野怪技能随机占位（`uDNR`）；掉落表为官方图联合分布的简化模型；
- GUI 面向本机使用（无鉴权），不要暴露到公网。

## 免责声明

本项目与 Blizzard Entertainment 无关联。魔兽争霸 III 及其资产版权归
Blizzard Entertainment 所有。仓库不含任何游戏原始资产；使用本项目生成的
地图需要你自备合法获得的游戏客户端。请勿将生成的地图用于商业用途。

## License

[MIT](LICENSE)
