"""严谨对比「红底高跟鞋」：两画廊同一动作的脚部区域逐像素统计。

用户 2026-10-24 反馈：换回旧版运行时库后**鞋子没有恢复**。
这推翻了「补丁版库是根因」的判断，说明我上次靠截图下结论太草率。

本脚本只做一件事：把两画廊各自 idle 的**脚部区域**裁出来，
统计「红色像素数」与「该区域像素哈希」，用数字说话，不靠肉眼。
同时把裁好的区域放大存盘，供双方目视核对。

用法: py -3 scripts/diag/cmp_shoe_pixels.py
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

import cdp_helper  # noqa: E402
from cdp_helper import open_page  # noqa: E402
from PIL import Image  # noqa: E402

OUT = os.path.join(ROOT, '.diag', 'shoe_cmp2')
os.makedirs(OUT, exist_ok=True)

SITES = [('old', 8777), ('new', 8778)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookS2) return; proto.__dshHookS2=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""


def red_count(img):
    px = img.load()
    W, H = img.size
    n = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]
            if r > 100 and r - g > 55 and r - b > 55:
                n += 1
    return n


def crop_foot(path):
    """裁脚部区域：画面左下偏中。用固定比例，两个画廊一致。"""
    im = Image.open(path).convert('RGB')
    w, h = im.size
    # 查看器区域: x 42%~99%, y 10%~92%
    vx0, vx1 = int(w * .42), int(w * .99)
    vy0, vy1 = int(h * .10), int(h * .92)
    vw, vh = vx1 - vx0, vy1 - vy0
    # 脚在查看器内: 水平 10%~55%, 垂直 45%~95%
    box = (vx0 + int(vw * .10), vy0 + int(vh * .45),
           vx0 + int(vw * .55), vy0 + int(vh * .95))
    return im.crop(box)


def run(tag, port):
    url = 'http://127.0.0.1:%d/gallery_v2/index.html' % port
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            if r.status != 200:
                return None, 'HTTP %d' % r.status
    except Exception as e:  # noqa: BLE001
        return None, str(e)

    pg = open_page(url, tag='s2' + tag)
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': url})
        time.sleep(6)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var cards=[...document.querySelectorAll('.card')];
          var c=cards.find(function(e){ var t=e.textContent||''; return t.indexOf('欧根亲王')>=0; });
          if(!c) return 'NO_CARD'; c.click(); return 1;})()
        """)
        time.sleep(2.5)
        pg.ev("""(function(){var rows=[...document.querySelectorAll('#mSkins .skin')];
          var d=rows.find(function(e){return e.dataset.k==='ougen_8';});
          if(!d) return 'NO_ROW'; d.click(); return 1;})()
        """)
        time.sleep(1.5)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';});
          if(!t) return 'NO_TAB'; if(t.classList.contains('dis')) return 'DIS';
          t.click(); return 1;})()
        """)
        time.sleep(15)

        if pg.ev("typeof window.__l2model") != 'object':
            pg.shot(os.path.join(OUT, '%s_notready.png' % tag))
            return None, '模型未就绪'

        # 播 idle，等稳定
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
          if(s) s.value='idle';
          if(window.__l2play) window.__l2play('idle'); return 1;})()""")
        time.sleep(4)

        p = os.path.join(OUT, '%s_idle.png' % tag)
        pg.shot(p)
        return p, None
    finally:
        pg.close()


def main():
    res = {}
    for tag, port in SITES:
        p, err = run(tag, port)
        if err:
            print('%-4s FAIL: %s' % (tag, err)); continue
        im = crop_foot(p)
        full = Image.open(p)
        res[tag] = (p, im, full.size)
        print('%-4s 截图 %s 尺寸%s 脚部区域%s 红像素 %d'
              % (tag, os.path.basename(p), full.size, im.size, red_count(im)))

    if 'old' in res and 'new' in res:
        print('\n=== 对照 ===')
        po, io_, _ = res['old']
        pn, inn, _ = res['new']
        ro, rn = red_count(io_), red_count(inn)
        print('红像素: 旧 %d / 新 %d   差 %+d' % (ro, rn, rn - ro))
        # 存放大图
        for tag, im in (('old', io_), ('new', inn)):
            z = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
            z.save(os.path.join(OUT, 'foot_%s_zoom.png' % tag))
        print('放大图: .diag/shoe_cmp2/foot_old_zoom.png / foot_new_zoom.png')
    return 0


if __name__ == '__main__':
    sys.exit(main())