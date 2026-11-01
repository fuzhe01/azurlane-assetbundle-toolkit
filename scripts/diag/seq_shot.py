# -*- coding: utf-8 -*-
"""seq_shot.py — 播放一个动作，按固定间隔连拍截图，供目视判定「哪个部位在消失」。

为什么需要（2026-10-25）：
  trace_vanish_matrix 已证明 `mail` 期间 drawable 不透明度只闪 4 件、且都不在 256..277，
  所以「左脚/右手消失」不是不透明度造成的。剩下可能是顶点几何被压扁/移出、
  遮罩裁掉、或绘制序被盖住。这几种都只能看**像素**。

判据：连拍图里同一部位在某一帧丢失，而它在相邻帧存在 → 消失成立，且能直接看出是哪一处。

用法:
  py -3 scripts/diag/seq_shot.py [--key=ougen_8] [--clip=mail] [--secs=14] [--gap=0.7]
  py -3 scripts/diag/seq_shot.py --key=ougen_8 --clip=mail --crop=1   # 顺便裁出取景框
输出目录: .diag/seq/<key>_<clip>/
⚠️ 走 8778 + gallery_v2/index.html。
"""
import base64
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
CLIP = ARGS.get('clip', 'mail')
SECS = float(ARGS.get('secs', 14))
GAP = float(ARGS.get('gap', 0.7))
PORT = int(ARGS.get('port', 9472))
W, H = int(ARGS.get('w', 1000)), int(ARGS.get('h', 1000))
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'seq', '%s_%s' % (KEY, CLIP))

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSS) return; proto.__dshHookSS=true;
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

# canvas 在页面里的位置 + 模型在 canvas 内的包围盒，用来裁图
RECT = r"""
(function(){
  var cs=document.querySelectorAll('canvas'), best=null;
  for(var i=0;i<cs.length;i++){
    var r=cs[i].getBoundingClientRect();
    if(r.width>200 && r.height>200 && (!best || r.width*r.height>best.w*best.h))
      best={x:r.x,y:r.y,w:r.width,h:r.height};
  }
  if(!best) return 'NO_CANVAS';
  var m=window.__l2model, info={canvas:best};
  try{ var b=m.getLocalBounds(); info.lb={x:b.x,y:b.y,w:b.width,h:b.height}; }catch(e){}
  try{ var g=m.getBounds(); info.gb={x:g.x,y:g.y,w:g.width,h:g.height}; }catch(e){}
  try{ info.scale={x:m.scale.x,y:m.scale.y}; info.pos={x:m.x,y:m.y}; }catch(e){}
  return JSON.stringify(info);
})()
"""

ST = r"""
(function(){ var m=window.__l2model; if(!m) return '';
 var mm=m.internalModel.motionManager;
 return JSON.stringify({g:mm.state.currentGroup||'', rg:mm.state.reservedGroup||''}); })()
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    prof = os.path.join(ROOT, '.diag', 'chrome_ss%d' % (int(time.time()) % 100000))
    pg = Page(PORT, prof, URL, (W, H))
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
        print('模型就绪 = %s' % pg.ev("typeof window.__l2model"))
        info = pg.ev(RECT)
        print('canvas/包围盒: %s' % str(info)[:400])
        try:
            ii = json.loads(info)
            cb = ii['canvas']
            print('  canvas 屏幕矩形 x=%.1f y=%.1f w=%.1f h=%.1f' % (cb['x'], cb['y'], cb['w'], cb['h']))
        except Exception:
            pass

        shots = []
        for t_before in (0.0,):
            pass
        # 先拍一张待机基线
        base = os.path.join(OUT, '000_idle.png')
        pg.shot(base); shots.append(base)
        print('基线: %s' % base)

        r = pg.ev("(function(){ if(!window.__l2play) return 'NO_HOOK';"
                  " return window.__l2play(%s)===false?'REFUSED':'ok'; })()" % json.dumps(CLIP))
        print('play(%s) = %s' % (CLIP, r))
        t0 = time.time()
        k = 1
        while time.time() - t0 < SECS:
            st = pg.ev(ST)
            p = os.path.join(OUT, '%03d_t%.1fs.png' % (k, time.time() - t0))
            pg.shot(p)
            shots.append(p)
            print('  %s  %s' % (os.path.basename(p), str(st)[:80]))
            k += 1
            time.sleep(GAP)
        print('\n共 %d 张，目录 %s' % (len(shots), OUT))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
