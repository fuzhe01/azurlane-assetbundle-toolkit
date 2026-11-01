"""直接实验：在画布上按坐标点击，找出哪个区域能「让鞋子出现/消失」，并记录参数变化。

用户线索：在红底高跟鞋位置点击 → 触发脱鞋局部动画 → 露出黑丝袜左脚。
所以「穿鞋态」与「脱鞋态」是两套参数组合。找出切换它的开关。

方法（不猜坐标，用数据驱动）：
  1. 页面有 hitAreas（Id=Touch*, Name=动作组）。把它们读出来（注意 hitAreas 的实际结构）
  2. 对每个 hitArea，用 internalModel 拿 drawable 包围盒 → 换算成屏幕坐标 → 真实点击
  3. 每次点击后 dump 全部参数，记录 diff

用法: py -3 scripts/diag/click_hitareas_dump.py ougen_8
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
PORT = 9340
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookHA) return; proto.__dshHookHA=true;
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
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_ha'), URL, (1400, 1000))
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

        # hitAreas 的实际结构
        ha = pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return 'NO_MODEL';
          var im=m.internalModel;
          var h=im.hitAreas;
          var info={type: typeof h, isArr: Array.isArray(h), len: h&&h.length};
          if(h && typeof h.length==='number'){
            info.sample = [];
            for(var i=0;i<Math.min(h.length,5);i++){
              var x=h[i];
              info.sample.push(x? Object.keys(x): null);
            }
          } else if(h) { info.keys=Object.keys(h).slice(0,10); }
          return JSON.stringify(info);
        })()
        """)
        print('hitAreas 结构:', ha)

        # 用页面自己的 hitAreas → 屏幕坐标，逐一点击
        click_plan = pg.ev("""
        (function(){
          var m=window.__l2model; if(!m) return '[]';
          var im=m.internalModel, core=im.coreModel;
          var h=im.hitAreas||[];
          var out=[];
          function bboxCenterOfDrawable(name){
            try{
              var idx=core.getDrawableIndex(name);
              if(idx<0) return null;
              var v=core.getDrawableVertexPositions(idx);
              if(!v||v.length<2) return null;
              var xs=[],ys=[];
              for(var k=0;k+1<v.length;k+=2){xs.push(v[k]);ys.push(v[k+1]);}
              return [(Math.min.apply(null,xs)+Math.max.apply(null,xs))/2,
                      (Math.min.apply(null,ys)+Math.max.apply(null,ys))/2];
            }catch(e){ return null; }
          }
          for(var i=0;i<h.length;i++){
            var id = (typeof h[i]==='object')? h[i].Id : h[i];
            var nm = (typeof h[i]==='object')? h[i].Name : null;
            var c = bboxCenterOfDrawable(id);
            out.push({id:id, name:nm, c:c});
          }
          return JSON.stringify(out);
        })()
        """)
        print('\nhitAreas → 画布中心:', click_plan[:800])
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())