"""确认点击是否真的命中 touchdrag17：在页面里记录 onUp 的判定结果。

之前点完 35 个参数变了但画面没变——那 35 个大概只是 idle 呼吸的正常漂移，
并不能证明点击命中了判定区。本脚本在页面内拦截 hitAt，打印每次点击的判定名。

用法: py -3 scripts/diag/verify_click_hit.py ougen_8
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
OUT = os.path.join(ROOT, '.diag', 'clickhit')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCH) return; proto.__dshHookCH=true;
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
  // 记录页面上所有 pointer/click 事件，确认点击进得来
  window.__evts=[];
  ['pointerdown','pointerup','click'].forEach(function(t){
    window.addEventListener(t, function(e){
      window.__evts.push([t, Math.round(e.clientX), Math.round(e.clientY)]);
    }, true);
  });
})();
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='ch')
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

        # 取判定区可取的全部 hit 名（页面自己算的）
        info = pg.ev("""
        (function(){
          var out={};
          try{ out.hitUse = window.__L2_HITUSE ? window.__L2_HITUSE() : null; }catch(e){ out.err1=String(e); }
          try{ out.allNames = JSON.parse(JSON.stringify(
                 (window.__l2model.internalModel.hitAreas||{}))); }catch(e){ out.err2=String(e); }
          return JSON.stringify(out);
        })()
        """)
        print('页面 hitAreas:', info[:600])

        # 统计可用区数量
        try:
            d = json.loads(info)
            hu = d.get('hitUse') or []
            print('\n可用判定区 %d 个: %s' % (len(hu), hu[:20]))
        except Exception:  # noqa: BLE001
            pass

        # 取 touchdrag17 drawable 的屏幕坐标并点击
        c = pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return 'NO_MODEL';
          var core=m.internalModel.coreModel, im=m.internalModel;
          var ix=core.getDrawableIndex('TouchDrag17');
          if(ix<0) return 'NO_DRAWABLE';
          var v=core.getDrawableVertexPositions(ix);
          var xs=[],ys=[];
          for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
          var cx=(Math.min.apply(null,xs)+Math.max.apply(null,xs))/2;
          var cy=(Math.min.apply(null,ys)+Math.max.apply(null,ys))/2;
          var ppu=im.pixelsPerUnit||1;
          var p=m.toGlobal(new PIXI.Point(cx*ppu, cy*ppu));
          var wrap=document.getElementById('l2wrap').getBoundingClientRect();
          var sc=(m.scale&&m.scale.x)||1;
          return JSON.stringify({drawableLocal:[+cx.toFixed(1),+cy.toFixed(1)],
            global:[+p.x.toFixed(1),+p.y.toFixed(1)], scale:+sc.toFixed(4),
            wrap:[+wrap.left.toFixed(0),+wrap.top.toFixed(0)]});
        })()
        """)
        print('\ntouchdrag17 坐标:', c)
        cd = json.loads(c)
        sx = cd['wrap'][0] + cd['global'][0] * cd['scale']
        sy = cd['wrap'][1] + cd['global'][1] * cd['scale']
        print('点击点: (%.0f, %.0f)' % (sx, sy))

        before = pg.ev("window.__evts && window.__evts.length")
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent',
                   {'type': typ, 'x': int(sx), 'y': int(sy), 'button': 'left',
                    'clickCount': 1, 'buttons': 1})
            time.sleep(0.1)
        time.sleep(1.5)

        evts = pg.ev("JSON.stringify(window.__evts||[])")
        print('\n页面收到的输入事件:', evts)

        # 再直接问页面：这个点命中什么
        hit = pg.ev("""
        (function(){
          try{
            var m=window.__l2model;
            var r=document.getElementById('l2wrap').getBoundingClientRect();
            var lp=m.toLocal(new PIXI.Point(%d - r.left, %d - r.top));
            var im=m.internalModel, ppu=im.pixelsPerUnit||1;
            var res=window.__L2_HIT ? window.__L2_HIT(lp.x/ppu, lp.y/ppu) : null;
            var all=window.__L2_HITALL ? window.__L2_HITALL(lp.x/ppu, lp.y/ppu) : null;
            return JSON.stringify({single:res, all:all});
          }catch(e){ return 'ERR:'+String(e); }
        })()
        """ % (sx, sy))
        print('该点命中的判定区:', hit)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())