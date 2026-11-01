"""诊断：为什么所有非待机动作都回落到「初始 idle」而不是 motion_chain 的 best。

用户观察（2026-10-24）：除了 idle* 待机组，其它动作播完都回到初始 idle。
而 motion_chain.json 里 42 组有 27 组的 best 指向具体变体（如 touch_idle14→idle9）。

三个候选：
  A. chainModel 为 null（motion_chain.json 没加载成功）→ best 查不到 → 全落 idleGroup
  B. lastGroup 在回落时已经被改成 idle 组 → best 查到的是 idle 的 best（空）
  C. _durs 缺失 → _scheduleFallback 不安排定时器 → 靠库自身回落（库落 groups.idle）

用法: py -3 scripts/diag/diag_fallback_target.py ougen_8
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

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookFT) return; proto.__dshHookFT=true;
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
  // 记录 motion_chain 的加载
  window.__mcOk=null; window.__mcErr=null;
  var of=window.fetch;
  window.fetch=function(u){
    var url=(typeof u==='string')?u:(u&&u.url)||'';
    var p=of.apply(this,arguments);
    if(url.indexOf('motion_chain')>=0){
      p.then(function(r){
        window.__mcStatus=r.status;
        return r.clone().json();
      }).then(function(j){ window.__mcOk=j; }).catch(function(e){ window.__mcErr=String(e); });
    }
    return p;
  };
})();
"""

SNAP = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var st=m.internalModel.motionManager.state||{};
  var e=document.getElementById('l2Curr');
  return JSON.stringify({group: st.currentGroup===undefined?'<undef>':st.currentGroup,
                         label: e?e.textContent:null, pri: st.currentPriority});
})()
"""

MCINFO = r"""
(function(){
  var mc=window.__mcOk;
  if(!mc) return JSON.stringify({loaded:false, status:window.__mcStatus, err:window.__mcErr});
  var models=mc.models||{};
  var m=models[%s]||null;
  if(!m) return JSON.stringify({loaded:true, hasModel:false, modelKeys:Object.keys(models)});
  var chain=m.chain||{}, durs=m.durations||{};
  return JSON.stringify({loaded:true, hasModel:true,
    nChain:Object.keys(chain).length,
    nDurs:Object.keys(durs).length,
    idleGroups:(m.idle_groups||[]).length,
    sample:{ 'touch_idle14': (chain['touch_idle14']||{}).best,
             'touch_idle20': (chain['touch_idle20']||{}).best,
             'mail': (chain['mail']||{}).best },
    durSample:{ 'touch_idle14': durs['touch_idle14'],
                'touch_idle20': durs['touch_idle20'],
                'mail': durs['mail'] }
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

    pg = open_page(URL, tag='ft')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
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
        time.sleep(14)

        print('模型:', pg.ev("typeof window.__l2model"))
        print('\n=== motion_chain 加载状态 ===')
        print(pg.ev(MCINFO % json.dumps(KEY)))

        # 实测三组动作的回落目标
        print('\n=== 实测回落目标 ===')
        for grp in ('touch_idle14', 'touch_idle20', 'mail'):
            r = pg.ev("""
            (function(){var s=document.getElementById('l2Motion');
              if(!s) return 'NO_SEL';
              if(![...s.options].some(function(o){return o.value===%s;})) return 'NO_GROUP';
              s.value=%s;
              if(window.__l2play){ window.__l2play(%s); return 'PLAYED'; }
              return 'NO_HOOK';})()
            """ % (json.dumps(grp), json.dumps(grp), json.dumps(grp)))
            trace = []
            t0 = time.time()
            while time.time() - t0 < 18:
                raw = pg.ev(SNAP)
                try:
                    d = json.loads(raw)
                except Exception:  # noqa: BLE001
                    d = {}
                g = d.get('group')
                if not trace or trace[-1][1] != g:
                    trace.append((round(time.time() - t0, 1), g))
                time.sleep(0.4)
            print('  %-14s %-8s 轨迹: %s' % (grp, r, trace))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())