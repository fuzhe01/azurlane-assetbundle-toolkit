# -*- coding: utf-8 -*-
"""读 CubismMotion 的 fade 时间字段实值，验证 paramWeight≈0 假说。

推理链（来自库源码 CubismMotion.doUpdateParameters）：
    fin  = getEasingSine((userTimeSeconds - entry.getFadeInStartTime()) / _fadeInSeconds)
    fout = getEasingSine((entry.getEndTime() - userTimeSeconds) / _fadeOutSeconds)
    paramWeight = _weight * fin * fout
    v = sourceValue + (value - sourceValue) * paramWeight
    model.setParameterValueByIndex(parameterIndex, v)

  sourceValue = model.getParameterValueByIndex(i)，即**上一帧写完后的值**。
  ⇒ 若 paramWeight ≈ 0，v ≈ sourceValue，参数被"冻结"在 motion 开始前的值。
    动作开始前 ParamAngleX = 0 → 整个动作期间恒 0。
    Param194 会极缓慢爬升（每帧只逼近 target 的一小部分），实测 2.6s 才到 0.61（target 10）。

  ⇒ 若 userTimeSeconds 与 getFadeInStartTime() 时间基准不一致（一个用秒、
    另一个用 performance.now()/1000 之类的绝对时间），差值会是巨大负数 → fin=0。

本脚本只读字段，不 hook、不造栈、不逐帧写日志，单次读取后立即返回。
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

import ensure_servers  # noqa: E402
from cdp_helper import open_page  # noqa: E402

KEY = 'ougen_8'
GROUP = 'touch_idle14'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookFD) return;
    proto.__dshHookFD=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c&&c.internalModel&&c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
})();
"""

READ = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, cm=im.coreModel;
    const mm=im.motionManager;
    const st=mm.state||{};
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0];
    const o={g:st.currentGroup, now:performance.now()};

    // 队列条目
    let entry=null;
    try{
      const q=(mm._motions||[]).filter(x=>x!=null);
      if(q.length) entry=q[q.length-1];
    }catch(e){}
    o.qLen = (function(){ try{return (mm._motions||[]).filter(x=>x!=null).length;}catch(e){return null;} })();

    const call=(obj,f)=>{ try{ return (typeof obj[f]==='function')? obj[f]() : null; }catch(e){ return 'ERR:'+String(e).slice(0,60); } };
    if(entry){
      o.startTime   = call(entry,'getStartTime');
      o.fadeInStart = call(entry,'getFadeInStartTime');
      o.endTime     = call(entry,'getEndTime');
      o.fadeOutSec  = call(entry,'getFadeOutSeconds');
      o.stateWeight = call(entry,'getStateWeight');
      o.isFinished  = call(entry,'isFinished');
    }
    o.userTime = mm._userTimeSeconds;
    o.motionFadeIn = mo && mo._fadeInSeconds;
    o.motionFadeOut = mo && mo._fadeOutSeconds;
    o.motionWeight = mo && mo._weight;
    o.motionLastWeight = mo && mo._lastWeight;
    o.isLoop = mo && mo._isLoop;
    o.loopDur = mo && mo._loopDurationSeconds;

    // 关键参数：实际值 + motion 曲线的目标值（用库的 time 口径近似）
    const gv=(p)=>{ try{const i=cm.getParameterIndex(p);
                       return i>=0? cm.getParameterValueByIndex(i): null;}catch(e){return null;} };
    o.vals = {ParamAngleX: gv('ParamAngleX'), Param194: gv('Param194'),
              Param207: gv('Param207'), Param343: gv('Param343')};

    // 手动算 fin / fout / paramWeight（用读到的字段）
    if(entry && typeof o.startTime==='number' && typeof o.userTime==='number'){
      const sine=(v)=> (v<0?0:(v>1?1:0.5-0.5*Math.cos(v*Math.PI)));
      const off = o.userTime - o.startTime;
      const fi = (o.motionFadeIn<=0)?1:sine(off/o.motionFadeIn);
      let fo=1;
      if(o.motionFadeOut>0 && o.endTime>=0) fo=sine((o.endTime-o.userTime)/o.motionFadeOut);
      o.calc = {offset:off, fin:fi, fout:fo,
                paramWeight:(o.motionWeight||0)*fi*fo};
    }
    return JSON.stringify(o);
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
""" % json.dumps(GROUP)


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='fd')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              "if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(14)
        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        print('\n[基线 idle]')
        b0 = json.loads(pg.ev(READ))
        print('  userTime=%s vals=%s' % (b0.get('userTime'), b0.get('vals')))

        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))

        print('\n[播放 touch_idle14 期间，逐次只读快照]')
        for wait in (0.35, 0.5, 0.7, 0.9, 0.7):
            time.sleep(wait)
            d = json.loads(pg.ev(READ))
            print('\n  --- g=%s qLen=%s ---' % (d.get('g'), d.get('qLen')))
            for k in ['now','startTime','fadeInStart','endTime','userTime',
                      'motionFadeIn','motionFadeOut','motionWeight','isLoop',
                      'loopDur','stateWeight','isFinished']:
                if k in d:
                    print('    %-14s %s' % (k, d[k]))
            if d.get('calc'):
                print('    calc: offset=%s fin=%s fout=%s paramWeight=%s'
                      % (d['calc'].get('offset'), d['calc'].get('fin'),
                         d['calc'].get('fout'), d['calc'].get('paramWeight')))
            print('    vals: %s' % d.get('vals'))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
