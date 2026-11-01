# -*- coding: utf-8 -*-
"""trace_part_visible.py — 按 Part 分组统计「有多少帧不被绘制」，并与待机基线对照。

为什么（2026-10-24）：
  trace_vanish_matrix 证明 `mail` 期间不透明度只闪 4 件（都不在 256..277），
  所以「消失」不是不透明度造成的；trace_vanish_geom 显示 Part7/Part11 有 34/57 帧
  `isVisible=0` —— 那是硬布尔量，不是面积那种软阈值。
  本脚本把「看不见」量化成 **部件组不被绘制的帧比例**，对照组是 idle 待机：
  待机时也有同样比例 ⇒ 是未穿着的换装层（正常）；动作期明显更高 ⇒ 是真消失。

仪器教训（本轮踩过）：
  * 用 CDP 逐帧 `ev` 拉数据，13 秒只能采到 19 帧（每次往返约 0.4s）⇒ 采样必须在页面内
    用 rAF 累加，只回传聚合结果。
  * `print` 里写裸 `%` 会炸（`%` 是格式化符），必须 `%%`。

用法:
  py -3 scripts/diag/trace_part_visible.py [--key=ougen_8] [--clips=mail] [--secs=13]
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
SECS = float(ARGS.get('secs', 13))
PORT = int(ARGS.get('port', 9476))
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPV3) return; proto.__dshHookPV3=true;
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

INIT = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var cm=m.internalModel.coreModel._model; if(!cm) return 'NO_CM';
  var D=cm.drawables, n=D.count, PA=cm.parts, CI=cm.canvasinfo;
  window.__pv = {n:n, meta:[], halfW:CI.CanvasWidth/CI.PixelsPerUnit/2,
                 halfH:CI.CanvasHeight/CI.PixelsPerUnit/2};
  for(var i=0;i<n;i++){
    var pt=D.parentPartIndices[i];
    window.__pv.meta.push([D.ids[i], pt, PA.ids[pt]]);
  }
  window.__pvReset = function(){
    var A=window.__pv;
    A.inv=new Array(n).fill(0); A.tot=0; A.gseq=[];
    A.opMax=new Array(n).fill(0);
    A.x0=new Array(n).fill(1e9); A.x1=new Array(n).fill(-1e9);
    A.y0=new Array(n).fill(1e9); A.y1=new Array(n).fill(-1e9);
    A.hasBx=new Array(n).fill(0); A.lastG='\u0000'; A.on=true;
  };
  window.__pvReset();
  if(!window.__pvTickOn){
    window.__pvTickOn=1;
    window.__pvTick=function(){
      var A=window.__pv;
      if(A && A.on){
        A.tot++;
        var g=''; try{ g=m.internalModel.motionManager.state.currentGroup||''; }catch(e){}
        if(g!==A.lastG){ A.gseq.push([A.tot, g]); A.lastG=g; }
        for(var i=0;i<n;i++){
          if(!(D.dynamicFlags[i]&1)){ A.inv[i]++; continue; }
          var o=D.opacities[i]; if(o>A.opMax[i])A.opMax[i]=o;
          var vp=D.vertexPositions[i];
          if(vp&&vp.length){
            var x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
            for(var k=0;k+1<vp.length;k+=2){
              var x=vp[k],y=vp[k+1];
              if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y;
            }
            if(x0<A.x0[i])A.x0[i]=x0; if(x1>A.x1[i])A.x1[i]=x1;
            if(y0<A.y0[i])A.y0[i]=y0; if(y1>A.y1[i])A.y1[i]=y1;
            A.hasBx[i]=1;
          }
        }
      }
      requestAnimationFrame(window.__pvTick);
    };
    requestAnimationFrame(window.__pvTick);
  }
  return 'ok';
})()
"""

DUMP = r"""
(function(){
  var A=window.__pv; if(!A) return 'NO_PV';
  A.on=false;
  return JSON.stringify({n:A.n, tot:A.tot, gseq:A.gseq, meta:A.meta,
    halfW:A.halfW, halfH:A.halfH, inv:A.inv, opMax:A.opMax,
    hasBx:A.hasBx, x0:A.x0, x1:A.x1, y0:A.y0, y1:A.y1});
})()
"""


def sample(pg, secs):
    pg.ev("window.__pvReset(); 1")
    t0 = time.time()
    time.sleep(secs)
    raw = pg.ev(DUMP)
    if not (isinstance(raw, str) and raw.startswith('{')):
        raise RuntimeError('dump failed: %r' % (raw,))
    d = json.loads(raw)
    d['wall'] = round(time.time() - t0, 1)
    return d


def analyse(rows, halfW, halfH, d, title):
    n, tot = d['n'], d['tot']
    print('\n--- %s：%d 帧 / %.1fs（约 %.1f fps）---' % (title, tot, d['wall'], tot / max(d['wall'], .1)))
    print('    动作组序列（帧号,组）: %s'
          % ' -> '.join('%s@%d' % ((g or '(空)'), i) for i, g in d['gseq']))
    groups = {}
    for i in range(n):
        p = rows[i][1]
        g = groups.setdefault(p, {'name': rows[i][2], 'idx': []})
        g['idx'].append(i)
    for p, g in groups.items():
        g['inv'] = sum(d['inv'][i] for i in g['idx']) / float(len(g['idx']) * max(tot, 1))
        g['opMax'] = max(d['opMax'][i] for i in g['idx'])
        seen = [i for i in g['idx'] if d['hasBx'][i]]
        if seen:
            g['bbox'] = (min(d['x0'][i] for i in seen), min(d['y0'][i] for i in seen),
                         max(d['x1'][i] for i in seen), max(d['y1'][i] for i in seen))
            g['border'] = ((g['bbox'][2] - g['bbox'][0]) > halfW * 0.9 or
                           (g['bbox'][3] - g['bbox'][1]) > halfH * 0.9)
        else:
            g['bbox'] = None
            g['border'] = False
    return groups


def main():
    prof = os.path.join(ROOT, '.diag', 'chrome_pv%d' % (int(time.time()) % 100000))
    pg = Page(PORT, prof, URL, (1300, 1000))
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
        if r != 'ok':
            print('打开舰船失败: %s' % r)
            return 1
        time.sleep(1.5)
        pg.ev("""(function(){var d=[].slice.call(document.querySelectorAll('#mSkins .skin')).filter(function(e){
           return e.dataset.k===%s;}); if(d[0]) d[0].click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab')).filter(function(e){
           return e.dataset.k==='live2d';}); if(t[0]&&!t[0].classList.contains('dis')) t[0].click(); return 1;})()""")
        ready = False
        for _ in range(40):
            time.sleep(1)
            if pg.ev("!!window.__l2model") is True:
                ready = True
                break
        if not ready:
            print('模型未就绪')
            return 1
        ini = pg.ev(INIT)
        if ini != 'ok':
            print('初始化累加器失败: %s' % ini)
            return 1
        meta = json.loads(pg.ev(
            "JSON.stringify({rows:window.__pv.meta,halfW:window.__pv.halfW,halfH:window.__pv.halfH})"))
        rows, halfW, halfH = meta['rows'], meta['halfW'], meta['halfH']
        print('drawables=%d  halfW=%.2f halfH=%.2f' % (len(rows), halfW, halfH))

        raw_avail = pg.ev("JSON.stringify([].slice.call(document.querySelectorAll('#l2Motion option'))"
                          ".map(function(o){return o.value;}))")
        avail = json.loads(raw_avail) if isinstance(raw_avail, str) and raw_avail.startswith('[') else []

        base = analyse(rows, halfW, halfH, sample(pg, min(SECS, 10)), 'idle 基线（不主动播放）')

        results = {}
        for clip in CLIPS:
            if avail and clip not in avail:
                print('\n=== %s === 页面无此动作组，跳过' % clip)
                continue
            rep = pg.ev("(function(){ if(!window.__l2play) return 'NO_HOOK';"
                        " return window.__l2play(%s)===false?'REFUSED':'ok'; })()" % json.dumps(clip))
            print('\n=== %s === play=%s' % (clip, rep))
            results[clip] = analyse(rows, halfW, halfH, sample(pg, SECS), clip)

        for clip, act in results.items():
            print('\n########## %s 对比 idle 基线：不可见比例显著上升的 Part ##########' % clip)
            cand = []
            for p, g in act.items():
                bf = base[p]['inv'] if p in base else 0.0
                if g['inv'] >= 0.30 and (g['inv'] - bf) >= 0.20:
                    cand.append((g['inv'] - bf, g['inv'], bf, p, g))
            cand.sort(reverse=True)
            print('  候选 %d 个（动作期不可见 >=30%% 且比基线高 >=20 个百分点）' % len(cand))
            for (_delta, af, bf, p, g) in cand[:25]:
                bb = g['bbox']
                bbs = ('x[%.1f,%.1f] y[%.1f,%.1f]' % bb) if bb else '(无可见帧)'
                print('    Part%-4d %-12s 不可见 动作%3.0f%% / 基线%3.0f%% 件数=%-3d op_max=%.2f %s%s'
                      % (p, g['name'], af * 100, bf * 100, len(g['idx']), g['opMax'], bbs,
                         '  [画布围边]' if g['border'] else ''))
                names = [rows[i][0] for i in g['idx'][:6]]
                print('        drawables: %s%s' % (', '.join(names),
                      '' if len(g['idx']) <= 6 else ' ...(共 %d)' % len(g['idx'])))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
