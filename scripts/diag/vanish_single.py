# -*- coding: utf-8 -*-
"""vanish_single.py — 对单个 (模型, 动作组) 跑一遍可见件扫描，并打印指定下标件的名字。

用途：`vanish_matrix.py` 的聚合对照只能告诉你「偏离 3 点」，要知道是**哪一件**、
以及它在我们和官方参考里各是什么形态，就得按下标把 drawable 名捞出来。
本脚本是 `vanish_matrix.py` 的定点放大镜。

用法:
  py -3 scripts/diag/vanish_single.py --base=../_ab/E --ship=benningdun_2 --grp=idle --idx=292
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402


def arg(name, default=None):
    for a in sys.argv[1:]:
        if a == '--' + name:
            return True
        if a.startswith('--' + name + '='):
            return a.split('=', 1)[1]
    return default


BASE = arg('base', '../_ab/E')
SHIP = arg('ship', 'benningdun_2')
GRP = arg('grp', 'idle')
IDX = [int(x) for x in str(arg('idx', '')).split(',') if x.strip()]
FPS = arg('fps', '30')
NOPHYS = str(arg('nophys', ''))
WAIT = float(arg('wait', 600))
PORT = arg('port', '8778')
TRACE = str(arg('trace', ','.join(str(i) for i in IDX)))
URL = ('http://127.0.0.1:%s/gallery_v2/_vanishcan.html?base=%s&ship=%s&grp=%s&fps=%s&trace=%s%s'
       % (PORT, BASE, SHIP, GRP, FPS, TRACE, '&nophys=1' if NOPHYS == '1' else ''))


def main():
    prof = os.path.join(ROOT, '.diag', 'chrome_vs%d' % int(time.time() * 1000 % 1000000))
    pg = Page(9699 + int(time.time()) % 60, prof, URL, (760, 760), gpu=True)
    try:
        t0 = time.time()
        title = None
        while time.time() - t0 < WAIT:
            time.sleep(1)
            title = pg.ev('document.title')
            if title in ('DONE', 'ERR'):
                break
        print('title=%s base=%s ship=%s grp=%s' % (title, BASE, SHIP, GRP))
        if title != 'DONE':
            print(pg.ev("(function(){var e=document.getElementById('log');"
                        "return e?e.textContent:'(no log)';})()"))
            return 1
        names = json.loads(pg.ev('window.__names()'))
        raw = pg.ev('(async function(){return await window.__scan();})()')
        data = json.loads(raw)
        for g, r in data.items():
            print('-- %s dur=%s durSrc=%s frames=%s total=%s never=%s always=%s partial=%s'
                  % (g, r.get('dur'), r.get('durSrc'), r.get('frames'), r.get('total'),
                     r.get('neverSeen'), r.get('alwaysSeen'), r.get('partial')))
            cls = r.get('cls') or ''
            for i in IDX:
                if i < len(cls):
                    hit = [x for x in (r.get('flickerList') or []) if x and x[0] == names[i]]
                    print('   #%d %-22s cls=%s  flicker=%s tailOff=%s'
                          % (i, names[i] if i < len(names) else '?', cls[i],
                             hit[0][1:] if hit else 'none',
                             [x[1:] for x in (r.get('tailOffList') or []) if x and x[0] == names[i]]))
                    tr = (r.get('trace') or {}).get(str(i)) or []
                    if tr:
                        vs = [t.split('|')[0] for t in tr]
                        ops = [float(t.split('|')[1]) for t in tr]
                        pc = [(t.split('|')[2] if len(t.split('|')) > 2 else '') for t in tr]
                        flips = [j for j in range(1, len(vs)) if vs[j] != vs[j - 1]]
                        print('        trace: vis=%d/%d  flips=%s' % (vs.count('1'), len(vs), flips[:20]))
                        # 值级 RLE：(vis, opacity) 连续相同段压缩，避免只看 ±2 帧邻域就下结论
                        # ——窄于 1/FPS 的峰在低 fps 下会被压成单帧，邻域看不到上升/下降沿。
                        runs, s0 = [], 0
                        for j in range(1, len(ops) + 1):
                            if j == len(ops) or vs[j] != vs[s0] or abs(ops[j] - ops[s0]) > 1e-4:
                                runs.append((s0, j - 1, vs[s0], ops[s0]))
                                s0 = j
                        print('        rle: %d runs' % len(runs))
                        for a, b, v, o in runs:
                            if not (a == 0 and b == len(ops) - 1):
                                print('          [%4d-%4d] vis=%s op=%.4f  (t=%.3f~%.3f)'
                                      % (a, b, v, o, (a + 1) / float(FPS), (b + 1) / float(FPS)))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
