# -*- coding: utf-8 -*-
"""锁定 paramWeight 恒为 0 的精确算术。

已确认的事实链：
  Cubism4InternalModel.update(dt, now):  now /= 1e3;  motionManager.update(coreModel, now)
     ⇒ 传进 doUpdateMotion 的 now 是**秒**
  Cubism4MotionManager._startMotion:
     queueManager.startMotion(motion, false, performance.now())   ← 传的是**毫秒**
  CubismMotionQueueManager.startMotion(motion, autoDelete, userTimeSeconds):
     第三个参数只用于……（待验证：是否被写入 _startTimeSeconds）

实测队列条目： startT = 12.1366（秒量级），而 qm._userTimeSeconds = 0。

本脚本直接 hook Cubism4MotionManager.prototype.updateParameters，
记录每帧收到的 now，并同时读队首条目的 startTime / fadeInStartTime，
当场算出 fin / fout / paramWeight。不造栈、不写日志到数组以外的东西。
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
GROUP = 'touch_idle1'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  window.__NU = [];
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookNU) return;
    proto.__dshHookNU=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c&&c.internalModel&&c.internalModel.coreModel){
            if(c.destroyed!==true){ window.__l2model=c; wrap(c); }
          }
        }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  function wrap(model){
    try{
      var mm = model.internalModel.motionManager;
      if(!mm || mm.__dshNU) return;
      mm.__dshNU = true;
      var o = mm.updateParameters.bind(mm);
      mm.updateParameters = function(m, now){
        var r = o(m, now);
        try{
          if(window.__NU.length < 300){
            var qm = this.queueManager;
            var q = (qm&&qm._motions) ? qm._motions : [];
            var e0 = q.length ? q[0] : null;
            var eL = q.length ? q[q.length-1] : null;
            window.__NU.push({
              now: now,
              qUt: qm ? qm._userTimeSeconds : null,
              n: q.length,
              head: e0 ? {g:'?', sT:e0._startTimeSeconds, fT:e0._fadeInStartTimeSeconds,
                          eT:e0._endTimeSeconds, st:e0._started} : null,
              last: eL ? {sT:eL._startTimeSeconds, fT:eL._fadeInStartTimeSeconds,
                          eT:eL._endTimeSeconds, st:eL._started} : null
            });
          }
        }catch(x){}
        return r;
      };
    }catch(e){}
  }
  boot();
})();
"""

READ = """
(function(){
  var L = window.__NU || [];
  return JSON.stringify({n: L.length, head: L.slice(0,3), tail: L.slice(-5)});
})()
"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='nu')
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
        time.sleep(15)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        pg.ev("window.__NU.length = 0;")
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(6.0)

        d = json.loads(pg.ev(READ))
        print('\nupdateParameters 采样 %s 条' % d.get('n'))
        if not d.get('n'):
            print('!! 包装未生效（updateParameters 没被调用）—— 这本身就是线索：')
            print('   说明 MotionManager.update() 里 isFinished() 恒 true，直接 return false')
            return 0

        print('\n=== 头 3 帧 ===')
        for e in d.get('head') or []:
            print('  now=%-10s qUt=%-8s n=%s' % (e.get('now'), e.get('qUt'), e.get('n')))
            if e.get('last'):
                L = e['last']
                print('     队尾 sT=%s fT=%s eT=%s started=%s'
                      % (L.get('sT'), L.get('fT'), L.get('eT'), L.get('st')))
        print('\n=== 尾 5 帧 ===')
        for e in d.get('tail') or []:
            print('  now=%-10s qUt=%-8s n=%s' % (e.get('now'), e.get('qUt'), e.get('n')))
            if e.get('last'):
                L = e['last']
                print('     队尾 sT=%s fT=%s eT=%s started=%s'
                      % (L.get('sT'), L.get('fT'), L.get('eT'), L.get('st')))

        print('\n=== 算术复现 ===')
        tail = d.get('tail') or []
        if tail:
            e = tail[-1]
            now = e.get('now')
            for which in ('head', 'last'):
                ent = e.get(which)
                if not ent:
                    continue
                st = ent.get('st')
                fT = ent.get('fT')
                if not st:
                    print('  %s: started=false ⇒ 该条目从未 setFadeInStartTime，不参与求值' % which)
                    continue
                if isinstance(now, (int, float)) and isinstance(fT, (int, float)):
                    off = now - fT
                    v = off / 1.0
                    sine = 0 if v < 0 else (1 if v > 1 else 0.5 - 0.5 * __import__('math').cos(v * 3.141592653589793))
                    print('  %s: now=%.4f  fadeInStart=%.4f  offset=%.4f  fin=%.4f'
                          % (which, now, fT, off, sine))
                    if sine <= 0.001:
                        print('       ⇒ fin≈0 ⇒ paramWeight≈0 ⇒ 该条目写不进参数')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
