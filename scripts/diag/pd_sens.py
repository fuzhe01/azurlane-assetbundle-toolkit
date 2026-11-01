# -*- coding: utf-8 -*-
"""灵敏度扫描：逐个参数从 min 扫到 max，看目标 drawable 的 opacity 是否响应。

目的：`ArtMesh214` 在第 90 帧 opacity 1.0(F) vs 0(official)，但参数向量逐位相同、
且无任何参数在该帧跳变 ⇒ 需要先确定「这个 drawable 的 opacity 到底由哪些参数决定」，
才可能给它归因。若一个都不响应，说明是 Core 内部可见性判定而非参数驱动。


⚠️ 依赖 `Output/gallery_v2/_paramdump.html`（该页在 gitignore 的运行目录，
   换机器/重装环境后必须先把它放回运行目录）。`--base(s)` 取值相对 docroot(`Output/`) 解析。

用法: py -3 scripts/diag/pd_sens.py --base=../_ab/official --ship=X --grp=Y --didx=N
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


BASE = arg('base', '../_ab/official')
SHIP = arg('ship', 'benningdun_2'); GRP = arg('grp', 'idle')
DIDX = arg('didx', '292'); FPS = arg('fps', '30')

url = ('http://127.0.0.1:8778/gallery_v2/_paramdump.html?base=%s&ship=%s&grp=%s&fps=%s'
       % (BASE, SHIP, GRP, FPS))
prof = os.path.join(ROOT, '.diag', 'chrome_sn%d' % int(time.time() * 1000 % 1000000))
pg = Page(9700 + int(time.time()) % 90, prof, url, (520, 520), gpu=True)
try:
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(0.7)
        if pg.ev('document.title') in ('DONE', 'ERR'):
            break
    if pg.ev('document.title') != 'DONE':
        print(pg.ev("(function(){var e=document.getElementById('log');return e?e.textContent:'?';})()"))
        sys.exit(1)
    R = json.loads(pg.ev("(function(){return window.__sens(%s);})()" % DIDX))
finally:
    pg.close()

print('base=%s ship=%s grp=%s drawable=%s (#%s)' % (BASE, SHIP, GRP, R['drawable'], R['idx']))
print('baseOp=%.6f  scanned=%d  hits=%d' % (R['baseOp'], R['scanned'], len(R['hits'])))
print()
for h in R['hits']:
    print('  %-8s idx=%-4d range=[%8.3f,%8.3f] cur=%10.5f  opLo=%9.5f opHi=%9.5f'
          % (h['id'], h['i'], h['lo'], h['hi'], h['cur'], h['opLo'], h['opHi']))
if not R['hits']:
    print('  （无任何参数能改变该 drawable 的 opacity）')
