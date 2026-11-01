# -*- coding: utf-8 -*-
"""抓住 curves.length 翻倍的确切时机与调用方。

已确认：
  - 当前库与备份库的 parse() 源码逐字相同，都按 curveCount 一次性分配 curves
  - 运行时 _motionData.curves.length = 826 = 2 × curveCount(413)，且第二份 baseSeg 从 0 起
  - segments(1777) / points(2190) 没有翻倍 —— 与 Meta.TotalSegmentCount 数量一致

推论：parse() 被调用了两次；第二次往**同一数组** push（而不是重建），
或 curves 数组被外部 concat/push 追加了一份。

本脚本在页面加载前就 hook 住 parse：记录每次调用的入参 curveCount、调用栈，
以及在调用前后 curves.length 的变化，从而抓住"谁在什么时候把数组加长了一倍"。
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

# 页面前 hook：拦截 CubismMotion.parse（等库加载完再包），并记录 Array.prototype.push
HOOK = r"""
(function(){
  window.__PARSE_LOG = [];
  window.__PUSH_LOG = [];
  var tries=0;
  function patchParse(){
    // 库是 UMD，可能挂在 window 或某个模块闭包里；逐层找
    var found = null;
    var roots = [window];
    try{ if(window.PIXI) roots.push(window.PIXI); }catch(e){}
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<900) setTimeout(patchParse,20); return; }
    // hook Container.addChild 拿 model
    var proto = window.PIXI.Container.prototype;
    if(!proto.__dshHookPL){
      proto.__dshHookPL = true;
      var orig = proto.addChild;
      proto.addChild = function(){
        for(var i=0;i<arguments.length;i++){
          var c=arguments[i];
          try{
            if(c && c.internalModel && c.internalModel.coreModel){
              window.__l2model = c;
              hookMotionManager(c);
            }
          }catch(e){}
        }
        return orig.apply(this,arguments);
      };
    }
  }
  function hookMotionManager(model){
    try{
      var mm = model.internalModel && model.internalModel.motionManager;
      if(!mm || mm.__dshHookedPL) return;
      mm.__dshHookedPL = true;
      // 包 createMotion：库在这里把 json 变成 motion 对象
      var orig = mm.createMotion ? mm.createMotion.bind(mm) : null;
      if(orig){
        mm.createMotion = function(data, group, index, ...rest){
          var before = window.__PARSE_LOG.length;
          var r = orig(data, group, index, ...rest);
          try{
            var md = r && r._motionData;
            window.__PARSE_LOG.push({
              where:'createMotion', group:group, index:index,
              curveCount: md? md.curveCount : null,
              curvesLen: md&&md.curves? md.curves.length : null,
              segLen: md&&md.segments? md.segments.length : null,
              dataCurveCount: data && data.Curves? data.Curves.length : null
            });
          }catch(e){}
          return r;
        };
      }
    }catch(e){}
  }
  patchParse();
})();
"""

DUMP = """
(function(){
  var m=window.__l2model, im=m&&m.internalModel, mm=im&&im.motionManager;
  var out={log:window.__PARSE_LOG||[]};
  if(mm){
    var arr=(mm.motionGroups||{})[%s]||[];
    out.groupLen=arr.length;
    out.motions=arr.map(function(mo){
      var md=mo._motionData;
      return {curveCount: md?md.curveCount:null,
              curvesLen: md&&md.curves?md.curves.length:null,
              segLen: md&&md.segments?md.segments.length:null,
              pointLen: md&&md.points?md.points.length:null};
    });
  }
  return JSON.stringify(out);
})()
""" % json.dumps(GROUP)


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='push')
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
        time.sleep(22)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1
        print('\n[初始] 未播动作前：')
        d = json.loads(pg.ev(DUMP))
        print('  createMotion 调用次数:', len(d.get('log') or []))
        for e in (d.get('log') or [])[-6:]:
            print('   ', e)

        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(1.2)
        print('\n[播放 touch_idle14 后]')
        d2 = json.loads(pg.ev(DUMP))
        print('  createMotion 调用次数:', len(d2.get('log') or []))
        for e in (d2.get('log') or []):
            print('   ', e)
        print('\n  该组的 motion 实例:')
        for i, mv in enumerate(d2.get('motions') or []):
            print('   [%d] %s' % (i, mv))
        print()
        # 找 touch_idle14 的日志
        hits = [e for e in (d2.get('log') or []) if e.get('group') == GROUP]
        print('  touch_idle14 的 createMotion 次数 =', len(hits))
        if len(hits) >= 2:
            print('==> 同一动作被 createMotion 多次 → 每次 parse 都往 curves 追加，导致 826')
            for h in hits:
                print('   dataCurveCount=%s  resultCurvesLen=%s'
                      % (h.get('dataCurveCount'), h.get('curvesLen')))
        elif len(hits) == 1:
            print('==> 只调用一次，但返回的 curvesLen=%s（应为 413）→ parse 内部重复'
                  % hits[0].get('curvesLen'))
        else:
            print('==> 未捕获到（可能 createMotion 没被包上）')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
