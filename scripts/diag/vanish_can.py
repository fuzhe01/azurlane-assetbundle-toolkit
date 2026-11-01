# -*- coding: utf-8 -*-
"""vanish_can.py — 动作播放期间逐帧扫描可见件（运行时 isVisible 判据）。

用途：验证「部件在动作中消失」这类缺陷。与截图差分互补——截图分不清
「没画」与「画成纯黑」，本工具直接读 Cubism Core 的 dynamicFlags 第 0 位。

前置：8765 端口须有 docroot=D:\\azur 的静态服务器（run_bare_page.py 走 8778）。
页面：`Output/gallery_v2/_vanishcan.html`。正本在本目录 `vanish_can_page.html`（入库），
启动时 `ensure_page()` 会按 md5 比对并自动同步 —— 不需要手工 copy，也不会出现
「改了正本忘了部署」。`Output/` 被 .gitignore 整体忽略，所以运行副本不入库。

⚠️ 页面换版后旧扫描全部作废，必须校验两项：`durSrc != 'fallback5'`（真实时长取自
`motion.getLoopDuration()` 或 JSON `Meta.Duration`，而不是兜底的 5 秒）与
`frames/FPS ≈ dur`。`dur=5 / frames=152` 是「只扫了前 5 秒」的指纹，长动作会被误判
「无部件消失」（详见 `docs/TROUBLESHOOTING.md` §151）。

用法:
  py -3 scripts/diag/vanish_can.py [--base=../../Live2D] [--ship=ougen_8]
        [--grp=mail,mission] [--fps=30] [--gpu] [--wait=300]

--base 是相对 gallery_v2 的模型根，用来在 A/B 实验组目录间切换：
  生产      ../../Live2D
  E 组      ../_ab/E
  F 组      ../_ab/F
  官方参考  ../_ab/official
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


PAGE_SRC = os.path.join(HERE, 'vanish_can_page.html')
PAGE_DST = os.path.join(ROOT, 'Output', 'gallery_v2', '_vanishcan.html')


def ensure_page():
    """把入库的页面正本同步到运行目录（按 md5 判，幂等）。

    此前页面只存在于 Output/（被 .gitignore 忽略），换个 worktree 或清盘就静默丢失，
    于是拿到的是旧扫描器产出的假绿灯。现在正本入库，由这里负责部署。
    """
    if not os.path.isfile(PAGE_SRC):
        raise SystemExit('页面正本缺失: %s' % PAGE_SRC)
    a = open(PAGE_SRC, 'rb').read()
    if os.path.isfile(PAGE_DST) and open(PAGE_DST, 'rb').read() == a:
        return
    os.makedirs(os.path.dirname(PAGE_DST), exist_ok=True)
    with open(PAGE_DST, 'wb') as f:
        f.write(a)
    print('→ 已部署页面正本 → Output/gallery_v2/_vanishcan.html')


def check_scan_valid(data):
    """扫描有效性闸门：durSrc 与 frames 自洽。

    `durSrc == 'fallback5'` 意味着页面拿不到真实动作时长、只扫了前 5 秒，
    长动作的消失会被截断成「没消失」。这条曾产出过一轮假绿灯（详见
    docs/TROUBLESHOOTING.md §151）。
    """
    bad = []
    for grp, r in (data or {}).items():
        if r.get('durSrc') == 'fallback5':
            bad.append('%s: durSrc=fallback5（假时长）' % grp)
            continue
        dur, frames, fps = r.get('dur'), r.get('frames'), float(FPS)
        if not dur or not frames:
            bad.append('%s: dur/frames 缺失' % grp)
            continue
        if abs(frames / fps - dur) > max(0.05, dur * 0.02):
            bad.append('%s: frames/FPS=%.3f 与 dur=%.3f 不自洽'
                       % (grp, frames / fps, dur))
    return bad


BASE = arg('base', '../../Live2D')
SHIP = arg('ship', 'ougen_8')
GRP = arg('grp', 'mail')
FPS = arg('fps', '30')
GPU = bool(arg('gpu', False))
WAIT = float(arg('wait', 300))
PORT = arg('port', '8778')

URL = ('http://127.0.0.1:%s/gallery_v2/_vanishcan.html?base=%s&ship=%s&grp=%s&fps=%s'
       % (PORT, BASE, SHIP, GRP, FPS))


def main():
    ensure_page()
    prof = os.path.join(ROOT, '.diag', 'chrome_vc%d' % int(time.time() * 1000 % 1000000))
    port = 9699 + int(time.time()) % 60
    pg = Page(port, prof, URL, (760, 760), gpu=GPU)
    try:
        t0 = time.time()
        title = None
        while time.time() - t0 < WAIT:
            time.sleep(1)
            title = pg.ev("document.title")
            if title in ('DONE', 'ERR'):
                break
        print('title=%s  GPU=%s  base=%s  grp=%s'
              % (title, '真GPU' if GPU else 'SwiftShader', BASE, GRP))
        log = pg.ev("(function(){var e=document.getElementById('log');"
                    "return e?e.textContent:'(无 #log)';})()")
        if log:
            print('log: %s' % log)
        if title != 'DONE':
            return 1
        raw = pg.ev("(async function(){ return await window.__scan(); })()")
        if isinstance(raw, str) and raw.startswith('{'):
            data = json.loads(raw)
            print(json.dumps(data, ensure_ascii=False, indent=1))
        else:
            print('!! 未取到结果: %r' % (raw,))
            return 1
        bad = check_scan_valid(data)
        if bad:
            print('!! 扫描无效（结果不可用于判缺陷）:')
            for b in bad:
                print('   - %s' % b)
            return 2
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
