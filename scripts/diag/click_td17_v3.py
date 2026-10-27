"""用「画布像素 → 屏幕像素」的直接映射定位判定区（不依赖 toGlobal 的中间语义）。

之前的错误：把 `(Vx + cux/2)*ppu` 塞进 toGlobal，得到 138339 这种越界值。
`toGlobal` 内部已经包含 centeringTransform / localTransform，不该再手工加 cux/2。

本脚本改用最稳的路子：**用页面自己的 __L2_HIT 做二分搜索**。
判定区是一小块区域，画布坐标范围已知（bbox 的 x0..x1, y0..y1）。
在画布可见区域内做网格扫描 + 二分，找出「__L2_HIT 返回 touchdrag17」的那些画布点，
再映射回屏幕（映射方式用 __L2_HIT 的可逆性验证：在屏幕点 P 上调用 localHit 应命中同一区）。

映射的可靠做法：直接问页面「哪个屏幕点会命中 touchdrag17」——
即用页面自己的 localHit 逻辑反解：给定屏幕候选点，调用 localHit 得到 name，匹配则命中。

用法: py -3 scripts/diag/click_td17_v3.py ougen_8 touchdrag17
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
TARGET = (sys.argv[2] if len(sys.argv) > 2 else 'touchdrag17').lower().replace('_', '')
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'td17v3')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookT3) return; proto.__dshHookT3=true;
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
  // 暴露「屏幕点 → 命中名」的映射（与页面 onUp 用同一条 localHit 逻辑）
  window.__hitAtClient=function(cx, cy){
    try{
      var m=window.__l2model; if(!m) return null;
      var wrap=document.getElementById('l2wrap');
      var r=wrap.getBoundingClientRect();
      var lp=m.toLocal(new PIXI.Point(cx-r.left, cy-r.top));
      var im=m.internalModel, ppu=im.pixelsPerUnit||1;
      var P={x: lp.x/ppu - im.width/2, y: im.height/2 - lp.y/ppu};
      return window.__L2_HIT? window.__L2_HIT(P.x, P.y) : null;
    }catch(e){ return 'ERR:'+String(e); }
  };
})();
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='t3')
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

        # 在画布可见区域内网格扫描，找命中 TARGET 的屏幕点
        found = pg.ev("""
        (function(){
          var wrap=document.getElementById('l2wrap');
          var r=wrap.getBoundingClientRect();
          var want=%s;
          var step=8, hits=[];
          for(var y=Math.ceil(r.top)+4; y<r.bottom-4; y+=step){
            for(var x=Math.ceil(r.left)+4; x<r.right-4; x+=step){
              var n=window.__hitAtClient(x, y);
              if(n && String(n).toLowerCase().replace(/_/g,'')===want){
                hits.push([x, y]);
                if(hits.length>=40) break;
              }
            }
            if(hits.length>=40) break;
          }
          if(!hits.length) return JSON.stringify({found:false,
            sample:(function(){
              var s=[];
              for(var y=Math.ceil(r.top)+4; y<r.bottom-4 && s.length<8; y+=40){
                for(var x=Math.ceil(r.left)+4; x<r.right-4 && s.length<8; x+=60){
                  s.push([x,y,window.__hitAtClient(x,y)]);
                }
              }
              return s;
            })()});
          var xs=hits.map(function(h){return h[0];}), ys=hits.map(function(h){return h[1];});
          return JSON.stringify({found:true, n:hits.length,
            cx: Math.round(xs.reduce(function(a,b){return a+b;},0)/xs.length),
            cy: Math.round(ys.reduce(function(a,b){return a+b;},0)/ys.length),
            bbox:[Math.min.apply(null,xs), Math.min.apply(null,ys),
                  Math.max.apply(null,xs), Math.max.apply(null,ys)]});
        })()
        """ % json.dumps(TARGET))
        print('扫描结果:', found)
        d = json.loads(found)
        if not d.get('found'):
            print('[FAIL] 画布内没有命中 %s 的点' % TARGET)
            print('  采样:', d.get('sample'))
            return 2

        px, py = d['cx'], d['cy']
        print('命中中心: (%d, %d)  区域 %d 个点, bbox=%s' % (px, py, d['n'], d['bbox']))

        pg.shot(os.path.join(OUT, '0_before.png'))
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent',
                   {'type': typ, 'x': px, 'y': py,
                    'button': 'left', 'buttons': 1, 'clickCount': 1})
            time.sleep(0.12)
        print('已点击 (%d, %d)' % (px, py))
        for i, w in enumerate((0.3, 0.9, 1.6, 3.0)):
            time.sleep(w)
            p = os.path.join(OUT, '%d_after.png' % (i + 1))
            pg.shot(p)
            lbl = pg.ev("(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()")
            print('  +%.1fs 标签=%s -> %s' % (w, lbl, os.path.basename(p)))
        print('\n截图: .diag/td17v3/')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())