# -*- coding: utf-8 -*-
"""抓住 ParamAngleX 的最终写入者（谁在 motion 写入后又把它改回 0）。

已排除：
  restTick（动作期间直接 return）、focusController（enabled=false）、
  getParameterIndex 返回 -1（moc3 里确有此参数）、Target 乱序、type 枚举、
  枚举曲线段结构（Segments 完全正常，末帧 -18.367）

已知：curves 数组被库自身 push bug 变成 826，但前 413 条正确，
doUpdateParameters 只走前 413 条，所以 motion 侧写入路径是对的。

本脚本 hook coreModel.setParameterValueByIndex，
记录每次对 ParamAngleX 所在 index 的写入：谁写的（调用栈） + 写了什么值 +
写入后的立即读回值。这样能看到「motion 写 -18.367 之后是谁又写了 0」。
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
  window.__WR = [];
  window.__watching = null;
  var tries = 0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto = window.PIXI.Container.prototype;
    if(proto.__dshHookWR) return;
    proto.__dshHookWR = true;
    var orig = proto.addChild;
    proto.addChild = function(){
      for(var i=0;i<arguments.length;i++){
        var c = arguments[i];
        try{
          if(c && c.internalModel && c.internalModel.coreModel){
            window.__l2model = c;
            wrapCore(c.internalModel.coreModel);
          }
        }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  function wrapCore(cm){
    try{
      if(!cm || cm.__dshWrappedW) return;
      cm.__dshWrappedW = true;
      var idx = cm.getParameterIndex('ParamAngleX');
      window.__angleXIdx = idx;
      if(idx < 0){ window.__WR.push({note:'ParamAngleX index = -1'}); return; }
      var oSet = cm.setParameterValueByIndex;
      cm.setParameterValueByIndex = function(i, v, w){
        var r = oSet.apply(this, arguments);
        if(i === idx && window.__WR_ACTIVE){
          if(window.__WR.length < 4000){
            var st = '';
            try{ st = String(new Error().stack||'').split('\n').slice(1,6)
                   .map(function(s){return s.trim().slice(0,70);}).join(' | '); }catch(e){}
            window.__WR.push({v: v, w: (w===undefined?null:w), stack: st,
                              t: performance.now()});
          }
        }
        return r;
      };
      var oSetId = cm.setParameterValueById;
      cm.setParameterValueById = function(id, v, w){
        var r = oSetId.apply(this, arguments);
        if(id === 'ParamAngleX' && window.__WR_ACTIVE){
          if(window.__WR.length < 4000){
            var st = '';
            try{ st = String(new Error().stack||'').split('\n').slice(1,6)
                   .map(function(s){return s.trim().slice(0,70);}).join(' | '); }catch(e){}
            window.__WR.push({byId:true, v: v, w: (w===undefined?null:w), stack: st,
                              t: performance.now()});
          }
        }
        return r;
      };
      window.__WR.push({note:'wrapped ok, idx=' + idx});
    }catch(e){ window.__WR.push({note:'wrapErr ' + String(e)}); }
  }
  boot();
})();
"""

START = """
(function(){
  window.__WR.length = 0;
  window.__WR_ACTIVE = true;
  window.__WR_t0 = performance.now();
  return 1;
})()
"""

DUMP = """
(function(){
  var out = {n: window.__WR.length, active: !!window.__WR_ACTIVE,
             idx: window.__angleXIdx};
  var cnt = {};
  var vals = {};
  for(var i=0;i<window.__WR.length;i++){
    var e = window.__WR[i];
    if(e.note){ continue; }
    var k = (e.byId? 'byId':'byIdx');
    var v = (typeof e.v==='number')? e.v.toFixed(3) : String(e.v);
    var key = k + '=' + v;
    cnt[key] = (cnt[key]||0) + 1;
    var sk = (e.stack||'').slice(0,150);
    vals[sk] = (vals[sk]||0) + 1;
  }
  out.byValue = cnt;
  out.topStacks = Object.keys(vals).map(function(k){return [k, vals[k]];})
                        .sort(function(a,b){return b[1]-a[1];}).slice(0,8);
  out.first = window.__WR.slice(0,5);
  out.notes = window.__WR.filter(function(e){return e.note;}).map(function(e){return e.note;});
  return JSON.stringify(out);
})()
"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='wr')
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

        print('\nParamAngleX index =', pg.ev("window.__angleXIdx"))
        print(pg.ev("JSON.stringify((window.__WR||[]).filter(e=>e.note).map(e=>e.note))"))

        pg.ev(START)
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(2.6)
        pg.ev("window.__WR_ACTIVE = false;")

        d = json.loads(pg.ev(DUMP))
        print('\n写入记录条数:', d['n'], ' 包装成功:', bool(d['idx'] is not None and d['idx'] >= 0))
        print('notes:', d.get('notes'))
        print('\n按写入值统计:')
        for k, v in sorted((d.get('byValue') or {}).items(),
                           key=lambda kv: -kv[1])[:12]:
            print('  %-22s %d 次' % (k, v))
        print('\n最常见的调用栈:')
        for s, c in (d.get('topStacks') or [])[:6]:
            print('  [%d 次] %s' % (c, s))
        print('\n前 5 条原始记录:')
        for e in (d.get('first') or []):
            print('  ', json.dumps(e, ensure_ascii=False)[:260])

        nz = [k for k in (d.get('byValue') or {}) if k.split('=')[1] not in ('0.000',)]
        print()
        if nz:
            print('==> 存在非零写入:', nz[:6])
            zeros = sum(v for k, v in (d.get('byValue') or {}).items() if k.endswith('=0.000'))
            nonzeros = sum(v for k, v in (d.get('byValue') or {}).items() if not k.endswith('=0.000'))
            print('    非零写入总次数 = %d，零写入总次数 = %d' % (nonzeros, zeros))
            if nonzeros and zeros > nonzeros:
                print('    → motion 写了非零值，但被更频繁的零写入覆盖')
            elif nonzeros == 0:
                print('    → 只有零写入：motion 求值结果本来就是 0（曲线求值有问题）')
        else:
            print('==> 全部是零写入')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
