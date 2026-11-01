"""验证 touch_idle14 播完是否真的回落到 idle9（不只是索引里写着 idle9）。

用户观察：ougen_8 的 touch_idle14 回落到「完全不衔接的 idle」，应回落 idle9。
索引侧 motion_chain.json 里 best 已经是 idle9 —— 所以要查**运行时实际停在哪**。

判据：播 touch_idle14，等其时长+余量后，读 mm.state.currentGroup，
     与 motion_chain.json 的 best 对照。

用法: py -3 .diag/verify_touch14.py [key]
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
GROUP = sys.argv[2] if len(sys.argv) > 2 else 'touch_idle14'
PORT = 9320
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookT14) return; proto.__dshHookT14=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel) window.__l2model=c; }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

SNAP = r"""
(function(){var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var st=m.internalModel.motionManager.state||{};
  var e=document.getElementById('l2Curr');
  return JSON.stringify({group: st.currentGroup===undefined?'<undef>':st.currentGroup,
                         label: e?e.textContent:null});})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    mc = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2', 'motion_chain.json'), encoding='utf-8'))
    model = mc['models'].get(KEY, {})
    expect = (model.get('chain', {}).get(GROUP) or {}).get('best')
    dur = ((model.get('durations') or {}).get(GROUP))
    print('索引期望 best = %s，该组时长 = %s' % (expect, dur))

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_t14'), URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(9)

        r = pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(!s) return 'NO_SEL';
                   if(![...s.options].some(function(o){return o.value===%s;})) return 'NO_GROUP';
                   s.value=%s;
                   if(window.__l2play){ window.__l2play(%s); return 'PLAYED'; }
                   return 'NO_HOOK';})()""" % (json.dumps(GROUP), json.dumps(GROUP), json.dumps(GROUP)))
        print('播放:', r)

        wait = int((dur or 10) + 4)
        print('\n逐秒观察（播完应在 %ds 左右回落）:' % int((dur or 10) + 1))
        for t in range(0, wait + 1, 2):
            time.sleep(2)
            print(' t=%2ds %s' % (t + 2, pg.ev(SNAP)))

        final = json.loads(pg.ev(SNAP))
        print('\n=== 结论 ===')
        print('  实际停在: %s   索引期望: %s' % (final.get('group'), expect))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())