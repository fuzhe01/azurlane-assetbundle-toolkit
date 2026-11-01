<!-- 归档 | 原第 88-100 行 | 2026-10-29 外迁（PROJECT_STATUS 超 400 行红线） | 内容=动作保真裁决定稿（E 组终态）与独立复核表，逐字未改 -->

> ✅ **动作保真裁决定稿：E 组为终态（2026-10-27，§147~§150）**。上一轮「F 更忠实 / E 过度插值」的裁决**已被推翻**，根因是当时把**官方参考导出当 `--gt` 真值**，而官方导出器本身就是「smoothstep → Linear」的有损降级版（它与我方 F 组偏差 0.289905 vs 0.294278，几乎同质）。改用 **Unity `m_StreamedClip` 每键三次多项式**作真值（`v(τ)=Aτ³+Bτ²+Cτ+D`，`τ=t−起点键`）后：
> | 组 | 采样点 | 平均偏差 | 最大偏差 | 超 0.5 曲线 |
> |---|---|---|---|---|
> | **E（终态）** | 181961 | **2.68786e-07** | 3.67162e-05 | **0** |
> | F（零切线贝塞尔→Linear） | 181961 | 0.294278 | 8.65986 | 1359 |
> | 官方参考导出 | 181961 | 0.289905 | 8.65985 | 1353 |
> 抽样口径：5 模型（aersasi_2/aersasi_3/antu_2/benningdun_2/ougen_8）× 25 clip × 12 曲线 × 51 点。**E 平均偏差比 F/官方小 109 万倍、0 条曲线超阈。**
> **2026-10-27 独立复核（换 seed / 183383 采样点）**：E `3.04924e-07 / 最大 2.89303e-05 / 超阈 0`；F `0.332025 / 8.65998 / 1569`；official `0.326594 / 8.65984 / 1564` ⇒ **裁定不变，E 为终态**；F 与官方仍同质（平均偏差同量级、最大偏差差 1e-4）。命令：`py -3 scripts/diag/l2d_poly_truth_verdict.py --sample --bases=Output/_ab/E,Output/_ab/F,Output/_ab/official --models=<5 模型> --clips-per-model=25 --curves-per-clip=12`。
> ✅ **换入状态事实更正（2026-10-27）**：`Output/Live2D/` 与 `Output/_ab/E/` **367/367 个 `motion3.json` md5 逐字节相同**（`scripts/diag/l2d_group_cmp.py --files`）⇒ **E 组早已换入生产，不需要再跑 `apply_live2d_motions.py`**。此前记录「E 组尚未换入生产 / 生产仍是旧版」是错的（`Output/Live2D/ougen_8/motion/home.motion3.json` 的 mtime 10-25 10:41 是 E 组自己的生成时间，换入是后来的硬链）。
> **E 配方（已 367/367 `motion3.json` sha256 逐字节复现）**：`L2D_MOTION_SEGTYPE=1 L2D_MOTION_BEZIER=1 L2D_MOTION_LINEAR=0 L2D_MOTION_EMIT_CONST=1`。裁决器 `scripts/diag/l2d_poly_truth_verdict.py`；段类型混淆矩阵 `scripts/diag/l2d_segtype_confusion.py`（**它的 62.98% / 99.75% 结论作废**，同理因 `--gt` 选错）。
> ⚠️ **判据元教训**：① 判据给出近 100% 一致率先查是否退化成恒等（段中点偏离对对称 smoothstep **恒为 0**）；② 单向判据只证明一个方向（`l2d_bezier_quantization_audit.py` 只看 L→B）；③ **基准本身也要被怀疑**——「官方参考」可能比自己的产物差 109 万倍。
> ⚠️ **aersasi_2/ougen_8 肢体抖动（§116，进行中）**：重建版 .moc3/.physics3 与 AS 版逐字节/逐字段一致已**否证**「提取/物理数值」两条；`L2D_MOTION_EMIT_CONST=1` 换入 A/B 实测 **idle 内波形不变** ⇒ **否证**「真抖动=constant 曲线缺失」（常量曲线只在**切动作复位**轴上生效，idle 循环内部无复位）。待办：真抖动按「切换轴」CDP 目视、动作复位按「切段复位」另测；改用 `scripts/diag/l2d_jitter_probe.py`（读参数名走 `_parameterIds`）。
> **2026-10-19 复核（审计轮）**：idle3 的肩部曲线本身就是 `-24 ↔ -0.25` 每 0.667s 交替（10 个来回），`DenseClip.curveCount=0`、meta 总段数 1611 / 257 曲线 ⇒ 是**稀疏作者关键帧**，且与 AS 版逐字段相同 ⇒ 不是提取/接线造成的。运行时 `physics=true`、`breath` 参数数 0（呼吸层已关）。无头只有 ~2fps，测不出高频观感，需游戏内同 clip 对照。
