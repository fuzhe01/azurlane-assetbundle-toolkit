"""正确计算判定区的屏幕坐标并点击（修正之前的坐标换算错误）。

之前的错误：把 `m.toGlobal(PIXI.Point(cx*ppu, cy*ppu))` 的结果当成 stage 坐标去乘 scale，
算出 (266,59)，实际命中的却是 touch_body —— 换算链路完全错了。

页面的真实链路（gallery_src/index.html L2216 + L1762）：
    lp = mdl.toLocal(PIXI.Point(clientX - wrap.left, clientY - wrap.top))
    P  = {x: lp.x/ppu - cux/2,  y: cuy/2 - lp.y/ppu}
其中 cux/cuy 是 internalModel 的画布宽高（width/height）。
所以要反推：给定 drawable 的画布坐标 (Vx, Vy)，
    lp.x = (Vx + cux/2) * ppu
    lp.y = (cuy/2 - Vy) * ppu
再 toGlobal 得到 stage 坐标，加上 canvas 的实际绘制偏移，即为 client 坐标。

更稳的做法：直接调 mdl.toGlobal，再与 canvas 的 getBoundingClientRect 对齐。

用法: py -3 scripts/diag/click_hit_correct.py ougen_8 touchdrag17
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
TARGET = sys.argv[2] if len(sys.argv) > 2 else 'touchdrag17'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'hitclick')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookHC) return; proto.__dshHookHC=true;
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
  window.__clicks=[];
  document.addEventListener('click', function(e){
    window.__clicks.push([Math.round(e.clientX), Math.round(e.clientY), e.target.tagName||'']);
  }, true);
})();
"""

# 用页面自己的坐标链路反推 client 坐标
COORD = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel;
  var want=%s;
  var ix=core.getDrawableIndex(want);
  if(ix<0){
    // 退化：遍历 drawable ids 找名字（getDrawableIds 可能只在 _model 上）
    var ids=null;
    try{ ids=core.getDrawableIds? core.getDrawableIds(): null; }catch(e){}
    if(!ids){ try{ ids=core._model&&core._model.drawables&&core._model.drawables.ids; }catch(e){} }
    if(ids){
      for(var q=0;q<ids.length;q++){ if(String(ids[q])===String(want)){ ix=q; break; } }
    }
    if(ix<0) return JSON.stringify({err:'NO_DRAWABLE', tried:want,
      sample:(ids? Array.prototype.slice.call(ids,0,10):null), n:(ids?ids.length:null)});
  }
  var v=core.getDrawableVertexPositions(ix);
  if(!v||!v.length) return JSON.stringify({err:'NO_VERTS'});
  var xs=[],ys=[];
  for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
  var Vx=(Math.min.apply(null,xs)+Math.max.apply(null,xs))/2;
  var Vy=(Math.min.apply(null,ys)+Math.max.apply(null,ys))/2;
  var cux=im.width, cuy=im.height, ppu=im.pixelsPerUnit||1;
  // 正变换（页面 localHit 的逆）
  var lpx=(Vx + cux/2)*ppu;
  var lpy=(cuy/2 - Vy)*ppu;
  var g=m.toGlobal(new PIXI.Point(lpx, lpy));
  // stage→屏幕：PIXI 的 canvas 在 document 里的位置
  var view=m.parent && m.parent.view ? m.parent.view : (window.app && window.app.view);
  var rc=view? view.getBoundingClientRect() : document.getElementById('l2wrap').getBoundingClientRect();
  return JSON.stringify({
    drawable: want,
    canvasCoord:[+Vx.toFixed(2), +Vy.toFixed(2)],
    localPx:[+lpx.toFixed(1), +lpy.toFixed(1)],
    stageGlobal:[+g.x.toFixed(1), +g.y.toFixed(1)],
    canvasRect:[+rc.left.toFixed(1), +rc.top.toFixed(1), +rc.width.toFixed(1), +rc.height.toFixed(1)],
    hint:'client = canvasRect.left + stageGlobal.x'
  });
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='hc')
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

        c = pg.ev(COORD % json.dumps(TARGET))
        print('坐标推算:', c)
        d = json.loads(c)
        if 'err' in d:
            print('[FAIL]', d['err']); return 2

        px = d['canvasRect'][0] + d['stageGlobal'][0]
        py = d['canvasRect'][1] + d['stageGlobal'][1]
        print('点击点: (%.0f, %.0f)' % (px, py))

        # 先用页面自己的 __L2_HIT 校验这个点命中什么
        chk = pg.ev("""
        (function(){
          var m=window.__l2model, im=m.internalModel, core=im.coreModel;
          var rc=(m.parent&&m.parent.view? m.parent.view: document.getElementById('l2wrap')).getBoundingClientRect();
          var lp=m.toLocal(new PIXI.Point(%.1f - rc.left, %.1f - rc.top));
          var ppu=im.pixelsPerUnit||1;
          var cux=im.width, cuy=im.height;
          var P={x: lp.x/ppu - cux/2, y: cuy/2 - lp.y/ppu};
          var one=window.__L2_HIT? window.__L2_HIT(P.x, P.y): null;
          var all=window.__L2_HITALL? window.__L2_HITALL(P.x, P.y): null;
          return JSON.stringify({P:[+P.x.toFixed(2),+P.y.toFixed(2)], hit:one, all:all});
        })()
        """ % (px, py))
        print('预检命中:', chk)

        before_shot = os.path.join(OUT, '0_before.png')
        pg.shot(before_shot)

        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent',
                   {'type': typ, 'x': int(px), 'y': int(py),
                    'button': 'left', 'buttons': 1, 'clickCount': 1})
            time.sleep(0.12)
        time.sleep(0.5)
        pg.shot(os.path.join(OUT, '1_after_05s.png'))
        time.sleep(1.0)
        pg.shot(os.path.join(OUT, '2_after_15s.png'))
        time.sleep(2.0)
        pg.shot(os.path.join(OUT, '3_after_35s.png'))

        print('\n页面收到的 click:', pg.ev("JSON.stringify(window.__clicks||[])"))
        print('当前动作标签:', pg.ev("(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()"))
        print('\n截图: .diag/hitclick/')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())