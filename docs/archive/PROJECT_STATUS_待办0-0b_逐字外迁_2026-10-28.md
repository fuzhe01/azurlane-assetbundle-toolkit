# PROJECT_STATUS_待办0-0b_逐字外迁_2026-10-28.md（逐字保留，勿编辑）


<!-- A31 §6 已闭环待办 0 / 0b（2026-10-27 收官轮 + 探针清单体检）逐字外迁 -->

<!-- ↓ 待办 0 · 2026-10-27 收官轮改动已提交｜原第 207-211 行 -->
**✅ 0. 2026-10-27 收官轮改动已全部提交**（`b3adae9` 文档与技能 / 本条提交 管线与探针）：`extract_motions.py` 段类型三段式 + `Meta.FadeInTime` 真根因、`scripts/diag/**` 118 个入库探针（含 `vanish_can_page.html` 页面正本）、WF-45、§151/§153/§154、三个 `SKILL.md`。
⚠️ **页面正本必须留在 `scripts/diag/`**：`Output/` 被 `.gitignore` 整体忽略，正本放那儿会随清盘静默消失，`vanish_can.py` 便拿旧扫描器跑出假绿灯；判据工具依赖的资产一律入库。
验证（均可复现）：`deploy_gallery.py --check` 6/6 同 inode 漂移 0 ｜ `check_diag_hygiene` PASS ｜ `check_env` PASS ｜ `py_compile` 11 脚本 0 ｜ `l2d_group_cmp --files` prod vs E **367/367** ｜ `vanish_can` 实跑生产 `mail`（`durSrc=motion` / `dur=4.817` / `frames=144`，闸门 pass exit 0）。
未做（别当成已完成）：`.diag` 78 个 chrome profile / 6.83 GiB 未删（`clean_diag_profiles.py --yes` 未执行）；残留无头 Edge 进程未终止。

<!-- ↓ 待办 0b · 2026-10-27 探针清单体检｜原第 212-216 行 -->
**✅ 0b. 2026-10-27 探针清单体检：三处「尺子坏了」已修 + 全库执行**（先查验收工具本身；此前"已通过"的部分结论不可采信）。细节见 `TROUBLESHOOTING.md` **§156** / 流程 **WF-46**：
① 清理器**报成功却没杀**（`taskkill /T /F /PID` 对 Edge 无效，实测 rc=128 而 16~20 进程全活）⇒ `chrome_tree.py` 判据改为**按自己的 profile 回读**；
② 探针写 `window.l2State` 而页面用 `let` 声明（`l2d_coord_forensics.py` **恒 exit 3**）⇒ 改 `typeof`；
③ 加载预算按单跑拍（`interact_verify` 40s，连跑 5 模型超时）⇒ 抬到 100s。附带 `gallery_ui_shots` 默认截不存在的 `index_b.html` ⇒ 改只截 `index.html`。
**全库执行**（320 个探针）：缺 `install()` **40→0** ｜ 预算 <100s **5→0** ｜ 45 文件 `py_compile` 全 0 ｜ 抽样实跑正常退出后浏览器残留 **0**。⚠️ **顺带查出、本轮未改**（勿与本轮三形态混改）：**24 个探针把 `CHROME` 写死成本机不存在的 `Google/Chrome`**（本机只有 Edge）⇒ 起不来；正解是 `scripts/paths.py` 的 `CHROME`（含 Edge 兜底）。
