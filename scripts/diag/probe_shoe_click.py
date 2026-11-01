"""实验：在红底高跟鞋位置点一下，记录前后**所有参数**的变化。

用户说在红底高跟鞋位置点击会触发脱鞋动画 → 露出黑丝袜左脚。
那么「点击前」的状态就是穿鞋态，「点击后」就是脱鞋态（或其过渡）。
两者参数的 diff 就指向控制鞋子显隐的参数。

做法：
  A. 进 idle 稳定，dump 全部参数
  B. 在画布上按 HitAreas / 已知交互区遍历点击，找到"会让鞋子出现/消失"的那个
  C. 每次点击后 dump 全部参数，diff 出变化参数

因为不知道确切坐标，先列出页面自己的 hitAreas 与它们的 Name（→动作组），
再从动作组里挑与鞋/脚相关的（touch_foot / touch_shoe / touch_dragN 等）。

用法: py -3 scripts/diag/probe_shoe_click.py ougen_8
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
PORT = 9335
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSC) return; proto.__dshHookSC=true;
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

DUMP_ALL = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel;
  var n=core.getParameterCount? core.getParameterCount() : 0;
  var ids=null;
  try{ ids=core.getParameterIds? core.getParameterIds() : null; }catch(e){}
  var out={};
  for(var i=0;i<n;i++){
    try{
      var id=(ids&&ids[i])? ids[i] : ('#'+i);
      out[id]=+core.getParameterValueByIndex(i).toFixed(3);
    }catch(e){}
  }
  return JSON.stringify(out);
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_sc'), URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
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
        time.sleep(9)

        print('模型:', pg.ev("typeof window.__l2model"))
        # 参数总数
        print('参数总数:', pg.ev("""
        (function(){var m=window.__l2model; if(!m) return -1;
          var core=m.internalModel.coreModel;
          return core.getParameterCount? core.getParameterCount() : -1;})()
        """))

        # 列 hitAreas 与对应动作组
        print('\n页面 hitAreas → 动作组:')
        print(pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return 'NO_MODEL';
          var im=m.internalModel;
          var hits=(im.hitAreas||[]);
          return JSON.stringify(hits.map(function(h){return [h.Id||h.id, h.Name||h.name];}));
        })()
        """))

        # 可用动作组里的 drag / foot / shoe 类
        groups = pg.ev("""(function(){var s=document.getElementById('l2Motion');
          return s? JSON.stringify([...s.options].map(function(o){return o.value;})) : '[]';})()""")
        gs = json.loads(groups)
        print('\n动作组总数:', len(gs))
        interesting = [g for g in gs if any(k in g.lower() for k in ('drag', 'foot', 'shoe', 'xie', 'leg', 'hand'))]
        print('与脚/鞋/腿/手/拖拽相关的组:', interesting)

        base = json.loads(pg.ev(DUMP_ALL))
        print('\nidle 参数数:', len(base))

        # 逐个播这些组，dump 参数 diff
        print('\n=== 逐组播放后与 idle 的参数差异 ===')
        for g in interesting[:20]:
            pg.ev("""(function(){var s=document.getElementById('l2Motion');
                       if(s) s.value=%s;
                       if(window.__l2play) window.__l2play(%s); return 1;})()"""
                 % (json.dumps(g), json.dumps(g)))
            time.sleep(3.5)
            cur = json.loads(pg.ev(DUMP_ALL))
            diff = {k: (base.get(k), cur.get(k)) for k in cur
                    if k in base and abs((cur.get(k) or 0) - (base.get(k) or 0)) > 0.5}
            print('%-20s 变化参数 %-3d  %s' % (g, len(diff),
                  list(diff.items())[:4] if diff else ''))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())