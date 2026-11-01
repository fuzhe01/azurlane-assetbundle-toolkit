"""专项验证 ShoseOff：它是「脱鞋」开关，值域 -1..1（非常规 0..1）。

上一轮测 -1 vs 1 只有 0.15% 差异，但 §139 记录 ShoseOff 是 0.64%。
可能原因：
  ① 两个端点都表示"穿着/都在画面内"，真正的切换在 0 ↔ ±1 之间
  ② 冻结在 effect 状态下，鞋本来就不在那个位置

本脚本测 4 个值：-1 / 0 / 1，两两比差异，找出真正的切换点。

用法: py -3 scripts/diag/probe_shoseoff.py ougen_8
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
from PIL import Image, ImageChops  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PORT = 9463
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'shoseoff')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSO) return; proto.__dshHookSO=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel) window.__l2model=c; }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

PIN = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var im=m.internalModel, core=im.coreModel;
  if(!window.__pinHook){
    window.__pinVal=null;
    window.__pinHook=function(){
      if(window.__pinVal===null) return;
      try{ core.setParameterValueById(window.__pinVal[0], window.__pinVal[1]); }catch(e){}
    };
    try{ im.on('beforeModelUpdate', window.__pinHook); }catch(e){ return 'NO_EVENT'; }
  }
  window.__pinVal=['ShoseOff', %s];
  try{ core.setParameterValueById('ShoseOff', %s); }catch(e){}
  return 'PIN';
})()
"""


def crop(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    return im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))


def dp(a, b):
    w = min(a.size[0], b.size[0]); h = min(a.size[1], b.size[1])
    d = ImageChops.difference(a.crop((0, 0, w, h)), b.crop((0, 0, w, h))).convert('L')
    hist = d.histogram(); tot = sum(hist)
    n = sum(hist[25:])
    return n, (n * 100.0 / tot if tot else 0)


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_so%d' % PORT), URL, (1400, 1000))
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
        time.sleep(11)

        # 先看 idle（不冻结）下的 ShoseOff 效果
        shots = {}
        for v in (-1, 0, 1):
            pg.ev(PIN % (v, v))
            time.sleep(1.5)
            p = os.path.join(OUT, 'idle_%s.png' % ('m1' if v == -1 else str(v)))
            pg.shot(p)
            shots[v] = p
        base = dp(crop(shots[-1]), crop(shots[1]))
        print('【idle 不冻结】-1 vs 1 : %d px = %.2f%%' % base)
        print('              -1 vs 0 : %d px = %.2f%%' % dp(crop(shots[-1]), crop(shots[0])))
        print('               0 vs 1 : %d px = %.2f%%' % dp(crop(shots[0]), crop(shots[1])))

        # 再播 effect 冻结后测
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value='effect';
                   if(window.__l2play) window.__l2play('effect'); return 1;})()""")
        time.sleep(6)
        shots2 = {}
        for v in (-1, 0, 1):
            pg.ev(PIN % (v, v))
            time.sleep(1.5)
            p = os.path.join(OUT, 'effect_%s.png' % ('m1' if v == -1 else str(v)))
            pg.shot(p)
            shots2[v] = p
        print('\n【effect 冻结】-1 vs 1 : %d px = %.2f%%' % dp(crop(shots2[-1]), crop(shots2[1])))
        print('              -1 vs 0 : %d px = %.2f%%' % dp(crop(shots2[-1]), crop(shots2[0])))
        print('               0 vs 1 : %d px = %.2f%%' % dp(crop(shots2[0]), crop(shots2[1])))
        print('\n截图在 .diag/shoseoff/ 可直接目视')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())