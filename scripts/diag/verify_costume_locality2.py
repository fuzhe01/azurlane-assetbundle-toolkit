"""局部性验证（修正版）：用 effect 冻结 + 走 beforeModelUpdate 写参数。

上一版两处错误（2026-10-24）：
  ① 误以为需要自己造冻结 —— 项目里 **effect 动作就是冻结语义**（FALLBACK_FIX 里
     `effect:'__hold__'` = 播完停在最后一帧，不回落），直接播 effect 即可冻结。
  ② 直接调 core.setParameterValueByIndex 会被每帧的 loadParameters 覆盖
     （实测读回全是 SET:0.000）。正确路径是**挂到 internalModel 的 beforeModelUpdate**
     ——项目里 stateApply 就是这么做的，注释写明「帧末 loadParameters 会把参数拉回
     motion 末态，但下一帧事件里会再写，渲染永远读到状态值」。

做法：播 effect 冻结 → 逐参数设为 hi/lo（每次都挂新的 beforeModelUpdate 覆盖值）→
      截图算差异面占比。本底用「同一参数同一值连拍两张」对照。

用法: py -3 scripts/diag/verify_costume_locality2.py ougen_8
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
PORT = 9462
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'costume_locality3')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCL3) return; proto.__dshHookCL3=true;
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

# 设置「钉住」某参数：挂一个 beforeModelUpdate 监听，每次都把该参数写回目标值。
# 这样绕开 loadParameters 的覆盖（项目 stateApply 用的就是这个钩子）。
SET_PIN = r"""
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
  window.__pinVal=[%s, %s];
  try{ core.setParameterValueById(%s, %s); }catch(e){}
  return 'PINNED:'+String(window.__pinVal);
})()
"""


def crop_view(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    return im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))


def diff_px(a, b):
    w = min(a.size[0], b.size[0]); h = min(a.size[1], b.size[1])
    d = ImageChops.difference(a.crop((0, 0, w, h)), b.crop((0, 0, w, h))).convert('L')
    hist = d.histogram()
    tot = sum(hist)
    big = sum(hist[25:])
    return big, (big * 100.0 / tot if tot else 0.0)


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    table = json.load(open(os.path.join(ROOT, '.diag', 'costume_scan', 'costume_by_range.json'),
                           encoding='utf-8'))
    cands = table.get(KEY, {})
    if not cands:
        print('[FAIL] 无候选表'); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_cl3%d' % PORT), URL, (1400, 1000))
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

        # 用 effect 冻结（项目语义：effect = '__hold__'，播完停末帧）
        r = pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(!s) return 'NO_SEL';
                   if(![...s.options].some(function(o){return o.value==='effect';})) return 'NO_EFFECT';
                   s.value='effect';
                   if(window.__l2play){ window.__l2play('effect'); return 'PLAYED'; }
                   return 'NO_HOOK';})()""")
        print('播 effect 冻结:', r)
        time.sleep(6)

        # 冻结有效性：同状态连拍两张
        p0 = os.path.join(OUT, '_b0.png'); pg.shot(p0)
        time.sleep(2.0)
        p1 = os.path.join(OUT, '_b1.png'); pg.shot(p1)
        n0, r0 = diff_px(crop_view(p0), crop_view(p1))
        print('effect 冻结后本底: %d px = %.3f%%' % (n0, r0))

        rows = []
        for pid, info in sorted(cands.items()):
            lo, hi = info['lo'], info['hi']

            # 钉到 hi
            rh = pg.ev(SET_PIN % (json.dumps(pid), hi, json.dumps(pid), hi))
            time.sleep(1.2)
            ph = os.path.join(OUT, '%s_hi.png' % pid); pg.shot(ph)

            # 钉到 lo
            rl = pg.ev(SET_PIN % (json.dumps(pid), lo, json.dumps(pid), lo))
            time.sleep(1.2)
            pl = os.path.join(OUT, '%s_lo.png' % pid); pg.shot(pl)

            n, ratio = diff_px(crop_view(ph), crop_view(pl))
            if ratio < max(r0 * 3, 0.2):
                verdict = '几乎无变化'
            elif ratio < 3.0:
                verdict = '局部开关'
            else:
                verdict = '影响面大(疑姿势)'
            rows.append((pid, info['label'], ratio, verdict))
            print('%-16s %-8s 差异 %6.2f%%  %-16s' % (pid, info['label'], ratio, verdict))

        print('\n=== 汇总（本底 %.3f%%）===' % r0)
        ok = [r for r in rows if r[3] == '局部开关']
        print('局部开关: %d / %d' % (len(ok), len(rows)))
        for pid, lb, ratio, v in sorted(rows, key=lambda x: x[2]):
            print('  %-16s %-8s %6.2f%%  %s' % (pid, lb, ratio, v))
        json.dump([{'id': r[0], 'label': r[1], 'ratio': r[2], 'verdict': r[3]} for r in rows],
                  open(os.path.join(OUT, 'locality.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())