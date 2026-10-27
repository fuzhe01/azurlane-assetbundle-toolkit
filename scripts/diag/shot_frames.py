# -*- coding: utf-8 -*-
"""shot_frames.py — 打开裸页，确定性步进到指定帧并逐帧 CDP 截图存盘（供人眼审查）。

为什么需要这个工具：本轮前几次失败全在「自动判据测错对象」——
  * 「静息 >200px² 才算主体」把手掌/脚结构性排除；
  * bbox 面积不等于可见像素，对遮挡/遮罩/UV 全盲；
  * 不透明黑底无法区分「没画」与「画成黑色」。
所以改为把帧画出来（绿底，故「没画」=绿、「画成黑」=黑，可分），交人眼判定。

用法:
  py -3 scripts/diag/shot_frames.py '/gallery_v2/_mailshot.html?grp=mail' --frames=0,6,12,18,24,30 --tag=mail --gpu
参数:
  --frames=a,b,c   要截的帧号（逗号分隔）
  --tag=NAME       文件名前缀，存到 .diag/frames/
  --gpu            走真实 GPU（判据涉及像素时必须加）
  --wait=SEC       页面就绪等待上限
"""
import os
import sys
import time
import base64

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

OUTDIR = os.path.join(ROOT, '.diag', 'frames')


def argv(name, default=None):
    for a in sys.argv[1:]:
        if a.startswith(name + '='):
            return a.split('=', 1)[1]
    return default


REL = next((a for a in sys.argv[1:] if not a.startswith('--')), '/gallery_v2/_mailshot.html')
FRAMES = [int(x) for x in (argv('--frames', '0,10,20,30,40,50,60') or '').split(',') if x.strip()]
TAG = argv('--tag', 'shot')
GPU = '--gpu' in sys.argv
WAIT = float(argv('--wait', 180))


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    prof = os.path.join(ROOT, '.diag', 'chrome_sf%d' % int(time.time() * 1000 % 1000000))
    port = 9550 + int(time.time()) % 40
    url = 'http://127.0.0.1:8778' + REL
    pg = Page(port, prof, url, (960, 960), gpu=GPU)
    try:
        t0 = time.time()
        title = None
        while time.time() - t0 < WAIT:
            time.sleep(1)
            title = pg.ev('document.title')
            if title in ('DONE', 'ERR'):
                break
        print('title=%s 用时=%.1fs GPU=%s' % (title, time.time() - t0, '真GPU' if GPU else 'SwiftShader'))
        print('renderer=%s' % pg.ev("""
        (function(){try{var c=document.createElement('canvas');
          var gl=c.getContext('webgl')||c.getContext('experimental-webgl');
          if(!gl) return 'NO_WEBGL';
          var d=gl.getExtension('WEBGL_debug_renderer_info');
          return d? gl.getParameter(d.UNMASKED_RENDERER_WEBGL):'unknown';}catch(e){return 'ERR:'+e;}})()
        """))
        print('log=%s' % pg.ev("(function(){var e=document.getElementById('log');"
                               "return e?e.textContent:'(none)';})()"))
        if title != 'DONE':
            return 1
        saved = []
        for f in FRAMES:
            r = pg.ev('String(window.__step(%d))' % f)
            now = pg.ev('String(window.__now())')
            info = pg.ev("String(window.__p(['Param31','ParamAngleX','ParamBodyAngleX']))")
            png = pg.cmd('Page.captureScreenshot', {'format': 'png'})
            data = png.get('data')
            path = os.path.join(OUTDIR, '%s_f%03d.png' % (TAG, f))
            with open(path, 'wb') as fh:
                fh.write(base64.b64decode(data))
            saved.append(path)
            print('  f=%-4s step->%s  %s  %s  -> %s' % (f, r, now, info, os.path.basename(path)))
        print('\n截图目录: %s' % OUTDIR)
        for p in saved:
            print('  ' + p)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
