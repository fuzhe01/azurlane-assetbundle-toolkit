# -*- coding: utf-8 -*-
"""抓 `model.update()` 之后、`loadParameters()` 还原之前的真实参数值。

动机：`ArtMesh214` 的 opacity 只由 `BG_TMD` 一个参数驱动（灵敏度扫描实测 hits=1），
而页面上任何时刻读到的 `P.values` 都是 `loadParameters()` 还原后的状态 —— 若 `BG_TMD`
由 physics/pose/motion 在 `model.update()` 前写入、随后被还原，则常规读数必然看不到。
本脚本对 `loadParameters` 挂钩（`_paramdump.html` 里的 `core.loadParameters` 包装），
取还原前的快照 `pre`，两端差分定位真正分歧的参数。


⚠️ 依赖 `Output/gallery_v2/_paramdump.html`（该页在 gitignore 的运行目录，
   换机器/重装环境后必须先把它放回运行目录）。`--base(s)` 取值相对 docroot(`Output/`) 解析。

用法: py -3 scripts/diag/pd_pre.py --bases=../_ab/E,../_ab/official --ship=X --grp=Y --didx=N --f0=84 --f1=94
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
F0, F1 = int(arg('f0', '84')), int(arg('f1', '94'))
FRAMES = ','.join(str(i) for i in range(F0, F1 + 1))


def run(base):
    url = ('http://127.0.0.1:8778/gallery_v2/_paramdump.html?base=%s&ship=%s&grp=%s&fps=%s'
           % (base, SHIP, GRP, FPS))
    prof = os.path.join(ROOT, '.diag', 'chrome_pp%d' % int(time.time() * 1000 % 1000000))
    pg = Page(9600 + int(time.time()) % 90, prof, url, (520, 520), gpu=True)
    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            time.sleep(0.7)
            if pg.ev('document.title') in ('DONE', 'ERR'):
                break
        if pg.ev('document.title') != 'DONE':
            print(pg.ev("(function(){var e=document.getElementById('log');return e?e.textContent:'?';})()"))
            return None
        return json.loads(pg.ev("(async function(){return await window.__dump('%s','%s',true);})()"
                                % (FRAMES, DIDX)))
    finally:
        pg.close()


A = run(BASES[0]); B = run(BASES[1])
if not A or not B:
    sys.exit(1)
IDS = A['ids']
print('A=%s  B=%s' % (BASES[0], BASES[1]))
iBG = IDS.index('BG_TMD') if 'BG_TMD' in IDS else -1
print('BG_TMD idx=%s' % iBG)
print()
print('%-5s %-9s | %-22s | %-22s | %s' % ('f', 't', 'A o/raw/pre[BG_TMD]', 'B o/raw/pre[BG_TMD]', 'pre 差异条数'))
for fa, fb in zip(A['frames'], B['frames']):
    da = list(fa['d'].values())[0]; db = list(fb['d'].values())[0]
    pa, pb = fa.get('pre'), fb.get('pre')
    nd = 0; tops = []
    if pa and pb:
        for i in range(min(len(pa), len(pb))):
            if abs(pa[i] - pb[i]) > 1e-5:
                nd += 1; tops.append((IDS[i], pa[i], pb[i], abs(pa[i] - pb[i])))
        tops.sort(key=lambda x: -x[3])
    ga = ('%9.6f' % pa[iBG]) if (pa and iBG >= 0) else 'n/a'
    gb = ('%9.6f' % pb[iBG]) if (pb and iBG >= 0) else 'n/a'
    print('%-5d %8.4f | o=%7.5f raw=%7.5f pre=%s | o=%7.5f raw=%7.5f pre=%s | %d'
          % (fa['f'], fa['t'], da['o'], da['raw'], ga, db['o'], db['raw'], gb, nd))
    for k, va, vb, dd in tops[:6]:
        print('        pre %-28s A=%12.6f  B=%12.6f  d=%.6f' % (k, va, vb, dd))
