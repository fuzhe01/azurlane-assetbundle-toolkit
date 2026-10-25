"""诊断：stateApply 里的装扮参数保留为什么没生效。

三个可能：
  A. stateApply 根本没被 beforeModelUpdate 调用
  B. 调用了，但 window.__costumePinsByModel[sk.key] 取不到（sk.key 不一致）
  C. 写进去了，但随后被 loadParameters 覆盖（时机不对）

做法：在页面里直接挂观察器，看 stateApply 是否执行、pm 是否为空、写入后值是否被改回。

用法: py -3 scripts/diag/diag_persist_why.py ougen_8
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

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookDPW) return; proto.__dshHookDPW=true;
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

    pg = open_page(URL, tag='dpw')
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

        print('模型:', pg.ev("typeof window.__l2model"))
        # A: 挂一个观察器统计 beforeModelUpdate 触发次数
        r = pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return 'NO_MODEL';
          var im=m.internalModel;
          window.__evCount=0;
          try{ im.on('beforeModelUpdate', function(){ window.__evCount++; }); }catch(e){ return 'HOOK_FAIL:'+e; }
          return 'HOOKED';
        })()
        """)
        print('挂观察器:', r)
        time.sleep(2)
        print('2 秒内 beforeModelUpdate 触发次数:', pg.ev("window.__evCount"))

        # B: 设 pins 看 pm 能否被读到
        r2 = pg.ev("""
        (function(){
          var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
          if(!pm[%s]) pm[%s]=Object.create(null);
          pm[%s]['ShoseOff']=1;
          var seen=(window.__costumePinsByModel||{})[%s];
          return JSON.stringify({
            keys: Object.keys(window.__costumePinsByModel||{}),
            seenKeys: seen? Object.keys(seen): null,
            seenVal: seen? seen['ShoseOff']: null
          });
        })()
        """ % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY), json.dumps(KEY)))
        print('设 pins:', r2)

        # C: 等几秒看值是否被 stateApply 写成 1
        for t in (1, 2, 3):
            time.sleep(1.5)
            v = pg.ev("""(function(){var m=window.__l2model;
              return +m.internalModel.coreModel.getParameterValueById('ShoseOff').toFixed(3);})()""")
            print('  等 %ds 后 ShoseOff = %s' % (t * 1.5, v))

        # D: 看 stateApply 是否真的在这个闭包里（检查全局是否暴露了它的痕迹）
        print('\nstateApply 相关线索:')
        print(pg.ev("""JSON.stringify({
            hasPins: !!(window.__costumePinsByModel && window.__costumePinsByModel[%s]),
            evCount: window.__evCount,
            coreHasSet: typeof window.__l2model.internalModel.coreModel.setParameterValueById
        })""" % json.dumps(KEY)))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())