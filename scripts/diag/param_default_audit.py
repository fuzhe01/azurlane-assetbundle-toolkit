"""取 moc3 里各参数的 (min, max, default)，与动作里写入的定值逐条比对。

关键问题：idle 把 Beimian_Hand_* / Zhengmian_Hand_* 全定成 0.0，
而 motion_chain.json 的 switch_params 里这些参数是 -40 / -10 / 5 / 9 / 18。
哪个才是模型默认（静止）姿势？0 还是那组非零值？

做法：用 Cubism Core 在浏览器里读 getParameterDefaultValue（最权威），
同时列出 idle 定值与默认值的差。

用法: py -3 scripts/diag/param_default_audit.py ougen_8
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
PORT = 9330
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
MD = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPD) return; proto.__dshHookPD=true;
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


def clip_const(clip):
    p = os.path.join(MD, clip + '.motion3.json')
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding='utf-8'))
    out = {}
    for c in d.get('Curves', []):
        s = c.get('Segments') or []
        if len(s) == 5 and abs(s[1] - s[-1]) < 1e-9:
            out[c.get('Id')] = s[1]
    return out


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    ci = clip_const('idle')
    names = [k for k in ci if 'Hand' in k]
    print('idle 定值里的手部参数:', names)

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_pd'), URL, (1400, 1000))
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

        r = pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return JSON.stringify({err:'NO_MODEL'});
          var core=m.internalModel.coreModel;
          var ids=%s;
          var out={};
          ids.forEach(function(id){
            try{
              var i=core.getParameterIndex(id);
              if(i<0){ out[id]={missing:true}; return; }
              out[id]={idx:i,
                       min:+core.getParameterMinimumValue(i).toFixed(3),
                       max:+core.getParameterMaximumValue(i).toFixed(3),
                       def:+core.getParameterDefaultValue(i).toFixed(3)};
            }catch(e){ out[id]={err:String(e)}; }
          });
          return JSON.stringify(out);
        })()
        """ % json.dumps(names))
        d = json.loads(r)
        print('\n=== moc3 参数定义 vs idle 定值 ===')
        print('%-22s %8s %8s %8s | %8s %s' % ('参数', 'min', 'max', 'default', 'idle定值', '判断'))
        for k in names:
            v = d.get(k, {})
            cv = ci.get(k)
            if 'missing' in v:
                print('%-22s  参数不存在（该曲线的 Id 不在参数表里）' % k)
                continue
            flag = ''
            if cv is not None and abs(cv - v.get('def', 0)) > 1e-6:
                flag = '<<< 与默认值不同'
            print('%-22s %8.3f %8.3f %8.3f | %8.3f %s'
                  % (k, v.get('min', 0), v.get('max', 0), v.get('def', 0), cv if cv is not None else -999, flag))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())