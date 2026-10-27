# -*- coding: utf-8 -*-
"""决定性取证：motion 队列里到底排着哪几条，谁在真正驱动参数。

上一步实测（probe_idle2_loop_state.py）暴露的异常：
  t=3.2s 起 currentGroup=idle2, loop=True, 但 started=False, qLen=3
  而且 Param278/45/46 全程冻结（波动 0.000）

推论：队列里有 3 个条目，最前面那个（初始 idle）一直 started=True 且在 loop，
      继续驱动参数；后压进去的 touch_idle1 / idle2 永远 start 不了。
      → 组名切到了 idle2（state 层），但**画面仍由旧 idle 条目驱动**
      → 用户看到「停在默认 idle」，完全正确。

本脚本把队列里的每个条目摊开：它是哪一组、started 了吗、finished 了吗、
endTime 多少。若确认队首是 idle 且仍在 loop，则根因锁定：
**新条目被压在旧循环条目之后，startMotion 没清空队列。**

判据：
  · 队首组名 = idle 且 started=true 且 finished=false → 旧 idle 仍在跑
  · 队尾组名 = idle2 且 started=false               → 新条目从没启动过
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
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookQ) return;
    proto.__dshHookQ=true;
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

# 把队列逐个条目摊开，并反查每条 motion 属于哪个组
DUMP = """
(function(){
  try{
    var m=window.__l2model, im=m.internalModel, mm=im.motionManager;
    var qm=mm.queueManager;
    var q=(qm&&qm._motions)?qm._motions:[];
    var defs=(mm.motionGroups||{});
    // 反查：motion 对象 → 组名（比对引用）
    var findGroup=function(mo){
      for(var g in defs){
        var arr=defs[g]||[];
        for(var i=0;i<arr.length;i++){ if(arr[i]===mo) return g; }
      }
      return '?';
    };
    var out={qLen:q.length, cur:(mm.state||{}).currentGroup, entries:[]};
    for(var i=0;i<q.length;i++){
      var e=q[i];
      if(!e){ out.entries.push(null); continue; }
      var mo=e._motion;
      out.entries.push({
        i:i,
        group: mo? findGroup(mo) : '(null motion)',
        started: e._started,
        finished: e._finished,
        startT: e._startTimeSeconds,
        endT: e._endTimeSeconds,
        loop: mo? mo._isLoop : null,
        dur: mo? mo._loopDurationSeconds : null
      });
    }
    out.userTime = qm? qm._userTimeSeconds : null;
    return JSON.stringify(out);
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

    pg = open_page(URL, tag='q')
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

        def dump(label):
            d = json.loads(pg.ev(DUMP))
            print('\n[%s]  qLen=%s  currentGroup=%s  qm.userTime=%s'
                  % (label, d.get('qLen'), d.get('cur'), d.get('userTime')))
            print('    %-3s %-14s %-8s %-9s %10s %10s %6s %6s'
                  % ('i', 'group', 'started', 'finished', 'startT', 'endT', 'loop', 'dur'))
            for e in (d.get('entries') or []):
                if e is None:
                    print('    (null)')
                    continue
                print('    %-3s %-14s %-8s %-9s %10s %10s %6s %6s'
                      % (e.get('i'), e.get('group'), e.get('started'),
                         e.get('finished'), e.get('startT'), e.get('endT'),
                         e.get('loop'), e.get('dur')))
            return d

        dump('基线（初始 idle）')

        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(1.0)
        dump('播放 touch_idle1 中')
        time.sleep(3.0)
        d = dump('回落后（此时应为 idle2）')

        print('\n=== 判定 ===')
        ents = [e for e in (d.get('entries') or []) if e]
        if not ents:
            print('  队列空，无数据')
            return 0
        head = ents[0]
        print('  队首: group=%s started=%s finished=%s loop=%s'
              % (head.get('group'), head.get('started'),
                 head.get('finished'), head.get('loop')))
        tail = ents[-1]
        print('  队尾: group=%s started=%s finished=%s loop=%s'
              % (tail.get('group'), tail.get('started'),
                 tail.get('finished'), tail.get('loop')))
        print()
        stuck = (head.get('group') != tail.get('group')
                 and head.get('started') is True
                 and head.get('finished') is False
                 and tail.get('started') is False)
        if stuck:
            print('==> 根因确认：旧条目（%s）仍在队首 loop 并继续驱动参数，' % head.get('group'))
            print('    新条目（%s）排在后面、started=false，从未开始 → 画面不变' % tail.get('group'))
            print('    ⇒ 组名切到 idle2 只是 state 层记录，实际渲染仍由旧 idle 曲线驱动')
        elif head.get('group') == tail.get('group'):
            print('==> 队列里只有同一组（%s），无堆积' % head.get('group'))
        else:
            print('==> 其它形态：队首 %s / 队尾 %s，需逐条分析'
                  % (head.get('group'), tail.get('group')))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
