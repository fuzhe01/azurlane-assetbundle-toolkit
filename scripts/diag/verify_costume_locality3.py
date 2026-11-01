"""局部性验证（最终版）：先暂停前端回落，再用非循环动作停末帧冻结。

三轮踩坑记录（别重犯）：
  第一轮：直接 setParameterValueByIndex → 读回全 0，被每帧 loadParameters 覆盖。
  第二轮：改 mdl.autoUpdate=false → 画面不动了，但 effect 姿态下鞋不在可见位置，
          ShoseOff 测出 0.19%，判不出效果。
  第三轮：用 touch_head（Loop=False）停末帧 → 我上一轮加的**定时回落**把画面拉回 idle，
          本底 60%，完全测不了。

本轮做法：把「回落定时器」临时停掉（clearTimeout + 拦 setTimeout），
          于是 touch_head 播完就真的停在末帧，且姿态接近 idle，能测出换装效果。

用法: py -3 scripts/diag/verify_costume_locality3.py ougen_8
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
PORT = 9465
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'locality_final')
os.makedirs(OUT, exist_ok=True)
MD = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookLF) return; proto.__dshHookLF=true;
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
  // 拦掉回落定时器：测参影响面期间不能让画面被拉回 idle
  window.__noFallback=false;
  var _st=window.setTimeout;
  window.setTimeout=function(fn, ms){
    if(window.__noFallback && ms >= 1000) return -1;   // 只拦长延时（回落用的），短延时保留
    return _st.apply(this, arguments);
  };
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


def pick_freeze_clip():
    """挑 Loop=False、时长较长、姿态接近 idle 的动作。"""
    for want in ('mail', 'touch_special', 'touch_body', 'touch_head'):
        p = os.path.join(MD, want + '.motion3.json')
        if os.path.exists(p):
            m = json.load(open(p, encoding='utf-8')).get('Meta', {})
            if m.get('Loop') is False:
                return want
    return None


def main():
    freeze = pick_freeze_clip()
    if not freeze:
        print('[FAIL] 找不到 Loop=False 的冻结动作'); return 2
    print('冻结动作:', freeze)

    table = json.load(open(os.path.join(ROOT, '.diag', 'costume_scan', 'costume_by_range.json'),
                           encoding='utf-8'))
    cands = table.get(KEY, {})
    if not cands:
        print('[FAIL] 无候选表'); return 2

    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_lf%d' % PORT), URL, (1400, 1000))
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

        # 关掉回落，再播冻结动作
        print('关闭回落:', pg.ev("window.__noFallback=true; 1"))
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value=%s;
                   if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(freeze), json.dumps(freeze)))
        print('已播 %s，等 12s 停末帧...' % freeze)
        time.sleep(12)

        p0 = os.path.join(OUT, '_b0.png'); pg.shot(p0)
        time.sleep(2.5)
        p1 = os.path.join(OUT, '_b1.png'); pg.shot(p1)
        n0, r0 = dp(crop(p0), crop(p1))
        print('本底: %d px = %.3f%% %s' % (n0, r0, '（冻结成功）' if r0 < 1.0 else '（仍在动，判据可能不可靠）'))

        rows = []
        for pid, info in sorted(cands.items()):
            lo, hi = info['lo'], info['hi']
            pg.ev(PIN % json.dumps({pid: hi}))
            time.sleep(1.5)
            ph = os.path.join(OUT, '%s_hi.png' % pid); pg.shot(ph)
            pg.ev(PIN % json.dumps({pid: lo}))
            time.sleep(1.5)
            pl = os.path.join(OUT, '%s_lo.png' % pid); pg.shot(pl)
            n, ratio = dp(crop(ph), crop(pl))
            if ratio < max(r0 * 3, 0.2):
                verdict = '几乎无变化'
            elif ratio < 3.0:
                verdict = '局部开关'
            else:
                verdict = '影响面大(疑姿势)'
            rows.append((pid, info['label'], ratio, verdict))
            print('%-16s %-8s %6.2f%%  %s' % (pid, info['label'], ratio, verdict))

        print('\n=== 汇总（本底 %.3f%%）===' % r0)
        ok = [r for r in rows if r[3] == '局部开关']
        print('局部开关: %d / %d' % (len(ok), len(rows)))
        json.dump([{'id': r[0], 'label': r[1], 'ratio': round(r[2], 3), 'verdict': r[3]} for r in rows],
                  open(os.path.join(OUT, 'locality.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())