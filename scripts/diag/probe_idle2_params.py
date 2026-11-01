# -*- coding: utf-8 -*-
"""决定性测试：组名 = idle2 时，参数到底是不是 idle2 的值。

背景（2026-10-24 用户指出分歧）：
  用户：「touch_idle1 最后应该保持在 idle2 循环，现在保持在默认 idle 循环」
  我的探针：state.currentGroup == idle2 → 我判「正确」
  截图比对：A(idle) 与 B(idle2) 画面几乎相同；C(回落) 多了大 Menu 卡片
          → 组名对、画面不对

关键区分点：这些参数在 idle / idle2 的**首帧值不同**，可以一测定论。

  Param278     idle= 0.000   idle2= 10.000
  Param46      idle= 0.000   idle2= -5.062
  ParamAngleY  idle=-11.812  idle2= -7.000
  Param10      idle= -3.570  idle2=  0.470
  Param117     idle= 1.504   idle2= -1.999
  ParamAngleZ  idle= 0.000   idle2=  3.402

三态采样（每态等 3 秒，让淡入完成）：
  S1 强制 idle  → 若值≈idle 列，说明 motion 驱动正常
  S2 强制 idle2 → 若值≈idle2 列，说明 idle2 驱动正常；若仍≈idle 列，说明没切
  S3 播 touch_idle1 等回落 → 看落在哪一列

判据：谁的参数值对上谁，就说明 motion 有没有真的驱动参数。
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
WATCH = ['Param278', 'Param46', 'ParamAngleY', 'Param10', 'Param117',
         'ParamAngleZ', 'ParamAngleX', 'Param194', 'Param45', 'Param115']

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookDP) return;
    proto.__dshHookDP=true;
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

READ = """
(function(){
  try{
    var m=window.__l2model;
    if(!m) return JSON.stringify({err:'no model'});
    var im=m.internalModel, cm=im.coreModel, mm=im.motionManager;
    var o={g:(mm.state||{}).currentGroup};
    var W=%s;
    for(var i=0;i<W.length;i++){
      try{ var idx=cm.getParameterIndex(W[i]);
        o[W[i]] = (idx>=0)? Math.round(cm.getParameterValueByIndex(idx)*1000)/1000 : null;
      }catch(e){ o[W[i]]=null; }
    }
    return JSON.stringify(o);
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
""" % json.dumps(WATCH)


def motion_starts(group):
    """从磁盘读该组首帧参数值。"""
    L = os.path.join(ROOT, 'Output', 'Live2D', KEY)
    d = json.load(open(os.path.join(L, KEY + '.model3.json'), encoding='utf-8'))
    ent = ((d.get('FileReferences') or {}).get('Motions') or {}).get(group) or []
    if not ent:
        return {}
    f = os.path.join(L, ent[0]['File'])
    if not os.path.isfile(f):
        return {}
    j = json.load(open(f, encoding='utf-8'))
    out = {}
    for c in j.get('Curves') or []:
        if c.get('Target') != 'Parameter':
            continue
        s = c.get('Segments') or []
        if len(s) >= 2:
            out[c['Id']] = round(float(s[1]), 3)
    return out


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    idle_v = motion_starts('idle')
    idle2_v = motion_starts('idle2')
    t1_v = motion_starts('touch_idle1')

    pg = open_page(URL, tag='dp')
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

        def state(label, group, wait=3.2):
            pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(group))
            time.sleep(wait)
            d = json.loads(pg.ev(READ))
            print('\n[%s]  请求=%s  实际组=%s' % (label, group, d.get('g')))
            return d

        s1 = state('S1 强制 idle', 'idle')
        s2 = state('S2 强制 idle2', 'idle2')
        s3 = state('S3 touch_idle1 回落', 'touch_idle1', wait=5.0)

        print('\n=== 参数对照表（磁盘 motion 首帧值 vs 运行时实测）===')
        print('  %-12s %9s %9s %9s | %9s %9s %9s'
              % ('param', 'idle磁盘', 'idle2磁盘', 't1磁盘', 'S1实测', 'S2实测', 'S3实测'))
        for p in WATCH:
            print('  %-12s %9s %9s %9s | %9s %9s %9s'
                  % (p,
                     idle_v.get(p, '-'), idle2_v.get(p, '-'), t1_v.get(p, '-'),
                     s1.get(p), s2.get(p), s3.get(p)))

        def dist(meas, ref):
            """实测与某参考的首帧值差异（只比双方都有的）。"""
            tot = 0.0
            n = 0
            for p in WATCH:
                a = meas.get(p)
                b = ref.get(p)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    tot += (a - b) ** 2
                    n += 1
            return (tot ** 0.5), n

        print('\n=== 欧氏距离（越小越接近）===')
        for label, meas in (('S1(请求idle)', s1), ('S2(请求idle2)', s2), ('S3(回落)', s3)):
            d_i, n1 = dist(meas, idle_v)
            d_i2, n2 = dist(meas, idle2_v)
            d_t1, n3 = dist(meas, t1_v)
            best = min((d_i, 'idle'), (d_i2, 'idle2'), (d_t1, 'touch_idle1'))[1]
            print('  %-14s  vs idle=%7.2f   vs idle2=%7.2f   vs t1=%7.2f   → 最像 %s'
                  % (label, d_i, d_i2, d_t1, best))

        print('\n=== 判定 ===')
        s2_v = [s2.get(p) for p in WATCH]
        i2_v = [idle2_v.get(p) for p in WATCH]
        moved = sum(1 for a, b in zip(s2_v, i2_v)
                    if isinstance(a, (int, float)) and isinstance(b, (int, float))
                    and abs(a - b) < 0.6)
        tot = sum(1 for a, b in zip(s2_v, i2_v)
                  if isinstance(a, (int, float)) and isinstance(b, (int, float)))
        print('  idle2 实测与磁盘值相符的参数: %d / %d' % (moved, tot))
        if tot and moved >= tot * 0.7:
            print('  → idle2 的 motion 确实驱动了参数')
            d_i2, _ = dist(s3, idle2_v)
            d_i, _ = dist(s3, idle_v)
            if d_i2 < d_i:
                print('  → 且回落后的参数更接近 idle2 ⇒ 行为其实是对的，你看画面差异需另找')
            else:
                print('  → 但回落后的参数更接近 idle ⇒ 复现问题：回落后参数是 idle 的')
        else:
            print('  → idle2 的 motion 没有真正驱动参数（组名变了、参数没变）')
            print('     与 §145 记录的「曲线求值未生效」一致，是同一根因')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
