# -*- coding: utf-8 -*-
"""长时观测 touch_idle1：确认 idle2 播完后是否发生「二次回落」到默认 idle。

用户观察：最后应该保持在 idle2 循环，实际保持在默认 idle 循环。

前一次短测（12s）看到 3.63s 变成 idle2 后就不再变化，但那不足以下结论：
  idle2 的 Meta 是 Duration=4.0 / Loop=True。
  若运行时把它当 isLoop:false 播一次（本项目记录过的既有特性），
  则 idle2 会在 3.63+4.0 ≈ 7.6s 处结束 → 之后可能被回落成默认 idle。

本脚本观测 45 秒，每 0.15s 采样一次，记录全部组名变化时刻。
判据：
  - 若 idle2 稳定到最后 → 无二次回落，用户看到的可能是缓存旧前端
  - 若 idle2 在约 +4s 后变成 idle → 确认二次回落，根因在「待机组播完后的处理」
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
GROUP = sys.argv[1] if len(sys.argv) > 1 else 'touch_idle1'
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookLT) return;
    proto.__dshHookLT=true;
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

SNAP = """
(function(){
  try{
    var m=window.__l2model;
    if(!m) return JSON.stringify({err:'no model'});
    var im=m.internalModel, mm=im.motionManager;
    var st=mm.state||{};
    var qm=mm.queueManager;
    var q=(qm&&qm._motions)?qm._motions.filter(function(x){return x!=null;}):[];
    var e=q.length?q[q.length-1]:null;
    return JSON.stringify({
      g: st.currentGroup===undefined?'<u>':st.currentGroup,
      pri: st.currentPriority,
      qLen: q.length,
      started: e? e._started : null,
      endT: e? e._endTimeSeconds : null,
      fin: e? e._finished : null
    });
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

    pg = open_page(URL, tag='lt')
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

        pg.ev("(function(){try{return window.__l2play(%s,3);}catch(e){return 'E';}})()"
              % json.dumps(GROUP))
        print('播放 %s，观测 %.0f 秒（每 0.15s 采样）' % (GROUP, DURATION))

        prev = None
        t0 = time.time()
        changes = []
        last = None
        while time.time() - t0 < DURATION:
            d = json.loads(pg.ev(SNAP))
            t = time.time() - t0
            last = d
            if d.get('g') != prev:
                changes.append((t, d))
                print('  t=%5.2fs  %-14s pri=%-2s qLen=%-3s endT=%s fin=%s'
                      % (t, d.get('g'), d.get('pri'), d.get('qLen'),
                         d.get('endT'), d.get('fin')))
                prev = d.get('g')
            time.sleep(0.15)

        print('\n=== 结论 ===')
        print('  最终组:', last.get('g'))
        seq = [str(d.get('g')) for _, d in changes]
        print('  组名序列:', ' -> '.join(seq))
        if last.get('g') == 'idle2':
            print('==> idle2 稳定保持到最后，无二次回落')
            print('    用户看到的「停在默认 idle」可能是缓存旧前端，需 Ctrl+F5 后复测')
        elif 'idle2' in seq and seq[-1] == 'idle':
            idx = seq.index('idle2')
            t_idle2 = changes[idx][0]
            t_idle = [t for t, d in changes if str(d.get('g')) == 'idle' and t > t_idle2]
            print('==> 确认二次回落：idle2 在 t=%.2fs 出现，t=%.2fs 又变回 idle'
                  % (t_idle2, t_idle[0] if t_idle else -1))
            print('    idle2 Duration=4.0 → 播完被回落成默认 idle')
        else:
            print('==> 序列异常，需另查')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
