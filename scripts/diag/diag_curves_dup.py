# -*- coding: utf-8 -*-
"""查清 curves.length=826 vs curveCount=413 的具体成因。

候选：
  A. parse() 被调用两次，第二次把 curves 数组重复填充（curves 是本实例字段，
     若第二次 parse 往同一数组 push 就会翻倍）
  B. 前端在加载后手动给 curves 追加了一份（例如为了"补常量曲线"）
  C. 前端代码 patch 了 CubismMotion.prototype.parse

本脚本不猜，直接：
  1) 打印 curves 前 413 条与后 413 条的 id 序列，判断是不是"整份重复"
  2) 检查 CubismMotion.prototype.parse 是否被改写（toString 与原生比对）
  3) 检查 window 上是否有前端塞的补曲线钩子
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
    if(proto.__dshHookDUP) return; proto.__dshHookDUP=true;
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

DUP = """
(function(){
  try{
    const m=window.__l2model, im=m.internalModel, mm=im.motionManager;
    const arr=(mm.motionGroups||{})[%s]||[];
    const mo=arr[0]; const md=mo._motionData; const cs=md.curves;
    const N=md.curveCount;
    const out={curveCount:N, len:cs.length};
    const ids=(a,b)=>Array.from({length:Math.max(0,b-a)},(_,k)=>cs[a+k].id);
    out.head=ids(0,8);
    out.atN=ids(N-4,N+6);            // 边界两侧
    out.tail=ids(cs.length-6,cs.length);
    // 是否整份重复：前 N 条的 id 序列 == 后 N 条的 id 序列
    let same=true, firstDiff=-1;
    const M=Math.min(N, cs.length-N);
    for(let i=0;i<M;i++){
      if(cs[i].id!==cs[N+i].id){ same=false; firstDiff=i; break; }
    }
    out.duplicated=same; out.firstDiff=firstDiff;
    // 后半段的 baseSegmentIndex 是否为 0 起（说明是第二份完整解析）
    if(cs[N]) out.secondBaseSeg=cs[N].baseSegmentIndex;
    if(cs[0]) out.firstBaseSeg=cs[0].baseSegmentIndex;
    // segments / points 是否也翻倍
    out.segLen=md.segments?md.segments.length:null;
    out.pointLen=md.points?md.points.length:null;
    // parse 是否被改写
    try{
      const P=window.CubismMotion||window.Cubism4&&window.Cubism4.CubismMotion;
      out.hasCubismMotion=!!P;
      if(P&&P.prototype&&P.prototype.parse){
        const s=String(P.prototype.parse);
        out.parseLen=s.length;
        out.parseNative=s.indexOf('__dsh')<0 && s.indexOf('curveCount')>=0;
        out.parseHead=s.slice(0,120).replace(/\\n/g,' ');
      }
    }catch(e){ out.parseErr=String(e).slice(0,120); }
    // 是否有全局补曲线痕迹
    out.winKeys=Object.keys(window).filter(k=>/curve|motion|patch|fix/i.test(k)).slice(0,20);
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

    pg = open_page(URL, tag='dup')
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

        d = json.loads(pg.ev(DUP))
        if 'err' in d:
            print('ERR', d['err'])
            return 1
        for k in ['curveCount', 'len', 'segLen', 'pointLen', 'duplicated', 'firstDiff',
                  'firstBaseSeg', 'secondBaseSeg', 'hasCubismMotion', 'parseLen',
                  'parseNative', 'parseErr', 'winKeys']:
            if k in d:
                print('  %-14s %s' % (k, d[k]))
        print('  head     ', d.get('head'))
        print('  atN(边界)', d.get('atN'))
        print('  tail     ', d.get('tail'))
        if d.get('parseHead'):
            print('  parseHead', d['parseHead'])
        print()
        if d.get('duplicated'):
            print('==> curves 是整份重复：前 %d 条与后 %d 条 id 序列完全相同'
                  % (d['curveCount'], d['curveCount']))
        else:
            print('==> 不是整份重复，首个差异 index = %s' % d.get('firstDiff'))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
