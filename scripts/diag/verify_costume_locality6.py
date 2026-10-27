"""局部性验证 v6：暂停态 + beforeModelUpdate 钉值 + 手动重绘。

v5 失败的根因：setParameterValueByIndex 后再调 im.update()，
update 内部会 loadParameters(motion) 把参数拉回动作值 → 读回全 0。
项目 stateApply 的注释早已写明这一点（「帧末 loadParameters 会把参数拉回 motion 末态，
但下一帧事件里会再写，渲染永远读到状态值」）。

v6 做法：
  1. 挂 beforeModelUpdate 监听，在该时机写参数（motion 已算完、渲染尚未发生）
  2. 手动调 im.update() 触发一次该事件链 → 参数在渲染前被覆写为钉值
  3. app.render() 出帧 → 截图

用法: py -3 scripts/diag/verify_costume_locality6.py ougen_8
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
PORT = 9468
URL = 'http://127.0.0.1:8778/gallery_v2/index.html?pause'
OUT = os.path.join(ROOT, '.diag', 'locality_v6')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookV6) return; proto.__dshHookV6=true;
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

# 在 beforeModelUpdate 里写参数（唯一能生效的时机），然后手动推进一帧并重绘
PIN_REDRAW = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var im=m.internalModel, core=im.coreModel;
  if(!window.__pinHooked){
    window.__pinHooked=true;
    window.__pinVal=null;
    window.__pinApplied=null;
    try{
      im.on('beforeModelUpdate', function(){
        if(!window.__pinVal) return;
        try{
          for(var k in window.__pinVal){
            core.setParameterValueById(k, window.__pinVal[k]);
          }
          window.__pinApplied = core.getParameterValueById(Object.keys(window.__pinVal)[0]);
        }catch(e){}
      });
    }catch(e){ return 'HOOK_FAIL'; }
  }
  window.__pinVal=%s;
  // 用页面的 __step 推进几帧（内部会停住并手动 render），确保新参数真的落到 canvas
  var done=false;
  try{
    if(window.__step){
      window.__step(4).then(function(){ done=true; });
    }else{ done=true; }
  }catch(e){ done=true; }
  return 'PIN:'+(window.__pinApplied!==null? Number(window.__pinApplied).toFixed(3) : 'null');
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

    base_url = URL.split('?')[0]
    try:
        with urllib.request.urlopen(base_url, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_v6%d' % PORT), URL, (1400, 1000))
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

        print('暂停态:', pg.ev("String(window.__paused)"))

        # 本底：同参同值两次
        r0a = pg.ev(PIN_REDRAW % json.dumps({'Param494': 0}))
        time.sleep(0.6)
        p0 = os.path.join(OUT, '_b0.png'); pg.shot(p0)
        r0b = pg.ev(PIN_REDRAW % json.dumps({'Param494': 0}))
        time.sleep(0.6)
        p1 = os.path.join(OUT, '_b1.png'); pg.shot(p1)
        n0, r0 = dp(crop(p0), crop(p1))
        print('对称本底: %d px = %.3f%%  (%s / %s)' % (n0, r0, r0a, r0b))

        rows = []
        for pid, info in sorted(cands.items()):
            lo, hi = info['lo'], info['hi']
            rh = pg.ev(PIN_REDRAW % json.dumps({pid: hi}))
            time.sleep(0.6)
            ph = os.path.join(OUT, '%s_hi.png' % pid); pg.shot(ph)
            rl = pg.ev(PIN_REDRAW % json.dumps({pid: lo}))
            time.sleep(0.6)
            pl = os.path.join(OUT, '%s_lo.png' % pid); pg.shot(pl)
            n, ratio = dp(crop(ph), crop(pl))
            if ratio < max(r0 * 4, 0.3):
                verdict = '几乎无变化'
            elif ratio < 3.0:
                verdict = '局部开关'
            else:
                verdict = '影响面大(疑姿势)'
            rows.append((pid, info['label'], ratio, verdict))
            print('%-16s %-8s %6.2f%%  %-18s hi=%s lo=%s'
                  % (pid, info['label'], ratio, verdict, rh, rl))

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