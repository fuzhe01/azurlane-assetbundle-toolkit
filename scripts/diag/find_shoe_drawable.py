"""找出「红底高跟鞋」到底由哪些 drawable 画出来，再反查控制它们的参数。

用户目视证据（2026-10-24，用户提供截图）：
  touchdrag17 区域有三种状态——① 无脚  ② 黑丝左脚  ③ 红底高跟鞋
  点一次脱鞋 → 黑丝左脚；再点 → 红底高跟鞋闪现即消失。

已知：ShoseOff 参数切换（0/1/-1）画面**无变化**（已截图确认），所以它不是开关。

本脚本换思路——**从部件反查参数**：
  1. 用页面坐标定位「红底高跟鞋」在画面上的位置（用户截图所示区域）
  2. 在该位置找它对应的 drawable（顶点覆盖该点、且不是背景）
  3. 对每个候选 drawable，逐个扫全部参数，看哪个参数能改变它的 opacity/顶点

用法: py -3 scripts/diag/find_shoe_drawable.py ougen_8
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
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'shoe_drawable')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSD) return; proto.__dshHookSD=true;
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

# 列出 touchdrag17 区附近（画布坐标）覆盖的 drawable
NEAR = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel;
  // 用户截图里高跟鞋的位置 ≈ touchdrag17 的 bbox
  var list=window.__L2_HITINFO? window.__L2_HITINFO(): [];
  var td=list.find(function(h){ return String(h.name).toLowerCase().replace(/_/g,'')==='touchdrag17'; });
  if(!td || !td.canvas) return '{"err":"NO_TD17"}';
  var b=td.canvas, cx=b.cx, cy=b.cy;
  var ids=core._model&&core._model.drawables&&core._model.drawables.ids;
  var n=core.getDrawableCount();
  var out=[];
  for(var i=0;i<n;i++){
    var v=null; try{ v=core.getDrawableVertexPositions(i); }catch(e){}
    if(!v||!v.length) continue;
    var xs=[],ys=[];
    for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
    var x0=Math.min.apply(null,xs), x1=Math.max.apply(null,xs);
    var y0=Math.min.apply(null,ys), y1=Math.max.apply(null,ys);
    // drawable 覆盖 touchdrag17 中心点
    if(cx>=x0 && cx<=x1 && cy>=y0 && cy<=y1){
      var op=null; try{ op=+core.getDrawableOpacity(i).toFixed(3); }catch(e){}
      out.push({idx:i, id:(ids? String(ids[i]): ('#'+i)), op:op,
                box:[Math.round(x0*100)/100, Math.round(y0*100)/100,
                     Math.round(x1*100)/100, Math.round(y1*100)/100]});
    }
  }
  return JSON.stringify({td17:{cx:+cx.toFixed(2), cy:+cy.toFixed(2), box:b}, covering:out});
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='sd')
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

        r = pg.ev(NEAR)
        print('touchdrag17 区域覆盖的 drawable:')
        try:
            d = json.loads(r)
            print('  touchdrag17:', d.get('td17'))
            cov = d.get('covering') or []
            print('  覆盖该点的 drawable 共 %d 个:' % len(cov))
            for c in cov:
                print('    #%-4d %-14s op=%-6s box=%s' % (c['idx'], c['id'], c['op'], c['box']))
        except Exception as e:  # noqa: BLE001
            print('  解析失败', e, r[:200])
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())