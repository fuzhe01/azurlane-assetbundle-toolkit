"""探明「参数名」的正确取法：Cubism Core / patched.js 的各种候选接口。

已确认：getParameterCount / getParameterMinimumValue / getParameterMaximumValue /
        getParameterDefaultValue / getParameterValueByIndex 全部可用。
未知：getParameterId(i) 的正确名字。已知 Cloth1 等参数存在于 moc3，
      所以只要有一个接口能拿到名字，就能枚举。

本脚本逐个试探，并打印每种方式的结果，避免再猜。

用法: py -3 scripts/diag/probe_param_names.py ougen_8
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
PORT = 9455
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPN) return; proto.__dshHookPN=true;
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

PROBE = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel;
  var out={};
  out.coreMethods = Object.keys(core).filter(function(k){return /param/i.test(k);}).slice(0,30);
  out.imParamKeys = Object.keys(im).filter(function(k){return /param/i.test(k);}).slice(0,20);
  out.modelParamKeys = Object.keys(m).filter(function(k){return /param/i.test(k);}).slice(0,20);
  function tryGet(label, fn){
    try{ var v=fn(); out[label] = (v===undefined||v===null)? 'undefined'
             : (typeof v==='string'? v : (Array.isArray(v)? ['len='+v.length, String(v[0]), String(v[1])] : typeof v)); }
    catch(e){ out[label]='EXC:'+String(e).slice(0,60); }
  }
  tryGet('core.getParameterId(0)', function(){ return core.getParameterId(0); });
  tryGet('core.getParameterIds()[0]', function(){ return core.getParameterIds()[0]; });
  tryGet('im._parameterIds[0]', function(){ return im._parameterIds[0]; });
  tryGet('core._parameterIds[0]', function(){ return core._parameterIds[0]; });
  tryGet('core.parameters[0]', function(){ return core.parameters[0]; });
  tryGet('core._model.parameters[0]', function(){ return core._model.parameters[0]; });
  tryGet('core.getParameterName?(0)', function(){ return core.getParameterName? core.getParameterName(0) : 'no-fn'; });
  return JSON.stringify(out, null, 1);
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_pn%d' % PORT), URL, (1400, 1000))
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

        print(pg.ev(PROBE))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())