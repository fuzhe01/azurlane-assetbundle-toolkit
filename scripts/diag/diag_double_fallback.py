"""验证「二次回落」假说：动作 → best 待机组 → 又被拉回默认 idle。

用户报告（2026-10-24）：ougen_8 的 touch_idle20 先正确回落到 idle12，
**接着立马**回落到默认初始 idle。

两个候选原因：
  A. 库在 idle12 播完后请求 `groups.idle`（默认待机组），把画面拉回默认 idle
  B. 我们的 `_scheduleFallback` 有残留定时器，第二次触发时 lastGroup 已变，落到 idleGroup

本脚本做连续观测：播 touch_idle20，每 0.5s 记一次 currentGroup，看组名轨迹。
判据：若出现 `touch_idle20 → idle12 → idle` 的轨迹，说明确实有二次回落。

用法: py -3 scripts/diag/diag_double_fallback.py ougen_8 touch_idle20
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

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
GROUP = sys.argv[2] if len(sys.argv) > 2 else 'touch_idle20'
PORT = 9500
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookDF) return; proto.__dshHookDF=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

SNAP = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var st=m.internalModel.motionManager.state||{};
  var e=document.getElementById('l2Curr');
  return JSON.stringify({
    group: st.currentGroup===undefined?'<undef>':st.currentGroup,
    label: e?e.textContent:null,
    pri: st.currentPriority
  });
})()
"""


def main():
    mc = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2', 'motion_chain.json'), encoding='utf-8'))
    model = mc['models'].get(KEY, {})
    best = (model.get('chain', {}).get(GROUP) or {}).get('best')
    dur = (model.get('durations') or {}).get(GROUP)
    print('索引: %s -> best=%s, 时长=%s' % (GROUP, best, dur))

    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_df%d' % PORT), URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
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
        time.sleep(12)

        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value=%s;
                   if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(GROUP), json.dumps(GROUP)))
        print('已播 %s，开始高频采样（每 0.4s）...' % GROUP)

        trace = []
        t0 = time.time()
        while time.time() - t0 < 45:
            raw = pg.ev(SNAP)
            try:
                d = json.loads(raw)
            except Exception:  # noqa: BLE001
                d = {'raw': raw}
            g = d.get('group')
            if not trace or trace[-1][1] != g:
                trace.append((round(time.time() - t0, 1), g, d.get('pri')))
                print('  t=%5.1fs  -> %-14s pri=%s' % (round(time.time() - t0, 1), g, d.get('pri')))
            time.sleep(0.4)

        print('\n=== 轨迹（变组时刻）===')
        for t, g, pri in trace:
            print('  %5.1fs  %-14s pri=%s' % (t, g, pri))

        groups = [g for _, g, _ in trace]
        print('\n判据：期望 %s → %s；若之后又出现 idle，即为二次回落' % (GROUP, best))
        if best and best in groups:
            idx = groups.index(best)
            after = groups[idx + 1:]
            if after:
                print('  [FAIL] %s 之后又落到: %s  ← 二次回落' % (best, after))
                return 1
            print('  [PASS] 停在 %s，没有二次回落' % best)
            return 0
        print('  [FAIL] 未观察到期望的 best=%s；实际轨迹: %s' % (best, groups))
        return 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())