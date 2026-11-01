# -*- coding: utf-8 -*-
"""run_bare_page.py — 打开一个放在 Output/gallery_v2 下的裸诊断页，等它跑到 title=DONE，打印 __RESULT。

用途：把「核心库层面的最小实验」从页面逻辑里摘出来跑。
⚠️ 注意端口：8778 的 docroot 是 D:\\azur，8777 的 docroot 是 D:\\Azur Lane Assets\\Output。
   放在 D:\\azur\\Output\\gallery_v2 下的页面只能走 8778（走 8777 会 404）。

用法: py -3 scripts/diag/run_bare_page.py <相对URL路径> [--wait=120]
"""
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

ARGV = [a for a in sys.argv[1:] if not a.startswith('--')]
REL = ARGV[0] if ARGV else '/gallery_v2/_bare_moc3.html'
WAIT = 180
# --gpu：走真实 GPU 而非 SwiftShader。凡判据涉及「可见性 / 像素」必须加，
# 否则软件渲染与真 GPU 的 isVisible 判定差异会造出假绿灯（TROUBLESHOOTING §137）。
GPU = '--gpu' in sys.argv
for a in sys.argv[1:]:
    if a.startswith('--wait='):
        WAIT = float(a.split('=', 1)[1])

URL = 'http://127.0.0.1:8778' + REL


def main():
    # ⚠️ 每次用新的 profile 目录：复用固定目录时，若上次的 msedge 进程没退干净，
    # `Page.__init__` 会报 "no CDP tab"（新实例被旧实例接管，看着像脚本坏了）。
    prof = os.path.join(ROOT, '.diag', 'chrome_bp%d' % int(time.time() * 1000 % 1000000))
    port = 9499 + int(time.time()) % 60
    pg = Page(port, prof, URL, (900, 900), gpu=GPU)
    try:
        t0 = time.time()
        title = None
        while time.time() - t0 < WAIT:
            time.sleep(1)
            title = pg.ev("document.title")
            if title in ('DONE', 'ERR'):
                break
        print('title=%s  用时=%.1fs  GPU=%s' % (title, time.time() - t0, '真GPU' if GPU else 'SwiftShader'))
        print('renderer=%s' % pg.ev("""
        (function(){try{var c=document.createElement('canvas');
          var gl=c.getContext('webgl')||c.getContext('experimental-webgl');
          if(!gl) return 'NO_WEBGL';
          var d=gl.getExtension('WEBGL_debug_renderer_info');
          return d? gl.getParameter(d.UNMASKED_RENDERER_WEBGL):'unknown';}catch(e){return 'ERR:'+e;}})()
        """))
        log = pg.ev("(function(){var e=document.getElementById('log');"
                    "return e?e.textContent:'(无 #log)';})()")
        if log:
            print('----- #log -----')
            print(log)
        r = pg.ev("window.__RESULT")
        if r:
            print('----- __RESULT -----')
            print(r)
        return 0 if title == 'DONE' else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
