# -*- coding: utf-8 -*-
"""实证「回落后闪回默认 idle」的执行者就是 restTick（gallery_src/index.html:1617-1647）。

假设（读码得出）：
  touch_idle14 末帧 ParamAngleX = -18.367，但回落目标 idle9 只有 109 条呼吸曲线，
  没有 ParamAngleX / Param194 / Param207 / Param315 的曲线，且它们不在 switchParams 白名单
  → restTick 的 want 集合包含它们 → 回落 idle9 后等 REST_DELAY=400ms，
    再花 REST_MS=700ms 线性拉回 getParameterDefaultValue(=0)
  → 用户看到「回落后立马闪回初始默认 idle」。

⚠️ 前一版探针（diag_pose_reset）观测的是 Param345，它有 idle9 曲线、本来就不会被
   restTick 拉回，所以得出「没被抹平」的错误结论。本脚本只观测真断崖参数，并加对照组。

用法: py -3 scripts/diag/diag_rest_tick_cliff.py [model_key] [group] [idle]
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

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
GROUP = sys.argv[2] if len(sys.argv) > 2 else 'touch_idle14'
IDLE = sys.argv[3] if len(sys.argv) > 3 else 'idle9'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

# 真断崖参数（末值非零、idle9 无曲线）里幅度最大的 6 个
CLIFF = ['ParamAngleX', 'Param194', 'Param207', 'Param315', 'Param10', 'Param9']
# 对照组：idle9 有曲线的参数，restTick 不该动它们
CTRL = ['Param343', 'Param394', 'Param348']

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookRC) return; proto.__dshHookRC=true;
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


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        print('!! 服务未就绪，结论无效')
        return 1
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status)
                return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e)
        return 2

    pg = open_page(URL, tag='cliff')
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

        ready = pg.ev("(typeof window.__l2play==='function' && !!window.__l2model)?1:0")
        print('live2d ready:', ready)
        if ready != 1:
            print('!! Live2D 未就绪，结论无效')
            return 1

        # 先让画面进 idle9，保证基线是"正确待机"
        pg.ev("(function(){ try{ window.__l2play(%s,1); }catch(e){} return 1; })()" % json.dumps(IDLE))
        time.sleep(2.2)

        watch = CLIFF + CTRL
        pg.ev("""
        (function(){
          window.__RC=[];
          if(window.__rcTimer) clearInterval(window.__rcTimer);
          var W=%s;
          var read=function(){
            try{
              var m=window.__l2model, im=m.internalModel, cm=im.coreModel;
              var st=im.motionManager.state||{};
              var o={};
              for(var i=0;i<W.length;i++){ var p=W[i];
                try{ var idx=cm.getParameterIndex(p);
                  o[p]=(idx>=0)?cm.getParameterValueByIndex(idx):null; }catch(e){ o[p]=null; } }
              return {g:st.currentGroup===undefined?'<u>':st.currentGroup, v:o};
            }catch(e){ return null; }
          };
          window.__rcTimer=setInterval(function(){
            var r=read(); if(r) window.__RC.push([performance.now(), r.g, r.v]);
          }, 50);
        })();
        """ % json.dumps(watch))

        time.sleep(0.8)
        base = pg.ev("window.__RC.length")
        print('baseline samples:', base)

        r = pg.ev("(function(){ try{ return window.__l2play(%s,3); }catch(e){ return 'ERR:'+e; } })()"
                  % json.dumps(GROUP))
        print('play %s -> %s' % (GROUP, r))

        # 动作 3.017s + 回落 + REST_DELAY 0.4 + REST_MS 0.7 ≈ 4.2s；取 9s 留余量
        time.sleep(9.0)
        data = pg.ev("window.__RC")
        pg.ev("if(window.__rcTimer) clearInterval(window.__rcTimer);")

        if not data:
            print('!! 无采样数据')
            return 1

        t0 = data[0][0]
        rel = [(t - t0, g, v) for t, g, v in data]
        print('total samples: %d  span=%.0fms' % (len(rel), rel[-1][0]))

        idx_fb = None
        for i, (t, g, v) in enumerate(rel):
            if g == IDLE:
                idx_fb = i
                break
        print()
        if idx_fb is None:
            print('!! 采样期内未进入 %s，最终组 = %s' % (IDLE, rel[-1][1]))
            return 1
        print('首次进入 %s 于 rel_t=%.0fms' % (IDLE, rel[idx_fb][0]))

        lo = max(0, idx_fb - 10)
        hi = min(len(rel), idx_fb + 46)
        hdr = ' '.join('%11s' % p for p in watch)
        print('\n%8s %14s %s' % ('rel_t', 'group', hdr))
        for i in range(lo, hi):
            t, g, v = rel[i]
            if i % 2 and i != idx_fb:
                continue
            row = ' '.join(('%11.3f' % v[p]) if v.get(p) is not None else '       None'
                           for p in watch)
            mark = ' <== 回落' if i == idx_fb else ''
            print('%8.0f %14s %s%s' % (t, str(g), row, mark))

        print('\n=== 结论 ===')
        verdict = []
        for p in CLIFF:
            v_fb = rel[idx_fb][2].get(p)
            v_end = rel[-1][2].get(p)
            if v_fb is None or v_end is None:
                print('%-12s 无数据' % p)
                continue
            dropped = abs(v_end) < abs(v_fb) - 1.0
            verdict.append(dropped)
            print('%-12s 回落瞬间=%9.3f  结束=%9.3f  Δ=%+8.3f  %s'
                  % (p, v_fb, v_end, v_end - v_fb,
                     '【被拉回】' if dropped else '保持'))
        print()
        for p in CTRL:
            v_fb = rel[idx_fb][2].get(p)
            v_end = rel[-1][2].get(p)
            if v_fb is None or v_end is None:
                continue
            print('%-12s(对照,idle9有曲线) 回落=%9.3f 结束=%9.3f Δ=%+8.3f'
                  % (p, v_fb, v_end, v_end - v_fb))
        print()
        if verdict and all(verdict):
            print('==> 确认：restTick 在回落成功后把断崖姿态参数拉回默认 0')
        elif any(verdict):
            print('==> 部分确认：部分断崖参数被拉回')
        else:
            print('==> 否证：断崖参数未被拉回，restTick 不是执行者，需另找')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
