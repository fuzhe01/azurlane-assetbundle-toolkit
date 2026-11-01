# -*- coding: utf-8 -*-
"""自测跑之前的"资产在不在"预检：**缺资产就 SKIP，不许假红、也不许钝性抛异常**。

为什么需要（2026-11-01 实测）：本机没有 `files/`、`Output/`、`inputs/gamecfg/`，于是
`test_spine_exit_code` / `test_voice_owner` / `gallery_server_range_test` 全部直接
`FileNotFoundError`——**看起来像产品坏了，其实只是这台机器没备料**；
`test_pipeline_gating` 更阴：它的判据刻意拿"盘上真实存在"的包名当裁判，源包一缺，
磁盘裁判把整份清单滤空 ⇒ 断言红，而代码完全是对的。
"永远红的检查"必然被绕过（本项目对这个形状的态度见 TROUBLESHOOTING §71），
所以缺料必须显式 SKIP 并把恢复命令打出来。

⚠️ 这不是把红变绿：判据本身一个都没改，只是把"环境不足"和"判据不成立"分开。
真跑出红时这里不会插手。

用法（在每个自测的 main() 最开头、import 被测模块**之前**调用）：

    from _precheck import require
    require(os.path.join(ROOT, 'inputs', 'gamecfg', 'character_voice.json'),
            note='语音归属判据要读游戏配置表')
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RECIPES = {
    'files/AssetBundles': '把游戏源包放进 files/AssetBundles/（或设 AL_ASSETS_ROOT 指向已备料的根）',
    'Output/dependency_manifest.json': 'py -3 scripts/export_dependency_manifest.py',
    'Output/gallery_v2': 'py -3 scripts/build_gallery_index.py 之后再 py -3 scripts/deploy_gallery.py',
    'inputs/azdata': 'py -3 scripts/diag/check_inputs.py 会列出缺哪几份；按 inputs/azdata/MANIFEST.json 补回',
    'inputs/gamecfg': 'py -3 scripts/diag/check_inputs.py 会列出缺哪几份；按 inputs/gamecfg/MANIFEST.json 补回',
}


def _recipe(path):
    rel = os.path.relpath(path, ROOT).replace('\\', '/')
    for key, hint in RECIPES.items():
        if rel == key or rel.startswith(key + '/') or rel.startswith(key):
            return hint
    return '先把这份资产备到该路径再跑（本机不持有该文件是正常的）'


def missing(paths):
    """返回实际缺失的路径列表（目录按"存在即为有"判；文件按 isfile 判）。"""
    bad = []
    for p in paths:
        p = p if os.path.isabs(p) else os.path.join(ROOT, p)
        ok = os.path.isdir(p) if os.path.isdir(p) else os.path.isfile(p)
        if not ok:
            bad.append(p)
    return bad


def require(*paths, note='', exit_code=0):
    """缺任何一项 ⇒ 打印 `[SKIP]` + 恢复方法后 `sys.exit(exit_code)`，不返回。

    exit_code 默认 0：缺料不是产品缺陷，不该把串行 runner（wf16_regression）判成失败；
    但 SKIP 行会同时给出 `MISSING` 清单，人一眼能看出"这轮其实没验"。
    """
    bad = missing(paths)
    if not bad:
        return
    print('[SKIP] ' + (note or '本机缺少跑这个自测所需的资产'))
    for p in bad:
        print(f'       MISSING {os.path.relpath(p, ROOT).replace(chr(92), "/")}')
        print(f'               → {_recipe(p)}')
    print('       （这不是判据失败：判据一条都没跑到。备好资产后重跑同一条命令即可。）')
    sys.exit(exit_code)
