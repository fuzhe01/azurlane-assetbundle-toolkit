# -*- coding: utf-8 -*-
"""R4：验证「点热区后，参数变了，画面/部件是否真的跟着变」。

遗留矛盾（probe_costume_write_timing.py 记录，2026-10-24）：
  「热区点击后参数确实变成 1 且稳定，但 pins 稳态 lo=-1 vs hi=1 逐 drawable 比对为
   **0 差异**；而同一 evaluate 内强制 im.update() 再比，却有 2 个 drawable 差异。」

本脚本用**顶点坐标**而非不透明度做判据，理由是：
  · 换装参数多改变 drawable 的**形状/位置**（鞋脱掉=部件挪走或缩放），不只是透明度
  · 不透明度可能都是 1（可见），但顶点大幅位移 —— 只看 opacity 会误判「无变化」

判据链（全部走产品入口 __costumeToggle，不 monkey-patch）：
  S0 记 ShoseOff 驱动部件 [460,461] 的顶点包围盒 + 全部 drawable 顶点哈希
  S1 __costumeToggle('ShoseOff') → 等 tween 走完(1.5s)
  S2 再记一遍
  比对：① 460/461 的顶点是否变化；② 全模型哪些 drawable 变化
  判定：460/461 有变化 → 写入到达渲染（R4 PASS）；全无变化 → 写入没到达

补充：同时记录 param_drawables 里该参数的全部驱动部件，看变化集合与之是否有交集。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import ensure_servers  # noqa: E402
from cdp_helper import open_page  # noqa: E402

KEY = 'ougen_8'
PID = sys.argv[1] if len(sys.argv) > 1 else 'ShoseOff'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookR4) return;
    proto.__dshHookR4=true;
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

CARD = """(function(){var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key===%s;});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
    return e.dataset.k===%s;}); if(d) d.click(); return 1;})()"""
TAB = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
    return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()"""

# 快照：驱动部件的顶点包围盒 + 全模型逐 drawable 顶点求和哈希 + 参数值
SNAP = """
(function(){
  try{
    var m=window.__l2model, im=m.internalModel, cm=im.coreModel;
    var ids=%s;
    var out={param:null, drv:{}, all:[]};
    try{ out.param = cm.getParameterValueById(%s); }catch(e){ out.param='ERR'; }
    var nd = cm.getDrawableCount();
    for(var i=0;i<nd;i++){
      var p=null;
      try{ p=cm.getDrawableVertexPositions(i); }catch(e){ continue; }
      if(!p||p.length<2) continue;
      var x0=1e9,y0=1e9,x1=-1e9,y1=-1e9, sum=0;
      for(var k=0;k+1<p.length;k+=2){
        if(p[k]<x0)x0=p[k]; if(p[k]>x1)x1=p[k];
        if(p[k+1]<y0)y0=p[k+1]; if(p[k+1]>y1)y1=p[k+1];
        sum += p[k]*1.7 + p[k+1]*3.1;
      }
      var rec={i:i, h:Math.round(sum*1000)/1000,
               w:Math.round((x1-x0)*10000)/10000,
               hh:Math.round((y1-y0)*10000)/10000,
               x0:Math.round(x0*10000)/10000, y0:Math.round(y0*10000)/10000};
      out.all.push(rec);
      if(ids.indexOf(i)>=0) out.drv[i]=rec;
    }
    return JSON.stringify(out);
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1

    # 从数据表读该参数的驱动部件
    pd = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2',
                                     'param_drawables.json'), encoding='utf-8'))
    drive = (pd.get(KEY) or {}).get(PID) or []
    print('参数 %s 的驱动部件（来自 param_drawables.json）: %s' % (PID, drive))
    if not drive:
        print('!! 该参数没有驱动部件映射')
        return 1

    pg = open_page(URL, tag='r4')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              "if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        time.sleep(0.9)
        pg.ev(CARD % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev(SKIN % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev(TAB)
        time.sleep(15)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        expr = SNAP % (json.dumps(drive), json.dumps(PID))

        print('\n[S0] 记录初始状态')
        s0 = json.loads(pg.ev(expr))
        print('  %s = %s' % (PID, s0.get('param')))
        for i, r in (s0.get('drv') or {}).items():
            print('   drawable %-4s  w=%-9s hh=%-9s  x0=%-9s y0=%s'
                  % (i, r['w'], r['hh'], r['x0'], r['y0']))

        print('\n[S1] __costumeToggle(%s)' % PID)
        r = pg.ev("(function(){try{return window.__costumeToggle(%s);}catch(e){return 'E:'+e;}})()"
                  % json.dumps(PID))
        print('  toggle 返回:', r)
        time.sleep(2.2)   # tween 0.45s + 余量

        print('\n[S2] 记录切换后状态')
        s2 = json.loads(pg.ev(expr))
        print('  %s = %s' % (PID, s2.get('param')))
        for i, r2 in (s2.get('drv') or {}).items():
            print('   drawable %-4s  w=%-9s hh=%-9s  x0=%-9s y0=%s'
                  % (i, r2['w'], r2['hh'], r2['x0'], r2['y0']))

        print('\n=== 判定 ===')
        d0 = s0.get('drv') or {}
        d2 = s2.get('drv') or {}
        changed = []
        for i in d0.keys() & d2.keys():
            a, b = d0[i], d2[i]
            if (abs(a['w'] - b['w']) > 1e-4 or abs(a['hh'] - b['hh']) > 1e-4
                    or abs(a['x0'] - b['x0']) > 1e-4 or abs(a['y0'] - b['y0']) > 1e-4
                    or abs(a['h'] - b['h']) > 1e-3):
                changed.append(i)
        print('  参数值 %s → %s' % (s0.get('param'), s2.get('param')))
        print('  驱动部件中发生变化的: %s' % (changed or '无'))

        # 全模型变化集合
        all0 = {r['i']: r for r in (s0.get('all') or [])}
        all2 = {r['i']: r for r in (s2.get('all') or [])}
        allchg = []
        for i in all0.keys() & all2.keys():
            a, b = all0[i], all2[i]
            if (abs(a['h'] - b['h']) > 1e-3 or abs(a['w'] - b['w']) > 1e-4
                    or abs(a['hh'] - b['hh']) > 1e-4):
                allchg.append(i)
        print('  全模型 %d 个 drawable 中变化的: %d 个' % (len(all0), len(allchg)))
        inter = set(allchg) & set(drive)
        print('  变化集合与驱动部件的交集: %s' % (sorted(inter) or '空'))

        print()
        if changed:
            print('==> R4 PASS：泵动部件顶点确实随参数变化，写入到达渲染')
        elif inter:
            print('==> R4 PASS（部分）：变化集合命中驱动部件 %s' % sorted(inter))
        elif allchg:
            print('==> R4 存疑：全模型有 %d 个部件变化，但都不属于该参数的驱动部件' % len(allchg))
            print('    可能原因：呼吸/物理漂移。需对照组确认。')
            print('    变化清单（前 12）: %s' % allchg[:12])
        else:
            print('==> R4 FAIL：没有任何 drawable 变化，参数写入未到达渲染')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
