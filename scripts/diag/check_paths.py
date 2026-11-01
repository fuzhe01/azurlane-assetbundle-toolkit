# -*- coding: utf-8 -*-
"""漂移探测器：还有没有脚本把 `D:\\Azur Lane Assets` / `C:\\Users\\xxx` 写死在源码里。

2026-10-01 把 13 阶段调用链上 9 个脚本改成走 `scripts/paths.py` 之后，必须有东西**拦住下一个人**
（包括下一个会话里的我）：这类回归不会报错，只会在新机器上第一次跑的时候炸，
或者更糟——静默把资产写到错误的目录。

    py -3 scripts/diag/check_paths.py            # 退出码即结论
    py -3 scripts/diag/check_paths.py --verbose  # 列出每条命中

允许出现绝对路径的只有两处：`paths.py` 自己的候选清单、以及明确标了 legacy 的归档脚本。

⚠️ **扫的范围必须是整棵 `scripts/`（`.py` + `.bat` + `.ps1`），不能只认 `.py`。**
2026-11-01 实测漏网：`scripts/mumu_adb.bat` / `mumu_sync.bat` 第 3 行把某个用户目录下的
python.exe 写死成绝对路径，本检查完全看不见（`endswith('.py')` 一律 continue）⇒
换机器后双击**必然报 "Python not found"**，而闸门一直显示 PASS。批处理/PS 脚本
和 Py 脚本一样是会被人双击的入口，属于同一个失效模式。逃检是两层原因叠加的：
扩展名筛 + 正则要求盘符前有引号（`set "PY=<盘符>:..."` 不满足）。
"""
import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.dirname(HERE)                       # scripts/
ROOT = os.path.dirname(S)
# 基线文件与 pyflakes 那条闸门同形状（`count` + `fingerprints`）：只冻存量、只拦新增。
# 合并 fork 的 97 个提交后，scripts/diag 里有 89 个探针仍写死绝对路径，**全部来自 fork**，
# 本分支为 0；它们是一次性诊断脚本、不在调用链上。逐个迁移等于重写 fork 的 334 个脚本，
# 战线远超「把两个分支合起来」本身，而常亮的闸门必然被绕过（§71 / WF-61）。
PATHS_BASE = os.path.join(HERE, 'paths_baseline.json')

# 不再要求盘符前有引号：`set "PY=<盘符>:\\Users\\..."` 里盘符前面是 `=PY` 而不是引号，
# 这正是两份 .bat 逃检的第二个原因（只放宽**前引号**，捕获内容的边界没变）。
DRIVE = re.compile(r'''[A-Za-z]:[\\/](?:Users|Program Files|Azur Lane Assets|azur)''')
# 允许：路径出口本身（它的职责就是列已知安装位置）
ALLOW = {'paths.py'}
# 批处理/PS 也是"会被人双击的入口"，必须一起扫（2026-11-01：两份 .bat 写死 python.exe 逃检一轮）
SCAN_EXTS = ('.py', '.bat', '.ps1')
# 归档/一次性脚本：不在调用链上，改它们等于扩大战线；新增条目要写明理由
LEGACY = set()

sys.path.insert(0, S)
# 调用链上这些**必须**已经走 paths —— 少一个就是漏改，直接判红
MUST_USE_PATHS = ['compose_paintings_v2.py', 'extract_spine_v2.py', 'reconstruct_live2d.py',
                  'extract_motions.py', 'fix_model3.py', 'extract_cv_voice.py',
                  'export_dependency_manifest.py', 'mumu_sync.py',
                  os.path.join('diag', 'run_cg_export.py'), 'update_pipeline.py']

# 分两档曾经是为了让这个闸门**当时就能绿**（一次扫出 46 个文件全判红 = 闸门当天就被绕过，
# 见 §71）。2026-11-01 账已清完 ⇒ **软档清零、--strict 变成默认**，
# 再多一条写死路径就是直接红。新增条目要写明理由，别把它当"先放过去"的口袋。
SOFT_DIRS = ()
SOFT_FILES = set()


def tier_of(rel):
    if (SOFT_DIRS and rel.startswith(SOFT_DIRS)) or rel.split('/')[-1] in SOFT_FILES:
        return 'soft'
    return 'hard'


# 双击启动器也必须是"换机器能跑"的：不许写死解释器绝对路径（闸门管的是这个失效模式本身）。
BAT_LAUNCHERS = ['mumu_adb.bat', 'mumu_sync.bat']


def _check_launchers():
    """`.bat` 里写死 python.exe 的路径就算 DRIVE 正则抓不到（不含 Users/Program Files 等），
    换机器同样必然报 "Python not found"。这里直接按"有没有 py/python 探测"判。"""
    bad = []
    for fn in BAT_LAUNCHERS:
        p = os.path.join(S, fn)
        if not os.path.isfile(p):
            continue
        txt = io.open(p, encoding='utf-8', errors='replace').read()
        lines = [l.strip() for l in txt.splitlines()]
        # 注释掉的探测不算数（`rem where py ...` 仍含子串，必须逐行判"真执行"）
        live = [l for l in lines if l and not l.lower().startswith(('rem', '::', '@rem'))]
        if not any(('where py' in l) or ('where python' in l) for l in live):
            bad.append(fn)
    return bad


def _scan_bad():
    """真正的扫描口径。抽成函数是为了让**基线生成**与**判据**共用同一个 os.walk + 排除表
    —— 两把尺子各写一遍必然对不上（WF-61 踩过的坑：第二次跑数出来的数和基线不符，闸门天天假红）。"""
    bad = []
    for dirpath, dirnames, files in os.walk(S):
        dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '_archive')]
        for fn in files:
            if not fn.endswith(SCAN_EXTS):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), S).replace('\\', '/')
            base = rel.split('/')[-1]
            if base in ALLOW or rel in LEGACY:
                continue
            try:
                txt = io.open(os.path.join(dirpath, fn), encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            hits = [(i + 1, l.strip()[:110]) for i, l in enumerate(txt.splitlines()) if DRIVE.search(l)]
            if hits:
                bad.append((rel, hits))
    return bad


def scan_bad():
    return _scan_bad()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--no-strict', dest='strict', action='store_false',
                    help='软档只报数不判红（仅在还有明确待迁条目时临时用）')
    ap.add_argument('--update', action='store_true',
                    help='把当前写死绝对路径的文件冻成基线（清了债才许用，与 check_lint_baseline 同形状）')
    ap.set_defaults(strict=True)
    a = ap.parse_args()
    bad = _scan_bad()
    if a.update:
        payload = {
            'hardcoded_paths_files': len(bad),
            'note': '既有存量的文件清单；新增文件一律判红。清了债用 --update 重写本文件。',
            'fingerprints': sorted(rel for rel, _h in bad),
        }
        json.dump(payload, open(PATHS_BASE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[OK] 基线已更新：{len(bad)} 个文件 → {os.path.relpath(PATHS_BASE, ROOT)}')
        return 0

    if not os.path.isfile(PATHS_BASE):
        print(f'[FAIL] 基线文件不存在：{os.path.relpath(PATHS_BASE, ROOT)}'
              f'（这是"检查没接上"，不是全绿）')
        return 1
    base = json.load(open(PATHS_BASE, encoding='utf-8'))
    known = set(base.get('fingerprints') or [])
    allowed = base.get('hardcoded_paths_files')

    missing = []
    new_bad = [x for x in bad if x[0] not in known]
    for rel in MUST_USE_PATHS:
        p = os.path.join(S, rel.replace('/', os.sep))
        txt = io.open(p, encoding='utf-8', errors='replace').read() if os.path.isfile(p) else ''
        if 'import paths as P' not in txt:
            missing.append(rel)

    launcher_bad = _check_launchers()

    # 已清的债也要报出来：基线里列了但现在已经不写死 ⇒ 基线过期，提示收紧而不是静默放行
    cleaned = sorted(known - {rel for rel, _h in bad})

    if a.verbose or new_bad or missing or launcher_bad:
        for rel, hits in new_bad:
            print(f'  写死了绝对路径（基线之外的新增）: {rel}')
            for n, l in hits[:4]:
                print(f'      {n}: {l}')
        for rel in missing:
            print(f'  调用链上的脚本没走 paths: {rel}')
        for fn in launcher_bad:
            print(f'  启动器没有 py/python 探测（换机器双击必炸）: {fn}')

    n = len(new_bad) + len(missing) + len(launcher_bad)
    if n == 0 and cleaned:
        print(f'  提示：{len(cleaned)} 个文件已不再写死绝对路径，可跑 --update 收紧基线')
    print(f'{"[FAIL] " if n else "[PASS] "}写死绝对路径新增 {len(new_bad)} 个文件'
          f'（存量 {len(known) - len(cleaned)}/{allowed} 已冻结）'
          f'，未接 paths 的链路脚本 {len(missing)} 个'
          f'，无解释器探测的启动器 {len(launcher_bad)} 个')
    return 1 if n else 0



if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
