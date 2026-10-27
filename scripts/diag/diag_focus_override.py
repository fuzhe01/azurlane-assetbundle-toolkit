# -*- coding: utf-8 -*-
"""验证 focusController 是否覆盖动作曲线（ParamAngleX 恒 0 的元凶）。

上一探针（diag_rest_tick_cliff）实测：播 touch_idle14 期间 ParamAngleX 恒为 0.000，
而 motion3 里该参数末帧应为 -18.367。这说明有更高优先级的东西在写它。

pixi-live2d-display 的 InternalModel.update() 会调用 focusController.update(dt)，
它按鼠标位置写 ParamAngleX/Y/Z + ParamBodyAngleX。鼠标不动 → focus 在画布中心 → 写 0。

本脚本三步取证：
  1) 读 focusController 是否存在 / enabled / ParamAngleX 的 min-max 范围
  2) 播 touch_idle14，动作中段读 ParamAngleX（期望约 -10，实际若为 0 即证明被覆盖）
  3) focusController.enabled=false 后重播，再读同一时刻 —— 若变回负值，覆盖成立
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

import ensure_servers  # noqa: E402
from cdp_helper import open_page  # noqa: E402

KEY = 'ougen_8'
GROUP = 'touch_idle14'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookFO) return; proto.__dshHookFO=true;
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

READ = """
(function(){
  try{
    var m=window.__l2model, im=m.internalModel, cm=im.coreModel;
    var fc=im.focusController;
    var idx=cm.getParameterIndex('ParamAngleX');
    var o={
      g:(im.motionManager.state||{}).currentGroup,
      angleX: idx>=0? cm.getParameterValueByIndex(idx): null,
      hasFC: !!fc,
      fcEnabled: fc? !!fc.enabled : null,
      fcFocusX: fc&&fc._focusX!==undefined? fc._focusX : (fc&&fc.focusX!==undefined? fc.focusX : null),
      fcFocusY: fc&&fc._focusY!==undefined? fc._focusY : (fc&&fc.focusY!==undefined? fc.focusY : null),
      xMin: null, xMax: null
    };
    try{
      var mi=cm._model && cm._model.parameters;
      if(mi && mi.minimumValues && mi.maximumValues){
        o.xMin=mi.minimumValues[idx]; o.xMax=mi.maximumValues[idx];
      }
    }catch(e){}
    return JSON.stringify(o);
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""


def sample(pg, label, n=1, gap=0.15):
    out = []
    for _ in range(n):
        out.append(json.loads(pg.ev(READ)))
        time.sleep(gap)
    print('  %-22s %s' % (label, out[0]))
    return out[0]


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='focus')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              "if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(14)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        print('\n[1] 初始状态')
        st = sample(pg, 'idle 基线')

        print('\n[2] 播 %s（focusController 保持默认 enabled）' % GROUP)
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        # 在动作 40%~60% 处密集采样（motion3 显示此处 ParamAngleX 应为 -2 ~ -11）
        time.sleep(1.2)
        a = sample(pg, '动作 1.35s')
        time.sleep(0.6)
        b = sample(pg, '动作 1.95s')
        acc_x_1 = [x['angleX'] for x in (a, b)]

        print('\n[3] 关掉 focusController.enabled，重播同一动作')
        r = pg.ev("(function(){try{var im=window.__l2model.internalModel;"
                  "if(im.focusController){im.focusController.enabled=false;}"
                  "return 'disabled=' + (im.focusController? im.focusController.enabled : 'no-fc');}"
                  "catch(e){return 'ERR:'+e;}})()")
        print('  ', r)
        # 先回 idle 稳定，再重播
        pg.ev("(function(){try{window.__l2play('idle',1);}catch(e){}return 1;})()")
        time.sleep(1.5)
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(1.2)
        c = sample(pg, '动作 1.35s (FC off)')
        time.sleep(0.6)
        d = sample(pg, '动作 1.95s (FC off)')
        acc_x_2 = [x['angleX'] for x in (c, d)]

        print('\n[4] 恢复 focusController')
        pg.ev("(function(){try{window.__l2model.internalModel.focusController.enabled=true;"
              "return 1;}catch(e){return 0;}})()")

        print('\n=== 结论 ===')
        print('ParamAngleX 范围: [%s, %s]' % (st.get('xMin'), st.get('xMax')))
        print('FC 存在=%s  enabled=%s' % (st.get('hasFC'), st.get('fcEnabled')))
        print('FC 开启时动作中段 ParamAngleX =', acc_x_1)
        print('FC 关闭时动作中段 ParamAngleX =', acc_x_2)
        on_max = max(abs(v) for v in acc_x_1 if v is not None)
        off_max = max(abs(v) for v in acc_x_2 if v is not None)
        print()
        if off_max > on_max + 2.0:
            print('==> 确认：focusController 覆盖动作的 ParamAngleX'
                  '（开启时 |x|<=%.2f，关闭时 |x|<=%.2f）' % (on_max, off_max))
        else:
            print('==> 否证：关掉 FC 后 ParamAngleX 没有明显变大（%.2f -> %.2f），'
                  '不是 FC 覆盖，需另找执行者' % (on_max, off_max))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
