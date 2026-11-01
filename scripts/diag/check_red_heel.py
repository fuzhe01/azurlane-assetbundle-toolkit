"""验证「红底高跟鞋」在两边是否都出现：多帧 + 颜色采样。

用户观察：旧画廊 ougen_8 idle 里左脚穿红底高跟鞋可见，新画廊看不到。
上一轮多帧对比显示两站渲染差异 ≈ 呼吸本底（1.1x），疑似只是时序。
但「鞋在不在」是**结构性事实**，不该被呼吸相位影响 —— 所以要专门验：
在画面里找**红色低饱和区域**（红底高跟鞋的鞋底是红色），看两边多帧里是否都出现。

用法: py -3 scripts/diag/check_red_heel.py ougen_8 idle
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402
from PIL import Image, ImageStat, ImageFilter  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
CLIP = sys.argv[2] if len(sys.argv) > 2 else 'idle'
OUT = os.path.join(ROOT, '.diag', 'redheel')
os.makedirs(OUT, exist_ok=True)

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9380),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9381)]


def red_pixels(path):
    """统计查看器区域里的「红色」像素：R 明显高于 G/B 且不太暗。
    红底高跟鞋的鞋底是纯红，与画面其余部分（黑/白/棕）区分度高。"""
    im = Image.open(path).convert('RGB')
    w, h = im.size
    im = im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))
    px = im.load()
    W, H = im.size
    n = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]
            if r > 110 and r - g > 60 and r - b > 60:
                n += 1
    return n


def run(tag, url, port):
    pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_rh%d' % port), url, (1400, 1000))
    shots = []
    try:
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(10)
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value=%s; if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(CLIP), json.dumps(CLIP)))
        time.sleep(6)
        for i in range(4):
            p = os.path.join(OUT, '%s_%s_f%d.png' % (CLIP, tag, i))
            pg.shot(p)
            shots.append(p)
            time.sleep(2.0)
        return shots
    finally:
        pg.close()


def main():
    for tag, url, _ in SITES:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                if r.status != 200:
                    print('[INVALID] %s' % tag); return 2
        except Exception as e:  # noqa: BLE001
            print('[INVALID] %s: %s' % (tag, e)); return 2

    res = {}
    for tag, url, port in SITES:
        shots = run(tag, url, port)
        vals = [red_pixels(p) for p in shots]
        res[tag] = vals
        print('%-4s 红色像素数（4 帧）: %s' % (tag, vals))

    o, n = res['old'], res['new']
    print('\n=== 判读 ===')
    print('  旧最大 %d / 新最大 %d' % (max(o), max(n)))
    if max(n) == 0 and max(o) > 0:
        print('  → 只有一个画廊出现红色区域（结构性差异）')
    elif max(o) > 0 and max(n) > 0:
        print('  → 两边都出现红色区域')
    else:
        print('  → 两边都没有明显红色区域（可能鞋底未朝向镜头 / 颜色不够饱和）')
    return 0


if __name__ == '__main__':
    sys.exit(main())