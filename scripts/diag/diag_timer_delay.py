"""诊断：为什么回落定时器延迟了 7 秒（3.6s → 实测 10.1s）。

候选原因：
  A. setTimeout 被上游拦截（某处覆盖了 window.setTimeout）
  B. _scheduleFallback 被多次调用，每次都 clearTimeout 重设 → 不断推迟
  C. 探针的 evaluate 太慢，把真实时间拖长了（每 0.3s 一次 SNAP，含 JSON 往返）

先排除 C（探针自身开销）：改用「页面内自记时间戳」的方式，
由页面自己记录 setTimeout 被安排/触发的时刻，探针只读结果，不做轮询。

同时记录 setTimeout 的调用次数与参数（是否被反复重设）。

用法: py -3 scripts/diag/diag_timer_delay.py ougen_8 touch_idle14
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

import cdp_helper  # noqa: E402
from cdp_helper import open_page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
GROUP = sys.argv[2] if len(sys.argv) > 2 else 'touch_idle14'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  // 1) 记录 setTimeout 的调用（>=500ms 的长延时）
  window.__stLog=[];
  var _st=window.setTimeout;
  window.setTimeout=function(fn, ms){
    if(ms>=500){
      window.__stLog.push({ms:ms, at:+(performance.now()).toFixed(0), phase:'set'});
    }
    var wrapped = function(){
      if(ms>=500) window.__stLog.push({ms:ms, at:+(performance.now()).toFixed(0), phase:'fire'});
      try{ fn.apply(this, arguments); }catch(e){ window.__stLog.push({ms:ms,phase:'ERR:'+e}); }
    };
    return _st(wrapped, ms);
  };
  // 2) 记录所有 startMotion 调用（谁在什么时候切了什么组）
  window.__smLog=[];
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookTD) return; proto.__dshHookTD=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel){
          window.__l2model=c;
          var im=c.internalModel;
          if(im.motionManager && !im.motionManager.__logged){
            im.motionManager.__logged=true;
            var os=im.motionManager.startMotion.bind(im.motionManager);
            im.motionManager.startMotion=function(g,i2,p){
              window.__smLog.push({g:g, pri:p, at:+(performance.now()).toFixed(0)});
              return os(g,i2,p);
            };
          }
        } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='td')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(15)

        # 清空记录，播目标动作
        pg.ev("window.__stLog=[]; window.__smLog=[]; performance.now()")
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
          if(s) s.value=%s;
          if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(GROUP), json.dumps(GROUP)))
        print('已播 %s，等 20 秒（不做轮询，避免探针开销）...' % GROUP)
        time.sleep(20)

        print('\n=== setTimeout 记录（>=500ms）===')
        for r in json.loads(pg.ev("JSON.stringify(window.__stLog||[])")):
            print('  ', r)

        print('\n=== startMotion 调用记录 ===')
        for r in json.loads(pg.ev("JSON.stringify(window.__smLog||[])")):
            print('  ', r)

        print('\n=== 当前状态 ===')
        print(pg.ev("""(function(){
          var m=window.__l2model; var st=m.internalModel.motionManager.state||{};
          return JSON.stringify({g: st.currentGroup===undefined?'<undef>':st.currentGroup});
        })()"""))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())