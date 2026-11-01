"""局部性验证（最终版 v4）：用页面自带的 ?pause 停住渲染循环再测。

为什么前面三版都失败（记录，别重犯）：
  v1 直接 setParameterValueByIndex → 被每帧 loadParameters 覆盖，读回全 0。
  v2 mdl.autoUpdate=false → effect 姿态下鞋不在可见位置，ShoseOff 测出 0.19%。
  v3 播 Loop=False 动作停末帧 → idle 是 Loop=True 的呼吸循环，本底 6%~44% 淹没判据；
     即使拦了回落定时器，模型自身的呼吸/物理仍在推进。

本版：页面新增 ?pause 开关（app.ticker.stop()），渲染循环**完全停住**；
     改参数后用 __step(3) 推进几帧让写入生效，再停住截图。
     此时本底应为 0，任何差异都是参数本身造成的。

用法: py -3 scripts/diag/verify_costume_locality4.py ougen_8
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
PORT = 9466
URL = 'http://127.0.0.1:8778/gallery_v2/index.html?pause'
OUT = os.path.join(ROOT, '.diag', 'locality_v4')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookV4) return; proto.__dshHookV4=true;
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
    table = json.load(open(os.path.join(ROOT, '.diag', 'costume_scan', 'costume_by_range.json'),
                           encoding='utf-8'))
    cands = table.get(KEY, {})
    if not cands:
        print('[FAIL] 无候选表'); return 2

    try:
        with urllib.request.urlopen(URL.replace('?pause', ''), timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_v4%d' % PORT), URL, (1400, 1000))
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
        time.sleep(12)

        print('页面暂停态:', pg.ev("String(window.__paused)"))

        # 本底：暂停后连拍两张
        p0 = os.path.join(OUT, '_b0.png'); pg.shot(p0)
        time.sleep(2.0)
        p1 = os.path.join(OUT, '_b1.png'); pg.shot(p1)
        n0, r0 = dp(crop(p0), crop(p1))
        print('本底: %d px = %.3f%%' % (n0, r0))
        if r0 > 0.5:
            print('[WARN] 本底偏高，pause 可能未生效')

        rows = []
        for pid, info in sorted(cands.items()):
            lo, hi = info['lo'], info['hi']
            # 钉 hi → 推进几帧 → 停 → 截图
            pg.ev(PIN % json.dumps({pid: hi}))
            pg.ev("window.__step && window.__step(4); 1")
            time.sleep(0.8)
            pg.ev("try{ app = null; }catch(e){}; 1")
            ph = os.path.join(OUT, '%s_hi.png' % pid); pg.shot(ph)

            pg.ev(PIN % json.dumps({pid: lo}))
            pg.ev("window.__step && window.__step(4); 1")
            time.sleep(0.8)
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