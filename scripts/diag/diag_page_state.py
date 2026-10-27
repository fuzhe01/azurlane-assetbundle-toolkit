"""诊断：页面到底加载了哪些数据、模型是否就绪。

前面 verify_cos_features 全 FAIL 且 __l2model 为 undefined，
说明不是功能问题，而是**页面/模型根本没起来**。先确认环境。

用法: py -3 scripts/diag/diag_page_state.py ougen_8
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
PORT = 9481
TS = int(time.time())
URL = 'http://127.0.0.1:8778/gallery_v2/index.html?v=%d' % TS

HOOK = r"""
(function(){
  window.__fetched=[];
  var of=window.fetch;
  window.fetch=function(u){
    var url=(typeof u==='string')?u:(u&&u.url)||'';
    window.__fetched.push(url);
    return of.apply(this,arguments);
  };
  window.__errs=[];
  window.addEventListener('error',function(e){ window.__errs.push(String(e.message)); });
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPS) return; proto.__dshHookPS=true;
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


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_ps%d' % PORT), URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)

        print('JS 错误:', pg.ev("JSON.stringify(window.__errs||[])"))
        print('GALLERY:', pg.ev("typeof window.GALLERY"))

        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('卡片点击:', pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD';
          c.click(); return 'OK';})()
        """ % json.dumps(KEY)))
        time.sleep(1.6)
        print('皮肤点击:', pg.ev("""
        (function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()
        """ % json.dumps(KEY)))
        time.sleep(1.3)
        print('tab 点击:', pg.ev("""
        (function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()
        """))
        time.sleep(13)

        print('\n模型钩子:', pg.ev("typeof window.__l2model"))
        print('已 fetch 的 URL:')
        raw = pg.ev("JSON.stringify(window.__fetched||[])")
        try:
            for u in json.loads(raw):
                print('   ', u)
        except Exception:  # noqa: BLE001
            print('   ', raw)

        print('\n数据是否就绪:')
        k = json.dumps(KEY)
        probe = (
            "(function(){return JSON.stringify({"
            "COSTUME: typeof window.COSTUME,"
            "costumeKeys: window.COSTUME? Object.keys(window.COSTUME): null,"
            "paramDraw: typeof window.__paramDrawables,"
            "paramKeys: window.__paramDrawables? Object.keys(window.__paramDrawables): null,"
            "regKey: window.__costumeHitsRegistered||null,"
            "hitsN: ((window.__costumeHitsByModel||{})[" + k + "]||[]).length,"
            "bodyText: document.body.innerText.slice(0,120)"
            "});})()"
        )
        print(pg.ev(probe))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())