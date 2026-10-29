<!-- 归档 | 原第 66 行 | 2026-10-29 外迁（PROJECT_STATUS 超 400 行红线） | 内容=新机 clone 后重建 5 个验收样本的步骤记录，逐字未改 -->

> **本机重建（2026-10-20，5 样本预览线）**：新机 clone 后 Output 为空，先重建 5 个验收样本（ougen_8 / antu_2 / aersasi_2 / aersasi_3 / qiershazhi_2）——贴图/motion/HitAreas 全部重跑，`tex_completeness` 5/5 全绿、`texorder` 5/5、motion 全非空曲线。⚠️ 贴图提取曾被 archspec `..` 路径间歇 PermissionError 静默跳过（`extract_textures` 异常 continue 无日志），修复两件套：`scripts/astc_import_patch.py`（import astc_encoder 前预填 archspec 懒加载数据，避开带 `..` 的路径）+ 失败写 ERRORS.log（不再静默）。取证见 `docs/TROUBLESHOOTING.md` §131。全库 269 重跑时**必须**先接 astc_import_patch。
