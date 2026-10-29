# 碧蓝航线 AssetBundles 解包项目 — 进度总结

> **生成时间**: 2026-10-29（**用户实测纠错两处产品层干预**：① 撤销 `COSTUME_DEFAULT_ON` 对 `Param233` 的强钉（`idle` 定值是 0，硬钉 1 与动作打架）；② 面板部件区只列有内容的 226/310，参数区标题标注调试用途 —— 通路实测正常（520470 px / 27259 px），真因是列了 84 个空部件。见 §171 / WF-57 追补四；此前：**需求② 收口：换装表现在覆盖全部 5 个模型**。旧扫描判据方向是反的（把「动作间恒定」当成无不调空间 ⇒ 装扮参数全被剔），改用运行时反查绑定后 `costume_params.json` 从 1 个模型扩到 5 个、`ougen_8` 12→13 条，5 个模型全部通过可点击性验收，见 §170 / WF-57 追补三；此前：**需求① 真根因已定位并修复**：`ShoseOff` 是三态参数（-1/0/1）被两态逻辑钳到残缺档 `-1`（0=穿鞋 7 件 / 1=脱鞋 5 件 / -1=残缺 3 件）；`stateCurOn` 因 0 到两端等距改写启动态、`costumeTarget` 用 min 当关端导致点击循环回不到 0。修后连点 4 次渲染值 `0,1,0,1`、可见鞋件 `7,5,7,7`，见 §169 / WF-57 追补二；此前：**需求② 可点击性已清点**：新增 `l2d_hotzone_clickable.py`，以屏幕像素为判据，`ougen_8` 12 条参数 10 条 ≥8px 可点，`BondEyes`/`HeartEyes` 驱动件为空按设计走面板控件，见 §168 / WF-57 追补；此前：**③④ 两条互动区需求本轮收口**：③ 定位并修掉两个真缺陷 —— 参数热区盒被 `Touch*` 点击标记撑爆（`Stock1` 85994→30.5）、参数热区无条件抢占动作判定区（改成「更具体者胜」，A/B 下 HIT 19→26 / WIRING 4→0 / 判定区中心 31/31 不变），见 §167 / WF-57 / SKILL §30；④ 逐动作验完（渲染有效值为判据，55 动作 × 12 参数 0 偏差），见 `l2d_param_retain_verify.py`；同批修掉 3 个探针假红（`plainWheelNoop` 的 `ResizeObserver→refit` 竞态、重试漏捕 WebSocket 超时、`WIRING` 未算拖拽编号轮转），**WF-16 六件套现全绿**（第 6 项环境跳过）；此前：**参数效果测量的五个仪器缺陷已逐个证死并修掉**（眨眼污染 / 绝对阈值 / 仅 ro / 基线只取一次 / 值写≠几何重算），`ougen_8` 全 12 条参数的可信映射已产出、`ParamEyeSmile` 由 0 改判 14 件，见 §166 / WF-56；**`l2d_costume_hotzone_verify.py` 最后一处红已查明是探针自身两处缺陷并已修**：取点落进 trigger 判定区 + CDP 两段式派发间隔 4.6–29.9 s，见 §164 / WF-54；修后 `ougen_8/ShoseOff` 7 PASS / 0 FAIL，`aersasi_2` 墨镜 5/5 零回归，可达率基线重标；`ougen_8` 少一只鞋定性为素材侧缺省关闭**：那 16 件由 `Param233` 统一控制、`def=0`、idle/idle9 各 220 帧全 0，仅 `touch_idle2/4/10/18` 里推到 1，见 §163 / WF-53；**热区判定改真实三角形 + 渲染序裁决 + 幽灵区第二遍**，八热区基线五满三欠、点击时序两处真实缺陷已修，见 §162 / WF-52；**逐帧探针仪器体检前置**见 WF-51 + §158 续六十一条 bug 全表；`toggleState` tween 起点取错源已修，守 `l2d_state_toggle_regress.py`；**看图预算**：截图不得直接进上下文，先 `shot_budget.py` 读指标/压缩，见 §160 / WF-50；无头浏览器生命周期改内核级兜底：Job Object + 启动前清理 + 回读确认，见 §159 / WF-49）
> **环境安装（换机器复刻先做）**：
>   1. 装 Python **3.15**（2026-10-23 起本机约定；UnityPy 1.25.4 无 cp315 预编译轮子，需源码编译，见 §2 Python 行）。⚠️ 本机同时装着 3.14，`py -3` 指向谁由 `%APPDATA%\py.ini` 决定（现固定 3.15），**跑之前先 `py -3 scripts/diag/check_env.py`** 确认实际解释器与依赖
>   2. 仓库根 `py -3 -m pip install -r requirements-v2.txt`（3.15 上必须走阿里云/腾讯云源，清华源连 sdist 都没有；需 MSVC BuildTools 编译 UnityPy + lz4）
>   3. 校验依赖**真的可用**：`py -3 scripts/diag/check_env.py`（载荷级验证，比 `scan_build_deps.py` 强 —— 后者只做 AST 静态扫描，import 缺失也照样 exit 0）
>   4. 外部工具走 `scripts/paths.py`（adb/vgmstream/ffmpeg/chrome；env 或已知安装位兜底）
>   5. 画廊前端 vendor：`py -3 scripts/fetch_gallery_vendor.py --check`（4 个第三方 JS；spine-all.js 已换官方上游源；缺件用 `py -3 scripts/fetch_gallery_vendor.py` 补齐）

> 历轮会话流水（2026-09-20 ~ 10-17 逐轮记录）已逐字外迁 `docs/archive/PROJECT_STATUS_2026-10-17_逐字外迁.md`（A30 段）；本文只留当前状态。
> **用途**: 跨会话对接。**v1 时代历史已外迁 `docs/archive/PROJECT_STATUS_历史归档.md`**，本文只保留当前状态与主线。当前待办见 §6。
>
> **【其它待办】**~~§6.11 HitAreas 生成规则漏了 `touch_*` 组名~~ **已于 2026-09-22 修复落地**（13 模型真实判定区、全库 806/807）｜**官方交互层**：用 `CubismRaycastable` 真点击区替换现在猜的 `Touch*` drawable HitAreas、以及 `CubismExpressionController` 表情还原（注意运行时不读 pose3.json/exp 需验证）｜§6 待办 7「晶环联盟阵营码」三选一（A 逆向 sharecfgdata 加密 / B 走 381 旁路 / C 搁置）｜**剧情 CG 混进 `Paintings_v2/`** 的识别与分离（用户指出"脸黑的基本都是剧情 CG"，与缺脸是两类问题，见 §6.8）｜**结构隐患**：~~`azdata_*.json` 权威元数据源仍住在可被清理的 `.diag/`~~（**2026-09-24 已迁 `inputs/azdata/` + sha256 台账 `MANIFEST.json` + 校验 `scripts/diag/check_inputs.py`；数据本体仍不入库**，理由：9.2MB 游戏配置属资产、zlib 后 0.67MB 虽小但仓库原则是「只承载可复现的工具与知识」）——剩余一项：**21 个脚本硬编码 `D:\Azur Lane Assets` / `C:\Users\KLLM` 绝对路径**，其中 **13 阶段调用链上 9 个**
（`compose_paintings_v2`、`extract_spine_v2`、`reconstruct_live2d`、`extract_motions`、`fix_model3`、
`extract_cv_voice`、`export_dependency_manifest`、`mumu_sync`、`run_cg_export` 的 Chrome 路径，外加
vgmstream/ffmpeg 钉在 `C:\Users\KLLM\AppData\Local`）⇒ **换盘符或换用户名必炸，不是"迁移困难"**
（2026-10-01 应"这项目可迁移吗"实测；`update_pipeline.py`/`pipeline_panel.py` 自己走 `__file__` 推导，可迁；
数据 `files/` 28.9GB + `Output/` 约 45GB 不入库，需单独拷。建议：抽 `scripts/paths.py` 统一根目录 + 工具路径走 env 兜底）｜
**控制台执行侧（2026-10-01 体检，见 §71）**：13 阶段全串行、同一时刻 1 个子进程、**稳态约 0.7GB**，
跟 MuMu 不冲突（只有第 1 步要设备）；立绘 ≈1.25 秒/张 ⇒ 全量 4488 张 ≈1.5 小时、一把梭全量 4~6 小时
约 41GB 写入；`deps` 实测 3 秒 / 0.20GB（旧文档"依赖表 43 分钟"是报错的数）。§71~§75 那几轮的逐轮流水
已逐字外迁 **A18 段**，结论在 §71 / §74 / §75。
> **上一轮（2026-10-02）执行快照**：源包 92679 已同步、12 张新立绘已换入（4488→4500）、13 档全部有结论
> （`audio`/`cg` 只跑了只读半边）。逐轮叙述（§79~§85、控制台第五/六轮、§76 那条签字框接线缺失）已**逐字外迁 A22 段**。
> 仍要带的五条结论：① 权威皮肤表 = 设备侧 + 快照**逐字段合并**（`scripts/skin_table.py` 是唯一读取口）；
> ② 语音/台词归属只有**一份**三分类规则 `extract_cv_voice.row_candidates()`（`_hei` 不回退，它是剧情黑脸剪影）；
> ③ **画廊皮肤名不读 `ship_meta.json`**，label 回落与语音接不上同一个根因（§82）；
> ④ 跑流水线前先 `py -3 scripts/diag/test_pipeline_gating.py`（56 条判据）；
> ⑤ 语音产物**无需单独备份**（可确定性再生，体检 `scripts/diag/l2d_voice_inventory.py`），不可复原的只有 `inputs/azdata`。
跑之前先 `py -3 scripts/diag/test_pipeline_gating.py`（56 条判据）。**§76 又挖出一条接线缺失**：卡片上的「签字放行」复选框只有那颗「单独跑」会读，主按钮「重跑到待确认」发的 `approve` 永远是空的 ⇒ 用户勾了等于没勾。现在勾选存 `SIGNED`、主按钮带上并二次确认、主屏那行小字显示"已勾签字：…"；另外设备不可达且范围清单有效时 `pull` 判绿沿用清单，不再把已同步完的人卡在第 1 档。。**语音产物口径已定：无需单独备份**（可确定性再生，体检 `scripts/diag/l2d_voice_inventory.py`），不可复原的只有 `inputs/azdata`｜**控制台界面（2026-10-01 第五轮，见 §73 / WF-23 追加）**：用户否掉第四轮的「常驻漂移」（「我要的就是渐进式显影」）⇒ 星野**退回显影式**（静止全黑、划过才亮、约 520ms 淡净、淡净回**同一张**帧），配色保留 B 的**海军蓝 + 蓝白**（五个状态色 rgb 不动），光效回到 **conic 边框光束 + 控件内柔光 + 磁吸**；新增**三态自定义光标**（默认/可点/主行动，内联 SVG、深色描边打底）与**进度台**（只在真在跑时出现的一条细带：阶段 N/M · 已用 · 内存〔整棵进程树工作集〕· 剩余〔各阶段历史均值，缺样本报「≥」下限〕）；帮助抽屉里**为设计辩护的文案删掉**（用户要求别把提示词写进界面）。`scripts/diag/panel_ui_probe.py` 契约改回「渐进式显影」并新增 9 条进度台判据，**86 条全绿**。**控制台第六轮（2026-10-02，见 §82）**：说明书加「简洁 / 详细」两档（默认简洁只留 5 节、收起 7 节、选择写 `panel.helpmode`）；星空先量后改——量出来静止帧整屏只有 **67 个像素**亮着（占视口 **0.01%**），"常驻微光"这个开关是开着的但屏幕上没东西 ⇒ 常驻档改为按星型分抽（47→280 颗）、`AMB` 0.10→0.26、密度 2187→2843、显影半径 9→46/130→190、银河带从 30 个正圆改成沿带轴拉长的纤维 ⇒ 静止 3702 px（0.33%）而**淡净后与初始帧仍逐像素相同**；探针 103→**109 条**，并新增一道硬预检「served 页面必须与磁盘正本一致」（§72 烘死 HTML 那条坑本轮第三次撞上）。｜低优先：声优中文姓名回填、UI/图标批量导出、`organize.py`。

---

## 1. 项目概览

- 对碧蓝航线 Unity AssetBundle 解包、分类、导出、还原。
- 源路径 `D:\Azur Lane Assets\files\AssetBundles`，**196 类目 / 71,393 文件 / 21.89 GB**（2026-10-06 按类目清理：删 dorm3d/island/char/ui 共 **21,286 个源包 / 7.53 GB**，删除与登记同时落 `ledger/pruned.json` ⇒ `mumu_sync` 不再把它们报成"新增"；清理前 240 类 / 92,679 文件 / 29.42 GB。判据与过程 **§111 / WF-28**）；产物侧 `Output/` 48.5 GB，全仓约 **70 GB**（口径统一 = `scripts/diag/check_disk_footprint.py`，GiB）。
- **当前主线 = v2 数据驱动管线**（见 §9）：零猜测、零手调，已全量收官。

### 仓库治理 ✅
- 忽略规则收敛为「保留源码与文档，忽略游戏资产与生成产物」：忽略 `files/`、`Output/`、`tools/`、`.micode/`、`.mimocode/`。
- 生成产物与资产元数据已从 Git 索引移除，避免再次提交游戏资产。

---

## 2. 各部分进度

### 2.1 目录扫描 ✅
**71,393 文件 / 21.89 GB / 111 类**；输出 `asset_manifest.json`(20MB)。脚本 `scripts/scan_assets.py`。
> ✅ 2026-10-06 重建：上一份停在 06-19 的 86,849 / 26.62 GB（三个月没跑，且那批数里含已按类目删除的 dorm3d/island/char/ui）。新数与 `scripts/diag/check_disk_footprint.py` 独立量出的 71,393 **逐位吻合**（两套工具同一结论才算数）。⚠️ 顺带否掉我上一轮的一句话：这份 manifest **没有**"只扫一层"的缺陷（它的 `path` 用反斜杠，最深 9 层，20,407 条是嵌套包）——那条误判来自我用 `/` 数层级，属判据自身写错，见 §112。

### 2.2 立绘导出 ✅
43,520 导出 / 0 失败。脚本 `scripts/export_assets.py`（UnityPy）。（v1 合成产物已被 v2 取代，见 §9.2。）

### 2.3 背景导出 ✅
1,897 张（bg 1,302 + helpbg 364 + commonbg 111 + loadingbg 50 + loadingbg_hx 13 + newshipbg 14 + worldhelpbg 29 + lotterybg 12 + backyardbg 2）。输出 `Output/Raw/{bg,commonbg,loadingbg,helpbg,...}/`。
> 2026-09-16 随源包更新全量重导 1897/1897；修复 `export_assets.py` 漏设 `FALLBACK_UNITY_VERSION` 导致较新包加载失败的问题。⚠️ **`Output/Raw/`（2.02 GB，1,964 png）不是 `files/` 的副本，是 09-16 那轮的冻结导出层**：当前 5 档管线不写不读它、前端索引引用 0 处、唯一读者 `organize.py` 至今未跑（§2.8），可由源包确定性重导。取证 **§111**。

### 2.4 音频导出 ✅（2026-10-19 重建 BGM）
`Output/Audio/BGM_flac/` = **561 首 `.flac` / 7.10 GB / 19.84 小时**；`Output/Audio/CV2/` = 20,760 文件 / 1.25 GB。BGM 的 561 个 wav（12.20 GB）在 `--verify-only` 561/561 全绿后已删。脚本 `export_cue_audio.py` / `transcode_bgm.py` / `build_bgm_index.py`（本轮把前两个的硬编码 KLLM 路径与 ffprobe 拼接修正，见 §126 / WF-39）。
✅ **音乐库可用**：`gallery_v2/bgm.json` 561 首；`bgm_page_probe.py` 全 PASS（播放在走、Range 拖动、筛选/搜索、两套主题截图）。归属：377 首有出处、413 有用途、40 首官方中文名（10 张专辑）、17 首连舰名。⚠️ 换格式必须重跑播放验收（`.flac` 默认 MIME 是 `audio/x-flac`）；无损靠 `--verify-only` 的 md5+整条解码证明，不能靠格式名字。取证 **§112 / §113 / §126**。

### 2.5 Live2D 模型还原 ✅（2026-09-21 动作层重建；2026-09-22 补齐 9 个 bundle → 269 模型；2026-09-26 修 5 个贴图索引错绑）
269/269 还原、纹理拼接正确、HitAreas 已全库补登真判定区。输出 `Output/Live2D/{舰名}/`，**4.7GB**（2026-09-24 实测，曲线补齐后从 ~3.9GB 涨上来）。脚本 `reconstruct_live2d.py` / `fix_model3.py` / `extract_motions.py`。
> ▸ **新机 clone 后重建 5 个验收样本的步骤**已外迁：`docs/archive/PROJECT_STATUS_local-rebuild_2026-10-20.md`（原第 66 行）。
| 指标 | 数值 |
|---|---|
| motion 文件 | **8154** 条（0 未引用 / 0 悬空引用；shell 仅剩 7 条资产层真为空，见下） |
| 曲线总数 | 全库 **2,662,615**（2026-09-24 全量重导：944,136 → 2,662,615，×2.82）。⚠️ **2026-10-20 发现全库仍缺 ConstantClip 定值段（平均 ~81%）**：`L2D_MOTION_EMIT_CONST` 生产从未打开，姿势层定值曲线整段未导出 →「播 idle9 卡在默认待机」根因（§134）。**2026-10-21 本机 5 样本已全部换入**（4487→23326 + 4 样本 28693→71117，合计 52019→94443 条，binding 对账 71117=71117 零回退；24 姿势参数运行时精确落值实测）；**其余 264 模型待重导**（换入后需重算 motion_chain + §25 规训） |
| PartOpacity 换装曲线 | 79 模型（`gaoxiong_7` 3548 条、`kebensi_2` 2940 条、`chaijun_3` 2492 条等），此前整层丢弃 |
| 审计 | shell **7** / misassign **0** / `clips 8154`（`scripts/diag/l2d_motion_audit.py`，2026-09-24 全库） |
| HitAreas（model3） | min 3 / max 78 / mean 12.3，**无 0 判定区模型**（2026-09-24 `fix_model3.py` 全库补登 `Touch*`）。⚠️ 其中**多数框静止态落在画布外**（抽样 11 模型 323/379=85%）——那是**换装/互动按钮的停放位**，播对应动作时随部件进画面才可点，**不是脏数据、不得按几何批量删**（2026-09-27 逐动作组实测，见 §51 / `l2d_hit_offcanvas.py --sweep`） |
| 资产层真为空的 clip | 7（*_3 的 effect、wuqi_3 的 idle11 等），已从 model3 引用剔除 |
| 贴图索引顺序闸门 | **269/269 升序**（`scripts/diag/l2d_texorder_check.py`，退出码即判据；2026-09-26 修掉 5 个乱序，见 §40） |
| 贴图完整性对账 | **269/269 全绿**：源 bundle `Texture2D` 清单 vs 磁盘 PNG，missing 0 / extra 0 / 非 `texture_%02d` 命名 0（`scripts/diag/l2d_tex_completeness.py`）。⚠️ 其中 **51/269 源枚举序 ≠ 编号序**，全靠 `fix_model3.py` 归一化兜住——该步骤是承重的，不可省 |
| 目视覆盖（Live2D 画面） | **26/269**，按 `(moc3 版本 × 贴图数)` 15 桶**全覆盖**、零新增破损；⚠️ 只覆盖"贴图绑定"这一类，其余 243 个未目视 |
> **2026-09-21 根因重建**：旧产物 5037/8154 条是 `"Curves": []` 空壳、其余曲线名全部错位（按位置猜），现按 `genericBindings[i].path == crc32("Parameters/<名>")` 权威映射重建。见 §17。
已知限制：StreamedClip 未完全逆向；HitAreas 用 moc3 `Touch<X>` drawable 而非官方 `CubismRaycastable` 真点击区（**2026-09-22 §6.11 修后全部 269 模型均带真实 HitAreas**，仅 `z46_3` Special 框嵌 Body 属模型自带歧义）；0.226% 绑定（疑 Drawable 颜色）运行时无对应 target，跳过。
> **网页交互层状态（2026-09-23 §6.12 + §21）**：点击命中已修「四边形包含 + V/P 坐标系换算」，idle 循环已交回运行时（前端零定时器），动作切换恢复交叉淡化，运行时自加的假呼吸层已关闭，另有判定区可视化与参数·部件检查器；改前端前**必读 WF-16**（六条硬规则 + 回归六件套）。
> ✅ 四条已闭环事故注记（判定区幽灵标签 **§51**｜语音被掐 **§41**｜代理指标假绿灯 **§40**｜全量重导覆写事故 **§25**）已外迁 A15 段；目视覆盖 26/269 见上表同一行，不重复。
> ▸ **状态切换交互（§132）、状态开关四联修（§135）、残留复位竞态（§133）、ConstantClip 定值段换入（§134）** 四条已闭环取证已逐字外迁：`docs/archive/PROJECT_STATUS_state-toggles_2026-10.md`（原第 82、83、85、86 行）。
 > ▸ **动作完整性与目视（2026-10-20）**：5 样本动作**全量**对账通过（源 clip=磁盘=model3 引用=空曲线 0：ougen_8 55 / antu_2 104 / aersasi_2 28 / aersasi_3 82 / qiershazhi_2 36，共 305 组）。Live2D 面板新增**「▶ 全部」顺序播放按钮**（从当前组逐个播完，每组 6s，pill 显示 `组名 [i/N]`；再点/手动选/切皮肤即停）——目视验收入口。
> ▸ **热区判定三段式（§162）、回落姿势保持（§145）** 已修，取证已外迁 `docs/archive/`。
> ▸ **参数型互动区验收、回落双路径竞争、方案B 数据侧**三条已闭环取证已外迁：`docs/archive/PROJECT_STATUS_costume-fallback_2026-10.md`（原第 86、88、103 行）。
> ▸ **`ougen_8` 鞋的旧定性（§163）已被 §169 推翻**（真根因是三态参数被两态逻辑钳到残缺档 `-1`，不是素材缺省关闭）；原文见 `docs/archive/`。
> ⚠️ **动效验证必须在播放窗口内高频采样**：运行时把每条 idle 解析成 `isLoop:false`（全 269 模型一致的既有特性），idle 只播一次即回静；等 ~12s 后两次快照比对会因短 idle(5~8s) 已播完而假报 `moved=0`。
> ✅ **动作保真定稿 = E 组**（2026-10-27，§147~§150）：平均偏差 2.68786e-07、367/367 `motion3.json` sha256 逐字节可复现。完整裁决表与独立复核已外迁：`docs/archive/PROJECT_STATUS_motion-fidelity-E_2026-10-27.md`（原第 88-100 行）。

### 2.6 Spine 动态立绘 ✅（v2 提取 + 全屏 CG 导出 + viewer 修复，2026-09-19）
> ✅ **2026-09-29 分层改认权威清单**：每个 `Output/Spine_v2/<目录>/parts.json` 由 prefab 的
> `SkeletonGraphic` 节点落盘（层名 + `localScale` + `startingAnimation` + `initialSkinName` + 位移），
> 索引与 viewer 与 `cg_export.html` **都只读它**，缺文件非零退出不回落 glob。
> 修掉 30 个目录多画 / 15 对本体与和谐版逐像素相同的 CG。做法 **WF-14 追加**、踩坑 **§64**。
`scripts/extract_spine_v2.py` 双结构兼容提取到 `Output/Spine_v2/`，232 主包。gallery 内 `spine-all.js`(3.8) 分层实时播放。**2026-09-19 三修复**：①相机视口（`SceneRenderer.resize()` 不更新 viewport → 比例怪）②`my` 变量遮蔽 TDZ（假「N 层失败」+ 取消失效）③过滤 0 秒空占位动画、默认播 `normal`、缺动画层回落 normal；另支持 JSON 骨架（beierfasite_g）。**全屏 CG 导出**：`cg_export.html` 渲染 setup pose 批量落盘 `Output/CG_v2/` **231/231 成功**（含二次像素包围盒构图修正）。
> ✅ **2026-09-26 Spine 三修**（补 `setSkin`｜CG 按 `animFrame` 全量重导｜弹窗取景 `boundsOf` 不再把"挂了附件"当成"会画出来"）结论与判据在 **§42 / §45 / §46** 与 WF-14 追加，流水外迁 A15 段。两条承重事实：**设 skin 前后画面大小不变、只是腿回来了**；**光加 `setSkin` 对 CG 导出无效**（CG 渲 setup pose，腿是动画第 0 帧的 AttachmentTimeline 挂上去的）。
> ▸ **取景遗留问题**处理史已外迁：`docs/archive/PROJECT_STATUS_framing-legacy_2026-10-29.md`（原第 110 行）。

### 2.7 UI/图标导出 ⏳ 未处理
`ui/` 4,059 文件 + 各 icon 目录数万，可复用 `export_assets.py`。优先级最低。
> ⚠️ **前置条件已变（2026-10-06）**：`ui/` 的 4,278 个源包按用户裁定删除，**只留 `ui/commonui_atlas`**（它是 `a2_2` / `2b_2` 两个已还原皮肤的 atlas 页依赖，删了重提取会缺页）⇒ 这条待办现在**必须先 `mumu_sync` 重拉 `ui` 类目**才能开工（`pruned.json` 已登记，diff 会把它们列成"归档"而不是"新增"，重拉要显式点名）。

### 2.8 资源分类整理 ⏳ 未处理
`scripts/organize.py` 已写未跑，需所有导出完成后进行。

### 2.9 Wiki 舰船数据 ✅
862 舰 / JSON(name,faction,ship_type,rarity) / `Output/WikiData/ship_data.json`。脚本 `scrape_wiki_fast.py`(8线程92秒)。已知：148 艘缺阵营（联动/特殊舰）。

---

> ▸ **画质验收（2026-10-19）**：Live2D 2x 通过（DPR=2 时 buffer=2.00×CSS）；**Spine 此前每帧 DPR 校正是假绿灯**——`SceneRenderer.resize()` 把 buffer 改回 CSS 尺寸，DPR=2 仍 1.00×，已修（§123），改后 2.00×。旧探针只在 DPR=1 下测，现已默认 `--dpr 2`。
> ▸ **Live2D 颜色（2026-10-19，§125/WF-38）**：0.4.0 运行时丢弃 per-drawable `MultiplyColor/ScreenColor` ⇒ 170 个 multiply=[0,0,0] 的层被画成原色（ougen_8 idle8 分割线虚影）、3 个 screen=[1,1,1] 的层没白填充（touch_idle17 倒酒）。已给 0.4.0 打最小补丁（三个 fragment shader + 按 drawable 绑 uniform），补丁副本入库并由 MANIFEST `local` 源供应；`hit_verify ougen_8` WIRING=0。
> ▸ **touch_idle* 回落修正（2026-10-19）**：15% 闸门只约束长动作；`touch_idle*` 无条件回 best（全库 1,945 条中 **148 条**因此从默认 idle 切到对应变体）。
> ▸ **2026-10-19 续修**：① 裁剪遮罩缓冲按 `N ≥ 长边×√maskCount` 自动取 2 的幂（ougen_8 mask=8192；阶梯显著变细，硬 alpha 边缘仍在，见 §127）；② 回落按用户要求**回退到 10-17 三层语义**（idle 循环 / touch_idle 用 norm、touch_drag 用 raw_sse 查表 best（不做覆盖度排除）/ 长动作默认 idle）+ ticker 看门狗（解决卡最后一帧）；③ `build_gallery_index.py` 写 index 前自动刷新 `motion_chain.json`；④ 开场 login（**默认开**，FORCE；设置可关）与眼神跟随（默认开，LOW ticker 写 `ParamEyeBallX/Y`）；⑤ 拖拽互动区补全（ougen_8 30+14=44，Ctrl/⌘+左键拖拽触发 touch_drag，普通拖拽仍平移）；⑥ 60 模型截图抽检（60/60 加载成功，夜间/黑底场景为模型本身）。
> ▸ **画质补丁（2026-10-19）**：静态立绘默认上限改 **1:1**（不再二次放大，小图留白）；Spine 开 **MSAA**（`antialias:true`）。
> ▸ **CG 入画廊（2026-10-19）**：`CG_v2` 235 张由 `build_gallery_index.py` 写成 `skin.cg`，并生成 `thumbs/<key>_cg.webp`；`gallery_index_diff_check --allow-skin cg` 只允许这 235 条变化。硬链去重 45 文件/201.8MB 已执行。

## 3. 已加工资产清单

| 类别 | 文件数 | 大小 | 说明 |
|---|---|---|---|
| Paintings_v2 | 4,452 | 16.07 GB | v2 静态立绘（当前正式产物） |
| Spine_v2 | 235 目录 | 3.64 GB | v2 Spine 提取 |
| Live2D | 262 | 5.31 GB | Live2D 模型 |
| Audio | 21,321 | 8.35 GB | BGM_flac 561 + CV2 20,760 |
| CG_v2 | 235 | 0.89 GB | 已进画廊索引（`skin.cg`） |
| gallery_v2 | 4,705 | ~0.19 GB | 本地浏览平台 |
| files/AssetBundles | 56,520 | 27.67 GB | 源数据（只读） |

（v1 旧产物与历次调试目录已清理；**2026-09-20 磁盘清理 126 项/7.3GB 与硬链接去重 531 文件/~358MB 的完整流水**（含"重复资产被画廊按文件名引用故不能删"的判据）见归档 A3 段与 `windows-hardlink-dedup-verify` 技能。）

---

## 4. 工具链

| 工具 | 版本 | 用途 | 状态 |
|---|---|---|---|
| Python | **3.15** | 运行脚本 | ✅（v2 用 `py -3`）｜**2026-10-23 起约定 3.15**：UnityPy 1.25.4 全部核心依赖已实测可用（5 项载荷级验证 + 3 个核心脚本与 3.14 输出逐字相同）。⚠️ 官方无 cp315 轮子，UnityPy/lz4 由本机 MSVC 18 编译；`%APPDATA%\py.ini` 已固定默认 3.15，3.14 保留作对照/回退 |
| UnityPy | 1.25.3 | 读取/导出 AssetBundle | ✅ 用户级 pip |
| Pillow | 12.x | 图像处理 | ✅ |
| ffmpeg | 7.1 | 音视频处理 | ✅ |
| vgmstream | v2117 | CRIWARE 音频解码 | ✅ |
| ALPA | 1.0.5.1 | 立绘注入/预览（参考真值） | ✅ 需 Java 17 |
| AssetStudio | v2.4.1 | 可视化预览/导出 | ✅ |
| spine-all.js | 3.8 | Spine 运行时（gallery 复用） | ✅（2026-10-18 换官方上游 3.8 构建；`fetch --check` 4/4 + 版本 3.8.75 + 前端符号 9/9 全覆盖，见 WF-36/§122） |

---

## 5. 关键文件清单

**核心脚本**：`scan_assets.py`、`export_assets.py`、`export_cue_audio.py`、`reconstruct_live2d.py`/`fix_model3.py`/`extract_motions.py`(★2026-09-21 权威映射重写)/`apply_live2d_motions.py`(★临时目录→备份换入)、`compose_paintings_v2.py`(★v2)、`extract_spine_v2.py`(★v2)、`export_dependency_manifest.py`、`build_gallery_index.py`、`make_thumbs.py`、`deploy_gallery.py`(gallery_src↔Output 硬链/漂移检查)、`fetch_gallery_vendor.py`(★2026-10-18 补 spine-all.js 官方上游源; 按 vendor 台账 sha256 补齐第三方库)、`mumu_sync.py`(★2026-10-18 同步范围放开为整棵 `files/`，`ONLY_TOP=[]`，`il2cpp` 等缺了可 sync 补，见 WF-35)、`ship_name_map.py`、`scrape_wiki_fast.py`、**`run_v2_full.py`**(两阶段全量驱动)、**`update_pipeline.py`**(★2026-09-29 新增：WF-15 那条 runbook 的阶段机，一条命令跑到待确认、第二条命令签字换入，见 **WF-23**)。

**可复用诊断/验证工具 `scripts/diag/`**：承重工具清单已逐字外迁至 `docs/archive/PROJECT_STATUS_diag-tools_2026-10-29.md`（原第 165 行）；具体清单以目录为准（该清单的计数已过期）。

**文档**（导航见根目录 `README.md`，写入路由见 `AGENTS.md`）：
- `docs/DEV_LOG.md` 操作手册 · `docs/WORKFLOWS.md` 可复用工作流 · `docs/TROUBLESHOOTING.md` 踩坑 · `docs/ERRORS.log` 错误流水
- `docs/tools/` ALPA、AssetStudio 使用说明
- **项目技能库 `.agents/skills/`**（8 个，入库）：`live2d-web-runtime-integration`(新建)、`unity-assetbundle-painting-restore`、`headless-chrome-cdp-batch-export`、`safe-pipeline-fix-targeted-rerun`、`windows-hardlink-dedup-verify`、`windows-local-server-launcher`、`cn-blocked-resource-mirror-fetch`、`project-doc-governance`——做同类任务前先查这里，别从零摸索
- `docs/archive/` 历史归档（含 `PROJECT_STATUS_历史归档.md`、旧目录审计报告、旧 Spine 交接）

**数据**：`asset_manifest.json`、`Output/dependency_manifest.json`(86,398 条官方依赖表)、`Output/WikiData/ship_data.json`、`Output/gallery_v2/index.json`。

---

## 6. 接下来的任务

### ★ 2026-09-29 画廊视觉（Q 轮）已定稿并刷进正本（新会话先读这条）

**已定（别再回头问）**：背景 = CPU 波动方程 + WebGL 着色的**水面**（静止一帧都不画，
划过才起浪，着色器里没有 noise/fbm/curl）；样板页**已刷进正本**（回滚锚点 = 换入前 `ee931aa`，
4/4 同 inode、探针打正本 24 条 `EXIT=0`）；底部 76px 空带**已删**（卡片改透玻璃悬空）；
§6.18 五条真缺陷全部关闭（含 ④`:focus-visible` 键盘焦点环、⑤开关用 LED 与瞬时动作区分）；
**不要**跟着鼠标发光、**不许**回弹/压扁（有回弹=果冻，只有亮度变化=iOS）、
弹层三个原生下拉不换自绘。做法与判据见 **WF-16 追加（2026-09-29）**，踩坑见 **§62**。

**待办（按序）**
1. ✅ **WF-16 全量回归六件套已过**（2026-09-29 串行 runner `wf16_regression.py`，六件退出码全 0；全库 269 模型 / 3309 部位 **WIRING=0 / OUTSIDE=0**、可点中率 97.1%，与 §27 基线差在抖动量级、总数不变）—— 流水外迁 **A21 段**。
2. ✅ **元数据兜底顺序已换成"配置优先"并换入**（原记"112 组"是错的：实测 84 组两名不同、其中 **49 组配置名属另一实体**、被零回退不变式自动挡下，最终换入 **64 组 = 45 真换名 + 10 去尾空格 + 9 占位符回落**，`with_cn` 984→975；占位垃圾按"像不像真名"写判据挡掉、不开例外名单）—— 全过程 `docs/name_review_20260929.md`，闸门 `--expect` 按值钉死，流水外迁 **A21 段**。
3. ✅ **`.diag/` 已清 + 那笔散落代码债已还**（2026-09-29：删 49 个 profile / **释放 4.42 GiB**；67 个代码文件里 10 个零损失直删、57 个独有的打包，顶层散落代码现 **0**）。⚠️ `.diag` 在 `.gitignore` 里 ⇒ **删了没有 git 兜底**，而那份 zip 也住在 `.diag/` —— 只保证能反悔一次，**不是永久备份**；要长留某个探针只能移进 `scripts/diag/` 入库。防复发闸门 `py -3 scripts/diag/check_diag_hygiene.py`（AGENTS.md 收尾第 4 条），流水外迁 **A21 段**。　（2026-10-17 再清 `chrome_*/ab_*/_old_*` 29 目录 / **11.3GB**，`.diag` 降至 0.76GB；`sharecfg_re` 因含唯一源 `scripts64.full.ab` + 完整 name_code 而保留，判据见 **WF-28**）
4. ✅ **本文档体量红线**：红线以 `wc -l` 实测为准（>400 触发）。⚠️ **"写得更省"压不住**——那一轮净增 3 行，只有整段逐字外迁才回到阈值内；溢出内容按轮次搬家（A15/A20/A21 段），工具 `py -3 scripts/diag/doc_verbatim_archive.py`（四条核对它自己跑）。
5. 若视觉再被否：**要外部参照物**（参考站/录屏）逐帧对齐，不要自己猜第 7 版。
6. ✅ **服务器"半死"已取证到底并堵掉一条无界泄漏**（已证死 `socketserver.handle_error` 往 stderr 打 traceback 时**每次客户端取消永久楔死一个 handler 线程**：2600 次掐断 ⇒ 线程 5→2605；修法落 `_gallery_server.py` 并配对照组证明没咽掉真异常，预检红路径已桩测）。**剩余靠现场不靠赌**：预检判红时会打一行进程外部 `pid/threads/handles/parentAlive`。两条否证 + 剂量学在 **§63**，流水外迁 **A21 段**。
7. ✅ **无头浏览器泄漏已从机制上堵掉**（2026-10-28，§159 / WF-49）：`atexit`/`finally` 在强杀下**都不执行**（实测三组对照），改由 `chrome_tree` 做三层兜底 —— **A Job Object**（`KILL_ON_JOB_CLOSE`，父进程一死内核杀光整棵树，`launch()` 与老接口 `install()` 都带）/ **B 启动前按 profile 精确清残留** / **C atexit + 回读确认**。全库 **60 个含 `--headless` 的文件 / 全部浏览器启动点已归一**（`launch` 58 + `install` 11，浏览器 `Popen` 残留 0），自测**五判据**全绿（阳性侧 15→0、`AL_NO_JOB=1` 阴性侧 15→24），顺带回收 **130 个 profile / 25.16 GiB**。⚠️ 接手：新探针一律 `chrome_tree.launch()`、不许自己写 `Popen`；收尾必跑 WF-49 的固定自检，非空即泄漏。**顺带更正一处流传口径**：宿主超时**不杀进程**（到点转后台，909 秒前台命令也能正常 exit 0），强杀来自会话关闭或外部 `Stop-Process`——`windows-long-running-batch-detach` 技能已同日改到 `version: 1.1.0`，WF-5 的历史前提也标注了更正。
> 诊断产物/缓存均在 `.diag/`（不入库，本机可继续用）。画廊前端**直接改 `gallery_src/` 里的正本即生效**（与 `Output/gallery_v2/` 已硬链，2026-09-26 起 4/4）；`py -3 scripts/deploy_gallery.py --check` 查有没有静默断链，`--relink` 补链，默认模式是断链后的 copy 回退。换机器/清过 `Output/` 后先 `py -3 scripts/fetch_gallery_vendor.py` 补运行时库（只双击 `Output\gallery_v2\` 里的 bat）。

### 既有待办

**✅ 0 / 0b. 2026-10-27 收官轮改动已全部提交 + 探针清单体检三处「尺子坏了」已修** —— 逐字外迁 `docs/archive/PROJECT_STATUS_待办0-0b_逐字外迁_2026-10-28.md`（A31 段）。
⚠️ 其中两条仍是活口：① `.diag` 78 个 chrome profile / 6.83 GiB 未删（`clean_diag_profiles.py --yes` 未执行）；② **24 个探针把 `CHROME` 写死成本机不存在的 `Google/Chrome`**（本机只有 Edge）⇒ 起不来，正解是 `scripts/paths.py` 的 `CHROME`（含 Edge 兜底）。**新增（2026-10-29）**：`f2811cb` 的批量迁移把 6 个探针改成「`chrome_tree.launch(...)` 跑在 `import chrome_tree` 之前」⇒ 运行时 `NameError`（`py_compile` 看不出来），已全修并给 `migrate_chrome_launch.py` 加了 AST 版 `--audit` 护栏（见 §165 / WF-55）。

**✅ 0c. 用户四条互动区需求（2026-10-28 提出；本轮 ③④ 收口，②仅剩眼睛/渐变待补）**
> **本轮（2026-10-29）③④ 的落地与判据**：③ 定位到**两个真缺陷**并修 ——
> ①「热区盒被 `Touch*` 点击标记撑爆」：`ougen_8` 的 `Stock1` 驱动集里 `#735 TouchDrag16`
> 读到 `(-293.09, 288.16)`，而整模顶点范围只有 `-448..154` ⇒ 热区盒从 **85994 缩到 30.5**
> （修前整块画布都是「丝袜开关」）；②「参数热区无条件抢在动作判定区之前」：改成
> **更具体者胜**（比可见多边形面积，幽灵区让位）。A/B 对照（改前页由
> `git show HEAD:gallery_src/index.html` 落盘）`ougen_8`：**HIT 19→26、WIRING 4→0、
> 判定区中心可达 31/31 不变**。见 §167 / WF-57 / SKILL §30。
> ④ **已逐动作验完**：`scripts/diag/l2d_param_retain_verify.py` 以**渲染有效值**为判据
> （包 `coreModel.update` 后读，不依赖 `beforeModelUpdate` emit —— 那个 emit 实测不稳定，
> 会给出空断言），`ougen_8` **55 个动作 × 12 条装扮参数全部保持、0 偏差**（两次复跑一致）。
> 反面对照：直接读 `getParameterValueById` 会报 51/55 个动作「被拉走」，那是曲线值不是渲染值。
> 同批修掉 3 个探针假红：`plainWheelNoop`（产品的 `ResizeObserver→refit` 竞态）、
> 重试循环漏捕 WebSocket 超时、`WIRING` 未算产品的拖拽编号轮转。**WF-16 六件套现全绿**
> （第 6 项为环境跳过）。
- **① `ougen_8` 少一只鞋 / 左脚消失** —— **✅ 已修（2026-10-29，§169）**，但**根因不是**原先记的
  「素材侧缺省关闭 + `Param233` 默认关」。真根因是 **`ShoseOff` 是三态参数（-1/0/1）被两态逻辑钳到残缺档**：
  `0`=穿鞋（7/15 件）、`1`=脱鞋黑丝光脚（5/15）、`-1`=残缺（3/15，左脚那只不见）。
  两处都掉进 `-1`：① `stateCurOn` 里 `cur=0` 到两端**等距** ⇒ 启动态被改写成 `-1`；
  ② `costumeTarget` 用 `min` 当关端 ⇒ 点击循环 `0→1→-1→1→-1…` 永远回不到 0。
  修法 = 默认值严格落在 `(min,max)` 之间时，关端取默认值。
  验证（走产品 `__costumeToggle` 连点 4 次）：渲染有效值 `0,1,0,1`、可见鞋件 `7,5,7,7`，全程未落 `-1`。
  ~~落地方式 = `Param233` 双写 pin~~ **该 pin 已于 2026-10-29 撤销**（§171）：`idle` 等动作里 `Param233` 的定值是 0，产品硬钉 1 与动作默认值打架，用户实测报「idle 的 Param233 默认被改错了」。现 `COSTUME_DEFAULT_ON` 已清空，装扮参数初始态一律以 moc3/动作为准（实测加载后 `Param233` 从 1 变回 0）。
  ⚠️ **两次翻盘留痕**：首版写「素材侧缺省关闭」→ 被"打开就有双脚鞋"推翻；
  二版写「`ShoseOff`/`Param233` 各管一只脚应联动」→ 被**逐件镜像配对 0 命中**推翻，联动代码已全删。
- **② 全部换装/可调参数的互动区** —— **✅ 已覆盖全部 5 个模型（2026-10-29，§170）**。
  旧扫描判据方向是反的（「动作间锁成不同档」⇒ 把装扮参数全剔掉，`ougen_8` 只报 4 条），
  改用**运行时反查绑定**（min/max 两态比 opacity+visible+顶点包围盒，任一变化即算控制画面）。
  `costume_params.json` 从 1 个模型扩到 **5 个**：`ougen_8` 12→13 条（新增 `ChestMoney`）、
  `benningdun_2` +3（`GloveTransparency_L/R`、`Paramring`）、`aersasi_2/3`、`antu_2` 各 +1（`Paramring`）。
  5 个模型全部通过可点击性验收（屏幕 ≥8px，最小 `aersasi_3` 14.7×14.7 px）。
  仍无热区的只剩 `BondEyes`/`HeartEyes`（`n_drawables=0`，按设计走面板控件）。
  ⚠️ 反查的仪器自噪声已修：复用全局基准会把 `benningdun_2/Paramring` 从 2 件虚报成 71 件，
  必须逐参数重取基准（见 §170）。
  **面板可读性（2026-10-29 用户反馈后修，§171）**：用户报「参数/部件拖了没反应、只有换装有效」。
  实测**通路本身是好的**（`Part34` opacity→0.05 画面变化 520470 px、`ParamAngleX` 变化 27259 px），
  真因是**列了空条目**：310 个部件里有 84 个挂 0 个 drawable（`Part406` 就是），拖它必然零变化。
  ⇒ 部件区只列有内容的（`部件 226（有内容 / 全部 310）`），参数区标题标注「调试用；
  多数条目在当前姿态下无可见效果」。参数/部件区**保留**（是定位参数控制什么的唯一入口，
  本项目多次排查靠它），没有按用户建议改名成「换装参数」并删掉 —— 问题在标签没说清用途，不在功能多余。
- **③ 互动区系统性排查**：可达率基线**已重标（`l2d_hotzone_reachability.py`，盒哈希 `-937102468`，GATE PASS）**：`Cloth1/Cloth2/Cloth3/Param233 100%`、`ShoseOff 97.8%`、`NeckMoney 82.4%(own=0 全靠幽灵区)`、`Stock1 78.9%(主要被 Stock2×279 抢)`、`Stock2 74.1%(被 Stock1×402+ShoseOff×167+Cloth1×38 抢)`、**`Paramring 0.0%（面积仅 0.25，结构性不可点）`**；⑥ 反解点 9/9 全部命中自己（exit 0，`reachability_ougen_8.json`）。~~另需用 `l2d_param_effect_scan.py` 对 12 条参数批量重扫并与 `param_drawables.json` 比对（`Param233` 漏 16、`ShoseOff` 漏 3）~~（**已做完**：改用修好仪器的 `l2d_param_map_batch.py`，12 条可信映射已产出并将逐字原文/逐条比对表外迁同目录 **B2 段**）；`param_drawables.json` 仍未替换（旧表 24 处漏项仍在）。
- **④ 切动作时参数合理保留** —— **✅ 已完成并逐动作验证**（见上「本轮 ③④」块）。数据层结论不变（换装参数在各动作里全是定值 0 ⇒ pin 接管是唯一路径，§162 / WF-47）；本轮补齐的是**验收**：`l2d_param_retain_verify.py` 覆盖全部 55 个动作 × 12 条参数，0 偏差。⚠️ 验收判据必须是**渲染有效值**，不能是参数回读值（后者 51/55 个动作会假红）。
- **影响面（用户问「其它角色还有没有部位消失」）**：对每个 skin 跑「几何镜像配对 + 不透明度绑定搜寻（带阳性对照）」。⚠️ **绝不许复用 292/45 或 9412 轮的任何区域框**，每 skin 重新取 canvas rect。优先筛「某 `ParamN` 只在少数动作被推到 1、其余恒 0、且控制 ≥5 件」——`Param233` 正是这个模式。

**优先级低**
5. UI/图标批量导出（~2 万）、3D 宿舍资源、资源分类整理 `organize.py`。⚠️ 前两项的源包（`ui/` 除 `commonui_atlas`、`dorm3d`、`island`、`char`）已于 2026-10-06 按裁定删除 ⇒ 开工前要先重拉，且**必须先撤销 `pruned.json` 里的对应登记**（否则 `mumu_sync` 会按"已归档"跳过它们，`--only ui` 也拉不回来；工具还没有 `--revive`，见 WF-28 已知缺口）。
6. ✅→⏳ **声优中文姓名补全（答案表已到手，回填待放行；2026-09-25）**：用新解析出的 `voice_actor_cn` 已拿到 **525 条 `code → 中文声优`**（`.diag/sharecfg_re/voice_actor_cn.json`）；对 `ship_skin_template` 实际用到的 499 个 `voice_actor` 值，**只缺哨兵 `-1`/`0`，真实 id 覆盖率 100%** ⇒ "CV 姓名表未缓存"这个前提作废。**已完成并写盘（2026-09-25 E1）**：`Output/ship_meta.json` 重写，逐字段比对 **既有值变化 0 / 字段消失 0**，**4041/4495 条带 `voice_actor_name`**（库尔斯克→衣川里佳、泛用型布里→下田麻美）；无名 454 = 427 剧情角色 + 27 个 voice_actor 为 0/-1。备份 `Output/_OLD_bak/ship_meta_pre_25.json`。见 §36。
8. ⏳ **磁盘优化仅剩一项**：`Output/Raw/` 2.02 GB（09-16 冻结层、零引用、可重导）⇒ 补完 `organize.py` 或承认它没用。✅ 本轮已收：BGM 改 FLAC 无损档并删净 wav 与 opus（回收 12.81 GB，见 §113）。
   ⚠️ **规模结论已过期，要重量**：并发会话今天为 4496 张立绘重渲换入新建了 `Output/_OLD_bak/paintings_v2_alpha_canvas_20261006/`（**16.1 GB**），使 `_OLD_bak` 从 §111 量到的 2.99 GB 涨到 **18.8 GB**；`.diag/paintings_rerun_20261006/` 另有 16.5 GB。两者都是**别人的在制品/其换前唯一备份，本轮一行没碰**——等那批收尾再跑一次 `check_disk_footprint.py` 才能谈清理。
   ✅ 本轮已做：① 按类目删 `dorm3d/island/char/ui` 共 **21,286 个源包 / 7.53 GB**，删除与登记同时落 `ledger/pruned.json`（依赖闭包闸门独立拦下 `ui/commonui_atlas`，与用户裁定一致；阴性对照 `--cat painting` 全拦、`artresource` 按深层传递依赖拦 105 个）；② **换入备份闸落地**：`extract_spine_v2.py` 写正式区必须带 `--bak`（覆写前逐份取前身字节 + md5 全等 + `MANIFEST.json`），顺带修掉 `main()` 丢返回值造成的"拒绝覆写也 exit 0"。判据 **WF-28** / 取证 **§111**。
12. ⏳ **一批"静止态就在画面内、却没登记"的判定区（2026-09-27 §51 顺带查出，另起一轮）**：
     `fix_model3.py` 登记 `Touch<X>` 的硬前提是"存在同名 `touch_<x>` 动作组"，于是**画面内、不透明度 1、
     但没有同名组**的标记被整批漏掉——实测 `yuanchou_3` 的 `TouchDrag20~23`、`qiershazhi_2` 的
     `TouchDrag7`（6.4×6.2 的大框压在角色身上）、`suweiaitongmeng_2` 的 5 个 `TouchDrag*`。
     游戏侧把这些按钮绑到哪条动作/哪个开关参数**没有权威依据**（`touch_drag20` 这类组根本不存在），
     不能猜着登记。取证工具已就位：`py -3 scripts/diag/l2d_hit_offcanvas.py <key>` 第 ② 段直接列全
     「moc3 里所有 `Touch*` drawable × 是否登记 × 此刻在不在视口内」。
     已知的相关机制（供下一轮起点）：换装状态是**各 clip 用定值曲线锁住 `TouchSiwa`/`Paramaixin` 这类开关参数**，
     所以只要找到"哪条 clip 锁成 1"，就能反推该按钮该播哪条。
15. ⏳ **4 张「整张画的每一层都是关闭态」的皮肤**（2026-09-27 §55 顺带查出）：
     `qiye_4` / `kelifulan_4`（各只有一层且它是关的）、`qiye_dark_memory` / `unknown2_memory`
     （`frame_0..3` 四层全关，游戏按剧情逐层激活）。过滤会把它们**清空**，所以规则是"一层不剩就原样保留"
     并记进 `C.INACTIVE_ALL`。要修得先知道游戏在哪一刻激活哪一层，**没有权威依据不许猜**。
     取证：`py -3 scripts/diag/painting_inactive_scan.py`（只读全库扫）+ `painting_inactive_rerun.py`（定向重渲+对照表）。

21. ⏳ **变体包按条切分，让 44 张「仅台词」皮肤也能点播**（用户未拍板，先不做）：那 36 张的 `voiceExtra`
     是 v1 时代**整包**导出的单个 wav（`Audio/CV/cv-<n>-<battle|gift>.wav`），对不到具体类别 ⇒
     现在只能整包听、配不上逐句正文。要修得重新解码 `-battle/-gift` 包并按 cue 切分（约 10 分钟 + 一次零回退比对）。
33. ⏳ **本轮查出来、与本轮改动无关的待办**：
     ① ~~`face_gate_labels_check.py` 那 4 条既有标签债~~ **已结案（2026-10-06 用户实见）**：
       `makeboluo`/`missd`/`feiteliedadi`/`dunkeerke` 四张对照图用户看过后判"没什么问题"
       ⇒ 维持现状（不叠），标签集不动、判据不动。
     ② **叠脸门控的判据本身有天花板**：MAD 量的是"底图这张脸是不是脸谱那张"，而正确动作要判的是
       "游戏在这里要不要换掉底图"——`yunlong_3`(该换，face 槽是 1924×2048 全身正面图、底图是背面)
       与 `xinzexi_h`(不该换，叠了切出矩形硬边) MAD 都是 32~34，这个量在原理上分不开，
       **抬阈值已否证**。要真修得去找 face 槽激活态的权威字段（`sharecfg` 侧？）。
     ③ **`gezi_2` Live2D 花瓣固定不动 —— 立绘侧已排除，Live2D 侧未结案（§114）**。
       排除依据：两张 4096² 贴图与源 `Texture2D` 上下翻转后 **0 像素差**；
       `l2d_motion_audit.py gezi_2 idle` 判 `ok`（源绑定 189 / 磁盘 681 = 189 真曲线 + 钉住的填充曲线，
       `unresolved=0`、时长 22.0 与源一致）；立绘三层全 active、零层被过滤。
       ⚠ 我上一版写的"Part 曲线 0 条"是**探针读错字段名**（真名 `PartOpacity`，idle 实有 150 条），
       且两次段值解析互相矛盾 ⇒ 现有测量不足以定案。**头号嫌疑 = `physics3.json` 的
       Inputs/Outputs 我读出来是空**（8 个 setting 组在，绑定读不出）——飘落类通常走物理不走曲线。
       下轮从这条接：先把 physics3 的键路径读对（拿一个已知会动的模型当阳性对照），
       再用自测过的解码器判"某参数值域是否真的不变"。

34. ⏳ **Spine 提取丢了 `MeshImage` 背景层 —— 14 个皮肤的 Spine 场景与 CG 缺背景（2026-10-06 查出，§114）**：
     `extract_spine_v2.py` 的 `skel_layers()` 只收 `SkeletonGraphic`，而游戏运行时这张 Spine 场景
     = `MeshImage` 背景 + `SkeletonGraphic` 角色。受影响 14 个：`aisaikesi_7` `banerwei_2`
     `bisimaiz` `gaoxiong_6`(BG1+BG2 两层) `haerbin_3` `haixiao_3_doa` `huanchang_2` `huben_2`
     `kaiersheng_2` `kalangshitade` `lundun_3` `luyisiweier_2` `masaiqu_2` `ougen_7`。
     另 12 个包的非骨架节点是 `*_shophx` 遮挡条，**本来就不该画**（§55），不要一起放过。
     ⚠ 别再用「依赖表名字含 `bg_tex`」筛——只捞出 3/14，其余 11 个背景住在 `_res` 包里、
     CAB 名不带 `bg`。权威信号 = 逐个 prefab 枚举 MonoBehaviour 类名 + `m_Sprite` 是否非空。
     修法：`skel_layers()` 一并输出这类节点（类名/CAB→bundle/世界框/绘制序），`parts.json`
     加一类 `image` 层，viewer 与 `cg_export.html` 在其上渲染骨架（复用 §110 的 DFS 先序绘制序）。
     做完这条之后，§6.33① 那个"画廊默认给 CG 还是给立绘"的取舍才不再是权衡问题。

---

## 7. 新会话对接指南

新会话发送：
```
我在做碧蓝航线 AssetBundles 解包项目。
进度: D:\Azur Lane Assets\PROJECT_STATUS.md
规则: D:\Azur Lane Assets\AGENTS.md（含文档写入路由表）
当前主线: v2 数据驱动管线（§9）+ gallery_v2（§10）
下一步: [具体任务]
```
要点：**画廊视觉（Q 轮）的待用户拍板项与待办在 §6 顶部 ★ 块，接手先读它**。静态立绘 / Spine 已由 v2 全量收官，Live2D 动作层已于 2026-09-21 按权威映射重建完毕，**2026-09-23 网页交互层三个根因（命中包含判定 / idle 循环 / V-P 坐标系）已修并回归**。接手前先读 §9 理解「游戏数据自洽、不要猜坐标/不要按位置猜参数名」这一核心结论。**验动效一律看内容**（曲线条数、Id 是否命中参数表、值是否随时间变化），不要只看 `currentGroup`/组名标签——空壳也能"启动"，这个坑已踩过一次（`docs/TROUBLESHOOTING.md` §17、`docs/WORKFLOWS.md` WF-7）。**验交互一律用独立锚点**——合成点击若与被测映射同源会自洽闭环、全绿也说明不了对齐（§20、WF-16）。历史 v1 调试见 `docs/archive/`，一般无需再读。

---

## 8. 技术备忘

**立绘命名**：`{舰名}`默认皮 / `_2`第2套 / `_tex`纹理 / `_n`夜战 / `_hx`换色 / `_rw`人物 / `_bj`背景 / `_front`前景 / `_jz`舰装 / `_alter`改造 / `_hei`黑化。多数脸烤进 `_rw`（仅 ~4% 有独立 face 部件）。
> **⚠️ 语义纠正（用户 2026-09-20 实测确认，别再按字面理解）**：**`_hx`「换色」实为和谐版**（内容被和谐处理后的立绘，不是调色变体）；**`_n`「夜战」实为不显示背景的立绘**（同一皮肤的无背景版，不是夜间场景）。二者都不是"另一套皮肤"。
> **⚠️ 又一处字面陷阱（用户 2026-10-03 纠正，见 **§88**）**：**`_hei`「黑化」实为剧情演出里的黑脸剪影**——不是另一套皮肤、**不是单独角色**、**本来就没有配音**（这 16 个键 `category` 全是 `story`、表内皮肤名是 `？？？`）。语音/台词层对它"不回退、归零算预期"是**对的**，但代码注释里"独立发声实体（用户裁定）"那句是错误转述，别当授权往下推。
> **✅ 画廊标签已改准（2026-09-20）**：`build_gallery_index.VARMAP` 由 `{'hx':'换色','n':'夜战'}` 改为 `{'hx':'和谐版','n':'无背景版'}`，重建 index 后 **1746 条皮肤 label 更新**，逐字段 diff 确认**非 label 字段变化 0**、船集合与皮肤集合完全不变、无「夜战/换色」残留。组合态形如 `皮肤2·无背景版·和谐版`。

**Live2D 结构**：`Output/Live2D/{name}/` = `{name}.model3.json` + `.moc3` + `.physics3.json` + `texture_*.png` + `motion/*.motion3.json`。

**PPtr 解析**：`m_Sprite=(FileID,PathID)`；FileID=0 本包，FileID=N → `SerializedFile.externals[N-1]` 的 CAB 名（≠ manifest deps 字母序）。

---

## 9. 当前主线：v2 数据驱动管线 ✅（2026-09-15，取代 v1 攻关路线）

### 9.1 匹配机制（游戏本体权威答案）★核心突破
- `AssetBundles/dependencies`(6.4MB 单包) 内 MonoBehaviour 携带 **86,398 条官方依赖表** → `Output/dependency_manifest.json`。
- 部件→纹理包 = deps + externals；对象定位 = PathID 精确匹配（一包多 mesh 不再错拿）；放置 = 统一 Unity UI 数学（anchor/pivot/sizeDelta/anchoredPosition/localScale 全递归；有 mesh 部件按画框 `mRawSpriteSize` 非等比映射 rect，无 mesh 部件 textureRect 直接拉伸铺满 rect）。
- 逆向关键：新版 bundle header `unity_version` 伪装成 `5.x.x`，真实 `2022.3.62f3` → 需 `UnityPy.config.FALLBACK_UNITY_VERSION="2022.3.62f3"`。静态立绘 = **纯 UI 结构**（RectTransform/CanvasRenderer，无 MeshRenderer），游戏把每个部件位置/大小/anchor/pivot 全写死，合成不需猜坐标。

### 9.2 静态立绘 v2（`scripts/compose_paintings_v2.py`）⚠️
零猜测、零手调。疑难样本 7/7 目视正确；v1 需手调的 feiteliekaer_3 / xili_alter / hailunna_4 现无参数自动正确。表情差分 `--faces all` 输出 `{name}_face{k}.png`。
> ✅ **嵌套容器错位已修（2026-09-18）**：带中间容器（`layers`/`Touch`）的皮肤子层曾被 `layout_all` 仿射多减 `p_local[0]` 甩偏（非 sortingOrder 问题），修复提交 `52782a7`，扫描 85/4486 受影响已全部换入。
> ✅ **i404 型背景缝隙已修（2026-09-19）**：无 mesh 部件误用 `mRawSpriteSize` 当画框致视差背景带压窄，改按 textureRect 拉伸铺满 RectTransform，10 张受影响已换入（见 §6 第 2 条）。注意 painting 本身即半景特写，完整 CG 走 Spine 线。
**全量收官**：4300 → **4486**（补合成 190，成功 186 / 失败 4 为非主皮肤杂项包，已加过滤）。输出 `Output/Paintings_v2/`。
> ✅ **2026-09-27 只画"游戏里开着的层"**（§9.3 第 7 条 / `TROUBLESHOOTING.md` §55）：`parse_painting`
> 现在把「自身 + 全祖先 `m_IsActive`」算进部件的 `active` 字段，`compose` 据此过滤。
> 全库 4488 张里 125 张有关闭层、48 张画面会变（26 张黑头 `shadow` + 14 张贴了 "NOT ABLE TO DISPLAY"
> 遮挡条 + 8 张赤城·改叠了四份画法），已备份换入并重建缩略图；12 张对照组逐字节零回退。
> 审计出口：`C.INACTIVE_SKIPPED`（跳过了哪些层）/ `C.INACTIVE_ALL`（4 张全层关闭、未过滤）。

### 9.3 九个系统性根因修复 ★教训（全部代码级、零逐角色参数）
1. 无 mesh 整图部件**双重 Y 翻转** → root 背景层颠倒。修：`arr = A[rect.y : rect.y+h]`。
2. Spine atlas 页纹理需 **`flip=True`**（运行时按行0=顶采样）。
3. Windows 分离进程 stdout 默认 GBK，`print('✓')` 抛错致全量**假失败** → `sys.stdout.reconfigure('utf-8')` + 子进程 `PYTHONIOENCODING=utf-8`。
4. `layout_all` **root scale 只乘子层未乘 root 自身** → 层间比例错。修：局部空间纯 anchor 数学 + 仿射映射世界 + 自身 scale 绕 pivot（负=镜像）+ root 屏幕适配 scale 归一为 1。
5. 无 mesh 部件**误用 `mRawSpriteSize` 当画框** → i404 型视差背景带（记录切分前原图尺寸）被压窄留黑洞。修：按 UI Image 语义 textureRect 拉伸铺满 RectTransform；mesh 部件才用 frame。
6. `rasterize_mesh` **把内容钳死在画框内** → mesh 顶点合法越框的皮肤（kuersike_rw 头部伸出框顶 713px）被裁头、纹理矩形露缝。修：按内容实际 AABB 输出（±2~3 倍框安全钳），越框部分由 render() 仿射照常映射。
7. **不读 `GameObject.m_IsActive`** → 游戏里**关着**的层被一律画上去：`shadow` 纯黑剪影压在头上
   （用户报的"头黑"）、`shop_hx`/`*_shophx` "NOT ABLE TO DISPLAY" 遮挡条贴在身上、
   `chicheng_alter_rw1..4` 四份备用画法叠成四个身子。修：`parse_painting` 把「自身 + 全祖先激活」
   算在部件的 `active` 字段上，`compose` 只画开着的层；**`face` 槽豁免**（恒关、运行时才激活，
   是 §48 叠层的输入）、**过滤后一层不剩则原样保留**（4 张全层关闭的皮肤清空=静默失败）。
   全库 4488 张命中 125、画面真会变 48、逐字节不变 73（白条早被 `is_lighting` 挡着）。见 **§55**。
8. **`canvas.paste(img, box, img)` 把 alpha 通道缩放两次**（Pillow 对 RGBA 蒙版的行为，
   文档原话 "scaling the alpha channel twice"）→ 铺在空画布上时 `a → a²/255`，
   **全部 4500 张的柔边系统性偏淡**（实测在盘成品 99.81% 半透明像素命中 a²/255）；
   并连带打出 1px 透明缝（用户报的"白雪皮肤2 脖子一条细空线"）、把叠脸门控的
   `alpha>=250` 读数压低 → `gezi_2` **正式产物一直在发被误叠的错表情**。
   修：`over()` = `Image.alpha_composite`（标准 source-over）。见 **§114** / **WF-29**。
9. **画布只取 `max(x+w)`/`max(y+h)`、从不减 min** → 世界框落在负侧的部件被 paste 静默裁掉
   （`beier_rw` 丢该层 15%、`jinluhao_2` **整张画下半截没了**、`i404` 只剩偏在一角的残片）。
   修：`canvas_frame()` = **所有节点框 ∪ 各层落笔框** 的并集，min 钳在 0。
   ⚠ 两个反例都进了判据：为省内存把容器 rect 从 max 侧剔掉 → `baixue` 画布**变窄**反而新裁
   2,771 像素；只按"负侧框"筛候选 → 影响面低估为 19 张（抽样实测 **2.0% ≈ 90 张**）。见 **§114**。
> 结论再次印证：游戏数据自洽，所有错位都是解析姿势不对。第 8/9 条补一句：**"姿势"也包括
> 用什么库函数落笔、画布边界取在哪**——数据读对了，落盘算子错一样全库错，且**不报任何错**。
> （完整明细含文件行号与验证样本，见 `docs/archive/PROJECT_STATUS_历史归档.md` 末尾「完整明细存档」。）

### 9.4 Spine v2（`scripts/extract_spine_v2.py`）✅
双结构兼容（内联型 + 分离 `_res` 型）+ 外部页纹理按 deps 补齐 → `Output/Spine_v2/`。全量 **232 主包**完成。skel 3.8.99，皮肤为多部件骨骼（B/M/T）需分层合成。

**失败语义已收口（2026-10-07）**：`main()` 现在 `失败 N>0 → exit 1`（以前掉出函数尾 ⇒ `sys.exit(None)` ⇒ 0），且整批路径下「提取成功但 `parts.json` 落不下」不再伪装成行首 `✓`（原 `parts.json ✗ 原因` 塞在行尾，而两个调用方 judge 都按行首匹配 ⇒ `run_v2_full` 连 `ERRORS.log` 都不写）。核实过两个程序化调用方（`run_v2_full.py:100` / `update_pipeline.py` `st_spine`）本来就不看退出码，故非零退出对它们是纯增益、无需放行。闸门 `py -3 scripts/diag/test_spine_exit_code.py`（桩驱动真实 `main()`，6 例含备份闸 exit 2 不退化）。取证 **§111 第 4 节** / 原则 **WF-15 第 1 条**（其余 8 个脚本仍未修，退出码依旧不作通过证据）。

### 9.5 Live2D 核查 ✅（2026-09-21 结论已更正）
266 个 live2d 包本地零缺失、自包含。**旧结论「剩余仅 motion 质量（§2.5 B 类 12 模型）」是错的**：
motion 大面积失效源于我们自己的解析器（帧 0 护栏 + 曲线名按位置猜），不是资产缺口；
已按 `genericBindings`/`crc32` 权威映射全量重建（见 §2.5 与 `docs/TROUBLESHOOTING.md` §17）。
资产层真为空的只有 7 条 clip（`effect` / `idle11` 一类占位动画）。

---

## 10. 本地资产浏览平台 `Output/gallery_v2` ✅（2026-09-15）

> ▸ 画廊**形态描述**（本地网页 / 数据规模 / 参照对象）已外迁（逐字）：`docs/archive/PROJECT_STATUS_gallery-shape_2026-10-29.md`（原第 377 行）。
- **数据**：`build_gallery_index.py`（合并四类 + `ship_name_map` 拼音→中文 812 条 → `index.json/js`；Spine 皮肤附 `cg` 字段指向 `CG_v2/`）+ `make_thumbs.py`（Paintings_v2 + CG_v2 → 380px WebP，CG 缩略图 `<stem>_cg.webp`）。结果 954 船 / 4489 皮肤 / spine 235 / CG 235 / live2d 262 / 语音 268。⚠️ **2026-10-17 重建**：静态立绘全量 4452/4452 重渲换入（`Paintings_v2`）、`ship_meta.json` 4458 条、`skin_words.json` 5.9MB、单体内 `index.js`（spine 235 / live2d 262）、CG_v2 全量 235/235（233 新 + 2 样本）——索引从中残留样条翻新为完整版。
- **前端** `index.html`：网格懒加载 + 搜索/阵营/舰种/稀有度筛选 + **类别分段（全部/舰船/剧情角色/剧情剪影 四档，主网格按 `category` 分区渲染各带小标题计数；「剧情剪影」是 2026-10-03 加的第 4 档，`_hei` 已不进皮肤区也不进主网格，见 §90）**；详情四标签。「静态立绘」对 Spine 皮肤默认展示全屏 CG（可切换回 painting 原件），支持**滚轮缩放(光标锚点)/拖拽平移/双击100%/全屏浏览/复位**；Spine 标签 `vendor/spine/spine-all.js`(3.8) 分层 WebGL 播放（相机视口/动画过滤已修，**支持全屏**）。服务器统一响应 `Cache-Control: no-cache`，改版后浏览器不再吃旧缓存。
> ▸ **取景与视角记忆**、**画质 2x·DPR 校正**、**视觉语言定稿**、**源码硬链治理**、**5 样本预览线**、**画廊形态**等已闭环内容均逐字外迁至 `docs/archive/`；原始行号见各归档文件首行注释。
> ▸ 画廊**视觉语言定稿**（水面背景 + 玻璃拟态 + iOS 丝滑，含 24 条验收判据与踩坑 §62）已外迁（逐字）：`docs/archive/PROJECT_STATUS_gallery-visual_2026-09-29.md`（原第 381-385 行）。
> ▸ 画廊**源码正本与运行目录的硬链治理**（`gallery_src/` 为唯一权威、`Output/gallery_v2/` 为运行目录、两边硬链、收尾必跑 `deploy_gallery.py --check`）已外迁（逐字）：`docs/archive/PROJECT_STATUS_gallery-srcauth_2026-10-29.md`（原第 386 行）。
- **运行**：`启动资产浏览器.bat`（→ `_gallery_server.py`：8777 端口 + `allow_reuse_address` + 端口占用即复用 + 结尾 `pause`，杜绝闪退）。file:// 下立绘/语音可看，Spine `fetch` 被 CORS 拦需走 .bat。
> ▸ **2026-10-24「动作数据补全 + 播完回落」的完整取证**（ConstantClip 曲线全丢 / 播完不回 idle / 旧画廊数据不能抄 / 「部件消失」已取证为源模型特性）已外迁（逐字）：`docs/archive/PROJECT_STATUS_motion-clips_2026-10-24.md`（原第 393-406 行）。

> ▸ 画廊**运行方式 / 运行时库台账 / 5 样本预览线**等运维细节已外迁（逐字）：`docs/archive/PROJECT_STATUS_gallery-ops_2026-10-29.md`（原第 388-389 行）。
> ▸ **5 样本 Live2D 预览线**、**画质 2x·DPR 校正**、**取景与视角记忆**三节的完整取证均已在 `docs/archive/` 下（逐字）；原始行号见各归档文件首行注释。`docs/archive/PROJECT_STATUS_gallery-5sample_2026-10-29.md`（原第 393 行）。
- **✅ 11 项权威输入已恢复（2026-10-23，游戏版本 9.7.385 → 9.7.395）**：新 clone 后 `check_inputs.py` 从 11 项缺失转为 **2 个台账全部一致、exit 0**。重建链路 `34 → 35 → 41 → 37 --scalar-all → 42 / 45 / 46 / 47 / 48`（azdata 另走 `publish_azdata_local.py`），原始数据取自本机 `files/AssetBundles/sharecfgdata`（32 表 / 113.4 MB）与 `files/AssetBundles/scripts64`。
  - **链路可信度有硬证据**：`voice_actor_cn.json`（525 行 / 10827 B）与 `character_voice.json`（85 行 / 12505 B）重建后 sha256 与旧台账**逐字节相同**；azdata 的 `statistics`(6438126 B) / `template`(3745427 B) 字节数亦完全相同。
  - **变了的就两行**：`ship_skin_words` 2574→2575、`ship_skin_template` 2870→2871（azdata 同名表 5060419→5062169），增量是**尼尔联动角色 A2 / 2B**（id 11700010 / 11700020 / 11700021），属真实版本更新而非解析错误。
  - ⚠️ **版本号此前是硬编码的假台账**：`42_publish_gamecfg.py` 与 `publish_azdata_local.py` 都把 `9.7.385` 写死，游戏已到 395 仍在台账里记 385。已改为**从 `files/version.txt` 读盘**，版本号只有一个权威来源。
- **✅ Live2D 动作数据补全 + 播完回落修复（2026-10-24）** —— 已闭环，完整取证（ConstantClip 曲线全丢 / 播完不回 idle 两个缺陷、旧画廊数据不能抄、「部件消失」取证为源模型特性）逐字外迁：`docs/archive/PROJECT_STATUS_motion-clips_2026-10-24.md`（原第 393-406 行）。

---

> **历史归档**：v1 时代攻关路线、多部件合成已知问题清单（Bug#1-#4）、7-30/7-31 修复记录、bj 背景层专项、调参工具 v3-v6 会话流水、旧 Spine Viewer 调试史 → 全部见 `docs/archive/PROJECT_STATUS_历史归档.md`。

> ▸ **2026-10-19 HitAreas 补全**：`fix_model3.py` 对 `Touch*` 先查 `touch_<x>`，没有再退回 `<x>`；全库 38 模型补 128 个 `TouchIdle*→idle*`（含 ougen_8 脱鞋 TouchIdle6→idle6）。`TouchDragN` 只播 drag 动作（有 touch_dragN 用同名，否则轮转）；脱鞋是玩家拖动交互，不能改播 idle6。取证 §130。
