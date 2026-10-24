# -*- coding: utf-8 -*-
"""验证 pose_keep 是否真的保住了回落姿势（ougen_8 touch_idle14 → idle9）。

要证明的三件事：
  1. motion 阶段：ParamAngleX 到达 -18.367（动作曲线生效，不是恒 0）
  2. 回落瞬间：组变成 idle9，且 ParamAngleX 仍是 -18.367（没被 loadParameters 归零）
  3. 稳定后（>1.5s，跨过 restTick 的 400+700ms 窗口）：ParamAngleX 仍 ≈ -18.367

⚠️ 读数纪律（本轮踩过两次）：
   - 队列对象是 mm.queueManager._motions，不是 mm._motions
   - 不要读 mm.queueManager._userTimeSeconds 来算 fadeIn（它恒 0 是正常的，
     Cubism4MotionManager.updateParameters 直接把外部 now 传给 doUpdateMotion）
   - 不要 hook setParameterValue 抓栈（会拖垮主循环到 4 次/2.6s）
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

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
GROUP = sys.argv[2] if len(sys.argv) > 2 else 'touch_idle14'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  window.__ALLM = [];
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPK) return;
    proto.__dshHookPK=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c&&c.internalModel&&c.internalModel.coreModel){
            window.__ALLM.push(c);
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
    const m=window.__l2model;
    if(!m) return JSON.stringify({err:'no model'});
    const im=m.internalModel, cm=im.coreModel, mm=im.motionManager;
    const gv=(p)=>{ try{const i=cm.getParameterIndex(p);
      return i>=0? cm.getParameterValueByIndex(i): null;}catch(e){return null;} };
    const pins=(window.__posePinsByModel||{})[%s]||null;
    const ex=(window.__poseKeepKeys||{})[%s];
    return JSON.stringify({
      g:(mm.state||{}).currentGroup,
      A:gv('ParamAngleX'), P194:gv('Param194'), P207:gv('Param207'),
      P315:gv('Param315'), P10:gv('Param10'), P343:gv('Param343'),
      eyeL:gv('ParamEyeLOpen'),
      pinCount: pins? Object.keys(pins).length : 0,
      exCount: ex? ex.size : null,
      pinA: pins? pins['ParamAngleX'] : null
    });
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
""" % (json.dumps(KEY), json.dumps(KEY))


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='pk')
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
        print(' ', pg.ev(READ))

        r = pg.ev("(function(){try{return window.__l2play(%s,3);}catch(e){return 'ERR:'+e;}})()"
                  % json.dumps(GROUP))
        print('\n播放 %s -> %s' % (GROUP, r))

        print('\n  %6s %14s %10s %9s %9s %9s %6s' %
              ('t(s)', 'group', 'AngleX', 'p194', 'p207', 'p315', 'pins'))
        # 前 4.5 秒每 0.35s（覆盖动作 3.017s + 回落 + restTick 窗口）
        t0 = time.time()
        recs = []
        while time.time() - t0 < 6.5:
            d = json.loads(pg.ev(READ))
            t = time.time() - t0
            recs.append((t, d))
            def f(v):
                return ('%10.3f' % v) if isinstance(v, (int, float)) else ('%10s' % '-')
            print('  %6.2f %14s %s %9s %9s %9s %6s'
                  % (t, str(d.get('g')), f(d.get('A')), f(d.get('P194')),
                     f(d.get('P207')), f(d.get('P315')), d.get('pinCount')))
            time.sleep(0.35)

        print('\n=== 判据 ===')
        # 1) 动作播放中 ParamAngleX 是否到过负值
        in_motion = [d for t, d in recs
                     if d.get('g') == GROUP and isinstance(d.get('A'), (int, float))]
        minA = min((d['A'] for d in in_motion), default=None)
        print('动作期间的 ParamAngleX 最小值 = %s  %s'
              % (minA, '(康: 到达 -18 附近)' if minA is not None and minA < -10
                 else '(曲线没生效)' if minA is not None else ''))
        # 2) 回落后的值
        after = [(t, d) for t, d in recs if t > 3.5 and isinstance(d.get('A'), (int, float))]
        if after:
            late = after[-1]
            print('回落稳定后(t=%.1fs) 组=%s ParamAngleX=%.3f %s'
                  % (late[0], late[1].get('g'), late[1]['A'],
                     '(保持住了)' if late[1]['A'] < -10 else '(被归零/未保持)'))
            print('                 p194=%.3f  p207=%.3f  eyeL=%s'
                  % (late[1].get('P194') or 0, late[1].get('P207') or 0,
                     late[1].get('eyeL')))
        print('pins=%s  exKeys=%s' % (recs[-1][1].get('pinCount'), recs[-1][1].get('exCount')))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
