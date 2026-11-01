"""用页面自算的判定区屏幕坐标（__L2_SCREENOF）点击 touchdrag17。

这样坐标来自页面自己的 localHit，不存在换算口径漂移。

用法: py -3 scripts/diag/click_td17_v4.py ougen_8 touchdrag17
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

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
TARGET = (sys.argv[2] if len(sys.argv) > 2 else 'touchdrag17').lower()
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'td17v4')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookT4) return; proto.__dshHookT4=true;
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


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='t4')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(13)

        r = pg.ev("JSON.stringify(window.__L2_SCREENOF? window.__L2_SCREENOF(%s): 'NO_FN')"
                  % json.dumps(TARGET))
        print('页面自算坐标:', r)
        if not r or r == 'null' or 'NO_FN' in str(r):
            print('[FAIL] 拿不到坐标'); return 2
        d = json.loads(r)
        px, py = d['cx'], d['cy']
        print('命中点 (%d,%d)，覆盖 %d 个采样点，box=%s' % (px, py, d['n'], d['box']))

        # 确认这个点确实命中目标
        chk = pg.ev("(function(){var e=document.getElementById('l2wrap').getBoundingClientRect();"
                    "return 'wrap='+[e.left,e.top,e.width,e.height].join(',');})()")
        print('画布区域:', chk)

        pg.shot(os.path.join(OUT, '0_before.png'))
        before_par = pg.ev("JSON.stringify({shose:0})")

        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent',
                   {'type': typ, 'x': px, 'y': py,
                    'button': 'left', 'buttons': 1, 'clickCount': 1})
            time.sleep(0.12)
        print('已点击 (%d,%d)' % (px, py))

        for i, w in enumerate((0.3, 0.9, 1.6, 3.0)):
            time.sleep(w)
            p = os.path.join(OUT, '%d_after.png' % (i + 1))
            pg.shot(p)
            lbl = pg.ev("(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()")
            print('  +%.1fs 标签=%s -> %s' % (w, lbl, os.path.basename(p)))
        print('\n截图: .diag/td17v4/')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())