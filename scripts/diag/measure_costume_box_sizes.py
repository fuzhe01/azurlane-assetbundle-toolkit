# -*- coding: utf-8 -*-
"""量出每个热区的真实 w/h，确定退化的判定阈值（只读）。"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import ensure_servers  # noqa: E402
from cdp_helper import open_page  # noqa: E402

KEY = 'ougen_8'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookWB) return;
    proto.__dshHookWB=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c&&c.internalModel&&c.internalModel.coreModel){
          if(c.destroyed!==true) window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
})();
"""

CARD = """(function(){var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key===%s;});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
    return e.dataset.k===%s;}); if(d) d.click(); return 1;})()"""
TAB = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
    return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1

    pg = open_page(URL, tag='wb')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              "if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        time.sleep(0.9)
        pg.ev(CARD % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev(SKIN % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev(TAB)
        time.sleep(15)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        boxes = json.loads(pg.ev("JSON.stringify(window.__costumeBoxes())"))
        print('\n=== 8 个热区的真实尺寸（V 空间）===')
        print('  %-12s %-8s %4s %9s %9s %9s %10s'
              % ('id', 'label', 'n', 'w', 'h', 'area', 'w*h校验'))
        rows = []
        for b in boxes:
            bx = b['box']
            w = bx['x1'] - bx['x0']
            h = bx['y1'] - bx['y0']
            rows.append((b['id'], b.get('label'), b.get('n'), w, h, b.get('area')))
            print('  %-12s %-8s %4s %9.3f %9.3f %9.3f %10.4f'
                  % (b['id'], b.get('label'), b.get('n'), w, h, b.get('area', 0), w * h))

        print('\n=== 尺寸排序（小 → 大）===')
        for r in sorted(rows, key=lambda x: x[3] * x[4]):
            mid = min(r[3], r[4])
            print('  %-12s min(w,h)=%8.4f  面积=%9.4f  %s'
                  % (r[0], mid, r[3] * r[4],
                     '← 退化，应排除' if mid < 1.0 else ''))

        print('\n=== 当前阈值 1e-3 的判定结果 ===')
        for r in rows:
            pass_cur = (r[3] > 1e-3) and (r[4] > 1e-3)
            print('  %-12s w>1e-3=%s  h>1e-3=%s  → 当前%s参与竞争'
                  % (r[0], r[3] > 1e-3, r[4] > 1e-3, '会' if pass_cur else '不'))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
