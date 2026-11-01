# -*- coding: utf-8 -*-
"""查清：播 touch_idle14 时 ParamAngleX 恒为 0 —— 动作曲线到底有没有生效。

已否证两个假设：
  - restTick 拉回（实测断崖参数未被拉回，动作期间 restTick 直接 return）
  - focusController 覆盖（实测 fcEnabled=false，关掉也无变化）

本脚本在浏览器里做三件事，全部读运行时真实对象，不读磁盘：
  1) fetch 实际 URL 的 motion3.json（确认拿到的是不是我们分析的那份），
     打印 ParamAngleX 曲线的原始 Segments 与曲线条数
  2) 读 motionManager 里已加载的 touch_idle14 motion 对象（_model.parameters /
     parameters 数组），确认库拿到的曲线里 ParamAngleX 是否存在
  3) 播放中逐帧读 ParamAngleX，并在同一帧同时读 Param194（已知会变的对照），
     判断是"所有参数都没生效"还是"只有 ParamAngleX 没生效"
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
MOTION_URL = 'http://127.0.0.1:8778/Live2D/ougen_8/motion/touch_idle14.motion3.json'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookMO) return; proto.__dshHookMO=true;
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

# 1) fetch 实际文件并解析
FETCH_PROBE = """
(async function(){
  try{
    const r=await fetch(%s, {cache:'no-store'});
    const j=await r.json();
    const cs=j.Curves||[];
    const ang=cs.find(c=>c.Id==='ParamAngleX');
    const p194=cs.find(c=>c.Id==='Param194');
    return JSON.stringify({
      url: r.url,
      status: r.status,
      curveCount: cs.length,
      meta: j.Meta,
      angleX: ang? {seg: ang.Segments.slice(0,18), len: ang.Segments.length} : null,
      p194: p194? {seg: p194.Segments.slice(0,12), len: p194.Segments.length} : null
    });
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
""" % json.dumps(MOTION_URL)

# 2) 库已加载的 motion 对象
LOADED_PROBE = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, mm=im.motionManager;
    const arr=(mm.motionGroups||{})[%s]||[];
    if(!arr.length) return JSON.stringify({n:0});
    const mo=arr[0];
    const out={n:arr.length, keys:Object.keys(mo)};
    try{
      const md=mo._model||mo;
      const ps=md.parameters||md._parameters;
      out.hasParams=!!ps;
      out.paramCount=ps?ps.length:null;
      if(ps){
        out.hasAngleX=ps.some(p=>p.id==='ParamAngleX');
        out.has194=ps.some(p=>p.id==='Param194');
        const ax=ps.find(p=>p.id==='ParamAngleX');
        out.angleXCurve=ax? {value:ax.value, pts:ax.curve?(ax.curve.length):null,
                             types:ax.curve?Array.from(ax.curve).slice(0,10):null} : null;
      }
    }catch(e){ out.innerErr=String(e); }
    return JSON.stringify(out);
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
""" % json.dumps(GROUP)

# 3) 逐帧读（一个 rAF 内同时读多个参数 + 曲线求值对照）
FRAME_PROBE = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, cm=im.coreModel;
    const mm=im.motionManager;
    const st=mm.state||{};
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0];
    const gv=(p)=>{ try{const i=cm.getParameterIndex(p);
                       return i>=0? cm.getParameterValueByIndex(i): null;}catch(e){return null;} };
    const out={g:st.currentGroup, t:performance.now(),
               angleX:gv('ParamAngleX'), p194:gv('Param194'), p207:gv('Param207'),
               p315:gv('Param315'), p343:gv('Param343'),
               eyeOpen:gv('ParamEyeLOpen')};
    try{
      if(mo){
        const md=mo._model||mo;
        const ps=md.parameters||md._parameters;
        if(ps){ const ax=ps.find(p=>p.id==='ParamAngleX');
          out.motionAngleX = ax? ax.value : null; }
        out.motionTime = (typeof mo.getCurrentTime==='function')? mo.getCurrentTime() : null;
      }
    }catch(e){}
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

    pg = open_page(URL, tag='mo')
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

        print('\n[1] 浏览器 fetch 的实际 motion3.json')
        d = json.loads(pg.ev(FETCH_PROBE))
        print('  url      :', d.get('url'))
        print('  status   :', d.get('status'))
        print('  Meta     :', d.get('meta'))
        print('  曲线数   :', d.get('curveCount'))
        if d.get('angleX'):
            print('  ParamAngleX 段长度=%s' % d['angleX']['len'])
            print('    Segments[前18]=', d['angleX']['seg'])
        else:
            print('  ParamAngleX: 【不存在】')
        if d.get('p194'):
            print('  Param194 段长度=%s Segments[前12]=%s' % (d['p194']['len'], d['p194']['seg']))

        # 先播一次让它加载
        print('\n[2] 播放并观察动作中段逐帧')
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(0.5)

        print('\n  库已加载的 motion 对象：')
        print('  ', pg.ev(LOADED_PROBE))

        frames = []
        t0 = time.time()
        while time.time() - t0 < 2.4:
            frames.append(json.loads(pg.ev(FRAME_PROBE)))
            time.sleep(0.12)

        print('\n  逐帧（每 3 帧一行）：')
        print('  %8s %14s %10s %10s %10s %10s %10s %12s'
              % ('t_ms', 'group', 'AngleX', 'p194', 'p207', 'p315', 'p343', 'motionAngleX'))
        for i, f in enumerate(frames):
            if i % 3 and i != 0:
                continue
            print('  %8.0f %14s %10s %10s %10s %10s %10s %12s'
                  % (f.get('t', 0) % 100000, str(f.get('g')),
                     f.get('angleX'), f.get('p194'), f.get('p207'),
                     f.get('p315'), f.get('p343'), f.get('motionAngleX')))

        ax = [f.get('angleX') for f in frames if f.get('angleX') is not None]
        p194 = [f.get('p194') for f in frames if f.get('p194') is not None]
        print('\n  ParamAngleX 采样范围: [%s, %s]' % (min(ax), max(ax)) if ax else '  无')
        print('  Param194   采样范围: [%s, %s]' % (min(p194), max(p194)) if p194 else '  无')
        print()
        if ax and max(abs(v) for v in ax) < 0.5:
            print('==> ParamAngleX 全程为 0：该参数没被动作驱动')
        else:
            print('==> ParamAngleX 有值')
        if p194 and (max(p194) - min(p194)) > 0.5:
            print('==> Param194 有变化：动作整体是生效的')
        else:
            print('==> Param194 无变化：动作整体没生效')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
