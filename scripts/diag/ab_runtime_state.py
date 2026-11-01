"""数据完全相同、画面却不同：锁定运行时差异。

已确认资产 4/4 逐字节相同、idle 末帧 582 个参数值 0 差异，
但旧画廊能看到红底高跟鞋、我们的看不到。
=> 差异只可能来自运行时：模型缩放/位置、physics 是否跑、遮罩、渲染顺序。

本脚本对两个站点各取同一组运行时测量值做对照。

用法: py -3 scripts/diag/ab_runtime_state.py ougen_8 idle
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

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
CLIP = sys.argv[2] if len(sys.argv) > 2 else 'idle'
OUT = os.path.join(ROOT, '.diag', 'runtime_ab')
os.makedirs(OUT, exist_ok=True)

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9350),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9351)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookRT) return; proto.__dshHookRT=true;
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

MEASURE = r"""
(function(){
  var m=window.__l2model; if(!m) return JSON.stringify({err:'NO_MODEL'});
  var im=m.internalModel, core=im.coreModel;
  var out={};
  out.modelScale = m.scale? [ +m.scale.x.toFixed(4), +m.scale.y.toFixed(4) ] : null;
  out.modelPos = [ +m.x.toFixed(2), +m.y.toFixed(2) ];
  out.ppu = im.pixelsPerUnit || null;
  out.imWH = [ im.width, im.height ];
  out.drawables = core.getDrawableCount();
  out.parts = (function(){ try{ return core.getPartCount(); }catch(e){ return null; } })();
  // 脚部/鞋子相关 drawable 的实际顶点与不透明度
  var footInfo=[];
  for(var i=0;i<out.drawables;i++){
    var op=null; try{ op=+core.getDrawableOpacity(i).toFixed(3); }catch(e){}
    var v=null; try{ v=core.getDrawableVertexPositions(i); }catch(e){}
    if(!v || !v.length) continue;
    var xs=[],ys=[];
    for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
    var bx=[Math.min.apply(null,xs),Math.min.apply(null,ys),
            Math.max.apply(null,xs),Math.max.apply(null,ys)];
    // 只记录"下半身"位置的 drawable（y 靠下 + 有一定面积）
    var h = bx[3]-bx[1], w = bx[2]-bx[0];
    if(h>20 && w>20 && bx[1] > 0.3*(im.height||1)){
      footInfo.push([i, op, [Math.round(bx[0]),Math.round(bx[1]),Math.round(bx[2]),Math.round(bx[3])]]);
    }
  }
  out.lowerBody = footInfo.slice(0,40);
  out.lowerBodyN = footInfo.length;
  out.visibleDrawables = (function(){
    var n=0; for(var i=0;i<out.drawables;i++){ try{ if(core.getDrawableOpacity(i)>0.02) n++; }catch(e){} }
    return n;
  })();
  return JSON.stringify(out);
})()
"""


def run(tag, url, port):
    pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_rt%s' % port), url, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': url})
        time.sleep(4)
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
                   if(s) s.value=%s;
                   if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(CLIP), json.dumps(CLIP)))
        time.sleep(6)
        pg.shot(os.path.join(OUT, '%s_%s.png' % (CLIP, tag)))
        return json.loads(pg.ev(MEASURE))
    finally:
        pg.close()


def main():
    for tag, url, _ in SITES:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                if r.status != 200:
                    print('[INVALID] %s HTTP %s' % (tag, r.status)); return 2
        except Exception as e:  # noqa: BLE001
            print('[INVALID] %s 不可达: %s' % (tag, e)); return 2

    res = {}
    for tag, url, port in SITES:
        res[tag] = run(tag, url, port)
    o, n = res['old'], res['new']
    if 'err' in o or 'err' in n:
        print('[INVALID] old=%s new=%s' % (o.get('err'), n.get('err'))); return 2

    for k in ('modelScale', 'modelPos', 'ppu', 'imWH', 'drawables', 'parts',
              'lowerBodyN', 'visibleDrawables'):
        print('%-18s 旧 %-24s 新 %s' % (k, o.get(k), n.get(k)))

    print('\n=== 下半身 drawable 逐项对比（index, opacity, bbox）===')
    om = {x[0]: x for x in o.get('lowerBody', [])}
    nm = {x[0]: x for x in n.get('lowerBody', [])}
    keys = sorted(set(om) | set(nm))
    differ = 0
    for i in keys:
        a, b = om.get(i), nm.get(i)
        if a and b:
            if abs((a[1] or 0) - (b[1] or 0)) > 0.02 or a[2] != b[2]:
                differ += 1
                print('  #%-4d 旧 op=%-6s bbox=%-22s  新 op=%-6s bbox=%s'
                      % (i, a[1], a[2], b[1], b[2]))
        else:
            differ += 1
            print('  #%-4d 单边存在: 旧=%s 新=%s' % (i, bool(a), bool(b)))
    print('\n下半身差异项: %d / %d' % (differ, len(keys)))
    return 0


if __name__ == '__main__':
    sys.exit(main())