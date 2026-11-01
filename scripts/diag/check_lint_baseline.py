# -*- coding: utf-8 -*-
"""pyflakes 基线闸门：**只拦新增，不逼人清历史**。

为什么是"基线"而不是"全清零"（2026-11-01 实测）：全库 94 条 pyflakes 里，
真正会咬人的只有两类 —— `undefined name`（运行到那行就 NameError）和
字典型字面量的重复键（后写静默覆盖前写）。本轮清掉的就是这两类：
`pipeline_panel._scope_units` 的 `importlib`、`spine_framing_scan` 的 `dead`、
`scan_assets` 的 `bg` 双写。
剩下 90 多条是 unused import / 无占位符 f-string，**清它们没有收益**，
唯一效果是让真信号淹没在噪声里被一起忽略（同一个形状的教训见 §71
"永远红的检查必然被绕过"）。所以把当前存量冻成基线，新增一律判红。

    py -3 scripts/diag/check_lint_baseline.py            # 退出码即结论
    py -3 scripts/diag/check_lint_baseline.py --update   # 重写基线（清了债才许用）

判据（三条都要过）：
  1. `undefined name` / `redefinition` / `repeated with different values` 必须为 **0**（硬红线，不进基线）
  2. 其余条目的总数不得超过基线文件里的基线值
  3. 基线文件必须存在且能被解析（不许静默"没有基线就当全绿"）
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
S = os.path.join(ROOT, 'scripts')
BASELINE = os.path.join(HERE, 'lint_baseline.json')

HARD = re.compile(r'undefined name|redefinition of unused|repeated with different values')


def run_pyflakes():
    files = []
    for dirpath, dirnames, names in os.walk(S):
        dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '_archive')]
        files += [os.path.join(dirpath, n) for n in names if n.endswith('.py')]
    try:
        p = subprocess.run([sys.executable, '-m', 'pyflakes'] + files,
                           capture_output=True, text=True)
    except OSError as e:
        print(f'[SKIP] 起不来 pyflakes：{e}')
        return None
    if p.returncode not in (0, 1) and 'No module named pyflakes' in (p.stderr or ''):
        print('[SKIP] 本机没装 pyflakes：py -3 -m pip install pyflakes')
        print('       （这是环境缺件，不是代码判据失败）')
        return None
    lines = [l for l in (p.stdout or '').splitlines() if l.strip()]
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--update', action='store_true')
    ap.add_argument('--selftest', action='store_true', help='只跑硬红线正则的阴性对照')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    if a.selftest:
        return selftest()

    lines = run_pyflakes()
    if lines is None:
        return 0                                  # 环境缺件 ⇒ SKIP，不假装绿也不假红

    hard = [l for l in lines if HARD.search(l)]
    soft = [l for l in lines if not HARD.search(l)]

    if a.update:
        if hard:
            print('[FAIL] 还有真缺陷，先修掉再冻基线：')
            for l in hard:
                print('   ' + l)
            return 1
        json.dump({'pyflakes_findings': len(soft), 'note': '见 check_lint_baseline.py 的 docstring'},
                  open(BASELINE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[OK] 基线已更新：{len(soft)} 条（硬红线仍为 0）')
        return 0

    if not os.path.isfile(BASELINE):
        print(f'[FAIL] 基线文件不存在：{os.path.relpath(BASELINE, ROOT)}（这是"检查没接上"，不是全绿）')
        return 1
    base = json.load(open(BASELINE, encoding='utf-8'))
    allowed = base.get('pyflakes_findings')

    bad = 0
    if hard:
        bad += len(hard)
        print(f'[FAIL] {len(hard)} 条真缺陷（这一类不许进基线）：')
        for l in hard:
            print('   ' + l)
    if allowed is None:
        print('[FAIL] 基线里没有 pyflakes_findings 字段')
        bad += 1
    elif len(soft) > allowed:
        bad += 1
        print(f'[FAIL] pyflakes 条目 {len(soft)} 条 > 基线 {allowed} 条（新增了 {len(soft) - allowed} 条）')
        print('       新增的条目（基线里没有的那些）：')
        known = set(base.get('fingerprints', []))
        for l in soft:
            if l not in known:
                print('   ' + l)

    if bad:
        return 1
    print(f'[PASS] 真缺陷 0 条；pyflakes 存量 {len(soft)}/{allowed} 条（未超基线）')
    return 0


def selftest():
    """反向对照：喂四条样本，确认 `HARD` 正则真的抓得住那三类、放得过无害那条。

    "只报数不判红"的闸门最容易形同虚设（本项目对这类形状的态度见 §71），
    所以这里自己做一次阴性对照，而不是等真缺陷出现时才发现正则写漏了。
    """
    samples = [
        "scripts/x.py:1:1: undefined name 'foo'",
        "scripts/x.py:2:1: redefinition of unused 'bar' from line 1",
        "scripts/x.py:3:5: dictionary key 'k' repeated with different values",
        "scripts/x.py:4:1: 'json' imported but unused",
    ]
    hits = [bool(HARD.search(s)) for s in samples]
    ok = hits == [True, True, True, False]
    print(f'{"PASS" if ok else "FAIL"} 硬红线正则分类：命中 {sum(hits)}/3，放行 1 条，与期望一致={ok}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
