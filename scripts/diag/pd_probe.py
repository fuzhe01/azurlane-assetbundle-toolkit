# -*- coding: utf-8 -*-
"""对 (ship, grp, drawableIdx) 在给定帧上 dump 全参数，比较两个 base 组。

⚠️ 依赖 `Output/gallery_v2/_paramdump.html`（该页在 gitignore 的运行目录，
   换机器/重装环境后必须先把它放回运行目录，否则本探针只会打印 ERR 日志。
   `--base` 的取值相对 docroot(`Output/`) 解析，如 `../_ab/E` / `../_ab/official`。

用法: py -3 scripts/diag/pd_probe.py --ship=X --grp=Y --didx=N --frames=88,89,90
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
        if a.startswith('--'+n+'='): return a.split('=',1)[1]
    return d

BASES = arg('bases', '../_ab/F,../_ab/official').split(',')
SHIP = arg('ship','benningdun_2'); GRP = arg('grp','idle')
DIDX = arg('didx','292'); FRAMES = arg('frames','88,89,90')
PORT = arg('port','8778')

def run(base):
    url = ('http://127.0.0.1:%s/gallery_v2/_paramdump.html?base=%s&ship=%s&grp=%s&fps=30'
           % (PORT, base, SHIP, GRP))
    prof = os.path.join(ROOT, '.diag', 'chrome_pd%d' % int(time.time()*1000%1000000))
    pg = Page(9800+int(time.time())%90, prof, url, (520,520), gpu=True)
    try:
        t0=time.time()
        while time.time()-t0 < 300:
            time.sleep(0.7)
            if pg.ev('document.title') in ('DONE','ERR'): break
        if pg.ev('document.title') != 'DONE':
            print(pg.ev("(function(){var e=document.getElementById('log');return e?e.textContent:'?';})()")); return None
        raw = pg.ev("(async function(){return await window.__dump('%s','%s');})()" % (FRAMES, DIDX))
        return json.loads(raw)
    finally:
        pg.close()

A = run(BASES[0]); B = run(BASES[1])
if not A or not B: sys.exit(1)
for nm, D in (('A', A), ('B', B)):
    print('== %s  frames=%s' % (nm, [(x['f'], x['t'], x['d']) for x in D['frames']]))
print()
for fa, fb in zip(A['frames'], B['frames']):
    pa, pb = fa['p'], fb['p']
    diffs = [(k, pa[k], pb[k], abs(pa[k]-pb[k])) for k in pa if k in pb and abs(pa[k]-pb[k]) > 1e-4]
    diffs.sort(key=lambda x: -x[3])
    print('SELFCHECK liveParams=%s paramCount=%s drawables=%s' % (A.get('liveParamsPerFrame'), A.get('paramCount'), A.get('drawableCount'))); print('-- frame %d  t=%.4f   差异参数 %d 条' % (fa['f'], fa['t'], len(diffs)))
    for k, va, vb, dd in diffs[:18]:
        print('     %-26s A=%12.5f  B=%12.5f  d=%.5f' % (k, va, vb, dd))
