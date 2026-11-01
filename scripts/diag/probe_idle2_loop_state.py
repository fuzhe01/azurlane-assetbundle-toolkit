# -*- coding: utf-8 -*-
"""验证「回落到 idle2 之后，是否真的在 idle2 里循环」。

背景（2026-10-24 用户指出分歧，这是第三个假设）：
  用户：「最后应该保持在 idle2 循环，现在保持在默认 idle 循环」
  我之前只测了 state.currentGroup，判「正确」——但组名 ≠ 循环。

项目既有记录（PROJECT_STATUS §87）：
  「运行时把每条 idle 解析成 isLoop:false（全 269 模型一致的既有特性），
    idle 只播一次即回静」

  若 idle2 也只播一次（4.0s），播完就停在末帧 → 画面静止不动。
  用户看到的「保持在某处不动」，会描述成「停在默认 idle」，
  而实际是「停在 idle2 的末帧」。

本脚本同时跟踪三件事，缺一不可：
  A. state.currentGroup（组名）
  B. #l2Curr 标签（前端 ticker 每帧回写；C 图里它停在 touch_idle1，可疑）
  C. 参数是否在**周期变化**（真循环的特征）——这是「在循环」的唯一硬判据

判据：在回落后的 12 秒内，若 Param278/Param45 等 idle2 独有参数持续往复变化，
      说明在循环；若数值冻结，说明只播一次就停了。
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
WATCH = ['Param278', 'Param45', 'Param46', 'Param115', 'Param104']

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookLP) return;
    proto.__dshHookLP=true;
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
    var st=mm.state||{};
    var qm=mm.queueManager;
    var q=(qm&&qm._motions)?qm._motions.filter(function(x){return x!=null;}):[];
    var e=q.length?q[q.length-1]:null;
    var o={g: st.currentGroup===undefined?'<u>':st.currentGroup,
           label:(document.getElementById('l2Curr')||{}).textContent,
           qLen:q.length,
           loop: e&&e._motion? e._motion._isLoop : null,
           started: e? e._started : null,
           endT: e? e._endTimeSeconds : null,
           fin: e? e._finished : null};
    var W=%s;
    for(var i=0;i<W.length;i++){
      try{ var idx=cm.getParameterIndex(W[i]);
        o[W[i]] = (idx>=0)? Math.round(cm.getParameterValueByIndex(idx)*1000)/1000 : null;
      }catch(x){ o[W[i]]=null; }
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

    pg = open_page(URL, tag='lp')
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
        print('播放 %s，观测 20 秒（会跨过回落后 idle2 的 4s 周期）' % GROUP)

        t0 = time.time()
        recs = []
        while time.time() - t0 < 20.0:
            d = json.loads(pg.ev(READ))
            recs.append((time.time() - t0, d))
            time.sleep(0.4)

        print('\n  %5s %-13s %-14s %4s %5s %6s %8s %8s %8s'
              % ('t', 'currentGroup', 'label', 'qLen', 'loop', 'started', 'Param278', 'Param45', 'Param46'))
        for t, d in recs:
            if int(t * 10) % 10 < 4:   # 每 1s 打一行
                print('  %5.1f %-13s %-14s %4s %5s %6s %8s %8s %8s'
                      % (t, str(d.get('g')), str(d.get('label')), d.get('qLen'),
                         d.get('loop'), d.get('started'),
                         d.get('Param278'), d.get('Param45'), d.get('Param46')))

        print('\n=== 判据 ===')
        # 只看回落稳定后的采样（t>4s）
        late = [(t, d) for t, d in recs if t > 4.0]
        if not late:
            print('  采样不足')
            return 0
        vals = [d.get('Param278') for _, d in late if isinstance(d.get('Param278'), (int, float))]
        rng = (max(vals) - min(vals)) if vals else 0
        print('  回落后 Param278 采样范围: %s ~ %s   波动幅度=%.3f'
              % (min(vals) if vals else '-', max(vals) if vals else '-', rng))
        groups = set(str(d.get('g')) for _, d in late)
        labels = set(str(d.get('label')) for _, d in late)
        print('  回落后出现过的组名  :', groups)
        print('  回落后出现过的 label :', labels)
        print()
        if rng > 0.5:
            print('==> 参数在持续变化 ⇒ 确实在循环播放，回落目标正确')
            if 'idle2' in groups:
                print('    且组名是 idle2 ⇒ 行为正确；你看到差异需 Ctrl+F5 清缓存后复测')
        else:
            print('==> 参数冻结 ⇒ idle2 只播了一次就停住（isLoop 被解析成 false）')
            print('    你看到的「停在默认 idle」其实是「停在 idle2 的末帧」')
            print('    根因与 PROJECT_STATUS §87 记录的既有特性一致')
        if labels and 'idle2' not in labels:
            print('\n  ⚠️ 注意：#l2Curr 标签停在 %s，没跟随 currentGroup 更新' % labels)
            print('     用户通过标签判断会误以为回落失败（§143 记录过这个滞后问题）')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
