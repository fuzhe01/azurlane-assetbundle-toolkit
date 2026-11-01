"""测「某参数在不同取值之间，画面/顶点差异各有多大」——判定两态到底该取哪两个值。

背景（2026-10-24 实测触发的疑问）：ShoseOff 数据表是 lo=-1 / hi=1 / def=0（kind:slider）。
热区点击在等距时取 hi，于是 0→1。但验收时「点后变化集合」里不含它驱动的 [460,461]，
而 ParamAngleX 却能移动 460/461 —— 必须确认 0 与 1 之间是否**本来就没有可见差异**
（若 0/1 同形，则 0→1 是"参数变了但画面没变"，两态应取 -1 / 1）。

方法（与 map_param_to_drawables.py 同一原理，规避呼吸相位）：
  同一次 evaluate 内，对每个取值 v：写参数 → im.update(0, now) 强制走一遍 keyform 求值 →
  逐 drawable 采顶点包围盒 + opacity。两两比对，报「变化 drawable 数 / 驱动集合内的数」。

用法: py -3 scripts/diag/probe_param_value_states.py ougen_8 ShoseOff [-1,0,1]
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

from cdp_helper import open_page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
VALS = [float(x) for x in (sys.argv[3].split(',') if len(sys.argv) > 3 else ['-1', '0', '1'])]
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){var t=0;function p(){if(!(window.PIXI&&window.PIXI.Container)){if(t++<900)setTimeout(p,20);return;}
  var pr=window.PIXI.Container.prototype;if(pr.__pvs)return;pr.__pvs=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

MEASURE = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel, pid=%s, vals=%s;
  var ix=core.getParameterIndex(pid);
  if(ix<0) return JSON.stringify({err:'NO_IDX'});
  function snap(){
    try{ im.update(0, performance.now()); }catch(e){}
    var n=core.getDrawableCount(), out=[];
    for(var i=0;i<n;i++){
      var op=0,bx=null;
      try{ op=+core.getDrawableOpacity(i); }catch(e){}
      try{ var v=core.getDrawableVertexPositions(i);
        if(v&&v.length>=2){ var xs=[],ys=[];
          for(var k=0;k+1<v.length;k+=2){xs.push(v[k]);ys.push(v[k+1]);}
          bx=[Math.min.apply(null,xs),Math.min.apply(null,ys),
              Math.max.apply(null,xs),Math.max.apply(null,ys)]; } }catch(e){}
      out.push([i,+op.toFixed(4),bx]);
    }
    return out;
  }
  var S={};
  for(var q=0;q<vals.length;q++){
    core.setParameterValueByIndex(ix, vals[q]);
    S[vals[q]]=snap();
  }
  // 恢复默认
  core.setParameterValueByIndex(ix, core.getParameterDefaultValue(ix));
  function cmp(a,b){
    var moved=[];
    for(var i=0;i<a.length;i++){
      var x=a[i],y=b[i],do_=Math.abs((x[1]||0)-(y[1]||0)),db=0;
      if(x[2]&&y[2]) db=Math.max(Math.abs(x[2][0]-y[2][0]),Math.abs(x[2][1]-y[2][1]),
                                 Math.abs(x[2][2]-y[2][2]),Math.abs(x[2][3]-y[2][3]));
      if(do_>0.02||db>0.5) moved.push([i,+do_.toFixed(3),+db.toFixed(2)]);
    }
    return {n:moved.length, idx:moved.map(function(z){return z[0];}), d:+(moved.reduce(function(s,z){return s+z[2];},0)).toFixed(2)};
  }
  var pairs=[];
  for(var i=0;i<vals.length;i++) for(var j=i+1;j<vals.length;j++)
    pairs.push({a:vals[i], b:vals[j], r:cmp(S[vals[i]],S[vals[j]])});
  return JSON.stringify({pid:pid, idx:ix, min:+core.getParameterMinimumValue(ix),
    max:+core.getParameterMaximumValue(ix), def:+core.getParameterDefaultValue(ix), pairs:pairs});
})()
"""


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2
    pg = open_page(BASE, tag='pvs')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Network.enable'); pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': BASE})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
              % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        for _ in range(40):
            time.sleep(1.0)
            if pg.ev("(window.__l2model && window.PARAM_DRAWABLES)?1:0") == 1:
                break
        # 停动作，避免曲线参与
        pg.ev("""(function(){var m=window.__l2model;
          try{ m.internalModel.motionManager.queueManager.stopAllMotions(); }catch(e){}
          return 1;})()""")
        time.sleep(0.8)
        raw = pg.ev(MEASURE % (json.dumps(PID), json.dumps(VALS)))
        d = json.loads(raw)
        if d.get('err'):
            print('[FAIL]', d); return 1
        driven = json.loads(pg.ev("""(function(){var t=(window.PARAM_DRAWABLES||{})[%s]||{};
           return JSON.stringify(t[%s]||[]);})()""" % (json.dumps(KEY), json.dumps(PID))))
        print('%s  值域 [%s,%s] 默认 %s  驱动部件 %s'
              % (PID, d['min'], d['max'], d['def'], driven))
        for p in d['pairs']:
            inter = sorted(set(p['r']['idx']) & set(driven))
            print('  %6s vs %6s：变化 %-3d 个（驱动集合内 %d 个 %s），累计位移 %.1f'
                  % (p['a'], p['b'], p['r']['n'], len(inter), inter, p['r']['d']))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
