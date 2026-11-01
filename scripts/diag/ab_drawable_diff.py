"""逐 drawable 找差异：两个画廊在同一动作下，哪个 drawable 的 opacity 或顶点不同。

上一轮 ab_runtime_state 显示 visibleDrawables 旧 313 / 新 312，差 1 个。
本脚本定位那一个，并打印其顶点包围盒（判断它是不是鞋/脚）。

用法: py -3 scripts/diag/ab_drawable_diff.py ougen_8 idle
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

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9360),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9361)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookDD) return; proto.__dshHookDD=true;
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

ALL = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, n=core.getDrawableCount();
  var ids=null; try{ ids=m.internalModel._drawableIds||null; }catch(e){}
  // drawable 名称在 patched.js 里可能通过 getDrawableId 暴露
  var arr=[];
  for(var i=0;i<n;i++){
    var op=null,v=null;
    try{ op=+core.getDrawableOpacity(i).toFixed(3); }catch(e){}
    try{ v=core.getDrawableVertexPositions(i); }catch(e){}
    var bx=null;
    if(v && v.length>=2){
      var xs=[],ys=[];
      for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
      bx=[Math.round(Math.min.apply(null,xs)),Math.round(Math.min.apply(null,ys)),
          Math.round(Math.max.apply(null,xs)),Math.round(Math.max.apply(null,ys))];
    }
    var nm=null;
    try{ nm = core.getDrawableId? core.getDrawableId(i) : null; }catch(e){}
    arr.push([i,op,bx,nm]);
  }
  return JSON.stringify({n:n, d:arr});
})()
"""


def run(tag, url, port):
    pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_dd%d' % port), url, (1400, 1000))
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
                   if(s) s.value=%s; if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(CLIP), json.dumps(CLIP)))
        time.sleep(6)
        return json.loads(pg.ev(ALL))
    finally:
        pg.close()


def main():
    for tag, url, _ in SITES:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                if r.status != 200:
                    print('[INVALID] %s' % tag); return 2
        except Exception as e:  # noqa: BLE001
            print('[INVALID] %s: %s' % (tag, e)); return 2

    o = run(*SITES[0])
    n = run(*SITES[1])
    if 'err' in o or 'err' in n:
        print('[INVALID]', o.get('err'), n.get('err')); return 2
    print('drawable 数: 旧 %d / 新 %d' % (o['n'], n['n']))

    om = {x[0]: x for x in o['d']}
    nm = {x[0]: x for x in n['d']}
    diffs = []
    for i in sorted(set(om) | set(nm)):
        a, b = om.get(i), nm.get(i)
        if not a or not b:
            diffs.append((i, a, b, 'only-one-side')); continue
        da = abs((a[1] or 0) - (b[1] or 0))
        db = 0
        if a[2] and b[2]:
            db = max(abs(a[2][j] - b[2][j]) for j in range(4))
        if da > 0.02 or db > 6:
            diffs.append((i, a, b, 'op_d=%.3f bbox_d=%d' % (da, db)))

    print('有差异的 drawable: %d / %d' % (len(diffs), o['n']))
    print('\n%-6s %-8s %-26s %-8s %-26s %s' % ('idx', '旧op', '旧bbox', '新op', '新bbox', '差异'))
    for i, a, b, why in diffs[:30]:
        print('%-6s %-8s %-26s %-8s %-26s %s'
              % (i,
                 (a[1] if a else '—'), (a[2] if a else '—'),
                 (b[1] if b else '—'), (b[2] if b else '—'), why))
    if len(diffs) > 30:
        print('... 共 %d 项，只显示前 30' % len(diffs))
    return 0


if __name__ == '__main__':
    sys.exit(main())