# -*- coding: utf-8 -*-
"""最终定位：运行时 evaluateCurve 对 ParamAngleX 返回 0 的确切原因。

已确认：
  - 库 parse() 有 push bug，curves 变成 826（前后同一对象引用）
  - ParamAngleX 自身的 baseSegmentIndex=123 / segmentCount=4 看起来正常
  - 它覆盖的 4 个 segments 的 basePointIndex 全部 = 157（不是递增）
  - 它覆盖的 points 序列 t=[0, 0.983, 0.983, 1.333, 1.333, 1.683, 1.683, 3.017]
    值 v=[0, 0, 0, -3.444, -3.444, -18.367, -18.367, -18.367]  ← 点数据是对的！

所以 points 有正确的 -18.367，但 evaluateCurve 在 t=2.0 时返回 0。
本脚本把 evaluateCurve 的每一步摊开：对 t=2.0 逐段检查 time 比较，
找出"为什么 target 落在第一段、返回 v=0"。
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
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookEV) return;
    proto.__dshHookEV=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c&&c.internalModel&&c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
})();
"""

# 把 evaluateCurve 的逻辑逐步摊开，对多个 t 求值
TRACE = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, mm=im.motionManager;
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0], md=mo._motionData, cs=md.curves;
    const ci = cs.findIndex(c=>c.id==='ParamAngleX');
    const curve = cs[ci];
    const out={ci:ci, base:curve.baseSegmentIndex, segCount:curve.segmentCount,
               segTotal:md.segments.length, pointTotal:md.points.length,
               steps:[], results:{}};
    const tEnd = curve.baseSegmentIndex + curve.segmentCount;

    // 逐步列出 evaluateCurve 会访问的 (i, basePointIndex, segType, pointPosition, point.time, point.value)
    for(let i=curve.baseSegmentIndex;i<tEnd;i++){
      const sg=md.segments[i];
      const pp = sg.basePointIndex + (sg.segmentType===1? 3:1);
      const pt = md.points[pp];
      out.steps.push({i:i, bpi:sg.basePointIndex, st:sg.segmentType, pp:pp,
                      ptTime: pt?pt.time:null, ptVal: pt?pt.value:null});
    }

    // 用 evaluateCurve 原逻辑对若干 t 求值
    const evalAt=(time)=>{
      let target=-1, pointPosition=0;
      for(let i=curve.baseSegmentIndex;i<tEnd;i++){
        pointPosition = md.segments[i].basePointIndex +
          (md.segments[i].segmentType===1?3:1);
        if(md.points[pointPosition].time > time){ target=i; break; }
      }
      if(target===-1) return {ret:'last', val: md.points[pointPosition].value, target:-1, pp:pointPosition};
      const seg=md.segments[target];
      const pts=md.points.slice(seg.basePointIndex, seg.basePointIndex+4);
      return {ret:'seg', target:target, pp:pointPosition,
              segBpi: seg.basePointIndex, segType: seg.segmentType,
              pts: pts.map(p=>({t:p.time,v:p.value}))};
    };
    [0.5, 1.0, 1.5, 1.7, 2.0, 2.5, 3.0].forEach(t=>{ out.results[t]=evalAt(t); });

    // 顺带：points 里全部 time/value（该曲线的窗口）
    out.axWindow={};
    for(let k=0;k<10;k++){
      const p=md.points[150+k];
      if(p) out.axWindow[150+k]={t:p.time, v:p.value};
    }
    return JSON.stringify(out);
  }catch(e){ return JSON.stringify({err:String(e)}); }
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

    pg = open_page(URL, tag='ev')
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

        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(0.3)

        d = json.loads(pg.ev(TRACE))
        if 'err' in d:
            print('ERR', d['err'])
            return 1
        print('ParamAngleX: idx=%s baseSeg=%s segCount=%s'
              % (d['ci'], d['base'], d['segCount']))
        print('segments 总数=%s  points 总数=%s' % (d['segTotal'], d['pointTotal']))
        print('\nevaluateCurve 的遍历步骤:')
        print('  %4s %6s %4s %6s %10s %10s' % ('i', 'bpi', 'type', 'pp', 'pt.time', 'pt.value'))
        for s in d['steps']:
            print('  %4s %6s %4s %6s %10s %10s'
                  % (s['i'], s['bpi'], s['st'], s['pp'], s['ptTime'], s['ptVal']))
        print('\n对若干 t 的求值结果:')
        for t, r in (d.get('results') or {}).items():
            print('  t=%-5s %s' % (t, json.dumps(r, ensure_ascii=False)))
        print('\npoints[150..159]:')
        for k, v in sorted((d.get('axWindow') or {}).items(), key=lambda kv: int(kv[0])):
            print('  [%s] t=%-10s v=%s' % (k, v['t'], v['v']))

        # 判定：看 pt.time 是否单调递增
        times = [s['ptTime'] for s in d['steps'] if s['ptTime'] is not None]
        print('\n=== 判定 ===')
        print('访问到的 pt.time 序列:', times)
        if len(times) >= 2 and all(times[i] <= times[i+1] for i in range(len(times)-1)):
            print('pt.time 单调不减 → 遍历可推进')
        else:
            print('pt.time 非单调 → 遍历在第一个段就 break，永远返回第一段的起始值 0 ← 根因')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
