"""长时观测 + 逐帧截图：确认回落后到底闪回什么。

用户（2026-10-24）：touch_idle14 回落成功后「立马闪回初始默认 idle」。

前面 diag_pose_reset 的数据显示：组稳定停在 idle9、Param345 稳定 -1.28，
并没有被 restTick 抹平 —— 所以「闪回」不是参数被拉回默认值。

那可能是：
  A. 组真的又变了（二次回落）
  B. 组没变，但 idle9 的画面本身就很像默认待机
  C. 回落过程中间经过了 idle（一帧级闪动）

本脚本：播 touch_idle14，长时（30s）记录组名序列 + 每 2s 截图，
最后把「回落后」与「初始 idle」两张图放一起比。

用法: py -3 scripts/diag/diag_flashback.py ougen_8 touch_idle14
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
from PIL import Image, ImageChops, ImageStat  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
GROUP = sys.argv[2] if len(sys.argv) > 2 else 'touch_idle14'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'flashback')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookFB) return; proto.__dshHookFB=true;
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
  var st=m.internalModel.motionManager.state||{};
  var e=document.getElementById('l2Curr');
  return JSON.stringify({g: st.currentGroup===undefined?'<undef>':st.currentGroup,
                         label: e?e.textContent:null});
})()
"""


def diff_of(a, b):
    w = min(a.size[0], b.size[0]); h = min(a.size[1], b.size[1])
    box = (int(w * .42), int(h * .10), int(w * .99), int(h * .92))
    aa = a.crop(box); bb = b.crop(box)
    if aa.size != bb.size:
        bb = bb.resize(aa.size)
    d = ImageChops.difference(aa, bb).convert('L')
    hist = d.histogram(); tot = sum(hist)
    return ImageStat.Stat(d).mean[0], sum(hist[25:]) * 100.0 / tot


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='fb')
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

        # 基线：idle 稳定后的画面
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
          if(s) s.value='idle'; if(window.__l2play) window.__l2play('idle'); return 1;})()""")
        time.sleep(5)
        p_idle = os.path.join(OUT, 'base_idle.png')
        pg.shot(p_idle)
        print('基线 idle 已截图')

        # 播目标动作，记录组名 + 定期截图
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
          if(s) s.value=%s;
          if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(GROUP), json.dumps(GROUP)))
        print('播 %s' % GROUP)

        trace = []
        shots = {}
        t0 = time.time()
        last_shot = -99
        while time.time() - t0 < 30:
            d = json.loads(pg.ev(SNAP))
            t = round(time.time() - t0, 1)
            g = d.get('g')
            if not trace or trace[-1][1] != g:
                trace.append((t, g, d.get('label')))
                print('  t=%5.1fs 组=%-12s 标签=%s' % (t, g, d.get('label')))
            if t - last_shot >= 3.0:
                last_shot = t
                p = os.path.join(OUT, 't%02d.png' % int(t))
                pg.shot(p)
                shots[t] = p
            time.sleep(0.3)

        print('\n=== 组名轨迹 ===')
        print('  ' + ' -> '.join('%s@%.1fs' % (g, t) for t, g, _ in trace))

        # 比对：最终画面 vs 基线 idle
        final_p = max(shots)
        a = Image.open(p_idle).convert('RGB')
        b = Image.open(shots[final_p]).convert('RGB')
        mean, pct = diff_of(a, b)
        print('\n最终画面(vs 基线 idle): 平均差 %.2f  显著差 %.2f%%' % (mean, pct))
        print('  判读: 差异大 = 确实停在变体待机；差异小 = 看起来像默认待机')

        print('\n截图目录:', OUT)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())