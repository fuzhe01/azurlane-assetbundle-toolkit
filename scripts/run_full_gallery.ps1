# -*- coding: utf-8 -*-
<#
run_full_gallery.ps1 — 全量画廊生成编排（Live2D → 动作回落表 → Spine → 静态立绘 → 索引 → 素材 → 关机）

为什么要脚本而不是一串命令：
  1) 每阶段要独立计时与退出码，失败不静默（长任务里"哪段挂了"必须一眼看出）；
  2) 全程单一日志，便于三分法判定（跑完 / 崩了 / 被截断）；
  3) 关机是不可逆动作，必须先过健康检查（模型数 + index.js 存在），不达标绝不关。

用法（建议 detached）:
  powershell -ExecutionPolicy Bypass -File scripts\run_full_gallery.ps1
  powershell -ExecutionPolicy Bypass -File scripts\run_full_gallery.ps1 -NoShutdown
  powershell -ExecutionPolicy Bypass -File scripts\run_full_gallery.ps1 -SkipPaintings
#>
param(
  [switch]$NoShutdown,
  [switch]$SkipPaintings
)
$ErrorActionPreference = 'Continue'
$ROOT = 'D:\IDEProjects\azurlane-assetbundle-toolkit'
Set-Location $ROOT
$STAMP = Get-Date -Format 'yyyyMMdd_HHmmss'
$LOG = Join-Path $ROOT ".diag\full_gallery_$STAMP.log"
$PY = (& py -3.14 -c "import sys;print(sys.executable)").Trim()
$env:PYTHONIOENCODING = 'utf-8'
$env:GALLERY_ALLOW_NO_WORDS = '1'   # 台词表未生成时显式放行，不静默当 0

function Log([string]$m) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
  Add-Content -Path $LOG -Value $line -Encoding utf8
}
function RunPy([string]$name, [string[]]$pyArgs) {
  Log "===== START $name ====="
  $t0 = Get-Date
  try {
    & $PY @pyArgs *>> $LOG
    $rc = $LASTEXITCODE
  } catch {
    $rc = -1
    Log "EXCEPTION in ${name}: $_"
  }
  $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
  Log "===== END $name rc=$rc ($mins min) ====="
  return $rc
}

Log "===== full gallery run start ====="
Log "python=$PY"
Log "skipPaintings=$SkipPaintings noShutdown=$NoShutdown"

# 索引会被重写：先备份当前版本（当前是 5 样本最小索引），失败时可直接回滚
$idx = Join-Path $ROOT 'Output\gallery_v2\index.js'
if (Test-Path $idx) {
  Copy-Item $idx ".diag\index_js_backup_$STAMP.js" -Force
  Log "index.js 已备份 -> .diag\index_js_backup_$STAMP.js"
}

# ---- 1. Live2D 全量重建（核心；约 1.5~2.5h / 262 bundle）----
$rc1 = RunPy 'live2d-full' @('scripts\rebuild_live2d_full.py', '--all', '--yes')

# ---- 2. 动作回落映射表全量重算（模型集变了必须重算，否则回落落空）----
$rc2 = RunPy 'motion-chain' @('scripts\build_motion_chain_map.py')

# ---- 3. Spine 动态立绘全量（约 20~40min / 456 源）----
$rc3 = RunPy 'spine' @('scripts\run_v2_full.py', '--only', 'spine')

# ---- 3.5 依赖清单（静态立绘的硬前提；缺它每张都 fail）----
$rc3b = RunPy 'dep-manifest' @('scripts\export_dependency_manifest.py')

# ---- 4. 静态立绘全量合成（最大头；10685 源 → 4454 目标，约 2 秒/张）----
if (-not $SkipPaintings) {
  $rc4 = RunPy 'paintings' @('scripts\run_v2_full.py', '--only', 'static')
} else {
  Log "===== SKIP paintings (SkipPaintings) ====="
  $rc4 = 0
}

# ---- 5. 索引重建（元数据缺 azdata → 中文名走 ship_name_map 兜底，阵营/稀有度可能为空）----
$rc5 = RunPy 'index' @('scripts\build_gallery_index.py')

# ---- 6. 画廊运行时库（clone/清空 Output 后必须补）----
$rc6 = RunPy 'vendor' @('scripts\fetch_gallery_vendor.py')

Log "stage rc: live2d=$rc1 chain=$rc2 spine=$rc3 dep=$rc3b paintings=$rc4 index=$rc5 vendor=$rc6"

# ---- 7. 健康检查 → 关机 ----
$models = 0
try {
  $models = (Get-ChildItem (Join-Path $ROOT 'Output\Live2D') -Directory -ErrorAction Stop |
    Where-Object { Test-Path (Join-Path $_.FullName "$($_.Name).model3.json") }).Count
} catch { $models = 0 }
$hasIndex = Test-Path (Join-Path $ROOT 'Output\gallery_v2\index.js')
$idxBytes = if ($hasIndex) { (Get-Item (Join-Path $ROOT 'Output\gallery_v2\index.js')).Length } else { 0 }
$paintings = 0
try { $paintings = (Get-ChildItem (Join-Path $ROOT 'Output\Paintings_v2') -File -ErrorAction SilentlyContinue).Count } catch { }
$spine = 0
try { $spine = (Get-ChildItem (Join-Path $ROOT 'Output\Spine_v2') -Directory -ErrorAction SilentlyContinue).Count } catch { }

Log "health: models=$models index.js=$hasIndex($idxBytes B) paintings=$paintings spineDirs=$spine"

if ($NoShutdown) {
  Log "NoShutdown 指定 → 不关机"
  exit 0
}
if ($models -ge 200 -and $hasIndex -and $idxBytes -gt 10000) {
  Log "健康检查通过 → 120 秒后关机（取消请运行: shutdown /a）"
  shutdown /s /t 120 /c "全量画廊生成完成，系统将在 2 分钟后关机"
} else {
  Log "健康检查未通过 → 不关机，请检查日志: $LOG"
}
Log "===== full gallery run end ====="
