"""找到「脱鞋」这个互动：逐个点击 hitArea，记录参数变化，定位鞋子显隐开关。

已确认（2026-10-24）：
  - ougen_8 的 hitAreas 是字典：{动作组名: {Id, Name}}
  - 无任何 PartOpacity 曲线，也没有 0↔1 的显隐参数
  => 鞋子不是靠透明隐藏，而是靠**参数驱动的骨骼位移**
所以要做的是：找出「哪个动作组播完后，鞋子参数组合变化」。

用户说点击红底高跟鞋位置能脱鞋 → 那个 hitArea 的 Name 就是脱鞋组。
本脚本遍历全部 hitAreas，对每个：播它 → dump 参数 → 与 idle 比 diff，
并输出 diff 里 Param 编号，供人工定位「哪条参数控制鞋子」。

用法: py -3 scripts/diag/sweep_hitareas.py ougen_8
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
PORT = 9341
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'hitarea_sweep')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSW) return; proto.__dshHookSW=true;
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

DUMP = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel;
  var n=core.getParameterCount();
  var ids=null;
  try{ ids=core.getParameterIds? core.getParameterIds() : null; }catch(e){}
  if(!ids){ try{ ids=m.internalModel._parameterIds||null; }catch(e){} }
  if(!ids){ return JSON.stringify({__err__: 'NO_PARAM_IDS', count: n}); }
  var out={};
  for(var i=0;i<n;i++){ try{ out[ids[i]]=+core.getParameterValueByIndex(i).toFixed(3); }catch(e){} }
  return JSON.stringify(out);
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_sw'), URL, (1400, 1000))
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
        time.sleep(10)

        base = json.loads(pg.ev(DUMP))
        print('idle 基线参数数:', len(base))
        if len(base) < 100:
            print('[INVALID] 参数读取异常（%d 个）' % len(base)); return 2

        ha = json.loads(pg.ev("""
        (function(){var m=window.__l2model; var h=m.internalModel.hitAreas||{};
          return JSON.stringify(Object.keys(h));})()
        """))
        print('hitAreas 数:', len(ha))

        results = {}
        for name in ha:
            # 播这个组
            pg.ev("""(function(){var s=document.getElementById('l2Motion');
                       if(s) s.value=%s;
                       if(window.__l2play) window.__l2play(%s); return 1;})()"""
                 % (json.dumps(name), json.dumps(name)))
            time.sleep(4)
            cur = json.loads(pg.ev(DUMP))
            diff = {k: round((cur.get(k) or 0) - (base.get(k) or 0), 2)
                    for k in cur if k in base and abs((cur.get(k) or 0) - (base.get(k) or 0)) > 0.5}
            shot = os.path.join(OUT, '%s.png' % name)
            pg.shot(shot)
            results[name] = diff
            print('%-16s 变化 %-3d 个参数  %s' % (name, len(diff), list(diff)[:6]))

        json.dump(results, open(os.path.join(OUT, 'diffs.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('\n详细 diff 已写 .diag/hitarea_sweep/diffs.json')
        print('截图在 .diag/hitarea_sweep/*.png（可逐张看哪个状态是「穿鞋」）')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())