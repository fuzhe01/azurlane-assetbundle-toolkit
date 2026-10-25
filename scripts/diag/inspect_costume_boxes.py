# -*- coding: utf-8 -*-
"""只读：打印 __costumeBoxes() 的真实字段结构（用于修正 healthcheck_costume.py）。"""
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
    if(proto.__dshHookFX) return;
    proto.__dshHookFX=true;
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

CARD = """(function(){
  var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key===%s;});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;});
  if(c) c.click(); return 1;})()"""

SKIN = """(function(){
  var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
    return e.dataset.k===%s;}); if(d) d.click(); return 1;})()"""

TAB = """(function(){
  var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
    return e.dataset.k==='live2d';});
  if(t&&!t.classList.contains('dis')) t.click(); return 1;})()"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1

    pg = open_page(URL, tag='fld')
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
        print('热区数:', len(boxes))
        print('\n第一个热区的完整字段:')
        print(json.dumps(boxes[0], ensure_ascii=False, indent=2))
        print('\n全部热区（只列 id 与关键数值字段）:')
        for b in boxes:
            keys = list(b.keys())
            brief = {k: b[k] for k in keys
                     if isinstance(b[k], (int, float, str, bool)) or b[k] is None}
            print('  ', json.dumps(brief, ensure_ascii=False))

        # screenOf 探测
        print('\n--- __costumeScreenOf ---')
        for pid in ('ShoseOff', 'Stock1', 'Cloth1', 'Paramring'):
            r = pg.ev("""(function(){try{
              var p=window.__costumeScreenOf(%s);
              if(!p) return JSON.stringify({id:%s, pt:null});
              var h=window.__costumeHit(p[0],p[1]);
              return JSON.stringify({id:%s, pt:p, hit:h?h.id:null});
            }catch(e){return JSON.stringify({id:%s, err:String(e)});}})()"""
                      % (json.dumps(pid), json.dumps(pid), json.dumps(pid), json.dumps(pid)))
            print('  ', r)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
