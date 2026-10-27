"""用 __L2_HITINFO 精确定位 touchdrag17，真实点击，观察脚部三态。

用户目视证据：该区点击后有脱鞋动画（黑丝左脚 / 红底高跟鞋 / 无脚）。
本脚本用页面自己暴露的判定区明细（含画布坐标）算出屏幕点，
走真实 pointerdown→hitAt 路径点击，并连续截图记录状态变化。

用法: py -3 scripts/diag/click_td17_v2.py ougen_8 touchdrag17
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
OUT = os.path.join(ROOT, '.diag', 'td17v2')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookT2) return; proto.__dshHookT2=true;
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


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='t2')
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

        # 用页面暴露的明细找目标
        info = pg.ev("""
        (function(){
          var list=window.__L2_HITINFO? window.__L2_HITINFO(): [];
          var want=%s;
          var hit=list.find(function(h){ return String(h.name).toLowerCase().replace(/_/g,'')===want; });
          return JSON.stringify({want:want, found: !!hit, item: hit,
                                 total: list.length,
                                 names: list.map(function(h){return h.name;}).slice(-12)});
        })()
        """ % json.dumps(TARGET.replace('_', '')))
        print('定位:', info)
        d = json.loads(info)
        if not d.get('found'):
            print('[FAIL] 未找到', TARGET); return 2

        item = d['item']
        g = item['canvas']
        print('该区画布包围盒:', g)

        # 画布坐标 → 屏幕坐标（用画布 bbox 中心 + 页面同款变换）
        pt = pg.ev("""
        (function(){
          var m=window.__l2model, im=m.internalModel;
          var cux=im.width, cuy=im.height, ppu=im.pixelsPerUnit||1;
          var Vx=%s, Vy=%s;
          var lpx=(Vx + cux/2)*ppu, lpy=(cuy/2 - Vy)*ppu;
          var gp=m.toGlobal(new PIXI.Point(lpx, lpy));
          var view=(m.parent&&m.parent.view)? m.parent.view : document.querySelector('#l2wrap canvas');
          var rc=view.getBoundingClientRect();
          return JSON.stringify({x: rc.left+gp.x, y: rc.top+gp.y,
                                 rect:[rc.left,rc.top,rc.width,rc.height],
                                 global:[gp.x,gp.y]});
        })()
        """ % (g['cx'], g['cy']))
        print('屏幕坐标:', pt)
        pd = json.loads(pt)
        px, py = pd['x'], pd['y']

        # 预检：这个点命中什么
        chk = pg.ev("""
        (function(){
          var m=window.__l2model, im=m.internalModel;
          var view=(m.parent&&m.parent.view)? m.parent.view : document.querySelector('#l2wrap canvas');
          var rc=view.getBoundingClientRect();
          var lp=m.toLocal(new PIXI.Point(%.1f - rc.left, %.1f - rc.top));
          var ppu=im.pixelsPerUnit||1, cux=im.width, cuy=im.height;
          var P={x: lp.x/ppu - cux/2, y: cuy/2 - lp.y/ppu};
          return JSON.stringify({hit: window.__L2_HIT? window.__L2_HIT(P.x,P.y): null,
                                 all: window.__L2_HITALL? window.__L2_HITALL(P.x,P.y): null});
        })()
        """ % (px, py))
        print('预检命中:', chk)

        pg.shot(os.path.join(OUT, '0_before.png'))
        before = pg.ev("(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()")
        print('点击前标签:', before)

        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent',
                   {'type': typ, 'x': int(px), 'y': int(py),
                    'button': 'left', 'buttons': 1, 'clickCount': 1})
            time.sleep(0.12)
        print('已点击')
        for i, w in enumerate((0.3, 0.8, 1.5, 3.0)):
            time.sleep(w)
            p = os.path.join(OUT, '%d_after.png' % (i + 1))
            pg.shot(p)
            lbl = pg.ev("(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()")
            print('  +%.1fs 标签=%s -> %s' % (w, lbl, os.path.basename(p)))
        print('\n截图: .diag/td17v2/')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())