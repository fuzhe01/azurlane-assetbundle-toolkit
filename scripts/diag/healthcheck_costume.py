# -*- coding: utf-8 -*-
"""只读体检：参数型互动区 + 参数跨动作保留，当前到底能用到什么程度。

用户问「分步重做如何了」，要求先别改任何文件，只报告状态。
本脚本纯只读（只 hook addChild 拿模型引用，不改任何参数/不触发任何点击），
逐项核对五件事，每项给 PASS/FAIL 与该看的具体数值：

  R1 数据层：costume_params.json / param_drawables.json 可加载，参数条数正确
  R2 热区：__costumeBoxes() 能列出热区，且驱动部件数 > 0
  R3 点击链路：__costumeScreenOf 能反解出屏幕点，__costumeHit 在该点命中目标参数
  R4 写入效果：toggle 后参数值真的从 lo 变到 hi（读 coreModel）
  R5 保留效果：切一个动作（该动作会把这个参数写成定值）后，参数是否被拉回 0

注意：R4/R5 会调用页面自己的 __costumeToggle / __l2play，属于"走产品入口"的验收；
      但本脚本不写任何文件、不改前端代码。
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
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookHC) return;
    proto.__dshHookHC=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c&&c.internalModel&&c.internalModel.coreModel){
          if(c.destroyed!==true) window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
})();
"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1

    pg = open_page(URL, tag='hc')
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
        time.sleep(15)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        print('\n' + '=' * 72)
        print('R1 数据层')
        print('=' * 72)
        r1 = pg.ev("""(function(){
          var c = window.COSTUME, pd = window.__paramDrawables;
          return JSON.stringify({
            COSTUME_type: typeof c,
            costumeKeys: c? Object.keys(c) : null,
            costumeN: (c && c[%s])? c[%s].length : null,
            paramDrawN: (pd && pd[%s])? Object.keys(pd[%s]).length : null,
            params: (c && c[%s])? c[%s].map(function(x){return x.id+'('+x.label+')';}) : null
          });
        })()""" % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY), json.dumps(KEY),
                    json.dumps(KEY), json.dumps(KEY)))
        d1 = json.loads(r1)
        print('  COSTUME 类型 :', d1.get('COSTUME_type'))
        print('  模型 key     :', d1.get('costumeKeys'))
        print('  换装参数条数 :', d1.get('costumeN'))
        print('  paramDrawables 参数数 :', d1.get('paramDrawN'))
        print('  参数清单     :', d1.get('params'))
        print('  → R1', 'PASS' if d1.get('costumeN') else 'FAIL')

        print('\n' + '=' * 72)
        print('R2 热区生成')
        print('=' * 72)
        r2 = pg.ev("""(function(){
          try{
            var b = window.__costumeBoxes? window.__costumeBoxes() : null;
            if(!b) return JSON.stringify({hasFn:false});
            return JSON.stringify({hasFn:true, n:b.length,
              rows: b.map(function(o){ return {id:o.id, nDrv:o.nDrawables,
                          w:Math.round(o.w||0), h:Math.round(o.h||0)}; })});
          }catch(e){ return JSON.stringify({err:String(e)}); }
        })()""")
        d2 = json.loads(r2)
        print('  __costumeBoxes 存在:', d2.get('hasFn'))
        print('  热区数:', d2.get('n'))
        for row in (d2.get('rows') or []):
            print('    %-14s 驱动部件=%-4s 尺寸=%sx%s'
                  % (row['id'], row['nDrv'], row['w'], row['h']))
        zero = [r for r in (d2.get('rows') or []) if not r.get('nDrv')]
        print('  → R2', 'PASS' if d2.get('n') and not zero else
              ('PARTIAL（%d 个热区驱动部件为 0）' % len(zero) if zero else 'FAIL'))

        print('\n' + '=' * 72)
        print('R3 点击链路（反解屏幕点 → 命中判定）')
        print('=' * 72)
        r3 = pg.ev("""(function(){
          try{
            var want = 'ShoseOff';
            var pt = window.__costumeScreenOf? window.__costumeScreenOf(want) : null;
            if(!pt) return JSON.stringify({ok:false, why:'__costumeScreenOf 返回空'});
            var hit = window.__costumeHit? window.__costumeHit(pt[0], pt[1]) : null;
            return JSON.stringify({ok:true, pt:pt, hitId: hit? hit.id : null,
                                   hitDrv: hit? hit.nDrawables : null});
          }catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
        })()""")
        d3 = json.loads(r3)
        print('  反解结果:', json.dumps(d3, ensure_ascii=False))
        print('  → R3', 'PASS' if d3.get('hitId') == 'ShoseOff' else 'FAIL')

        print('\n' + '=' * 72)
        print('R4 写入效果（toggle 后读 coreModel）')
        print('=' * 72)
        before = pg.ev("""(function(){var m=window.__l2model,cm=m.internalModel.coreModel;
          try{return cm.getParameterValueById('ShoseOff');}catch(e){return 'ERR';}})()""")
        pg.ev("(function(){try{return window.__costumeToggle('ShoseOff');}catch(e){return 'E';}})()")
        time.sleep(1.2)
        after = pg.ev("""(function(){var m=window.__l2model,cm=m.internalModel.coreModel;
          try{return cm.getParameterValueById('ShoseOff');}catch(e){return 'ERR';}})()""")
        print('  toggle 前 ShoseOff =', before)
        print('  toggle 后 ShoseOff =', after)
        changed = (isinstance(before, (int, float)) and isinstance(after, (int, float))
                   and abs(after - before) > 0.5)
        print('  → R4', 'PASS' if changed else 'FAIL')

        print('\n' + '=' * 72)
        print('R5 跨动作保留（播一个会把 ShoseOff 写成定值的动作）')
        print('=' * 72)
        pins = pg.ev("""(function(){var p=(window.__costumePinsByModel||{})[%s];
          return JSON.stringify(p||null);})()""" % json.dumps(KEY))
        print('  当前 pins        :', pins)
        pg.ev("(function(){try{window.__l2play('touch_idle14',3);}catch(e){}return 1;})()")
        time.sleep(5.0)
        mid = pg.ev("""(function(){var m=window.__l2model,cm=m.internalModel.coreModel;
          try{return cm.getParameterValueById('ShoseOff');}catch(e){return 'ERR';}})()""")
        print('  播动作后 ShoseOff =', mid)
        pinv = json.loads(pins) if pins and pins != 'null' else {}
        kept = (isinstance(mid, (int, float)) and 'ShoseOff' in pinv
                and abs(mid - pinv['ShoseOff']) < 0.3)
        print('  pins 里 ShoseOff 值 =', pinv.get('ShoseOff'))
        print('  → R5', 'PASS（被 pin 保住）' if kept else
              ('FAIL（被动作拉回）' if isinstance(mid, (int, float)) else '无法判定'))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
