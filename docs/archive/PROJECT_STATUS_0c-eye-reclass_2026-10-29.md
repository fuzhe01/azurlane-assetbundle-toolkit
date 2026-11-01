<!-- B 段 | 2026-10-29 逐字外迁自 PROJECT_STATUS.md §6 待办 0c（原文 = git show HEAD:PROJECT_STATUS.md L212 / L213）| 由 §166 / WF-56 收官 -->

# PROJECT_STATUS.md 外迁 B 段：需求②③ 的眼睛三条重新裁定与映射重做（2026-10-29）

## B1 ② 全部换装参数互动区（逐字原文，行 212）

- **② 全部换装/可调参数的互动区**：`Cloth1/2/3`、`Stock1/2`、`ShoseOff`、`Paramring` 之外还有眼型、渐变类；`costume_params.json` 里 `BondEyes/HeartEyes/ParamEyeSmile` 三条 `n_drawables=0` ⇒ **目前无热区**，需换判定法或降级为面板控件；`NeckMoney` 需核实（moc3 名表里**没有**这个名字，但 `param_drawables` 登记了 drawable 502）。渐变类（`ShoseOff` 已证实是**交叉淡化**）必须给 `mode:'slider'` 可拖。

### B1 原文里哪些句子被推翻（2026-10-29）

| 原文句 | 现结论 | 判据 |
|---|---|---|
| 「三条 `n_drawables=0` ⇒ **目前无热区**」 | **部分推翻**：`ParamEyeSmile` 真有效 **14 件**（像素 89 px）⇒ 必须做热区；`BondEyes`/`HeartEyes` 仍 **0 件**且像素级 **0 px** ⇒ 可信，降级面板控件 | 修掉 5 个仪器缺陷后重测（冻眨眼 + 相对阈值 + 每条重取基线 + 阳性对照有区分力），§166 / WF-56 |
| 「`NeckMoney` 需核实（moc3 名表里**没有**这个名字，但 `param_drawables` 登记了 drawable 502）」 | **前提作废**：参数真实存在，驱动 **1 件**（正是 drawable 502），旧登记正确 | 同上；全量跑曾误读 14 件（基线只取一次导致继承 `Param233` 残留），修后 1 件 |
| 「渐变类（`ShoseOff` 已证实是**交叉淡化**）必须给 `mode:'slider'` 可拖」 | **保留**（未被推翻） | — |

同批修掉的三处假读数：`ShoseOff` 842 件 → **20 件**（822 件只是绘序号重排，`why==['ro']` 剔除）；`NeckMoney` 14 → **1**；`Param233` 29 → **16**（与旧手写值一致）。

## B2 ③ 互动区排查里的映射重做明细（逐字原文，行 213）

- **③ 互动区系统性排查**：可达率基线**已重标（`l2d_hotzone_reachability.py`，盒哈希 `-937102468`，GATE PASS）**：`Cloth1/Cloth2/Cloth3/Param233 100%`、`ShoseOff 97.8%`、`NeckMoney 82.4%(own=0 全靠幽灵区)`、`Stock1 78.9%(主要被 Stock2×279 抢)`、`Stock2 74.1%(被 Stock1×402+ShoseOff×167+Cloth1×38 抢)`、**`Paramring 0.0%（面积仅 0.25，结构性不可点）`**；⑥ 反解点 9/9 全部命中自己（exit 0，`reachability_ougen_8.json`）。另需用 `l2d_param_effect_scan.py` 对 12 条参数批量重扫并与 `param_drawables.json` 比对（**已证漏项**：`Param233` 漏 16、`ShoseOff` 漏 3 ⇒ 这是「效果不对」的根因入口）。

### B2 已完成项（2026-10-29）

原文最后一句「另需用 `l2d_param_effect_scan.py` … 批量重扫比对」**已做完**（工具换成了修好仪器后的 `l2d_param_map_batch.py`）。12 条参数可信映射产出在 `.diag/param_drawables/ougen_8.batch.json`，与旧手写 `param_drawables.json` 逐条比对：

| 参数 | 新映射件数 | 旧手写 | 差 |
|---|---|---|---|
| `Stock1` | 15 | 14 | +1 |
| `Stock2` | 11 | 11 | 0 |
| `Paramring` | 1 | 1 | 0 |
| `BondEyes` | 0 | 0 | 0（面板控件） |
| `HeartEyes` | 0 | 0 | 0（面板控件） |
| `ParamEyeSmile` | 14 | — | 新增 |
| `Cloth1` | 4 | 4 | 0 |
| `Cloth2` | 12 | 12 | 0 |
| `Cloth3` | 4 | 2 | +2 |
| `ShoseOff` | 20 | 5 | +15 |
| `Param233` | 16 | 16 | 0 |
| `NeckMoney` | 1 | 1 | 0 |

⚠️ **`param_drawables.json` 还没替换**，24 处漏项仍在（消费方 `gallery_src/index.html:1138-1143` fetch、`:2144` `buildCosGeo`）。
