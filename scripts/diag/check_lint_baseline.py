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
  2. 其余条目里**基线之外新增的 (文件, 消息) 对**必须为 0（存量冻在 `lint_baseline.json`）
  3. 基线文件必须存在且能被解析（不许静默"没有基线就当全绿"）

为什么按"文件+消息"记基线而不是记条数（2026-11-01 合并 fork 97 提交时改的）：
原来只存一个总数（69）。合并 fork 的 334 个脚本后总数变 162，闸门立刻常红，
而 93 条新增里 **91 条来自 fork 既有的一次性诊断脚本**、我们这侧只有 2 条（已当场修掉）。
按条数判红的后果就是"我真正写的新增被 91 条别人的历史噪声淹没" —— 正是本条 docstring
第 14 行讲的那个形状。改成 (文件, 消掉行号的消息) 集合后：行号漂移不再假红、
别人多带进来的存量也不假红，只有**基线里没有的那一对**才红。
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
# pyflakes 的输出形如 `路径:行:列: 消息`；消息里的行号（`from line 3`）会随编辑漂移，
# 基线里只留"文件 + 消掉行号的消息"，判据才不会因为往上加了一行注释就假红。
LINE_RE = re.compile(r'^.*?([\\/]scripts[\\/].*?):(\d+):(\d+): (.*)$')


def fingerprint(line):
    """把一条 pyflakes 输出折成稳定的 (相对文件, 消息) 对；不是标准格式就原样返回。"""
    m = LINE_RE.match(line)
    if not m:
        return (line,)
    rel = m.group(1).replace('\\', '/').split('/scripts/', 1)[-1]
    return (rel, re.sub(r'line \d+', 'line N', m.group(4)))


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
        fps = sorted('.'.join(fingerprint(l)) for l in soft)
        json.dump({'pyflakes_findings': len(soft),
                   'note': '见 check_lint_baseline.py 的 docstring；按 (文件, 消息) 冻存量',
                   'fingerprints': fps},
                  open(BASELINE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[OK] 基线已更新：{len(soft)} 条 / {len(fps)} 组 (文件, 消息)（硬红线仍为 0）')
        return 0

    if not os.path.isfile(BASELINE):
        print(f'[FAIL] 基线文件不存在：{os.path.relpath(BASELINE, ROOT)}（这是"检查没接上"，不是全绿）')
        return 1
    base = json.load(open(BASELINE, encoding='utf-8'))
    allowed = base.get('pyflakes_findings')
    known = set(base.get('fingerprints') or [])

    bad = 0
    if hard:
        bad += len(hard)
        print(f'[FAIL] {len(hard)} 条真缺陷（这一类不许进基线）：')
        for l in hard:
            print('   ' + l)
    if allowed is None:
        print('[FAIL] 基线里没有 pyflakes_findings 字段')
        bad += 1
    if base.get('fingerprints') is None:
        print('[FAIL] 基线里没有 fingerprints：老格式只记总数，合并之后会常红，'
              '跑一次 --update 重写')
        bad += 1
    added = [l for l in soft if '.'.join(fingerprint(l)) not in known]
    if added:
        bad += 1
        print(f'[FAIL] 基线之外新增 pyflakes 条目 {len(added)} 条'
              f'（存量 {len(soft) - len(added)}/{allowed} 条已冻结）')
        for l in added:
            print('   ' + l)

    if bad:
        return 1
    print(f'[PASS] 真缺陷 0 条；pyflakes 存量 {len(soft)} 条（基线 {allowed} 条）'
          f'，基线之外新增 0 条')
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

    # 指纹必须对行号免疫、对"换了文件"敏感 —— 否则基线会因为往上加注释而天天假红。
    fp_ok = (fingerprint("D:\\x\\scripts\\a.py:10:1: 'json' imported but unused")
             == fingerprint("D:/x/scripts/a.py:99:1: 'json' imported but unused")
             != fingerprint("D:\\x\\scripts\\b.py:10:1: 'json' imported but unused"))
    print(f'{"PASS" if fp_ok else "FAIL"} 指纹：行号漂移不改变指纹、换文件必变')
    return 0 if (ok and fp_ok) else 1


if __name__ == '__main__':
    sys.exit(main())
