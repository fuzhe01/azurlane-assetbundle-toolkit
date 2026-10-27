# -*- coding: utf-8 -*-
"""逐帧扫描两组 base 的参数向量，找**首次分歧帧**（pd_probe 只看指定帧，看不到分歧起点）。

背景：benningdun_2/idle 第 86~90 帧参数向量逐位相同，但 drawable opacity 不同。
`Cubism4InternalModel.update()` 的顺序是
  motionManager.update -> saveParameters -> expression/eyeblink/focus/breath/physics/pose
  -> model.update() -> loadParameters()
所以页面上读到的 `P.values` 是 **loadParameters 还原后**的状态，看不到 physics/pose 写进去的量。
opacity 差异只能来自两处：① 分歧发生在更早的帧（physics 有状态、会拖着走）
② 同帧内 physics/pose 写入量不同（physics3 已验 md5 相同，故只可能是 physics 内部状态）
本脚本先用 ① 定位分歧起点，再用 --nophys=1 把 ② 单独隔离。


⚠️ 依赖 `Output/gallery_v2/_paramdump.html`（该页在 gitignore 的运行目录，
   换机器/重装环境后必须先把它放回运行目录）。`--base(s)` 取值相对 docroot(`Output/`) 解析。

用法: py -3 scripts/diag/pd_scan.py --ship=X --grp=Y --didx=N --f0=0 --f1=120 [--nophys=1]
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
F0, F1 = int(arg('f0', '0')), int(arg('f1', '120'))
NOPHYS = arg('nophys', '0')

FRAMES = ','.join(str(i) for i in range(F0, F1 + 1))


def run(base):
    url = ('http://127.0.0.1:8778/gallery_v2/_paramdump.html?base=%s&ship=%s&grp=%s&fps=%s&nophys=%s'
           % (base, SHIP, GRP, FPS, NOPHYS))
    prof = os.path.join(ROOT, '.diag', 'chrome_ps%d' % int(time.time() * 1000 % 1000000))
    pg = Page(9900 + int(time.time()) % 90, prof, url, (520, 520), gpu=True)
    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            time.sleep(0.7)
            if pg.ev('document.title') in ('DONE', 'ERR'):
                break
        if pg.ev('document.title') != 'DONE':
            print(pg.ev("(function(){var e=document.getElementById('log');return e?e.textContent:'?';})()"))
            return None
        return json.loads(pg.ev("(async function(){return await window.__dump('%s','%s');})()" % (FRAMES, DIDX)))
    finally:
        pg.close()


A = run(BASES[0]); B = run(BASES[1])
if not A or not B:
    sys.exit(1)

print('A=%s  B=%s  ship=%s grp=%s drawable=%s nophys=%s fps=%s'
      % (BASES[0], BASES[1], SHIP, GRP, DIDX, NOPHYS, FPS))
print('paramCount=%s drawableCount=%s liveParams(A)=%s'
      % (A['paramCount'], A['drawableCount'], A['liveParamsPerFrame'][:6]))
print()

first = None
for fa, fb in zip(A['frames'], B['frames']):
    keys = [k for k in fa['p'] if k in fb['p']]
    diffs = [(k, fa['p'][k], fb['p'][k], abs(fa['p'][k] - fb['p'][k])) for k in keys
             if abs(fa['p'][k] - fb['p'][k]) > 1e-6]
    opA = list(fa['d'].values())[0]; opB = list(fb['d'].values())[0]
    opDiff = abs(opA['o'] - opB['o']) > 1e-6
    if diffs and first is None:
        first = fa['f']
    if diffs or opDiff:
        tag = []
        if diffs: tag.append('P%d' % len(diffs))
        if opDiff: tag.append('O[%s vs %s]' % (opA['o'], opB['o']))
        print('f=%-4d t=%7.4f  %s' % (fa['f'], fa['t'], ' '.join(tag)))
        diffs.sort(key=lambda x: -x[3])
        for k, va, vb, dd in diffs[:8]:
            print('      %-30s A=%12.6f  B=%12.6f  d=%.6f' % (k, va, vb, dd))

print()
print('首次参数分歧帧 = %s' % first)
