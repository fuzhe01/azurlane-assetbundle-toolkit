# -*- coding: utf-8 -*-
"""全量 drawable opacity 跨组差分，定位 #292 的乘数来源。

背景：#292 `ArtMesh214` 两组 `raw` opacity 相同、`partChain` 全 1.0，但**有效可见度**不同。
Live2D 的有效可见度 = 自身 opacity × 部件链 × **clipping mask drawable 的 opacity**，
而 mask 关系不在 `parentPartIndices` 里。本脚本 dump 全部 drawable opacity 后逐帧差分，
找出「在目标帧翻转、且翻转幅度能解释目标 diff」的其它 drawable。


⚠️ 依赖 `Output/gallery_v2/_paramdump.html`（该页在 gitignore 的运行目录，
   换机器/重装环境后必须先把它放回运行目录）。`--base(s)` 取值相对 docroot(`Output/`) 解析。

用法: py -3 scripts/diag/pd_ops.py --bases=../_ab/E,../_ab/official --ship=X --grp=Y --didx=N --f0=85 --f1=92
"""
import json, os, sys, time
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag')); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import paths as P, gallery_ui_shots as GU
GU.CHROME = P.CHROME
from gallery_ui_shots import Page


def arg(n, d=None):
    for a in sys.argv[1:]:
        if a.startswith('--' + n + '='):
            return a.split('=', 1)[1]
    return d


BASES = arg('bases', '../_ab/F,../_ab/official').split(',')
SHIP = arg('ship', 'benningdun_2'); GRP = arg('grp', 'idle')
FPS = arg('fps', '30'); TARGET = arg('didx', '292')
F0, F1 = int(arg('f0', '85')), int(arg('f1', '92'))
FRAMES = ','.join(str(i) for i in range(F0, F1 + 1))


def run(base):
    url = ('http://127.0.0.1:8778/gallery_v2/_paramdump.html?base=%s&ship=%s&grp=%s&fps=%s'
           % (base, SHIP, GRP, FPS))
    prof = os.path.join(ROOT, '.diag', 'chrome_po%d' % int(time.time() * 1000 % 1000000))
    pg = Page(9800 + int(time.time()) % 90, prof, url, (520, 520), gpu=True)
    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            time.sleep(0.7)
            if pg.ev('document.title') in ('DONE', 'ERR'):
                break
        if pg.ev('document.title') != 'DONE':
            print(pg.ev("(function(){var e=document.getElementById('log');return e?e.textContent:'?';})()"))
            return None
        r = pg.ev("(async function(){ return await window.__ops('%s'); })()" % FRAMES)
        return r if isinstance(r, dict) else json.loads(r)
    finally:
        pg.close()


A = run(BASES[0]); B = run(BASES[1])
if not A or not B:
    sys.exit(1)
NAMES = A['names']; T = int(TARGET)
print('A=%s  B=%s   target=%s idx=%d  drawables=%d'
      % (BASES[0], BASES[1], NAMES[T], T, len(NAMES)))

print('\n--- 目标 drawable 逐帧 ---')
print('%-5s %-9s | %-10s %-10s %-10s | %-10s %-10s %-10s'
      % ('f', 't', 'A.op', 'B.op', 'd', 'A.vf', 'B.vf', 'name'))
for fa, fb in zip(A['frames'], B['frames']):
    d = fa['op'][T] - fb['op'][T]
    print('%-5d %-9.4f | %-10.6f %-10.6f %-10.6f | %-10d %-10d %s'
          % (fa['f'], fa['t'], fa['op'][T], fb['op'][T], d, fa['vf'][T], fb['vf'][T], NAMES[T]))

print('\n--- 其它 drawable 中，谁在第 ' + str(F1) + ' 帧两组不同（按 |d| 降序，前 25）---')
for fa, fb in zip(A['frames'], B['frames']):
    if fa['f'] != F1:
        continue
    diffs = []
    for d in range(len(NAMES)):
        dd = fa['op'][d] - fb['op'][d]
        fd = fa['vf'][d] - fb['vf'][d]
        if abs(dd) > 1e-6 or fd != 0:
            diffs.append((abs(dd), d, fa['op'][d], fb['op'][d], fa['vf'][d], fb['vf'][d]))
    diffs.sort(reverse=True)
    print('frame %d  t=%.4f  差异 drawable 数=%d' % (fa['f'], fa['t'], len(diffs)))
    for _, d, oa, ob, va, vb in diffs[:25]:
        mark = ' <<< TARGET' if d == T else ''
        print('   #%-5d %-24s A.op=%-10.6f B.op=%-10.6f  d=%-11.6f vf %d/%d%s'
              % (d, NAMES[d], oa, ob, oa - ob, va, vb, mark))

print('\n--- 全帧汇总：每帧差异 drawable 数 ---')
for fa, fb in zip(A['frames'], B['frames']):
    n = sum(1 for d in range(len(NAMES)) if abs(fa['op'][d] - fb['op'][d]) > 1e-6
            or fa['vf'][d] != fb['vf'][d])
    print('  f=%-4d t=%-9.4f diff=%d' % (fa['f'], fa['t'], n))
