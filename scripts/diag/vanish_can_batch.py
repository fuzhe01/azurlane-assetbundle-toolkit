# -*- coding: utf-8 -*-
"""vanish_can_batch.py — 批量扫描可见件（一次浏览器会话跑完整个 AB 矩阵）。

为什么需要独立于 vanish_can.py：vanish_can.py 每次调用都新起一个 headless 浏览器
（约 3s 启动开销 + 每次产一个 chrome profile 目录）。整个矩阵 3 组 × 5 模型 = 15 次
调用时要 45s+ 且留下 15 个 profile。本工具只起一次浏览器，用 Page.navigate 在
各 (base, ship) 之间切换，单组扫描约 0.3s。

⚠️ 2026-10-25 关键教训：`_vanishcan.html` 在 17:47 之前用 `defs[bi].duration` 取
clip 时长，而 model3.json 的 Motions 条目**没有 duration 字段** ⇒ 恒为 undefined
⇒ 静默回退 5 秒。5 个模型 6 个组的真实时长是 4.8~25.0 秒，**此前全部扫描只覆盖了
每个动作的前 5.07 秒**。修好后 durSrc 应为 `motion`（来自 getLoopDuration），
若看到 `fallback5` 说明页面又被改回去了，必须停下查。

用法:
  py -3 scripts/diag/vanish_can_batch.py --jobs=../_ab/E:ougen_8,../_ab/official:ougen_8 \
        --grp=mail,mission,home,touch_head,touch_body,idle --tag=E_ougen_8
  py -3 scripts/diag/vanish_can_batch.py --matrix --tag=off   # 预置矩阵：全部 base × 5 模型
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

MODELS = ['aersasi_2', 'aersasi_3', 'antu_2', 'benningdun_2', 'ougen_8']
GRPS = 'mail,mission,home,touch_head,touch_body,idle'
BASES = ['../_ab/E', '../_ab/official', '../../Live2D']


def arg(name, default=None):
    for a in sys.argv[1:]:
        if a == '--' + name:
            return True
        if a.startswith('--' + name + '='):
            return a.split('=', 1)[1]
    return default


GRP = arg('grp', GRPS)
FPS = arg('fps', '30')
GPU = bool(arg('gpu', False))
WAIT = float(arg('wait', 240))
PORT_ARG = arg('port', '8778')
TAG = arg('tag', 'batch')
OUTDIR = arg('outdir', os.path.join(ROOT, '.diag', 'vc'))
EXTRA = arg('extra', '')          # 透传给页面的额外 query（如 nophys=1）
MATRIX = bool(arg('matrix', False))


def parse_jobs():
    if MATRIX:
        return [(b, m) for b in BASES for m in MODELS]
    s = arg('jobs', '')
    if not s:
        raise SystemExit('需要 --jobs=base:ship[,base:ship...] 或 --matrix')
    out = []
    for item in s.split(','):
        b, m = item.split(':', 1)
        out.append((b, m))
    return out


def main():
    jobs = parse_jobs()
    prof = os.path.join(ROOT, '.diag', 'chrome_vcb%d' % (int(time.time() * 1000) % 100000))
    url = ('http://127.0.0.1:%s/gallery_v2/_vanishcan.html?base=%s&ship=%s&grp=%s&fps=%s%s'
           % (PORT_ARG, jobs[0][0], jobs[0][1], GRP, FPS, ('&' + EXTRA) if EXTRA else ''))
    pg = Page(9699 + int(time.time()) % 60, prof, url, (760, 760), gpu=GPU)
    ok = bad = 0
    try:
        for base, ship in jobs:
            u = ('http://127.0.0.1:%s/gallery_v2/_vanishcan.html?base=%s&ship=%s&grp=%s&fps=%s%s'
                 % (PORT_ARG, base, ship, GRP, FPS, ('&' + EXTRA) if EXTRA else ''))
            pg.cmd('Page.navigate', {'url': u})
            t0 = time.time()
            title = None
            while time.time() - t0 < WAIT:
                time.sleep(0.4)
                title = pg.ev('document.title')
                if title in ('DONE', 'ERR'):
                    break
            if title != 'DONE':
                print('!! %s %s title=%s' % (base, ship, title))
                bad += 1
                continue
            raw = pg.ev('(async function(){ return await window.__scan(); })()')
            if not (isinstance(raw, str) and raw.startswith('{')):
                print('!! %s %s 未取到结果: %r' % (base, ship, raw))
                bad += 1
                continue
            data = json.loads(raw)
            # 时长来源自检：fallback5 说明页面取不到真实 clip 时长，扫描窗口是错的
            srcs = sorted({v.get('durSrc', '?') for v in data.values()})
            if 'fallback5' in srcs:
                print('!! %s %s durSrc=%s ⇒ 扫描窗口回退成 5s，结果不可用'
                      % (base, ship, srcs))
                bad += 1
                continue
            name = '%s_%s.txt' % (TAG, ship) if TAG else '%s.txt' % ship
            os.makedirs(OUTDIR, exist_ok=True)
            path = os.path.join(OUTDIR, name)
            hdr = ('title=DONE  GPU=%s  base=%s  grp=%s\n' % ('真GPU' if GPU else 'SwiftShader', base, GRP))
            with open(path, 'w', encoding='utf-8') as f:
                f.write(hdr)
                f.write(json.dumps(data, ensure_ascii=False, indent=1))
            durs = ['%s=%.3fs/%d' % (g, v['dur'], v['frames']) for g, v in data.items()]
            print('OK %-16s %-13s -> %s  %s' % (base, ship, os.path.basename(path), ' '.join(durs)))
            ok += 1
    finally:
        pg.close()
    print('完成 ok=%d bad=%d' % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
