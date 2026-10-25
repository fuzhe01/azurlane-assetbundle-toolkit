"""读取换装参数的真实值域（min/max/default/当前值）。

之前的扫描判据「不同动作间被锁成不同档位」对这些参数失效：
Cloth1-3 / Stock1-2 / ShoseOff / Paramring 在全部 45 个动作里**恒为 0.0**，
所以没有「档位差异」可判。它们是**纯互动型参数**（只由玩家操作改变）。

本脚本从 Cubism Core 读每个参数的真实定义，确定：
  - min / max / default
  - 开关型（只有 2 个合法值）还是渐变型（连续）

用法: py -3 scripts/diag/probe_costume_ranges.py ougen_8 [参数名...]
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
NAMES = sys.argv[2:] or ['Cloth1', 'Cloth2', 'Cloth3', 'Stock1', 'Stock2',
                         'ShoseOff', 'Paramring', 'ParamEyeSmile', 'HeartEyes', 'BondEyes']
PORT = 9440
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCR) return; proto.__dshHookCR=true;
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


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_cr%d' % PORT), URL, (1400, 1000))
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
        time.sleep(11)

        r = pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
          var core=m.internalModel.coreModel;
          var names=%s;
          var out={};
          names.forEach(function(n){
            try{
              var i=core.getParameterIndex(n);
              if(i<0){ out[n]={missing:true}; return; }
              out[n]={idx:i,
                      min:+core.getParameterMinimumValue(i).toFixed(3),
                      max:+core.getParameterMaximumValue(i).toFixed(3),
                      def:+core.getParameterDefaultValue(i).toFixed(3),
                      now:+core.getParameterValueByIndex(i).toFixed(3)};
            }catch(e){ out[n]={err:String(e)}; }
          });
          return JSON.stringify(out);
        })()
        """ % json.dumps(NAMES))
        d = json.loads(r)
        print('%-14s %8s %8s %8s %8s  %s' % ('参数', 'min', 'max', 'default', '当前', '类型推断'))
        for n in NAMES:
            v = d.get(n, {})
            if v.get('missing'):
                print('%-14s 不存在于参数表' % n); continue
            if v.get('err'):
                print('%-14s err %s' % (n, v['err'])); continue
            lo, hi = v['min'], v['max']
            kind = '开关(2档)' if (hi - lo) <= 1.0001 else ('渐变(连续 %.2f..%.2f)' % (lo, hi))
            print('%-14s %8.3f %8.3f %8.3f %8.3f  %s'
                  % (n, lo, hi, v['def'], v['now'], kind))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())