# -*- coding: utf-8 -*-
"""直接测量 doUpdateMotion 收到的 now 与 entry.fadeInStart 的实际关系。

前一轮的读数陷阱（记入技能）：
  读 mm.queueManager._userTimeSeconds 得到 0 → 算出 fin=0 → 误判"paramWeight=0 导致曲线失效"。
  但 Cubism4MotionManager.updateParameters(model, now) 直接把外部 now 传给
  queueManager.doUpdateMotion(model, now)，**根本不使用 _userTimeSeconds**。
  ⇒ _userTimeSeconds 恒 0 是正常现象，不是 bug，据此算 fin 得到的是假象。

本脚本不读 _userTimeSeconds，改为 hook Cubism4MotionManager.prototype.updateParameters，
只记录**每帧的 now**（不造栈、不逐次写日志，只在 monkeypatch 里累加计数并保留最后 8 条），
同时读同一帧 entry 的 startTime/fadeInStart，用真实 now 复算 fin / paramWeight。
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
  window.__NOWLOG = [];
  window.__nowCount = 0;
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookNW) return;
    proto.__dshHookNW=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c&&c.internalModel&&c.internalModel.coreModel){
            if(c.destroyed!==true) window.__l2model=c;
            wrapMM(c);
          }
        }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  function wrapMM(model){
    try{
      var mm=model.internalModel.motionManager;
      if(!mm || mm.__dshWrapNW) return;
      mm.__dshWrapNW=true;
      var o=mm.updateParameters.bind(mm);
      mm.updateParameters=function(m, now){
        window.__nowCount++;
        try{
          if(window.__nowLog.length<4000){
            var qm=this.queueManager;
            var q=(qm&&qm._motions)?qm._motions.filter(function(x){return x!=null;}):[];
            var e=q.length?q[q.length-1]:null;
            window.__nowLog.push({
              now: now,
              qUt: qm?qm._userTimeSeconds:null,
              qLen: q.length,
              eStart: e?e._startTimeSeconds:null,
              eFadeIn: e?e._fadeInStartTimeSeconds:null,
              eEnd: e?e._endTimeSeconds:null,
              eStarted: e?e._started:null
            });
          }
        }catch(x){}
        return o(m, now);
      };
    }catch(e){}
  }
  boot();
})();
"""

READ = """
(function(){
  var L = window.__NOWLOG||[];
  return JSON.stringify({
    count: window.__nowCount,
    len: L.length,
    tail: L.slice(-10),
    head: L.slice(0, 4)
  });
})()
"""

PARAMS = """
(function(){
  try{
    var m=window.__l2model;
    if(!m) return JSON.stringify({err:'no model'});
    var cm=m.internalModel.coreModel;
    var gv=function(p){ try{var i=cm.getParameterIndex(p);
      return i>=0?cm.getParameterValueByIndex(i):null;}catch(e){return null;} };
    return JSON.stringify({g:(m.internalModel.motionManager.state||{}).currentGroup,
      A:gv('ParamAngleX'), P194:gv('Param194'), P207:gv('Param207')});
  }catch(e){ return JSON.stringify({err:String(e)}); }
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

    pg = open_page(URL, tag='nw')
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

        print('\n[基线：确认 updateParameters 每帧都在被调用]')
        d0 = json.loads(pg.ev(READ))
        print('  调用次数=%s 日志条数=%s' % (d0['count'], d0['len']))
        for e in d0.get('tail') or []:
            print('   ', json.dumps(e))
        print()

        pg.ev("window.__NOWLOG.length = 0;")
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(2.0)

        d = json.loads(pg.ev(READ))
        p = json.loads(pg.ev(PARAMS))
        print('[播放中] 调用次数累计=%s  本轮日志=%s' % (d['count'], d['len']))
        print('当前参数:', json.dumps(p))
        print('\n  %10s %10s %6s %10s %10s %10s %6s %8s %8s'
              % ('now', 'qm.ut', 'qLen', 'eStart', 'eFadeIn', 'eEnd', 'started', 'fin', 'pW'))
        for e in (d.get('tail') or []):
            now = e.get('now')
            fi = e.get('eFadeIn')
            fin = None
            if isinstance(now, (int, float)) and isinstance(fi, (int, float)):
                off = now - fi
                v = off / 1.0   # motion._fadeInSeconds = 1（Meta 无 FadeInTime → 默认 1）
                v = 0 if v < 0 else (1 if v > 1 else 0.5 - 0.5 * __import__('math').cos(v * 3.141592653589793))
                fin = v
            def f(x, w='10.3f'):
                return ('%10.3f' % x) if isinstance(x, (int, float)) else ('%10s' % '-')
            print('  %s %s %6s %s %s %s %6s %8s'
                  % (f(now), f(e.get('qUt')), e.get('qLen'),
                     f(e.get('eStart')), f(e.get('eFadeIn')), f(e.get('eEnd')),
                     str(e.get('eStarted')), ('%8.4f' % fin) if fin is not None else '       -'))
        print()
        tail = (d.get('tail') or [])
        if tail:
            last = tail[-1]
            now = last.get('now')
            fi = last.get('eFadeIn')
            if isinstance(now, (int, float)) and isinstance(fi, (int, float)):
                print('最后一帧: now=%.3f  eFadeIn=%.3f  差值=%.3f 秒'
                      % (now, fi, now - fi))
                if now - fi > 0.5:
                    print('==> fin 已到 1，paramWeight 正常 → 曲线应已生效')
                else:
                    print('==> 差值 <0.5，fadeIn 未完成')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
