# -*- coding: utf-8 -*-
"""trace_vanish_matrix.py — 在真实页面里按时刻采样「全部 drawable 不透明度」，抓中途变 0 又回来的件。

为什么换这个判据（2026-10-25）：
  前几轮一直用「固定时刻取一次」+ 按**编号**盯 256..277，结果两边都不可靠：
    - 固定时刻取点会跨越「动作结束 → 回落待机」的边界，把两个阶段混成一个读数；
    - 编号是上一轮猜出来的，从未与用户主诉部位（左脚 / 右手掌）做过对应验证。
  本轮改成**不预设目标**：全量 842 件逐时刻采样，凡「曾 >0.02 且曾 <0.02」的件都打出来。
  用户看到的消失一定落在这份闪烁清单里，之后再看名单里的名字/位置来认。

判据：
  - flicker 清单非空 → 消失确实发生（清单即嫌疑集），再按 bbox 认部位；
  - flicker 清单为空    → 该动作下**没有任何部件不透明度穿过 0**，
                          意味着「看不见」不是不透明度造成的（要考虑遮罩/乘色/绘制序）。

用法:
  py -3 scripts/diag/trace_vanish_matrix.py [--key=ougen_8] [--clips=mail,idle9,touch_idle14]
                                           [--secs=14] [--step=0.12] [--port=9470]
⚠️ 走 8778 / gallery_v2/index.html（正本硬链，改完即生效；只需 deploy --check 为绿）。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

ARGS = {}
for a in sys.argv[1:]:
    if a.startswith('--'):
        k, _, v = a[2:].partition('=')
        ARGS[k] = v

KEY = ARGS.get('key', 'ougen_8')
CLIPS = [c for c in ARGS.get('clips', 'mail').split(',') if c]
SECS = float(ARGS.get('secs', 14))
STEP = float(ARGS.get('step', 0.12))
PORT = int(ARGS.get('port', 9470))
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookVM) return; proto.__dshHookVM=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel) window.__l2model=c; }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

# 一次调用返回「本帧全部不透明度 + 当前动作组」
SAMPLE = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var im=m.internalModel, c=im.coreModel, mm=im.motionManager;
  var n; try{ n=c.getDrawableCount(); }catch(e){ return 'NO_COUNT'; }
  var ops=new Array(n);
  for(var i=0;i<n;i++){ try{ ops[i]=Math.round(c.getDrawableOpacity(i)*1000)/1000; }catch(e){ ops[i]=-1; } }
  var g='',rg='';
  try{ g=mm.state.currentGroup||''; rg=mm.state.reservedGroup||''; }catch(e){}
  return JSON.stringify({g:g, rg:rg, op:ops});
})()
"""

# 静态元信息：名字 / 父 Part / 顶点 bbox（取自核心 Model 包装器，不经页面渲染）
META = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var core=m.internalModel.coreModel;
  var cm=null;
  try{ cm=core._model; }catch(e){}
  if(!cm) return 'NO_CM';
  var D=cm.drawables, PA=cm.parts, CI=cm.canvasinfo;
  var rows=[];
  for(var i=0;i<D.count;i++){
    var vp=D.vertexPositions[i], x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
    if(vp && vp.length){ for(var k=0;k+1<vp.length;k+=2){
      if(vp[k]<x0)x0=vp[k]; if(vp[k]>x1)x1=vp[k];
      if(vp[k+1]<y0)y0=vp[k+1]; if(vp[k+1]>y1)y1=vp[k+1]; } }
    var mk=[]; try{ mk=[].slice.call(D.masks[i]||[]); }catch(e){}
    rows.push({i:i, name:D.ids[i], part:D.parentPartIndices[i], partName:PA.ids[D.parentPartIndices[i]],
               masks:mk, x0:x0,x1:x1,y0:y0,y1:y1});
  }
  return JSON.stringify({halfW:CI.CanvasWidth/CI.PixelsPerUnit/2,
                         halfH:CI.CanvasHeight/CI.PixelsPerUnit/2, rows:rows});
})()
"""


def main():
    prof = os.path.join(ROOT, '.diag', 'chrome_vm%d' % (int(time.time()) % 100000))
    pg = Page(PORT, prof, URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.6)
        r = pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[].slice.call(document.querySelectorAll('.card')).filter(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c.length) return 'NO_CARD';
          c[0].click(); return 'ok';})()
        """ % json.dumps(KEY))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[].slice.call(document.querySelectorAll('#mSkins .skin')).filter(function(e){
           return e.dataset.k===%s;}); if(d[0]) d[0].click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab')).filter(function(e){
           return e.dataset.k==='live2d';}); if(t[0]&&!t[0].classList.contains('dis')) t[0].click(); return 1;})()""")
        for _ in range(40):
            time.sleep(1)
            if pg.ev("!!window.__l2model") is True:
                break
        print('模型就绪 = %s' % pg.ev("typeof window.__l2model"))
        meta_raw = pg.ev(META)
        if not isinstance(meta_raw, str) or not meta_raw.startswith('{'):
            print('META 失败: %s' % str(meta_raw)[:200]); return 1
        meta = json.loads(meta_raw)
        rows, halfW, halfH = meta['rows'], meta['halfW'], meta['halfH']
        print('drawables=%d  halfW=%.2f halfH=%.2f' % (len(rows), halfW, halfH))

        groups = pg.ev("JSON.stringify([].slice.call(document.querySelectorAll('#l2Motion option')).map(function(o){return o.value;}))")
        avail = json.loads(groups) if isinstance(groups, str) and groups.startswith('[') else []
        print('可选动作组 %d 个' % len(avail))

        for clip in CLIPS:
            if avail and clip not in avail:
                print('\n=== %s === 该模型无此动作组，跳过' % clip); continue
            r = pg.ev("(function(){ if(!window.__l2play) return 'NO_HOOK';"
                      " return window.__l2play(%s)===false?'REFUSED':'ok'; })()" % json.dumps(clip))
            print('\n=== %s === play=%s' % (clip, r))
            t0 = time.time()
            frames = []
            while time.time() - t0 < SECS:
                raw = pg.ev(SAMPLE)
                if isinstance(raw, str) and raw.startswith('{'):
                    d = json.loads(raw)
                    d['t'] = round(time.time() - t0, 2)
                    frames.append(d)
                time.sleep(STEP)
            if not frames:
                print('  无采样'); continue
            print('  采样 %d 帧  动作组序列: %s' % (
                len(frames),
                ' -> '.join(sorted(set('%s%s' % (f['g'] or '?', '(res)' if f['rg'] else '')
                                       for f in frames)))))

            n = len(frames[0]['op'])
            flick, peaks = [], {}
            for i in range(n):
                vals = [f['op'][i] for f in frames]
                hi = max(vals); lo = min(vals)
                if hi <= 0.02:               # 全程不可见：未穿着换装层，正常
                    continue
                if lo > 0.02:                # 全程可见：不消失
                    continue
                # 曾可见又曾归零
                first_z = next((f['t'] for f in frames if f['op'][i] <= 0.02), None)
                back = any(f['op'][i] > 0.02 and f['t'] > first_z for f in frames)
                flick.append((i, hi, lo, first_z, back))
                peaks[i] = hi

            print('  ★ 闪烁件（曾可见 又 曾归零）= %d 件' % len(flick))
            # 去掉画布围边件干扰
            def is_border(rr):
                return (rr['x1'] - rr['x0']) > halfW * 0.9 or (rr['y1'] - rr['y0']) > halfH * 0.9
            def desc(i):
                rr = rows[i] if i < len(rows) else {'name': '?', 'part': -1, 'partName': '?',
                                                    'masks': [], 'x0': 0, 'x1': 0, 'y0': 0, 'y1': 0}
                return '#%d %s part=%d(%s)%s x[%.1f,%.1f] y[%.1f,%.1f]%s' % (
                    i, rr['name'], rr['part'], rr['partName'],
                    (' masks=[' + ','.join(str(m) for m in rr['masks']) + ']') if rr['masks'] else '',
                    rr['x0'], rr['x1'], rr['y0'], rr['y1'],
                    '  [围边]' if is_border(rr) else '')
            for (i, hi, lo, fz, back) in flick[:60]:
                print('    %-72s max=%.2f 归零于%.2fs 回来自=%s' % (desc(i), hi, fz, '是' if back else '否'))
            if len(flick) > 60:
                print('    ... 其余 %d 件略' % (len(flick) - 60))
            bd = [i for i in peaks if is_border(rows[i])]
            print('  其中围边件 %d 个: %s' % (len(bd), bd[:20]))
            print('  真实本体闪烁件 = %d' % (len(flick) - len(bd)))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
