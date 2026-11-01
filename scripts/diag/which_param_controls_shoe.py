"""反查：touchdrag17 区域那些 op=0 的 drawable，各自受哪个参数控制。

思路（从部件反查参数，而不是从参数反查部件）：
  用户看到的三态（无脚 / 黑丝左脚 / 红底高跟鞋）意味着这一小块区域里
  有若干 ArtMesh 在切换显隐。它们当前 op=0（不可见）。
  逐个参数扫一遍：改它之后，这些 drawable 的 opacity 是否变化？
  → 变了，就是我们要找的开关。

判据：一次 evaluate 内对每个参数 hi/lo 各采一遍这些 drawable 的 opacity，
     全量比对，避免多次往返和呼吸相位干扰。

用法: py -3 scripts/diag/which_param_controls_shoe.py ougen_8
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
OUT = os.path.join(ROOT, '.diag', 'whichparam')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookWP) return; proto.__dshHookWP=true;
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

# 一次性扫全：对每个参数，把该区内的 drawable opacity 在 hi/lo 两态下各取一遍，
# 记录变化量。全部在同一个 evaluate 内完成，不受呼吸相位影响。
SCAN = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel;
  var ids=core._model.drawables.ids;
  var targets=%s;              // 目标 drawable 索引列表
  var n=core.getParameterCount();
  var pids=core._parameterIds;

  function opacities(){
    try{ im.update(0, performance.now()); }catch(e){}
    var out=[];
    for(var q=0;q<targets.length;q++){
      var v=null;
      try{ v=core.getDrawableOpacity(targets[q]); }catch(e){}
      out.push(v===null? null : +v.toFixed(3));
    }
    return out;
  }

  // 基线
  for(var q=0;q<targets.length;q++){
    // 不改任何参数
  }
  var base = opacities();
  var hits=[];

  for(var pi=0; pi<n; pi++){
    var pid=pids[pi];
    var lo=0, hi=1;
    try{ lo=core.getParameterMinimumValue(pi); hi=core.getParameterMaximumValue(pi); }catch(e){ continue; }
    if(hi-lo < 0.05) continue;            // 无可调空间
    // hi
    try{ core.setParameterValueByIndex(pi, hi); }catch(e){ continue; }
    var A=opacities();
    // lo
    try{ core.setParameterValueByIndex(pi, lo); }catch(e){}
    var B=opacities();
    // 恢复
    try{ core.setParameterValueByIndex(pi, 0); }catch(e){}

    var maxd=0, which=-1;
    for(var q=0;q<targets.length;q++){
      if(A[q]===null || B[q]===null) continue;
      var d=Math.abs(A[q]-B[q]);
      if(d>maxd){ maxd=d; which=targets[q]; }
    }
    if(maxd>0.25){ hits.push([pid, +maxd.toFixed(3), which]); }
  }
  return JSON.stringify({base:base, n_targets:targets.length, hits:hits});
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='wp')
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

        # 取 touchdrag17 区域覆盖的、且当前 op 很低的 drawable（候选隐藏部件）
        cand = pg.ev("""
        (function(){
          var m=window.__l2model, im=m.internalModel, core=im.coreModel;
          var list=window.__L2_HITINFO? window.__L2_HITINFO(): [];
          var td=list.find(function(h){ return String(h.name).toLowerCase().replace(/_/g,'')==='touchdrag17'; });
          if(!td||!td.canvas) return '{"err":"NO_TD17"}';
          var b=td.canvas, cx=b.cx, cy=b.cy;
          var n=core.getDrawableCount(), out=[];
          for(var i=0;i<n;i++){
            var v=null; try{ v=core.getDrawableVertexPositions(i); }catch(e){}
            if(!v||!v.length) continue;
            var xs=[],ys=[];
            for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
            var x0=Math.min.apply(null,xs), x1=Math.max.apply(null,xs);
            var y0=Math.min.apply(null,ys), y1=Math.max.apply(null,ys);
            if(cx<x0||cx>x1||cy<y0||cy>y1) continue;
            var op=null; try{ op=core.getDrawableOpacity(i); }catch(e){}
            if(op!==null && op<0.05) out.push(i);   // 当前不可见 → 嫌疑最大
          }
          return JSON.stringify(out);
        })()
        """)
        print('该区内 op≈0 的 drawable:', cand)
        targets = json.loads(cand)
        if not isinstance(targets, list) or not targets:
            print('[FAIL] 没有候选部件'); return 2
        print('候选数:', len(targets))

        r = pg.ev(SCAN % json.dumps(targets))
        d = json.loads(r)
        if 'err' in d:
            print('[FAIL]', d['err']); return 2
        print('\n基线 opacity:', d['base'])
        print('扫遍 %d 个候选部件 × 全部参数，命中 %d 个参数能让它们改变:'
              % (d['n_targets'], len(d['hits'])))
        for pid, maxd, which in sorted(d['hits'], key=lambda x: -x[1])[:20]:
            print('  %-24s 最大变化 %.3f（drawable #%d）' % (pid, maxd, which))
        if not d['hits']:
            print('  （没有任何单参数能把它们切到可见 → 可能要多参数组合，或由动作驱动）')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())