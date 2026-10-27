"""用「非循环动作停末帧」冻结，再测 ShoseOff。

为什么之前的冻结法不对（2026-10-24 修正）：
  - `effect` 是 `Loop=False`，播完停末帧——但停在 effect 自己的姿态上，
    那个姿态下鞋本来就不在可见位置，所以测不出 ShoseOff 的效果（0.19%）。
  - `idle` 是 `Loop=True`（8s 循环），画面永远在动，两帧截图本底 6.9%。

正确做法：播一个**非循环**、且**姿态接近 idle** 的动作，等它停末帧后再测。
`touch_head` / `touch_body` 这类通常是 Loop=False 且姿态接近待机。

本脚本先列出候选的 Loop=False 动作及时长，再用它冻结测 ShoseOff。

用法: py -3 scripts/diag/probe_shoseoff2.py ougen_8
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
PORT = 9464
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'shoseoff2')
os.makedirs(OUT, exist_ok=True)
MD = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSO2) return; proto.__dshHookSO2=true;
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
      try{ for(var k in window.__pinVal) core.setParameterValueById(k, window.__pinVal[k]); }catch(e){}
    };
    try{ im.on('beforeModelUpdate', window.__pinHook); }catch(e){ return 'NO_EVENT'; }
  }
  window.__pinVal=%s;
  try{ for(var k in window.__pinVal) core.setParameterValueById(k, window.__pinVal[k]); }catch(e){}
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


def list_nonloop():
    out = []
    for f in sorted(os.listdir(MD)):
        if not f.endswith('.motion3.json'):
            continue
        d = json.load(open(os.path.join(MD, f), encoding='utf-8'))
        m = d.get('Meta', {})
        if m.get('Loop') is False:
            out.append((f[:-len('.motion3.json')], m.get('Duration')))
    return out


def main():
    print('=== Loop=False 的候选（可停末帧冻结）===')
    nl = list_nonloop()
    for nm, dur in nl:
        print('  %-16s dur=%s' % (nm, dur))
    # 挑姿态最接近 idle 的：touch_head / touch_body / mail
    frozen = None
    for want in ('touch_head', 'touch_body', 'mail', 'touch_special'):
        if any(nm == want for nm, _ in nl):
            frozen = want
            break
    if not frozen:
        frozen = nl[0][0] if nl else 'touch_head'
    print('\n选用冻结动作:', frozen)

    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_so2%d' % PORT), URL, (1400, 1000))
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

        # 播冻结动作（该动作为 Loop=False，播完停末帧）
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value=%s;
                   if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(frozen), json.dumps(frozen)))
        print('已播 %s，等待停末帧...' % frozen)
        time.sleep(10)

        # 冻结有效性
        p0 = os.path.join(OUT, '_b0.png'); pg.shot(p0)
        time.sleep(2.0)
        p1 = os.path.join(OUT, '_b1.png'); pg.shot(p1)
        n0, r0 = dp(crop(p0), crop(p1))
        print('本底: %d px = %.3f%% %s' % (n0, r0, '（已冻结）' if r0 < 0.5 else '（仍有动画）'))

        # ShoseOff 三个值
        shots = {}
        for v in (-1, 0, 1):
            pg.ev(PIN % json.dumps({'ShoseOff': v}))
            time.sleep(1.5)
            p = os.path.join(OUT, 'shose_%s.png' % ('m1' if v == -1 else str(v)))
            pg.shot(p)
            shots[v] = p
        print('\nShoseOff -1 vs 1 : %d px = %.2f%%' % dp(crop(shots[-1]), crop(shots[1])))
        print('ShoseOff -1 vs 0 : %d px = %.2f%%' % dp(crop(shots[-1]), crop(shots[0])))
        print('ShoseOff  0 vs 1 : %d px = %.2f%%' % dp(crop(shots[0]), crop(shots[1])))
        print('\n截图在 .diag/shoseoff2/')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())