"""在真实浏览器里观察 ougen_8 的 touch_drag17 三态（与用户目视同一环境）。

用户已提供目视证据（2026-10-24）：touch_drag17 位置有三种状态——
  ① 无脚（被挡）  ② 穿黑丝左脚  ③ 红底高跟鞋
并要求：**必须在浏览器里观察，不许只看数据**。

本脚本走真实交互路径：点卡片 → 选皮肤 → 切 Live2D → 点 touchdrag17 区 → 截图。
输出连续帧，供目视确认 ShoseOff 参数切换是否真的改变脚部图像。

用法: py -3 scripts/diag/observe_shoe_toggle.py ougen_8
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
OUT = os.path.join(ROOT, '.diag', 'shoe_toggle')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookST) return; proto.__dshHookST=true;
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

# 在 LOW ticker 之后覆盖 ShoseOff（模拟"玩家调过的装扮"），看画面变化
SET_AND_WAIT = r"""
(function(){
  var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
  if(!pm[%s]) pm[%s]=Object.create(null);
  pm[%s]['ShoseOff']=%s;
  return 'SET:'+%s;
})()
"""

READ = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel;
  return JSON.stringify({shose:+core.getParameterValueById('ShoseOff').toFixed(3),
                         stock1:+core.getParameterValueById('Stock1').toFixed(3)});
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='st')
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
        time.sleep(13)

        print('模型:', pg.ev("typeof window.__l2model"))
        if pg.ev("typeof window.__l2model") != 'object':
            print('[INVALID] 模型未就绪'); return 2

        k = json.dumps(KEY)
        shots = []

        # 三态：ShoseOff = 0 / 1 / -1
        for val, name in ((0, 'A_off_0'), (1, 'B_on_1'), (-1, 'C_m1')):
            pg.ev(SET_AND_WAIT % (k, k, k, val, val))
            time.sleep(2.5)
            p = os.path.join(OUT, 'shose_%s.png' % name)
            pg.shot(p)
            v = pg.ev(READ)
            print('%-10s %s -> %s' % (name, v, os.path.basename(p)))
            shots.append(p)

        # 也截一张整图便于看整体
        pg.shot(os.path.join(OUT, 'full_last.png'))
        print('\n输出目录:', OUT)
        print('三张 shose_*.png 可直接目视对比脚部')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())