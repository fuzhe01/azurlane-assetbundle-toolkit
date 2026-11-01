# 碧蓝航线 AssetBundles 解包项目 — 进度总结

> **生成时间**: 2026-11-01（**本轮收尾：修掉闸门自身的两个缺陷** —— `check_merge_numbering` 判据盲区导致「WORKFLOWS 44 正篇无重复」的假绿灯（真实 64 篇）、`§133` 重复且坏副本反引号被整体剥离，见 **§180**。上一段同轮：全库路径迁移落地。43 个 `.py` + 2 个 `.bat` 收进 `scripts/paths.py` 唯一出口，`AL_ASSETS_ROOT` 可覆盖、无 Chrome 时兜底 Edge；闸门 `check_paths.py` 由「软档只报数」改为默认全判红，并补上 `.bat`/`.ps1` 三个盲区 —— 换盘符/换用户名/换机器不再炸，见 **§178 / WF-62**。上一轮（同日）：一批"沉默型"缺陷全库体检，见 §177。2026-10-31 上一轮：修好「别名链自己成了单点」导致的会话 502 复发）① 用户报「修好后又报错」，真因**不是**上下文超限、**不是** SSE 补丁失效，而是上一轮为躲 `flash` 限流加的那一跳 `flash → -sg`：`flash` 先解禁（10:43）、`-sg` 仍在限流（13:18 才解禁），于是别名链**反向把请求引到唯一挂掉的通道**。判据 = 同一份真实 607 条请求体（1.03 MB）重放：`flash` 200 / 8.2 s / 31 字符 vs `-sg` **502 QUOTA_EXCEEDED / 0 字符**（阴性对照有效）；② 修法 = `--unalias` 删掉有害那一跳 + `--alias -sg=flash` 补漏网会话 `b05ca5fd`。最终别名 **3 条、全 1 跳**，复测 200；③ 新增纪律：「**别名链是单点**」——加跳前必须 `--probe` 实测终点、改完必须 `sync_session_model.py --list` 交叉核对（**不在别名表里 = 请求直接失败**）、**台账 `state.json` 的限流条目解禁后不消失，不可当判据**；④ 新增 `scripts/diag/probe_relay_models.py`（中转层通道实测，穿透「HTTP 200 + 流内 error」假绿灯）；`apply_oaicopilot_model_alias.py` 加 `--unalias/--probe/--selftest`（行为用例 7+3 全 PASS）。⚠️ **别名改动需重载窗口才生效**；⑤ 工作树两处来源不明的回退（`TROUBLESHOOTING.md` 少 78 行、`sync_session_model.py` 被删）已 `git checkout --` 无损复原。详见 §175「第三次复发」）
> **上一轮（2026-10-30 傍晚）**：判定区全库审计修 59 条真遗漏 + 分屏拖动界限。① 判定区规则已读源码并审计：`fix_model3.py` 两段规则（占位替换 + 补登记）；`benningdun_2` 因**下划线形态**（`Touch_Idle6` 被拼成 `touch__idle6`）漏登记 59 条，修后判定区 **217 → 277** 条，前端可用 78 条、**退化 0 条**，其它 4 模型**逐字段零回退**，见 §175 / WF-59；② 分屏拖动加了**界限**（遮罩边界必须落在画布内）：`vMin=4.57 / vMax=15.32`，两端左右内容占比均 >99%，拖到画布外被夹住；③ **否证**：`Param373` 只做遮罩**裁切**，内容位移**恒为 0**（一维互相关 5 档全 0、842 件可见性变化 0、25 个 fan-out 内容件 0 件移动、842 drawable 无重名）⇒ 该模型不存在「右侧画面跟随拖动平移」的机制，用户描述的游戏行为在解包数据里没有对应参数，见 §176；④ 仪器修正：探针必须关浏览器缓存（`model3.json` 被缓存会让「改了不生效」伪装成产品缺陷）。上一轮（同日）：双脚联动 + 分屏线拖动，流水逐字外迁 `docs/archive/PROJECT_STATUS_headline_2026-10-30.md`）
> **环境安装（换机器复刻先做）**：
>   1. 装 Python **3.15**（2026-10-23 起本机约定；UnityPy 1.25.4 无 cp315 预编译轮子，需源码编译，见 §2 Python 行）。⚠️ 本机同时装着 3.14，`py -3` 指向谁由 `%APPDATA%\py.ini` 决定（现固定 3.15），**跑之前先 `py -3 scripts/diag/check_env.py`** 确认实际解释器与依赖
>   2. 仓库根 `py -3 -m pip install -r requirements-v2.txt`（3.15 上必须走阿里云/腾讯云源，清华源连 sdist 都没有；需 MSVC BuildTools 编译 UnityPy + lz4）
>   3. 校验依赖**真的可用**：`py -3 scripts/diag/check_env.py`（载荷级验证，比 `scan_build_deps.py` 强 —— 后者只做 AST 静态扫描，import 缺失也照样 exit 0）
>   4. 外部工具走 `scripts/paths.py`（adb/vgmstream/ffmpeg/chrome；env 或已知安装位兜底）
>   5. 画廊前端 vendor：`py -3 scripts/fetch_gallery_vendor.py --check`（4 个第三方 JS；spine-all.js 已换官方上游源；缺件用 `py -3 scripts/fetch_gallery_vendor.py` 补齐）

> 历轮会话流水（2026-09-20 ~ 10-17 逐轮记录）已逐字外迁 `docs/archive/PROJECT_STATUS_2026-10-17_逐字外迁.md`（A30 段）；本文只留当前状态。
> **本轮（2026-11-01）**：① 全库路径迁移 —— 43 个 `.py` + 2 个 `.bat` 收进 `scripts/paths.py`，闸门由软档改默认全判红并补 `.bat`/`.ps1` 盲区（**§178** / **WF-62**），逐轮流水逐字外迁 A26 段。② **合并 fork `fuzhe01/…` 的 97 个提交**（分叉点 `149053b`，`git merge-tree` 干跑出 15 处冲突，全部并集解、两边零丢弃）：编号让号 `WF-30/31/32 → WF-60/61/62`、`§115/§116 → §177/§178`；三道闸门因「对方的存量」变红，改为**冻结基线 + 只拦新增**（`check_paths` 89 文件、`check_lint_baseline` 160 条指纹、`check_doc_numbering` 21 个缺号 —— 后者的「必须 1..N 连续」判据已**废弃**，闭环条目逐字外迁产生的缺号是正确的归档结果）；新增 `scripts/diag/check_merge_numbering.py`（三方 `§N`/`WF-N` 撞车比对，合并产物自检用 `--worktree`）。5 道闸门全 PASS，`PROJECT_STATUS.md` 414 → 359 行（0c 段 62 行逐字外迁）。见 **WF-63 / §179**。③ **收尾自查又抓出两个缺陷**：`check_merge_numbering` 的判据把标题形态钉死（只认 `^## §N` 与 `^### WF-N:`），漏掉 `### §136.` 与 `## WF-42 标题` 两种真实写法 ⇒ 得出「WORKFLOWS 44 正篇无重复」的**假绿灯**（真实 64 篇且有重复，漏检 19 篇 WF + 7 篇 §）；另发现 `§133` 同号重复两份，**前一份的反引号被整体剥离**（`play(g) 里 played.add(g)` 退化成 `里  先执行`，28 → 0 个反引号），删坏留全（`TROUBLESHOOTING.md` 10128 → 10106 行）。见 **§180**。
> **本轮当前修复（2026-11-01）**：恢复 4 个被压成单行注释、运行即静默 exit 0 的诊断/打包工具与一键重建入口；补上依赖扫描错误报告、截图包围盒坐标、更新计划单次指纹计算、MuMu 默认范围/非空目录保护，并让批处理检查最终汇总与失败数（**WF-64 / §181**）。只跑了计划、合成夹具和静态验证；本机缺少 `files/AssetBundles`，**未执行 `--yes`、未连模拟器、未跑真实资产全量重建**。
> **用途**: 跨会话对接。**v1 时代历史已外迁 `docs/archive/PROJECT_STATUS_历史归档.md`**，本文只保留当前状态与主线。当前待办见 §6。
>
> **【其它待办】**~~§6.11 HitAreas 生成规则漏了 `touch_*` 组名~~ **已于 2026-09-22 修复落地**（13 模型真实判定区、全库 806/807）｜**剧情 CG 混进 `Paintings_v2/`** 的识别与分离（用户指出"脸黑的基本都是剧情 CG"，与缺脸是两类问题，见 §6.8）｜**结构隐患**：~~`azdata_*.json` 权威元数据源仍住在可被清理的 `.diag/`~~（**2026-09-24 已迁 `inputs/azdata/` + sha256 台账 `MANIFEST.json` + 校验 `scripts/diag/check_inputs.py`；数据本体仍不入库**，理由：9.2MB 游戏配置属资产、zlib 后 0.67MB 虽小但仓库原则是「只承载可复现的工具与知识」）——**该项：21 个脚本硬编码 `D:\Azur Lane Assets` / `C:\Users\KLLM` 绝对路径**，其中 **13 阶段调用链上 9 个**
（`compose_paintings_v2`、`extract_spine_v2`、`reconstruct_live2d`、`extract_motions`、`fix_model3`、
`extract_cv_voice`、`export_dependency_manifest`、`mumu_sync`、`run_cg_export` 的 Chrome 路径，外加
vgmstream/ffmpeg 钉在 `C:\Users\KLLM\AppData\Local`）⇒ **换盘符或换用户名必炸，不是"迁移困难"**
（2026-10-01 应"这项目可迁移吗"实测；`update_pipeline.py`/`pipeline_panel.py` 自己走 `__file__` 推导，可迁；
数据 `files/` 28.9GB + `Output/` 约 45GB 不入库，需单独拷）｜~~**21 个脚本硬编码绝对路径 ⇒ 换盘符/换用户名必炸**~~ —— **2026-11-01 已全量迁移落地**：43 个 `.py` + 2 个 `.bat` 统一收进 `scripts/paths.py`（唯一路径出口，`AL_ASSETS_ROOT` 可覆盖；无 Chrome 时兜底 Edge，拿不到则 `chrome_or_die()` 给可执行补救句）；闸门 `check_paths.py` 由「软档只报数」改为**默认全判红**、并补上 `.bat`/`.ps1` 盲区——**换盘符/换用户名/换机器现在不会炸**（WF-62 / §178）。｜
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
> **上一轮执行快照续**（§76 又挖出一条接线缺失：卡片上的「签字放行」复选框只接线了展示、没接执行）已逐字外迁 `docs/archive/PROJECT_STATUS_prev-round_2026-10-30.md`（原第 31 行）。

---

## 1. 项目概览

- 对碧蓝航线 Unity AssetBundle 解包、分类、导出、还原。
- 源路径 `D:\Azur Lane Assets\files\AssetBundles`，**196 类目 / 71,393 文件 / 21.89 GB**（2026-10-06 按类目清理：删 dorm3d/island/char/ui 共 **21,286 个源包 / 7.53 GB**，删除与登记同时落 `ledger/pruned.json` ⇒ `mumu_sync` 不再把它们报成"新增"；清理前 240 类 / 92,679 文件 / 29.42 GB。判据与过程 **§111 / WF-28**）；产物侧 `Output/` 48.5 GB，全仓约 **70 GB**（口径统一 = `scripts/diag/check_disk_footprint.py`，GiB）。
- **当前主线 = v2 数据驱动管线**（见 §9）：零猜测、零手调，已全量收官。

### 仓库治理 ✅
- 忽略规则收敛为「保留源码与文档，忽略游戏资产与生成产物」：忽略 `files/`、`Output/`、`tools/`、`.micode/`、`.mimocode/`。
- 生成产物与资产元数据已从 Git 索引移除，避免再次提交游戏资产。
- **提交闸门（两道 hook）已装并可自检**（2026-11-01 体检时发现 `.git/hooks/` 只有 `.sample` ⇒ 闸门从未生效）：
  `py -3 scripts/install_git_hooks.py --check` 退出码即结论（4/4 与正本逐字节相同）。
  ⚠️ `.git/hooks/` 不入库，**换机器 / 重新 clone 后必须重装**，否则 AGENTS.md 那两条规范形同虚设。见 **WF-60**。
- **静态体检基线已冻结**（`py -3 scripts/diag/check_lint_baseline.py`）：真缺陷类
  （`undefined name` / `redefinition` / 字典重复键）**必须 0**，其余 pyflakes 存量 **160 条**按 `(文件, 消息)` 指纹冻结、不许再增（行号漂移不假红；WF-61 / §179）。
- **五道闸门全 PASS**（2026-11-01 合并 fork 97 提交后重建，总耗时 < 3 秒）：`check_paths`（绝对路径存量 89/89 冻结 + 只拦新增）、
  `check_lint_baseline`（160 条指纹）、`check_doc_numbering`（§6 缺号 21 个冻结，**原「必须 1..N 连续」判据已废弃** —— 闭环条目逐字外迁后缺号是正确的归档结果，不是缺陷）、
  `check_diag_hygiene`、`check_merge_numbering`（**新增**，三方比对 `§N`/`WF-N` 撞车；合并产物自检用 `--worktree`）。见 **WF-63 / §179**。
  ⚠️ 该工具的判据**曾自带盲区**（2026-11-01 收尾时自查发现并修正）：旧正则把井号级数与号后形态钉死
  （只认 `^## §N` 与 `^### WF-N:`），漏掉了 `### §136.` 与 `## WF-42 标题` 两种真实写法 ——
  实测漏 19 篇 WF（42..59）+ 7 篇 §（136..142、155），使「WORKFLOWS 44 正篇无重复」成了**假绿灯**
  （真实 64 篇且有重复）。现按宽规则抓（井号级数不固定 + 号后可为 `:`/`：`/空格标题），
  并排除「追加/续/补/更正」续篇与 `§58.1` 子节；两种形态各做一次注入→必红、还原→必绿的阴性对照。见 **§180**。
- **依赖清单已入库** `requirements.txt`（此前 README 只写 `UnityPy + Pillow`，而实际 import 到 7 个第三方包，
  照旧 README 装完会在跑语音/画廊页时才炸）。

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
| UnityPy | 1.25.3 | 读取/导出 AssetBundle | ✅ 用户级 pip（必须设 `FALLBACK_UNITY_VERSION="2022.3.62f3"`） |
| Pillow | 12.x | 图像处理 | ✅ |
| numpy | 2.x | 立绘层像素运算 | ✅（`compose_paintings_v2` 依赖） |
| requests / websocket-client | — | wiki 抓取 / CDP 探针 | ✅（后者 import 名是 `websocket`） |
| ffmpeg | 7.1 | 音视频处理 | ✅ |
| vgmstream | v2117 | CRIWARE 音频解码 | ✅ |
| ALPA | 1.0.5.1 | 立绘注入/预览（参考真值） | ✅ 需 Java 17 |
| AssetStudio | v2.4.1 | 可视化预览/导出 | ✅ |
| spine-all.js | 3.8 | Spine 运行时（gallery 复用） | ✅（2026-10-18 换官方上游 3.8 构建；`fetch --check` 4/4 + 版本 3.8.75 + 前端符号 9/9 全覆盖，见 WF-36/§122） |
| **本机 VS Code 侧**（不属本仓库） | oaicopilot 0.4.2 | 会话通道 | ⚠️ 已打两枚补丁（**路径别名重定向** + **SSE 流内错误转真异常**）；别名链**是单点**，加跳前必须 `--probe` 实测终点，改完必须 `sync_session_model.py --list` 核对，见 §175「第三次复发」 |

---

## 5. 关键文件清单

**核心脚本**：`scan_assets.py`、`export_assets.py`、`export_cue_audio.py`、`reconstruct_live2d.py`/`fix_model3.py`/`extract_motions.py`(★2026-09-21 权威映射重写)/`apply_live2d_motions.py`(★临时目录→备份换入)、`compose_paintings_v2.py`(★v2)、`extract_spine_v2.py`(★v2)、`export_dependency_manifest.py`、`build_gallery_index.py`、`make_thumbs.py`、`deploy_gallery.py`(gallery_src↔Output 硬链/漂移检查)、`fetch_gallery_vendor.py`(★2026-10-18 补 spine-all.js 官方上游源; 按 vendor 台账 sha256 补齐第三方库)、`mumu_sync.py`(★2026-10-18 同步范围放开为整棵 `files/`，`ONLY_TOP=[]`，`il2cpp` 等缺了可 sync 补，见 WF-35)、`ship_name_map.py`、`scrape_wiki_fast.py`、**`run_v2_full.py`**(两阶段全量驱动)、**`update_pipeline.py`**(★2026-09-29 新增：WF-15 那条 runbook 的阶段机，一条命令跑到待确认、第二条命令签字换入，见 **WF-23**)。

**可复用诊断/验证工具 `scripts/diag/`**：承重工具清单已逐字外迁至 `docs/archive/PROJECT_STATUS_diag-tools_2026-10-29.md`（原第 165 行）；具体清单以目录为准（该清单的计数已过期）。
**MuMu 同步当前默认**：`mumu_sync diff/sync` 仅枚举 `AssetBundles`；全 `files/` 必须显式加 `--all`。非空同名目录会报错保留，不递归删除（详见 WF-64；WF-35 记录的是 2026-10-18 的旧默认）。

**文档**（导航见根目录 `README.md`，写入路由见 `AGENTS.md`）：
- `docs/DEV_LOG.md` 操作手册 · `docs/WORKFLOWS.md` 可复用工作流 · `docs/TROUBLESHOOTING.md` 踩坑 · `docs/ERRORS.log` 错误流水
- `docs/tools/` ALPA、AssetStudio 使用说明
- **项目技能库 `.agents/skills/`**（16 个，入库；具体以目录为准）：`live2d-web-runtime-integration`、`live2d-motion-extraction-audit`、`unity-assetbundle-painting-restore`、`spine-web-runtime-integration`、`headless-chrome-cdp-batch-export`、`safe-pipeline-fix-targeted-rerun`、`windows-hardlink-dedup-verify`、`windows-local-server-launcher`、`windows-long-running-batch-detach`、`cn-blocked-resource-mirror-fetch`、`project-doc-governance`、`shared-worktree-takeover-commit`、`enforce-project-rule-as-git-hook`、`decision-brief`、`binary-container-vs-crypto`、`llm-relay-channel-alias-triage`(★2026-10-31 新建：中转层通道排障 + 别名链单点)——做同类任务前先查这里，别从零摸索
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
7. ✅ **无头浏览器泄漏已从机制上堵掉**（2026-10-28，§159 / WF-49）—— 完整取证已逐字外迁 `docs/archive/PROJECT_STATUS_chrome-leak_2026-10-30.md`（原第 183 行）。**接手要点**：新探针一律 `chrome_tree.launch()`、不许自己写 `Popen`；收尾必跑 WF-49 的固定自检，非空即泄漏。
> 诊断产物/缓存均在 `.diag/`（不入库，本机可继续用）。画廊前端**直接改 `gallery_src/` 里的正本即生效**（与 `Output/gallery_v2/` 已硬链，2026-09-26 起 4/4）；`py -3 scripts/deploy_gallery.py --check` 查有没有静默断链，`--relink` 补链，默认模式是断链后的 copy 回退。换机器/清过 `Output/` 后先 `py -3 scripts/fetch_gallery_vendor.py` 补运行时库（只双击 `Output\gallery_v2\` 里的 bat）。

### 既有待办

**✅ 0 / 0b. 2026-10-27 收官轮改动已全部提交 + 探针清单体检三处「尺子坏了」已修** —— 逐字外迁 `docs/archive/PROJECT_STATUS_待办0-0b_逐字外迁_2026-10-28.md`（A31 段）。
⚠️ 其中两条仍是活口：① `.diag` 78 个 chrome profile / 6.83 GiB 未删（`clean_diag_profiles.py --yes` 未执行）；② **24 个探针把 `CHROME` 写死成本机不存在的 `Google/Chrome`**（本机只有 Edge）⇒ 起不来，正解是 `scripts/paths.py` 的 `CHROME`（含 Edge 兜底）。**新增（2026-10-29）**：`f2811cb` 的批量迁移把 6 个探针改成「`chrome_tree.launch(...)` 跑在 `import chrome_tree` 之前」⇒ 运行时 `NameError`（`py_compile` 看不出来），已全修并给 `migrate_chrome_launch.py` 加了 AST 版 `--audit` 护栏（见 §165 / WF-55）。

**✅ 0c. 用户四条互动区需求（2026-10-28 提出；③④ 已收口，② 仅剩眼睛/渐变待补）**
> 完整取证与逐条流水**已逐字外迁** `docs/archive/PROJECT_STATUS_0c-互动区需求_逐字外迁_2026-11-01.md`（原第 206-267 行）。接手要点：
- **① 少一只鞋** ✅ 已修（§169）。真根因是 `ShoseOff` 三态参数（-1/0/1）被两态逻辑钳到残缺档 `-1`；修法 = 默认值严格落在 `(min,max)` 之间时，关端取默认值。☠️ 共翻盘 3 次（§171 pin 已撤销、§173 凭几何分箱确认双脚两参数）—— 不要重走。
- **② 全部可调参数互动区** ✅ 5 个模型全覆盖（§170）；拖动型 `COSTUME_DRAG`（§174 / WF-58），界限已加（§176）。**仅剩** `BondEyes`/`HeartEyes` 无热区（`n_drawables=0`，走面板控件）与眼睛/渐变待补。
- **③ 可达率** 已重标（`l2d_hotzone_reachability.py`，盒哈希 `-937102468`，GATE PASS）；≈§175 判定区全库审计完成（WF-59）。
- **④ 参数保留** ✅ 55 个动作 × 12 条参数零偏差；验收判据必须是**渲染有效值**（参数回读会 51/55 假红）。
- **影响面**待做：逐 skin 重取 canvas rect，**绝不许复用**旧轮区域框。

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
进度: D:\azurlane-assetbundle-toolkit\PROJECT_STATUS.md
规则: D:\azurlane-assetbundle-toolkit\AGENTS.md（含文档写入路由表）
当前主线: v2 数据驱动管线（§9）+ gallery_v2（§10）
下一步: [具体任务]
```
要点：**画廊视觉（Q 轮）的待用户拍板项与待办在 §6 顶部 ★ 块，接手先读它**。静态立绘 / Spine 已由 v2 全量收官，Live2D 动作层已于 2026-09-21 按权威映射重建完毕，**2026-09-23 网页交互层三个根因（命中包含判定 / idle 循环 / V-P 坐标系）已修并回归**。接手前先读 §9 理解「游戏数据自洽、不要猜坐标/不要按位置猜参数名」这一核心结论。**验动效一律看内容**（曲线条数、Id 是否命中参数表、值是否随时间变化），不要只看 `currentGroup`/组名标签——空壳也能"启动"，这个坑已踩过一次（`docs/TROUBLESHOOTING.md` §17、`docs/WORKFLOWS.md` WF-7）。**验交互一律用独立锚点**——合成点击若与被测映射同源会自洽闭环、全绿也说明不了对齐（§20、WF-16）。历史 v1 调试见 `docs/archive/`，一般无需再读。

**远端拓扑（2026-11-01 起）**：`origin` = `MrKLLM/azurlane-assetbundle-toolkit`（本地领先 100 个提交，**未推送**）；`fork` = `fuzhe01/azurlane-assetbundle-toolkit`（**已对齐**，`rev-list --left-right --count fork/master...HEAD` = `0 0`）。`fork` 侧曾有 97 个独立提交（分叉点 `149053b`），已全部并入且**从未 force push**；备份 ref `backup/local-master-before-fork-merge` / `backup/fork-master-1c16cea` 保留可回滚。⚠️ 以后同步 fork 只能合并、不能强推 —— 那份 97 提交是真实工作量。

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
> 九条根因（双重 Y 翻转 / Spine `flip=True` / GBK stdout 假失败 / root scale 未乘自身 /
> `mRawSpriteSize` 误当画框 / mesh 钳死画框 / 不读 `m_IsActive` / `paste` 二次缩放 alpha /
> 画布只取 max 不减 min）的完整取证与验证样本已逐字外迁：
> `docs/archive/PROJECT_STATUS_v2-nine-fixes_2026-10-30.md`（原第 344-371 行）。
> **接手要点**：游戏数据自洽，所有错位都是解析姿势不对；「姿势」也包括**用什么库函数落笔、
> 画布边界取在哪** —— 数据读对了、落盘算子错一样全库错，且**不报任何错**。
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
