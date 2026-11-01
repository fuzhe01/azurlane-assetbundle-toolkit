# -*- coding: utf-8 -*-
"""复核队列堆积：去掉一切包装干扰，纯只读观察 qLen + 队首/队尾 + 参数波动。

上一轮 dump_motion_queue.py 看到回落后 qLen=3（idle / touch_idle1 / idle2 堆积），
但 probe_update_chain.py 里 qLen=1 且 isFinished=False 正常工作。
两者矛盾，必须先确定哪个是真的——包装 hook 本身可能改变时序。

本脚本：
  · 不 hook 任何函数（不 wrap update / 不 wrap addChild 之外的东西）
  · 只读：state.currentGroup / queueManager._motions 各条目的 started+group / 参数值
  · 每 0.5s 一次，跑 14 秒，覆盖 播放→回落→idle2 首个周期
  · 同时判断参数是否在变化（真循环的判据）
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
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
WATCH = ['Param278', 'Param45', 'Param46']

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookRo) return;
    proto.__dshHookRo=true;
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

READ = """
(function(){
  try{
    var m=window.__l2model;
    if(!m) return JSON.stringify({err:'no model'});
    var im=m.internalModel, cm=im.coreModel, mm=im.motionManager;
    var qm=mm.queueManager;
    var q=(qm&&qm._motions)?qm._motions:[];
    var defs=(mm.motionGroups||{});
    var fg=function(mo){
      for(var g in defs){ var a=defs[g]||[];
        for(var i=0;i<a.length;i++){ if(a[i]===mo) return g; } }
      return '?';
    };
    var o={g:(mm.state||{}).currentGroup, qLen:q.length, qUt:qm?qm._userTimeSeconds:null,
           entries:[], label:(document.getElementById('l2Curr')||{}).textContent};
    for(var i=0;i<q.length;i++){
      var e=q[i];
      o.entries.push(e? {grp:fg(e._motion), st:e._started, fin:e._finished,
                         sT:e._startTimeSeconds, eT:e._endTimeSeconds} : null);
    }
    var W=%s;
    for(var j=0;j<W.length;j++){
      try{ var idx=cm.getParameterIndex(W[j]);
        if(idx<0){ o[W[j]]=null; continue; }
        o[W[j]] = Math.round(cm.getParameterValueByIndex(idx)*1000)/1000;
      }catch(x){ o[W[j]]=null; }
    }
    return JSON.stringify(o);
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
""" % json.dumps(WATCH)


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='ro')
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

        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        print('播放 %s，纯只读观察 14 秒\n' % GROUP)
        print('  %5s %-13s %-14s %4s %8s %-34s %8s %8s %8s'
              % ('t', 'currentGroup', 'label', 'q', 'qUt', '队列条目', 'P278', 'P45', 'P46'))

        t0 = time.time()
        recs = []
        while time.time() - t0 < 14.0:
            d = json.loads(pg.ev(READ))
            t = time.time() - t0
            recs.append((t, d))
            if int(t * 10) % 10 < 5 or int(t * 10) % 10 == 9:
                ents = ' | '.join(
                    '%s(%s%s)' % (e.get('grp'),
                                  'S' if e.get('st') else '-',
                                  'F' if e.get('fin') else '')
                    for e in (d.get('entries') or []) if e)
                print('  %5.1f %-13s %-14s %4s %8s %-34s %8s %8s %8s'
                      % (t, str(d.get('g')), str(d.get('label')), d.get('qLen'),
                         d.get('qUt'), ents[:34],
                         d.get('Param278'), d.get('Param45'), d.get('Param46')))
            time.sleep(0.5)

        print('\n=== 判定 ===')
        late = [(t, d) for t, d in recs if t > 4.0]
        ql = [d.get('qLen') for _, d in late]
        print('  回落后 qLen 取值集合:', sorted(set(ql)))
        v = [d.get('Param278') for _, d in late if isinstance(d.get('Param278'), (int, float))]
        print('  Param278 范围: %s ~ %s  波动=%.3f'
              % (min(v) if v else '-', max(v) if v else '-',
                 (max(v) - min(v)) if v else 0))
        gl = sorted(set(str(d.get('g')) for _, d in late))
        print('  回落后组名集合:', gl)
        print()
        if len(ql) and max(ql) > 1:
            print('==> 队列堆积确认：qLen 曾达到 %d' % max(ql))
        else:
            print('==> 队列没有堆积（qLen 恒为 %s）' % (ql[0] if ql else '-'))
        if v and (max(v) - min(v)) > 0.3:
            print('==> 参数在变化 ⇒ 有 motion 在驱动，处于循环中')
        else:
            print('==> 参数冻结 ⇒ 画面静止')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
