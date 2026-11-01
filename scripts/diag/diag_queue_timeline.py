# -*- coding: utf-8 -*-
"""用正确字段路径读 motion 队列时间线，验证 paramWeight 是否 ≈0。

⚠️ 前几轮探针的字段路径错误（必须记录，避免重跑）：
   错： mm._motions            → 不存在，永远 0 条（误判"队列空")
   错： mm._userTimeSeconds    → 不存在，永远 null
   对： mm.queueManager._motions / mm.queueManager._userTimeSeconds
   mmKeys 里顺序是 [..., "queueManager", "state", "playing", "destroyed", ...]

已知正确事实（不受上述错误影响，来自库源码与 JSON）：
   - touch_idle14 Meta: Duration=3.017 Loop=False，无 FadeInTime/FadeOutTime
     ⇒ parse() 取默认 _fadeInSeconds=1, _fadeOutSeconds=1
   - ParamAngleX 曲线末帧 -18.367，曲线段结构正确、points 值正确
   - doUpdateParameters: v = source + (value - source) * (_weight * fin * fout)

本脚本读 queueManager 的真实条目，算 fin/fout/paramWeight，
并同时读 ParamAngleX 实际值，确认「paramWeight 是否被压到≈0」。
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
  window.__ALLMODELS = [];
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookQM) return;
    proto.__dshHookQM=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c&&c.internalModel&&c.internalModel.coreModel){
            window.__ALLMODELS.push(c);
            if(c.destroyed!==true) window.__l2model=c;
          }
        }catch(e){}
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
    const qm=mm.queueManager;            // ← 正确的队列对象
    const st=mm.state||{};
    const o={g:st.currentGroup};

    o.userTime = qm? qm._userTimeSeconds : null;
    const q=(qm&&qm._motions)? qm._motions.filter(x=>x!=null) : [];
    o.qLen=q.length;

    // 当前组的 motion 定义字段
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0];
    if(mo){
      o.moFadeIn=mo._fadeInSeconds; o.moFadeOut=mo._fadeOutSeconds;
      o.moWeight=mo._weight; o.moIsLoop=mo._isLoop;
      o.moLoopDur=mo._loopDurationSeconds;
    }

    if(q.length){
      const e=q[q.length-1];
      const call=(f)=>{ try{ return (typeof e[f]==='function')? e[f]() : null; }catch(x){ return 'ERR'; } };
      o.eStart=call('getStartTime');
      o.eFadeInStart=call('getFadeInStartTime');
      o.eEnd=call('getEndTime');
      o.eFadeOutSec=call('getFadeOutSeconds');
      o.eFinished=call('isFinished');
      o.eStateWeight=call('getStateWeight');
      // 手算 fin / fout / paramWeight
      if(typeof o.eStart==='number' && typeof o.userTime==='number' && mo){
        const sine=(v)=> (v<0?0:(v>1?1:0.5-0.5*Math.cos(v*Math.PI)));
        const off=o.userTime-o.eStart;
        const fi=(mo._fadeInSeconds<=0)?1:sine(off/mo._fadeInSeconds);
        let fo=1;
        if(mo._fadeOutSeconds>0 && o.eEnd>=0) fo=sine((o.eEnd-o.userTime)/mo._fadeOutSeconds);
        o.calc={offset:off, fin:fi, fout:fo, paramWeight:(mo._weight||0)*fi*fo};
      }
    }
    const gv=(p)=>{ try{const i=cm.getParameterIndex(p);
                       return i>=0? cm.getParameterValueByIndex(i): null;}catch(e){return null;} };
    o.vals={A:gv('ParamAngleX'), P194:gv('Param194'), P207:gv('Param207'), P343:gv('Param343')};
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

    pg = open_page(URL, tag='qm')
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

        print('\n[基线]')
        d = json.loads(pg.ev(READ))
        print('  ', json.dumps(d, ensure_ascii=False))

        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))

        print('\n[播放中，逐帧快照]')
        print('  %8s %14s %4s %8s %8s %8s %9s %9s %9s %10s %10s'
              % ('now', 'group', 'qLen', 'userTm', 'eStart', 'eEnd',
                 'fin', 'fout', 'pWeight', 'AngleX', 'p194'))
        for _ in range(14):
            time.sleep(0.22)
            d = json.loads(pg.ev(READ))
            if 'err' in d:
                print('  ERR', d['err'])
                break
            c = d.get('calc') or {}
            def f(v, w='8.3f'):
                return ('%8.3f' % v) if isinstance(v, (int, float)) else ('%8s' % '-')
            print('  %8.3f %14s %4s %8s %8s %8s %9s %9s %9s %10s %10s'
                  % (0, str(d.get('g')), d.get('qLen'),
                     f(d.get('userTime')), f(d.get('eStart')), f(d.get('eEnd')),
                     f(c.get('fin'), '9.4f'), f(c.get('fout'), '9.4f'),
                     f(c.get('paramWeight'), '9.4f'),
                     ('%10s' % d['vals']['A']), ('%10s' % d['vals']['P194'])))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
