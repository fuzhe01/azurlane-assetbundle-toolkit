# -*- coding: utf-8 -*-
"""扫单个 (drawable, param) 的响应曲线，并逐帧打印该 param 的两组取值。

用途：验证「keyform 极陡 + 参数微差即翻转」这类假缺陷。
实测背景：`benningdun_2/idle` 的 `ArtMesh214`(idx292) opacity 只受 `BG_TMD`(140)
与 `Circulation5`(457) 影响；`Circulation5` 两组只差 4e-5，但它的 keyform 若在
0.9666 附近有一道陡坎，4e-5 的参数差就能把 opacity 从 1.0 推到 0.0。


⚠️ 依赖 `Output/gallery_v2/_paramdump.html`（该页在 gitignore 的运行目录，
   换机器/重装环境后必须先把它放回运行目录）。`--base(s)` 取值相对 docroot(`Output/`) 解析。

用法: py -3 scripts/diag/pd_curve.py --bases=../_ab/E,../_ab/official --ship=X --grp=Y --didx=N --pidx=P [--upto=N --n=400]
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
FPS = arg('fps', '30'); DIDX = arg('didx', '292'); PIDX = arg('pidx', '457')
UPTO = int(arg('upto', '88')); N = arg('n', '400')
F0, F1 = int(arg('f0', '84')), int(arg('f1', '94'))
FRAMES = ','.join(str(i) for i in range(F0, F1 + 1))


def run(base):
    url = ('http://127.0.0.1:8778/gallery_v2/_paramdump.html?base=%s&ship=%s&grp=%s&fps=%s'
           % (base, SHIP, GRP, FPS))
    prof = os.path.join(ROOT, '.diag', 'chrome_pc%d' % int(time.time() * 1000 % 1000000))
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
        # 先推进到 UPTO 帧，再取逐帧参数（含 pre）与响应曲线
        d = pg.ev("(async function(){ return await window.__dump('%s','%s',true); })()" % (FRAMES, DIDX))
        d = d if isinstance(d, dict) else json.loads(d)
        c = pg.ev("(async function(){ return await window.__curve(%s,%s,%s); })()" % (DIDX, PIDX, N))
        c = c if isinstance(c, dict) else json.loads(c)
        return d, c
    finally:
        pg.close()


res = {}
for b in BASES:
    r = run(b)
    if not r:
        sys.exit(1)
    res[b] = r

pname = None
print('== 逐帧 %s 取值（还原后 p / 还原前 pre / 目标 opacity）==' % ('param %s' % PIDX))
for b in BASES:
    d, _ = res[b]
    IDS = d['ids']; pname = IDS[int(PIDX)]
    print('-- %s  param=%s' % (b, pname))
    for fa in d['frames']:
        v = fa['p'].get(pname)
        pv = fa['pre'][int(PIDX)] if fa.get('pre') else None
        o = list(fa['d'].values())[0]
        print('   f=%-4d t=%-9.4f p=%-14.8f pre=%-14.8f op=%s'
              % (fa['f'], fa['t'], v if v is not None else float('nan'),
                 pv if pv is not None else float('nan'), o['o']))

print('\n== 响应曲线（%s 对 %s 的 opacity）==' % (pname, DIDX))
for b in BASES:
    _, c = res[b]
    pts = c['pts']
    print('-- %s  lo=%s hi=%s cur=%.8f' % (b, c['lo'], c['hi'], c['cur']))
    # 找跳变点（相邻两点 opacity 差 > 0.2）
    jumps = [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
             for i in range(len(pts) - 1) if abs(pts[i + 1][1] - pts[i][1]) > 0.2]
    print('   采样点=%d  跳变段=%d' % (len(pts), len(jumps)))
    for j in jumps[:10]:
        print('   跳变 at param ∈ [%.8f, %.8f]  op %.6f -> %.6f' % j)
    if jumps:
        mid = (jumps[0][0] + jumps[0][2]) / 2
        print('   首个跳变中点 param≈%.8f   cur=%.8f   距跳变=%.3e'
              % (mid, c['cur'], c['cur'] - mid))
