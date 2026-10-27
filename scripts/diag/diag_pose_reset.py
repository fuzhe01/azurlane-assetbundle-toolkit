"""验证「回落后闪回默认待机」的真因：restTick 把姿势参数拉回 moc3 默认值。

用户观察（2026-10-24）：touch_idle14 回落成功到 idle9，但**立马闪回初始默认 idle**。

关键理解：用户看到的"闪回初始 idle"很可能不是动作组变了，而是
**姿势参数被拉回默认值** —— 画面看起来就像回到了默认待机。

restTick（index.html L1613 起）的逻辑：
  当 currentGroup 是待机组时，它把「动作驱动过、但当前待机不驱动、且不在 switchParams 白名单」的参数
  从当前值**逐帧拉向 getParameterDefaultValue**。
  于是 idle9 的姿势（Param345=-1.28 等 9 条）会在 700ms 内被抹平 → 看起来像闪回了默认待机。

本脚本：播 touch_idle14，高频采样「动作组 + 关键姿势参数」，
看组变成 idle9 之后，这些参数是否又被拉回 0。

用法: py -3 scripts/diag/diag_pose_reset.py ougen_8
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

# idle9 的姿势定值（前面实测过）
POSE = ['Param345', 'Param372', 'Param494', 'Param500', 'Param502', 'Param506',
        'Param91', 'Param97', 'Param352']

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPR) return; proto.__dshHookPR=true;
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
  var m=window.__l2model; if(!m) return '{}';
  var core=m.internalModel.coreModel;
  var st=m.internalModel.motionManager.state||{};
  var o={g: st.currentGroup===undefined?'<undef>':st.currentGroup};
  %s.forEach(function(id){
    try{ o[id]=+core.getParameterValueById(id).toFixed(3); }catch(e){ o[id]=null; }
  });
  return JSON.stringify(o);
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='pr')
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
        time.sleep(14)

        snap_js = SNAP % json.dumps(POSE)

        # 先播 idle9 建立"正确姿势"的参照
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
          if(s) s.value='idle9';
          if(window.__l2play) window.__l2play('idle9'); return 1;})()""")
        time.sleep(3)
        ref = json.loads(pg.ev(snap_js))
        print('idle9 参考姿势:', {k: v for k, v in ref.items() if k != 'g'})

        # 播 touch_idle14（best=idle9），高频采样
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
          if(s) s.value=%s;
          if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(GROUP), json.dumps(GROUP)))
        print('\n播 %s，每 0.15s 采样:' % GROUP)
        print('  t(s)  组            Param345   Param494   说明')

        t0 = time.time()
        prev = None
        rows = []
        while time.time() - t0 < 10:
            d = json.loads(pg.ev(snap_js))
            t = round(time.time() - t0, 2)
            rows.append((t, d))
            if prev is None or (d.get('g') != prev.get('g')
                                or abs((d.get('Param345') or 0) - (prev.get('Param345') or 0)) > 0.2):
                note = ''
                if d.get('g') in ('idle9',) and abs((d.get('Param345') or 0) - (ref.get('Param345') or 0)) > 0.2:
                    note = '<- 组对了但姿势已偏离'
                print('  %5.2f  %-12s  %-9s  %-9s %s'
                      % (t, d.get('g'), d.get('Param345'), d.get('Param494'), note))
            prev = d
            time.sleep(0.15)

        print('\n=== 结论 ===')
        last = rows[-1][1]
        print('  最终组: %s' % last.get('g'))
        print('  Param345: 参考(idle9) %s → 最终 %s' % (ref.get('Param345'), last.get('Param345')))
        drifted = [k for k in POSE
                   if abs((last.get(k) or 0) - (ref.get(k) or 0)) > 0.2]
        print('  偏离 idle9 参考姿势的参数: %d/%d  %s' % (len(drifted), len(POSE), drifted[:6]))
        if last.get('g') in ('idle9', 'idle12', 'idle2') and drifted:
            print('  ⇒ 组正确但姿势被抹平 = 「闪回默认待机」的真因（restTick 复位）')
        elif last.get('g') == 'idle':
            print('  ⇒ 组真的变回了 idle（二次回落）')
        else:
            print('  ⇒ 姿态保持')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())