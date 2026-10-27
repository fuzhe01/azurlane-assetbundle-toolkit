# -*- coding: utf-8 -*-
"""弄清最后一个谜：updateParameters 从未被调用，画面上的呼吸是谁驱动的。

已确认：
  · 队首 idle  started=true, finished=false, loop=true, endT=-1
  · 队尾 idle2 started=false（新条目永远排不上）
  · qm._userTimeSeconds = 0
  · **Cubism4MotionManager.updateParameters 采样 0 条** ⇒ 从未被调用

  → MotionManager.update(model, now) 里 `if (!this.isFinished()) return this.updateParameters(...)`
    既然 updateParameters 没被调，说明 isFinished() 恒 true。
    但队首 idle 的 finished=false …… 矛盾。

  两个可能：
    A. `mm.update` 这个入口本身没被 InternalModel.update 调用
       （被前端/库的别的路径替代了）
    B. isFinished() 查的是**另一个** queueManager 实例

本脚本：
  1. 确认 InternalModel.update 是否每帧在跑（hook 它）
  2. 确认 mm.update 是否被调用
  3. 确认 mm.queueManager 是否与 mm 上的 isFinished 同源
  4. 若 mm.update 被调但 isFinished()==true，打印 isFinished 内部依据
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
  window.__CNT = {im:0, mm:0, mmUpd:0, isFin:0};
  window.__LOG = [];
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCNT) return;
    proto.__dshHookCNT=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c&&c.internalModel&&c.internalModel.coreModel){
            if(c.destroyed!==true){ window.__l2model=c; wrapAll(c); }
          }
        }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  function wrapAll(model){
    try{
      var im = model.internalModel;
      var mm = im.motionManager;
      /* 1. InternalModel.update */
      if(!im.__dshIM){
        im.__dshIM = true;
        var oIM = im.update.bind(im);
        im.update = function(dt, now){ window.__CNT.im++; return oIM(dt, now); };
      }
      /* 2/3. MotionManager.update —— 这里最关键：记录调用次数与返回 */
      if(mm && !mm.__dshMM){
        mm.__dshMM = true;
        var oMM = mm.update.bind(mm);
        mm.update = function(m, now){
          window.__CNT.mm++;
          var fin = null;
          try{ fin = mm.isFinished(); }catch(e){}
          var r = oMM(m, now);
          if(window.__LOG.length < 40){
            window.__LOG.push({now: now, isFin: fin, ret: r,
                               qn: (mm.queueManager&&mm.queueManager._motions)
                                     ? mm.queueManager._motions.length : null,
                               hasUPM: typeof mm.updateParameters === 'function',
                               qmSame: mm.queueManager === (mm.queueManager||null)});
          }
          return r;
        };
      }
    }catch(e){}
  }
  boot();
})();
"""

READ = """
(function(){
  var m = window.__l2model;
  var info = {};
  try{
    var im = m.internalModel, mm = im.motionManager;
    info.hasUpdateParameters = (typeof mm.updateParameters === 'function');
    info.updateParametersIsProto = (typeof mm.updateParameters === 'function')
        ? (mm.updateParameters.toString().indexOf('__CNT') >= 0) : null;
    info.ownKeysOfMM = Object.keys(mm).slice(0, 40);
    info.protoKeys = (function(){
      var k=[], p=Object.getPrototypeOf(mm);
      while(p && k.length<60){ k = k.concat(Object.getOwnPropertyNames(p)); p=Object.getPrototypeOf(p); }
      return k.filter(function(x){return /update|finish/i.test(x);});
    })();
    info.qmType = mm.queueManager ? (mm.queueManager.constructor||{}).name : null;
    info.qmMotions = (mm.queueManager&&mm.queueManager._motions)
        ? mm.queueManager._motions.length : null;
  }catch(e){ info.err = String(e); }
  return JSON.stringify({cnt: window.__CNT, info: info, log: (window.__LOG||[]).slice(-8)});
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

    pg = open_page(URL, tag='cnt')
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

        c0 = json.loads(pg.ev(READ))
        print('\n[基线 3 秒观察]')
        time.sleep(3.0)
        c1 = json.loads(pg.ev(READ))
        print('  计数差: InternalModel.update=%d  MotionManager.update=%d'
              % (c1['cnt']['im'] - c0['cnt']['im'],
                 c1['cnt']['mm'] - c0['cnt']['mm']))
        print('  hasUpdateParameters :', c1['info'].get('hasUpdateParameters'))
        print('  已包装(__CNT)        :', c1['info'].get('updateParametersIsProto'))
        print('  qm 类型              :', c1['info'].get('qmType'))
        print('  qm._motions 长度     :', c1['info'].get('qmMotions'))
        print('  mm 上 update/finish 相关键:', c1['info'].get('protoKeys'))
        if c1.get('log'):
            print('\n  MotionManager.update 最近调用:')
            for e in c1['log'][-5:]:
                print('    now=%-10s isFinished=%-6s ret=%-6s qn=%s'
                      % (e.get('now'), e.get('isFin'), e.get('ret'), e.get('qn')))

        print('\n=== 判定 ===')
        dim = c1['cnt']['im'] - c0['cnt']['im']
        dmm = c1['cnt']['mm'] - c0['cnt']['mm']
        if dim == 0:
            print('  InternalModel.update 根本没被调用 ⇒ 前端没用模型的 update 循环')
        else:
            print('  InternalModel.update 每帧在跑（%d 次/3s）' % dim)
        if dmm == 0:
            print('  MotionManager.update **没被调用**')
            print('  ⇒ 该库版本的 internalModel.update 可能不经过 mm.update，')
            print('     或前端自己维护了另一套 tick。参数由别的东西驱动。')
        else:
            print('  MotionManager.update 被调用 %d 次/3s' % dmm)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
