"""按页面的 hitAreas 结构定位 touchdrag17 并点它。

关键认知修正（2026-10-24）：`TouchDrag17` 是 **moc3 里的 hitArea 名**，
不是 drawable 名（drawable 叫 ArtMesh4 之类）。页面的 hitAreas 是
{moc3名: {Id, Name}} 结构，其中 Id 才是 drawable 名。

正确做法：从页面 hitAreas 里按名找 touchdrag17 → 取它的 Id → 用 Id 查 drawable → 算坐标。
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
OUT = os.path.join(ROOT, '.diag', 'hitclick2')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookHC2) return; proto.__dshHookHC2=true;
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

LOCATE = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel;
  var want=%s;
  var hits=im.hitAreas||{};
  var entry=null, key=null;
  // 键有两种写法：hitAreas 里是 touch_drag17；补区列表里是 touchdrag17（无下划线）
  var norm=function(x){ return String(x||'').toLowerCase().replace(/_/g,''); };
  var wantN=norm(want);
  for(var k in hits){
    if(norm(k)===wantN){ entry=hits[k]; key=k; break; }
  }
  if(!entry) return JSON.stringify({err:'NO_HITAREA', keys:Object.keys(hits).slice(0,15)});
  // entry.Id 才是 drawable 名
  var did=entry.Id||entry.id;
  var ix=core.getDrawableIndex(did);
  if(ix<0) return JSON.stringify({err:'NO_DRAWABLE_FOR_ID', key:key, id:did, name:entry.Name});
  var v=core.getDrawableVertexPositions(ix);
  if(!v||!v.length) return JSON.stringify({err:'NO_VERTS', key:key, id:did});
  var xs=[],ys=[];
  for(var q=0;q+1<v.length;q+=2){ xs.push(v[q]); ys.push(v[q+1]); }
  var Vx=(Math.min.apply(null,xs)+Math.max.apply(null,xs))/2;
  var Vy=(Math.min.apply(null,ys)+Math.max.apply(null,ys))/2;
  var cux=im.width, cuy=im.height, ppu=im.pixelsPerUnit||1;
  var lpx=(Vx + cux/2)*ppu, lpy=(cuy/2 - Vy)*ppu;
  var g=m.toGlobal(new PIXI.Point(lpx, lpy));
  var view=(m.parent&&m.parent.view)? m.parent.view : document.querySelector('#l2wrap canvas');
  var rc=view? view.getBoundingClientRect()
              : document.getElementById('l2wrap').getBoundingClientRect();
  return JSON.stringify({
    key:key, drawableId:did, actionName:entry.Name,
    canvasCoord:[+Vx.toFixed(2), +Vy.toFixed(2)],
    stageGlobal:[+g.x.toFixed(1), +g.y.toFixed(1)],
    canvasRect:[+rc.left.toFixed(1), +rc.top.toFixed(1), +rc.width.toFixed(1), +rc.height.toFixed(1)],
    bboxCanvas:[Math.round(Math.min.apply(null,xs)), Math.round(Math.min.apply(null,ys)),
                Math.round(Math.max.apply(null,xs)), Math.round(Math.max.apply(null,ys))]
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

    pg = open_page(URL, tag='hc2')
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

        c = pg.ev(LOCATE % json.dumps(TARGET))
        print('定位:', c)
        d = json.loads(c)
        if 'err' in d:
            print('[FAIL]', d); return 2

        px = d['canvasRect'][0] + d['stageGlobal'][0]
        py = d['canvasRect'][1] + d['stageGlobal'][1]
        print('点击点: (%.0f, %.0f)' % (px, py))

        chk = pg.ev("""
        (function(){
          var m=window.__l2model, im=m.internalModel;
          var rc=(m.parent&&m.parent.view? m.parent.view: document.querySelector('#l2wrap canvas')).getBoundingClientRect();
          var lp=m.toLocal(new PIXI.Point(%.1f - rc.left, %.1f - rc.top));
          var ppu=im.pixelsPerUnit||1, cux=im.width, cuy=im.height;
          var P={x: lp.x/ppu - cux/2, y: cuy/2 - lp.y/ppu};
          return JSON.stringify({hit: window.__L2_HIT? window.__L2_HIT(P.x,P.y): null,
                                 all: window.__L2_HITALL? window.__L2_HITALL(P.x,P.y): null});
        })()
        """ % (px, py))
        print('预检命中:', chk)

        pg.shot(os.path.join(OUT, '0_before.png'))
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent',
                   {'type': typ, 'x': int(px), 'y': int(py),
                    'button': 'left', 'buttons': 1, 'clickCount': 1})
            time.sleep(0.12)
        time.sleep(0.4)
        pg.shot(os.path.join(OUT, '1_after.png'))
        time.sleep(1.5)
        pg.shot(os.path.join(OUT, '2_after15.png'))
        print('\n动作标签:', pg.ev("(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()"))
        print('截图: .diag/hitclick2/')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())