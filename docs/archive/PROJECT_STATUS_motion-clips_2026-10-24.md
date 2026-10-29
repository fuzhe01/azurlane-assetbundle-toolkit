<!-- 归档 | 原第 393-406 行 | 2026-10-29 外迁（PROJECT_STATUS 超 400 行红线） | 内容=2026-10-24 已闭环的「动作数据补全 + 播完回落」全程取证，逐字未改 -->

- **✅ Live2D 动作数据补全 + 播完回落修复（2026-10-24）**：用户目视 ougen_8 发现「难以描述的不对」，与旧画廊 `D:\Azur Lane Assets` 对照后定位为两个独立缺陷。
  - **缺陷一：ConstantClip 曲线全丢**。`extract_motions.py` 默认不导 `m_ConstantClip` 复位曲线。实测四个样本丢失量：aersasi_2 2329 / aersasi_3 16997 / benningdun_2 28067 / ougen_8 18839 条（最高占 77.9%）。已用 `L2D_MOTION_EMIT_CONST=1` 全部重建：曲线数 7841 / 24924 / 36049 / 23326，与旧画廊基准**零缺失**（各模型仅差 1 条 `Opacity` 常量，值恒为 1.0 无视觉影响）。
    - 运行时验收（参数直读，技能要求的切换轴）：idle9 的 9 条姿势定值，对照组 0/9 命中 → 实验组 **9/9 精确命中**（`Param345 -1.280`、`Param494/500/502/506/91/97/352=1.000`），切回 idle 亦 9/9 复位。
  - **缺陷二：非循环动作播完不回 idle**。库的自动回落通道（`isFinished()`→`startRandomMotion`）在本工程从不成立（`getEndTime()` 恒 -1、`_finished` 不置位）。已改为按时长定时回落（`motion_chain.json` 新增 `durations`），回落必须用 **IDLE(1)** 优先级（`MotionState.start()` 对 2/3 要求先 reserve）。
    - 验证：ougen_8 / benningdun_2 / aersasi_3 三模型，播 login 后 12s 标签与 `currentGroup` 均正确回落到 idle 组。
  - ⚠️ **旧画廊的数据是错的、不能抄**：它 41/55 个 clip 的 `Meta.Loop=True`，而 Unity `m_LoopTime` 真值全部为 `False`；它是靠「动作永不结束」回避回落问题。**我们 55/55 与源数据一致**。详见 §143。
  - **回落目标修正（2026-10-24 续）**：_fallbackToIdle 原先写死 idleGroup，导致索引算出的 est 被丢弃
    （ougen_8 的 42 组里 27 组 best 指向具体变体）。已改为「手工覆盖 > chain[组].best > idleGroup 兜底」。
    验证：touch_idle14→idle9（原错落 idle）、touch_idle1→idle2、main_1→idle2 全部符合期望。
  - **「部件消失」已取证为源模型特性、非回归**：逐 drawable 比对旧画廊与本仓库（同动作 idle），
    842 个中 841 个不透明度完全一致、仅 1 个 0.034→0.019，两边画面肉眼等同。
    ⚠️ 注意「842 个 drawable 里 530 个透明度≈0」是 Live2D 常态（正反面两套肢体并存），不能当缺陷判据。
  - **antu_2 已加入样本**（安土 / 海上传奇 / 战巡 / 104 组动作），7 样本目视验收 7/7 PASS；截图在 .diag/samples_final/。
  - 6 样本目视验收已通过（立绘 haitian_3 / Spine aersasi / Live2D benningdun_2·aersasi_2·aersasi_3·ougen_8），截图在 `.diag/samples_final/`。
