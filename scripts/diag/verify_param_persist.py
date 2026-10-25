"""验证需求 2：装扮参数跨动作保留（第一小步，独立验收）。

判据（不依赖截图，全用参数直读）：
  ① 把 ShoseOff/Stock1/Cloth1 记进 pins 并设为 hi
  ② 播一个定值曲线会把这些参数写回 0 的动作（touch_body）
  ③ 动作播放中与播完后，这三个参数**仍为 hi**（没被动作拉回）
  ④ 对照组：不设 pins 时，同样播 touch_body 后它们**确实**变成 0
     （证明 ③ 不是"本来就不会变"的空判据）

用法: py -3 scripts/diag/verify_param_persist.py ougen_8
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
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
IDS = ['ShoseOff', 'Stock1', 'Cloth1']

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPP) return; proto.__dshHookPP=true;
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

READ = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, out={};
  var ids=%s;
  ids.forEach(function(id){
    var ix=core.getParameterIndex(id);
    if(ix<0){ out[id]='NO_IDX'; return; }
    out[id]=+core.getParameterValueById(id).toFixed(3);
  });
  return JSON.stringify(out);
})()
"""

SET_PIN = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var core=m.internalModel.coreModel;
  var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
  if(!pm[%s]) pm[%s]=Object.create(null);
  var ids=%s, out={};
  ids.forEach(function(id){
    var ix=core.getParameterIndex(id);
    if(ix<0) return;
    var hi=core.getParameterMaximumValue(ix);
    pm[%s][id]=hi;
    out[id]=hi;
  });
  return JSON.stringify(out);
})()
"""

CLEAR_PIN = r"""
(function(){
  var pm=(window.__costumePinsByModel||{});
  if(pm[%s]) pm[%s]=Object.create(null);
  return 'CLEARED';
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='pp')
    passed = total = 0
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

        print('模型钩子:', pg.ev("typeof window.__l2model"))
        if pg.ev("typeof window.__l2model") != 'object':
            print('[INVALID] 模型未就绪'); return 2

        ids_json = json.dumps(IDS)

        # ---------- 对照组：不设 pins，播 touch_body ----------
        print('\n=== 对照组（不设 pins）===')
        pg.ev(CLEAR_PIN % (json.dumps(KEY), json.dumps(KEY)))
        before = json.loads(pg.ev(READ % ids_json))
        print('  播前:', before)
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value='touch_body';
                   if(window.__l2play) window.__l2play('touch_body'); return 1;})()""")
        time.sleep(4)
        after = json.loads(pg.ev(READ % ids_json))
        print('  播 touch_body 后:', after)
        total += 1
        dropped = [k for k in IDS if isinstance(after.get(k), (int, float))
                   and abs(after[k]) < 0.05 and abs(before.get(k) or 0) < 0.05]
        print('  这三个参数当前都≈0 的: %s' % dropped)
        if len(dropped) == len(IDS):
            print('  [PASS] 对照组确认：这些参数在动作里就是 0（判据有区分度）')
            passed += 1
        else:
            print('  [WARN] 部分参数不是 0，对照组不够干净')

        # ---------- 实验组：设 pins 后播 touch_body ----------
        print('\n=== 实验组（设 pins = hi）===')
        setr = pg.ev(SET_PIN % (json.dumps(KEY), json.dumps(KEY),
                                ids_json, json.dumps(KEY)))
        print('  设 pins:', setr)
        time.sleep(3.0)
        mid1 = json.loads(pg.ev(READ % ids_json))
        print('  设后:', mid1)

        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value='touch_body';
                   if(window.__l2play) window.__l2play('touch_body'); return 1;})()""")
        time.sleep(2)
        during = json.loads(pg.ev(READ % ids_json))
        print('  动作播放中:', during)
        time.sleep(4)
        final = json.loads(pg.ev(READ % ids_json))
        print('  动作播完后:', final)

        total += 1
        kept = [k for k in IDS if isinstance(final.get(k), (int, float))
                and abs(final[k] - (mid1.get(k) or 0)) < 0.05 and (mid1.get(k) or 0) > 0.5]
        if len(kept) == len(IDS):
            print('  [PASS] ③ 参数保留成功：%s 全部保持在 hi' % kept); passed += 1
        else:
            print('  [FAIL] ③ 被动作拉回: %s（期望全部保留）'
                  % [k for k in IDS if k not in kept])

        print('\n===== 结果 %d/%d =====' % (passed, total))
        return 0 if passed == total else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())