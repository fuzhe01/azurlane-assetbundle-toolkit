# -*- coding: utf-8 -*-
"""trace_vanish_geom.py — 按时刻采样全部 drawable 的**顶点几何**，抓「某些帧塌成 0 面积/NaN」的件。

为什么换这个判据（2026-10-25）：
  trace_vanish_matrix 已证明 `mail` 期间不透明度只闪 4 件、且都不在 256..277 号。
  既然不透明度不是原因，而截图在软件渲染下每张 11s（不可用），
  就只能在页面内逐帧算几何：顶点塌陷 / 出画布 / 出现 NaN 都会让部件「看不见」。

判据：
  - 某 drawable 在部分帧 bbox 面积 > 阈值、在另一些帧 ≈ 0（或含 NaN） → 几何消失，成立
  - 全程面积稳定但画面里看不到                                        → 遮罩/绘制序问题，另查
  同时记录每帧 `isVisible` 位与 opacity，用来区分「不画」与「画了但塌了」。

用法:
  py -3 scripts/diag/trace_vanish_geom.py [--key=ougen_8] [--clips=mail] [--secs=14] [--step=0.08]
"""
import json
import math
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
STEP = float(ARGS.get('step', 0.08))
PORT = int(ARGS.get('port', 9474))
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookGM) return; proto.__dshHookGM=true;
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

# 每帧：对每个 drawable 算 bbox 跨度 + 是否 NaN + isVisible + opacity
SAMPLE = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var im=m.internalModel, c=im.coreModel, cm=c._model, mm=im.motionManager;
  if(!cm) return 'NO_CM';
  var D=cm.drawables, n=D.count;
  var sx=new Array(n), sy=new Array(n), nan=new Array(n), vis=new Array(n), op=new Array(n);
  for(var i=0;i<n;i++){
    var vp=D.vertexPositions[i];
    var x0=1e9,x1=-1e9,y0=1e9,y1=-1e9,bad=0;
    if(vp && vp.length){
      for(var k=0;k+1<vp.length;k+=2){
        var X=vp[k], Y=vp[k+1];
        if(X!==X || Y!==Y || !isFinite(X) || !isFinite(Y)){ bad=1; break; }
        if(X<x0)x0=X; if(X>x1)x1=X; if(Y<y0)y0=Y; if(Y>y1)y1=Y;
      }
    }
    sx[i] = bad? -1 : (x1>=x0? Math.round((x1-x0)*1000)/1000 : -1);
    sy[i] = bad? -1 : (y1>=y0? Math.round((y1-y0)*1000)/1000 : -1);
    nan[i]=bad;
    vis[i]=(D.dynamicFlags[i]&1)?1:0;
    op[i]=Math.round(D.opacities[i]*1000)/1000;
  }
  var g='',rg=''; try{ g=mm.state.currentGroup||''; rg=mm.state.reservedGroup||''; }catch(e){}
  return JSON.stringify({g:g,rg:rg,sx:sx,sy:sy,nan:nan,vis:vis,op:op});
})()
"""

META = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var cm=m.internalModel.coreModel._model; if(!cm) return 'NO_CM';
  var D=cm.drawables, PA=cm.parts, CI=cm.canvasinfo;
  var rows=[];
  for(var i=0;i<D.count;i++){
    var vp=D.vertexPositions[i], x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
    if(vp&&vp.length){ for(var k=0;k+1<vp.length;k+=2){
      if(vp[k]<x0)x0=vp[k]; if(vp[k]>x1)x1=vp[k];
      if(vp[k+1]<y0)y0=vp[k+1]; if(vp[k+1]>y1)y1=vp[k+1]; } }
    var mk=[]; try{ mk=[].slice.call(D.masks[i]||[]); }catch(e){}
    rows.push({i:i,name:D.ids[i],part:D.parentPartIndices[i],partName:PA.ids[D.parentPartIndices[i]],
               masks:mk,nv:(vp&&vp.length)?vp.length/2:0,x0:x0,x1:x1,y0:y0,y1:y1});
  }
  return JSON.stringify({halfW:CI.CanvasWidth/CI.PixelsPerUnit/2,
                         halfH:CI.CanvasHeight/CI.PixelsPerUnit/2, rows:rows});
})()
"""


def main():
    prof = os.path.join(ROOT, '.diag', 'chrome_gm%d' % (int(time.time()) % 100000))
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
            print('打开舰船失败: %s' % r); return 1
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
        if pg.ev("!!window.__l2model") is not True:
            print('模型未就绪'); return 1
        meta = json.loads(pg.ev(META))
        rows, halfW, halfH = meta['rows'], meta['halfW'], meta['halfH']
        print('drawables=%d halfW=%.2f halfH=%.2f' % (len(rows), halfW, halfH))
        groups = pg.ev("JSON.stringify([].slice.call(document.querySelectorAll('#l2Motion option')).map(function(o){return o.value;}))")
        avail = json.loads(groups) if isinstance(groups, str) and groups.startswith('[') else []

        for clip in CLIPS:
            if avail and clip not in avail:
                print('\n=== %s === 无此动作组，跳过' % clip); continue
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
            print('  采样 %d 帧  组序列: %s' % (len(frames),
                  ' -> '.join(dict.fromkeys(f['g'] or '?' for f in frames))))

            n = len(frames[0]['sx'])
            bad = []
            for i in range(n):
                sxs = [f['sx'][i] for f in frames]
                sys_ = [f['sy'][i] for f in frames]
                nans = [f['nan'][i] for f in frames]
                visl = [f['vis'][i] for f in frames]
                area = [max(0.0, a) * max(0.0, b) if a is not None and b is not None else 0.0
                        for a, b in zip(sxs, sys_)]
                hi, lo = max(area), min(area)
                if hi <= 1e-6:
                    continue                          # 全程无面积：本来就不画
                if lo > hi * 0.25 and not any(nans):
                    continue                          # 面积稳定，没有塌陷
                # 塌陷帧（面积 < 峰值 25%）或 NaN 帧
                col = [f['t'] for f, a, b in zip(frames, area, nans) if b or a <= hi * 0.25]
                vis_collapse = sum(1 for f in frames if f['vis'][i] == 0)
                bad.append((i, hi, lo, len(col), col[0] if col else None,
                            any(nans), vis_collapse, len(frames)))

            def is_border(rr):
                return (rr['x1'] - rr['x0']) > halfW * 0.9 or (rr['y1'] - rr['y0']) > halfH * 0.9

            print('  ★ 几何塌陷/NaN 件 = %d' % len(bad))
            for (i, hi, lo, ncol, first, has_nan, visz, nf) in bad[:40]:
                rr = rows[i]
                print('    #%-4d %-16s part=%d(%-8s)%s 峰值面积=%.4f 最小=%.4f 塌陷帧=%d/%d 首塌@%ss NaN=%s 不可见帧=%d%s'
                      % (i, rr['name'], rr['part'], rr['partName'],
                         (' masks=[' + ','.join(str(x) for x in rr['masks']) + ']') if rr['masks'] else '',
                         hi, lo, ncol, nf, first, '是' if has_nan else '否', visz,
                         '  [围边]' if is_border(rr) else ''))
            if len(bad) > 40:
                print('    ... 其余 %d 件略' % (len(bad) - 40))
            nb = [b for b in bad if not is_border(rows[b[0]])]
            print('  其中围边件 %d，本体塌陷件 = %d' % (len(bad) - len(nb), len(nb)))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
