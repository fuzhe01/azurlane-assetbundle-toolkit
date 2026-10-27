# -*- coding: utf-8 -*-
"""逐帧追踪 touch_idle1 的全过程：动作 → 回落 → 稳定，确认最终停在哪个组。

用户报告（2026-10-24）：`touch_idle1` 最后应该保持在 **idle2 循环**，
现在却停在**默认 idle 循环**。

数据层已确认无误（motion_chain.json）：
  touch_idle1.best = idle2, best_coverage = 0.991, raw_sse = 0.0
  （316 个共同参数逐位精确对齐，制作方刻意衔接的铁证）
  pose_keep = {} （315/316 覆盖，无姿态缺口，本就不该有 pin）

所以问题必然在前端"回落目标解析"这一段。三种可能：
  A. 回落压根没走到 best（走了 idleGroup 兜底）
  B. 走了 best 但 idle2 startMotion 失败（被优先级拒绝）→ 停住或退回 idle
  C. 走了 best、idle2 播了，但 idle2 播完后**再次**回落到 idle（二次回落）
     —— 这条最符合"最后保持在默认 idle 循环"的描述

判据：逐帧记 currentGroup 序列 + 每次变化的时刻。若序列里出现过 idle2
之后又变成 idle，就是 C（二次回落）；若从未出现 idle2，是 A 或 B。
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

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookTF) return;
    proto.__dshHookTF=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c&&c.internalModel&&c.internalModel.coreModel){
            if(c.destroyed!==true) window.__l2model=c;
          }
        }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
  /* 记录每一次 startMotion 调用：谁、什么组、什么优先级、返回了什么。
     这是判定 A/B 的关键——能看出 best 有没有被请求、请求有没有被拒。*/
  window.__SM = [];
  window.__smPatch = setInterval(function(){
    var m = window.__l2model;
    if(!m || !m.internalModel) return;
    var mm = m.internalModel.motionManager;
    if(!mm || mm.__dshSmWrapped) return;
    mm.__dshSmWrapped = true;
    var o = mm.startMotion.bind(mm);
    mm.startMotion = function(g, i, p){
      var before = (mm.state||{}).currentGroup;
      var r = o(g, i, p);
      window.__SM.push({t: performance.now(), want: g, idx: i, pri: p,
                        before: before,
                        after: (mm.state||{}).currentGroup});
      return r;
    };
    clearInterval(window.__smPatch);
  }, 100);
})();
"""

SNAP = """
(function(){
  try{
    var m=window.__l2model;
    if(!m) return JSON.stringify({err:'no model'});
    var im=m.internalModel, cm=im.coreModel, mm=im.motionManager;
    var st=mm.state||{};
    var gv=function(p){ try{var i=cm.getParameterIndex(p);
      return i>=0?cm.getParameterValueByIndex(i):null;}catch(e){return null;} };
    return JSON.stringify({
      g: st.currentGroup===undefined?'<u>':st.currentGroup,
      pri: st.currentPriority,
      resPri: st.reservePriority,
      label: (document.getElementById('l2Curr')||{}).textContent,
      A: gv('ParamAngleX')
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

    pg = open_page(URL, tag='tf')
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

        print('\n[基线]')
        print(' ', pg.ev(SNAP))
        pg.ev("window.__SM.length = 0;")

        r = pg.ev("(function(){try{return window.__l2play(%s,3);}catch(e){return 'ERR:'+e;}})()"
                  % json.dumps(GROUP))
        print('\n播放 %s -> %s   (Duration=1.500, 回落定时 = 1.5+0.6 = 2.1s)' % (GROUP, r))

        print('\n=== 逐帧组名序列（0.2s 采样，共 12s）===')
        prev = None
        t0 = time.time()
        last = None
        while time.time() - t0 < 12.0:
            d = json.loads(pg.ev(SNAP))
            t = time.time() - t0
            if d.get('g') != prev:
                print('  t=%5.2fs  %-14s pri=%s  label=%s  AngleX=%s'
                      % (t, d.get('g'), d.get('pri'), d.get('label'), d.get('A')))
                prev = d.get('g')
            last = d
            time.sleep(0.2)

        print('\n最终状态:', json.dumps(last, ensure_ascii=False))

        print('\n=== startMotion 调用记录（回落真相在这里）===')
        sm = json.loads(pg.ev("JSON.stringify(window.__SM||[])"))
        if not sm:
            print('  （无记录：包装未生效）')
        else:
            t_base = sm[0]['t']
            for e in sm:
                print('  +%6.0fms  want=%-14s pri=%-3s  %-14s -> %-14s'
                      % (e['t'] - t_base, e['want'], e['pri'],
                         str(e['before']), str(e['after'])))

        # 判定
        groups_seq = []
        for e in sm:
            g = e['after']
            if g is not None and (not groups_seq or groups_seq[-1] != g):
                groups_seq.append(g)
        print('\n=== 判定 ===')
        print('  组名变化序列:', ' -> '.join(str(g) for g in groups_seq))
        seen_idle2 = 'idle2' in [str(g) for g in groups_seq]
        final_is_idle2 = str(last.get('g')) == 'idle2'
        final_is_idle = str(last.get('g')) == 'idle'
        print('  是否出现过 idle2 :', seen_idle2)
        print('  最终组          :', last.get('g'))
        print()
        if final_is_idle2:
            print('==> 正确：最终停在 idle2')
        elif seen_idle2 and final_is_idle:
            print('==> 确认 C：曾回落到 idle2，但又二次回落到默认 idle')
        elif not seen_idle2:
            print('==> 确认 A/B：从未请求到 idle2（回落目标没解析成 best，或 startMotion 被拒）')
        else:
            print('==> 停在 %s，需继续查' % last.get('g'))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
