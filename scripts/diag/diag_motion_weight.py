# -*- coding: utf-8 -*-
"""查 motion 权重/曲线应用：为什么 ParamAngleX 恒 0、Param194 只有 0.61（应 10）。

已排除：restTick 拉回、focusController 覆盖。
已确认：动作整体生效（Param194 在变）、ParamAngleX 常量 0、且变化幅度远低于曲线值。

本脚本读 Cubism 4 Motion 对象的真实内部字段（_motionData / _weight / _fadeInSeconds /
_loopDurationSeconds / _isLoopFadeIn），并手动求曲线在某一时刻的值作为对照：
  - 若 _motionData.parameters 里有 ParamAngleX → 曲线在库内
  - 若 _weight 很小 → fade in 未完成，值被按权重插值压制 → 这解释"值远低于曲线"
  - 手动求值 vs 实际参数值 → 判定"库没写"还是"写了但被覆盖"
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
    if(proto.__dshHookMW) return; proto.__dshHookMW=true;
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

# 读 motion 内部字段 + 曲线结构
MOTION_INNER = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, mm=im.motionManager;
    const arr=(mm.motionGroups||{})[%s]||[];
    if(!arr.length) return JSON.stringify({n:0});
    const mo=arr[0];
    const o={
      n:arr.length,
      keys:Object.keys(mo),
      fadeIn: mo._fadeInSeconds, fadeOut: mo._fadeOutSeconds,
      weight: mo._weight, lastWeight: mo._lastWeight,
      offset: mo._offsetSeconds,
      loopDur: mo._loopDurationSeconds,
      isLoop: mo._isLoop, isLoopFadeIn: mo._isLoopFadeIn,
      srcFps: mo._sourceFrameRate,
      curTime: (typeof mo.getCurrentTime==='function')? mo.getCurrentTime() : null,
      dur: (typeof mo.getDuration==='function')? mo.getDuration() : null
    };
    const md=mo._motionData;
    o.hasMotionData=!!md;
    if(md){
      o.mdKeys=Object.keys(md);
      const ps=md.parameters || md._parameters;
      o.hasParams=!!ps;
      o.paramCount=ps?ps.length:null;
      if(ps){
        const ax=ps.find(p=>p.id==='ParamAngleX');
        const p194=ps.find(p=>p.id==='Param194');
        const dump=(p)=>{
          if(!p) return null;
          const c=p.curve;
          return {id:p.id, hasCurve:!!c, curveLen:c?c.length:null,
                  curveHead:c?_slice(c,0,10):null,
                  fadeIn:p.fadeInTime, fadeOut:p.fadeOutTime};
        };
        o.angleX=dump(ax); o.p194=dump(p194);
        function _slice(c,s,e){ try{ return Array.from(c).slice(s,e); }catch(x){ return null; } }
      }
    }
    return JSON.stringify(o);
  }catch(e){ return JSON.stringify({err:String(e), stack:(e&&e.stack)?String(e.stack).slice(0,300):null}); }
})()
""" % json.dumps(GROUP)

# 每帧：同时读 参数实际值 / motion 曲线手动求值 / 权重 / 时间
FRAME = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, cm=im.coreModel;
    const mm=im.motionManager, st=mm.state||{};
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0];
    const gv=(p)=>{ try{const i=cm.getParameterIndex(p);
                       return i>=0? cm.getParameterValueByIndex(i): null;}catch(e){return null;} };
    const o={g:st.currentGroup,
             pri:st.currentPriority,
             angleX:gv('ParamAngleX'), p194:gv('Param194'),
             p207:gv('Param207'), p315:gv('Param315')};
    if(mo){
      o.w = mo._weight; o.lw = mo._lastWeight;
      o.t = (typeof mo.getCurrentTime==='function')? mo.getCurrentTime() : null;
      o.fi = mo._fadeInSeconds;
      o.off = mo._offsetSeconds;
      // 手动求 ParamAngleX 曲线在 t 处的值
      try{
        const md=mo._motionData;
        const ps=md && (md.parameters||md._parameters);
        const ax=ps && ps.find(p=>p.id==='ParamAngleX');
        const p1=ps && ps.find(p=>p.id==='Param194');
        const evalC=(p)=>{ if(!p||!p.curve) return null;
          const c=Array.from(p.curve); const tt=o.t;
          // curve 是 [time, value, ...] 扁平数组，按 2*count 布局
          const pts=[]; for(let i=0;i+1<c.length;i+=2){ pts.push([c[i],c[i+1]]); }
          if(!pts.length) return null;
          if(tt<=pts[0][0]) return pts[0][1];
          if(tt>=pts[pts.length-1][0]) return pts[pts.length-1][1];
          for(let i=0;i+1<pts.length;i++){
            const a=pts[i], b=pts[i+1];
            if(tt>=a[0] && tt<=b[0]){
              if(b[0]-a[0]<1e-9) return b[1];
              const r=(tt-a[0])/(b[0]-a[0]);
              return a[1]+(b[1]-a[1])*r;
            }
          }
          return null; };
        o.curveAngleX=evalC(ax); o.curveP194=evalC(p1);
      }catch(e){ o.curveErr=String(e).slice(0,120); }
    }
    return JSON.stringify(o);
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

    pg = open_page(URL, tag='mw')
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
        time.sleep(0.35)

        print('\n[1] motion 内部字段')
        inner = json.loads(pg.ev(MOTION_INNER))
        for k in ['n', 'fadeIn', 'fadeOut', 'weight', 'lastWeight', 'offset', 'loopDur',
                  'isLoop', 'isLoopFadeIn', 'srcFps', 'curTime', 'dur',
                  'hasMotionData', 'mdKeys', 'hasParams', 'paramCount', 'err', 'stack']:
            if k in inner:
                v = inner[k]
                if k == 'mdKeys' and isinstance(v, list):
                    v = ','.join(v[:14])
                print('  %-14s %s' % (k, v))
        if inner.get('angleX'):
            print('  ParamAngleX   %s' % inner['angleX'])
        else:
            print('  ParamAngleX   【_motionData.parameters 里找不到】')
        if inner.get('p194'):
            print('  Param194      %s' % inner['p194'])

        print('\n[2] 逐帧：参数实际值 vs 曲线求值 vs 权重')
        print('  %7s %9s %6s %9s %10s %10s %10s %10s'
              % ('t', 'weight', 'pri', 'motionT', 'AngleX', 'curveAX', 'p194', 'curve194'))
        t0 = time.time()
        while time.time() - t0 < 3.4:
            f = json.loads(pg.ev(FRAME))
            if 'err' in f:
                print('  ERR', f['err'])
                break
            def fm(v, w='10.3f'):
                return ('%10.3f' % v) if isinstance(v, (int, float)) else (' ' * (w - 1) + '-')
            print('  %7.2f %9s %6s %9s %s %s %s %s'
                  % (f.get('t') or 0, ('%9.3f' % f['w']) if isinstance(f.get('w'), (int, float)) else '     -',
                     f.get('pri'), ('%9.3f' % f['t']) if isinstance(f.get('t'), (int, float)) else '     -',
                     fm(f.get('angleX')), fm(f.get('curveAngleX')),
                     fm(f.get('p194')), fm(f.get('curveP194'))))
            time.sleep(0.2)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
