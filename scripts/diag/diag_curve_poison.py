# -*- coding: utf-8 -*-
"""验证 curves.push bug 对 baseSegmentIndex / segmentCount 的实际污染范围。

已确认事实：
  - 库 parse() 先 Array.from 预分配 curveCount 个 CubismMotionCurve，再按索引填充，
    但每轮迭代末尾又 `curves.push(curve)` → 数组长度翻倍（413 -> 826）
  - 运行时 createMotion 只调一次，入参 413 曲线
  - CubismMotion.doUpdateParameters 亲自调用 evaluateCurve 得到 0 并写入
    ParamAngleX(index 255) —— 求值结果是错的，不是被覆盖

本脚本在浏览器里，对每条 curve 检查：
  a) 前 413 条各自的 segmentCount / baseSegmentIndex 是否与 JSON 的 Segments 数量一致
  b) 是否存在 segmentCount 被重复累加（= 2 倍或更多）
  c) 数组后 413 条与前 413 条是否「同一对象引用」（===）
  d) 手工用 segments/points 复算 ParamAngleX 在 t=2.0 的值，与 evaluateCurve 结果对比
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
    if(proto.__dshHookPC) return;
    proto.__dshHookPC=true;
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

PROBE = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, mm=im.motionManager;
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0], md=mo._motionData, cs=md.curves, N=md.curveCount;
    const out={N:N, len:cs.length};

    // c) 前后是否同一引用
    out.sameRef = (cs[0] === cs[N]);
    out.sameRefIdx = [];
    for(let i=0;i<5;i++){ out.sameRefIdx.push(cs[i]===cs[N+i]); }

    // a/b) 前 N 条的 segmentCount / baseSegmentIndex
    const dump=(i)=>({i:i, id:cs[i].id, seg:cs[i].segmentCount, base:cs[i].baseSegmentIndex});
    out.targets={};
    ['ParamAngleX','Param194','Param207','Param343','Param494'].forEach(k=>{
      const i=cs.findIndex(c=>c.id===k);
      out.targets[k]= i>=0? dump(i) : null;
    });
    out.head=[]; for(let i=0;i<5;i++) out.head.push(dump(i));

    // 统计 segmentCount 异常（> JSON 段数）
    const bad=[];
    for(let i=0;i<N;i++){
      if(cs[i].segmentCount>6) bad.push(dump(i));
      if(bad.length>8) break;
    }
    out.badSegCount = bad;

    // d) 手工求值 ParamAngleX
    const axIdx = cs.findIndex(c=>c.id==='ParamAngleX');
    const curve = cs[axIdx];
    const segs = [];
    const totalSeg = curve.baseSegmentIndex + curve.segmentCount;
    for(let i=curve.baseSegmentIndex;i<totalSeg;i++){
      segs.push({bpi: md.segments[i].basePointIndex,
                 st: md.segments[i].segmentType});
    }
    out.axCurve={idx:axIdx, base:curve.baseSegmentIndex, segCount:curve.segmentCount,
                 segs:segs};
    // 该曲线覆盖到的 points
    const pts=[];
    for(const s of segs){
      for(let k=0;k<=1;k++){
        const p=md.points[s.bpi+k];
        if(p) pts.push({t:p.time, v:p.value});
      }
    }
    out.axPoints=pts;
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

    pg = open_page(URL, tag='pc')
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

        d = json.loads(pg.ev(PROBE))
        if 'err' in d:
            print('ERR', d['err'])
            return 1
        print('curveCount=%s  curves.length=%s' % (d['N'], d['len']))
        print('后段与同索引前段是同一对象? %s  前5: %s'
              % (d['sameRef'], d['sameRefIdx']))
        print('\n前 5 条:')
        for h in d['head']:
            print('  idx=%-4s id=%-12s segmentCount=%-4s baseSeg=%s'
                  % (h['i'], h['id'], h['seg'], h['base']))
        print('\n关注曲线:')
        for k, v in d['targets'].items():
            if v is None:
                print('  %-12s 缺失' % k)
            else:
                print('  %-12s idx=%-4s segmentCount=%-4s baseSeg=%s'
                      % (k, v['i'], v['seg'], v['base']))
        if d.get('badSegCount'):
            print('\nsegmentCount 异常（>6）的曲线:')
            for b in d['badSegCount']:
                print('  ', b)
        print('\nParamAngleX 曲线覆盖的 segments:')
        for s in (d.get('axCurve') or {}).get('segs', []):
            print('  basePointIndex=%-5s type=%s' % (s['bpi'], s['st']))
        print('ParamAngleX 覆盖的 points:')
        for p in (d.get('axPoints') or []):
            print('  t=%.4f  v=%.4f' % (p['t'], p['v']))

        ax = d['targets'].get('ParamAngleX')
        print('\n=== 判定 ===')
        if ax and ax['seg'] > 4:
            print('ParamAngleX 的 segmentCount=%s（JSON 里只有 4 段）→ 段数被污染'
                  % ax['seg'])
        elif ax:
            print('ParamAngleX 的 segmentCount=%s（JSON 4 段）✓ 正常' % ax['seg'])
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
