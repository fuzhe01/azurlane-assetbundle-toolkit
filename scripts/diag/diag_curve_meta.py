# -*- coding: utf-8 -*-
"""定位 ParamAngleX 恒 0 的根因（已排除 restTick / focusController / Target 乱序）。

已确认事实：
  - 浏览器 fetch 到的是同一份 motion3.json（413 曲线，ParamAngleX 末帧 -18.367）
  - 动作整体生效（Param194 在变），但幅度远低于曲线（实际 0.61 vs 曲线 10）
  - ParamAngleX 恒 0
  - mo._motionData 有 413 条 curves（curveCount 正确）
  - fadeIn=0.5 weight=1

本脚本深入 _motionData 内部：逐条 curves 打印 id/type/segmentCount，
并手工调用库自己的 evaluateCurve（从模块内取不到就从 window 探），
找出 ParamAngleX 那条 curve 的 type 与 segment 是否异常。

关键怀疑：parse() 里 build 的 curves[c].type 可能对某些曲线为 0(Model)，
导致第一个 for 循环提前 break —— 但 Target 全是 Parameter，所以更可能是
segments/points 索引基准错位，使 evaluateCurve 返回 0。
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
    if(proto.__dshHookCV) return; proto.__dshHookCV=true;
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

# 深挖 _motionData：打印曲线元信息（type 是枚举数字）
DUMP = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, mm=im.motionManager;
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0]; const md=mo._motionData;
    const cs=md.curves;
    const out={curveCount:md.curveCount, arrLen:cs.length,
               segmentCount:md.segments?md.segments.length:null,
               pointCount:md.points?md.points.length:null,
               fps:md.fps, duration:md.duration, loop:md.loop};
    // 前 6 条 + ParamAngleX 那条的完整元信息
    const pick=(id)=>{
      const i=cs.findIndex(c=>c.id===id);
      if(i<0) return null;
      const c=cs[i];
      return {idx:i, id:c.id, type:c.type, segCount:c.segmentCount,
              baseSeg:c.baseSegmentIndex, fadeIn:c.fadeInTime, fadeOut:c.fadeOutTime};
    };
    out.head=cs.slice(0,6).map(c=>({id:c.id,type:c.type,seg:c.segmentCount,base:c.baseSegmentIndex}));
    out.targets={};
    ['ParamAngleX','Param194','Param207','Param343','Param494'].forEach(k=>{
      out.targets[k]=pick(k);
    });
    // type 分布
    const dist={};
    for(let i=0;i<cs.length;i++){ const t=cs[i].type; dist[t]=(dist[t]||0)+1; }
    out.typeDist=dist;
    // segments 前 8 个的原始字段
    if(md.segments && md.segments.length){
      out.segHead=Array.from(md.segments).slice(0,6).map(s=>({
        basePointIndex:s.basePointIndex, segmentType:s.segmentType}));
    }
    if(md.points && md.points.length){
      out.pointHead=Array.from(md.points).slice(0,6).map(p=>({t:p.time,v:p.value}));
    }
    return JSON.stringify(out);
  }catch(e){ return JSON.stringify({err:String(e), stack:String(e.stack||'').slice(0,240)}); }
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

    pg = open_page(URL, tag='cv')
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

        d = json.loads(pg.ev(DUMP))
        if 'err' in d:
            print('ERR:', d['err'])
            print(d.get('stack'))
            return 1
        print('curveCount =', d['curveCount'], ' curves.length =', d['arrLen'])
        print('segments   =', d['segmentCount'], ' points =', d['pointCount'])
        print('fps=%s duration=%s loop=%s' % (d['fps'], d['duration'], d['loop']))
        print('type 分布 =', d['typeDist'])
        print()
        print('前 6 条 curve：')
        for c in d['head']:
            print('  id=%-12s type=%s segCount=%-4s baseSeg=%s'
                  % (c['id'], c['type'], c['seg'], c['base']))
        print()
        print('关注的曲线：')
        for k, v in d['targets'].items():
            if v is None:
                print('  %-12s 【不在 curves 里】' % k)
            else:
                print('  %-12s idx=%-4s type=%s segCount=%-4s baseSeg=%-4s fadeIn=%s fadeOut=%s'
                      % (k, v['idx'], v['type'], v['segCount'], v['baseSeg'],
                         v['fadeIn'], v['fadeOut']))
        print()
        if d.get('segHead'):
            print('segments 前 6：', d['segHead'])
        if d.get('pointHead'):
            print('points 前 6：', d['pointHead'])

        # 判定
        ax = d['targets'].get('ParamAngleX')
        if ax is not None:
            print()
            if ax['segCount'] <= 0:
                print('==> ParamAngleX 的 segmentCount = 0：曲线没有被正确解析')
            elif ax['type'] != 1:
                print('==> ParamAngleX 的 type = %s（不是 Parameter=1）：会被第一个循环当 Model 或漏掉'
                      % ax['type'])
            else:
                print('==> ParamAngleX 元信息正常（type=%s seg=%s），问题在求值或后续覆盖'
                      % (ax['type'], ax['segCount']))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
