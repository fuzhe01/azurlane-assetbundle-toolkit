"""A/B：EMIT_CONST 产物 vs 仅 streamed 产物，看「鞋是否可见」。

用法: py -3 scripts/diag/ab_shot_one.py <输出tag>
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402
from PIL import Image  # noqa: E402

TAG = sys.argv[1] if len(sys.argv) > 1 else 'shot'
PORT = 9420
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'const_vs_streamed')
os.makedirs(OUT, exist_ok=True)


def red_px(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    im = im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))
    px = im.load(); W, H = im.size; n = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]
            if r > 110 and r - g > 60 and r - b > 60:
                n += 1
    return n


def main():
    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_abo%d' % PORT), URL, (1400, 1000))
    try:
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key==='ougen_8';});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """)
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k==='ougen_8';}); if(d) d.click(); return 1;})()""")
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(12)
        p = os.path.join(OUT, '%s.png' % TAG)
        pg.shot(p)
        print('%s 红像素 %d -> %s' % (TAG, red_px(p), p))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())