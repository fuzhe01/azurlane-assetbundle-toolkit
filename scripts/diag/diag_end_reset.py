# -*- coding: utf-8 -*-
"""一锤定音：动作结束瞬间参数是否被 loadParameters 重置为默认 0。

⚠️ 探针纪律（本轮踩过）：
   - 不得在 setParameterValue 里抓 Error().stack —— 每次写入都造栈会拖垮主循环，
     实测把 150 次/秒的更新压到 2.6s 只有 4 次，产出「只写了 0」的假结论。
   - 本脚本只读 getParameterValueByIndex，不 hook 任何写入路径。
   - 用 rAF（每帧一次）而不是 setInterval，避免和 ticker 抢时序。

要证明的链路：
   动作 3.017s 播完 → motionQueueEntry 被 release → 没有 motion 再写参数
   → internalModel.update() 末尾 model.loadParameters() 把全部参数恢复默认
   → ParamAngleX 从 -18.367 瞬间归 0（视角回正 = 用户说的"闪回初始默认 idle"）
   而 fallback 定时器是 duration+0.6s，这 0.6s 内画面已经归零。

判据：找到 motion 队列清空后第一帧的 ParamAngleX 值。
     若 ≈0 而末帧应为 -18.367 → 确认 loadParameters 是执行者。
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
    if(proto.__dshHookFR) return;
    proto.__dshHookFR=true;
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

# 只读采样器：rAF 每帧一次，记录 组名 / 队列内 motion 数 / 关键参数
SAMPLER = """
(function(){
  window.__FR = [];
  if(window.__frOn) return 1;
  window.__frOn = true;
  const W = %s;
  const tick = () => {
    try{
      const m = window.__l2model;
      if(m && m.internalModel){
        const im = m.internalModel, cm = im.coreModel;
        const mm = im.motionManager;
        const st = mm.state || {};
        const o = {};
        for(const p of W){
          try{ const i = cm.getParameterIndex(p);
               o[p] = (i >= 0) ? cm.getParameterValueByIndex(i) : null; }catch(e){ o[p]=null; }
        }
        let qn = null;
        try{ qn = (mm._motions||[]).filter(x=>x!=null).length; }catch(e){}
        window.__FR.push({t: performance.now(), g: st.currentGroup, q: qn, v: o});
      }
    }catch(e){}
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  return 1;
})();
""" % json.dumps(['ParamAngleX', 'Param194', 'Param207', 'Param315', 'Param343'])


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='fr')
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

        pg.ev(SAMPLER)
        time.sleep(0.6)
        pg.ev("window.__FR.length = 0;")
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        time.sleep(6.0)

        data = pg.ev("window.__FR")
        if not data:
            print('!! 无数据')
            return 1

        # 相对时间
        t0 = data[0]['t']
        rel = [(d['t'] - t0, d) for d in data]
        print('样本数 %d  跨度 %.0fms  帧率≈%.1f/s'
              % (len(rel), rel[-1][0], len(rel) / (rel[-1][0] / 1000.0)))

        # 找 duration 边界附近（3017ms）与队列清空时刻
        print('\n  %7s %14s %3s %10s %10s %10s %10s'
              % ('rel_t', 'group', 'q', 'AngleX', 'p194', 'p207', 'p343'))
        prev_q = None
        q_zero_at = None
        for t, d in rel:
            q = d['q']
            if q == 0 and q_zero_at is None and t > 2000:
                q_zero_at = t
            show = (2800 <= t <= 4200) or (q == 0 and prev_q not in (None, 0))
            if show:
                v = d['v']
                print('  %7.0f %14s %3s %10s %10s %10s %10s'
                      % (t, str(d['g']), q,
                         '%.3f' % v['ParamAngleX'] if v['ParamAngleX'] is not None else '-',
                         '%.3f' % v['Param194'] if v['Param194'] is not None else '-',
                         '%.3f' % v['Param207'] if v['Param207'] is not None else '-',
                         '%.3f' % v['Param343'] if v['Param343'] is not None else '-'))
            prev_q = q

        # 取 3000ms 前最后一帧 与 队列归零后第一帧
        before = None
        after = None
        for t, d in rel:
            if 2400 <= t <= 3100:
                before = (t, d)
            if d['q'] == 0 and t > 2800 and after is None:
                after = (t, d)
        print('\n=== 判据 ===')
        if before:
            print('动作末段(%.0fms)  ParamAngleX=%s  p194=%s  q=%s'
                  % (before[0], before[1]['v']['ParamAngleX'],
                     before[1]['v']['Param194'], before[1]['q']))
        if after:
            print('队列清空(%.0fms)  ParamAngleX=%s  p194=%s  q=%s  group=%s'
                  % (after[0], after[1]['v']['ParamAngleX'],
                     after[1]['v']['Param194'], after[1]['q'], after[1]['g']))
        print()
        if before and after:
            a = before[1]['v']['ParamAngleX']
            b = after[1]['v']['ParamAngleX']
            if a is not None and b is not None and abs(a - b) > 3:
                print('==> 确认：动作末段 AngleX=%.2f，motion 队列清空后骤变为 %.2f'
                      ' → loadParameters 重置是执行者' % (a, b))
            else:
                print('==> AngleX 从 %s 到 %s，未见骤变，需换角度看' % (a, b))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
