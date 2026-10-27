# -*- coding: utf-8 -*-
"""灵敏度扫描 v2：min / mid / max 三点，对比两组。

v1（`pd_sens.py`，只试 min/max）对 `ArtMesh214` 只报出 `BG_TMD`，但 `BG_TMD`
全程恒 1.0 —— 解释不了第 90 帧 F=1.0 / OFF=0 的差异。opacity 的 keyform 常见形状是
「两端 1.0、中间压到 0」，min/max 两点采样必然漏掉这类，故本版补中点。


⚠️ 依赖 `Output/gallery_v2/_paramdump.html`（该页在 gitignore 的运行目录，
   换机器/重装环境后必须先把它放回运行目录）。`--base(s)` 取值相对 docroot(`Output/`) 解析。

用法: py -3 scripts/diag/pd_sens2.py --bases=../_ab/E,../_ab/official --ship=X --grp=Y --didx=N [--upto=N]
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
DIDX = arg('didx', '292'); FPS = arg('fps', '30')
UPTO = int(arg('upto', '0'))   # 先推进到第 N 帧再扫（0 = 不推进）


def run(base):
    url = ('http://127.0.0.1:8778/gallery_v2/_paramdump.html?base=%s&ship=%s&grp=%s&fps=%s'
           % (base, SHIP, GRP, FPS))
    prof = os.path.join(ROOT, '.diag', 'chrome_ps%d' % int(time.time() * 1000 % 1000000))
    pg = Page(9700 + int(time.time()) % 90, prof, url, (520, 520), gpu=True)
    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            time.sleep(0.7)
            if pg.ev('document.title') in ('DONE', 'ERR'):
                break
        if pg.ev('document.title') != 'DONE':
            print(pg.ev("(function(){var e=document.getElementById('log');return e?e.textContent:'?';})()"))
            return None
        r = pg.ev("(async function(){ return await window.__sens2(%s,%d); })()" % (DIDX, UPTO))
        return r if isinstance(r, dict) else json.loads(r)
    finally:
        pg.close()


for b in BASES:
    r = run(b)
    print('==' + b)
    if not r:
        continue
    print('   drawable=%s idx=%d baseOp=%s scanned=%d hits=%d'
          % (r['drawable'], r['idx'], r['baseOp'], r['scanned'], len(r['hits'])))
    for h in r['hits'][:15]:
        print('   %-28s idx=%3d range=[%s, %s] cur=%-10s ops@lo/mid/hi=%s'
              % (h['id'], h['i'], h['lo'], h['hi'], h['cur'], h['ops']))
    print()
