"""第十四层取证：用**加载前注入**的 GL 调用计数器，看衰减期间每帧到底在发什么 GL 命令。

为什么必须注入在导航之前（`Page.addScriptToEvaluateOnNewDocument`）：
  产品代码在建上下文后就拿住 `gl` 对象了，事后再包 `getContext` 返回的对象已经太晚 ——
  那只包住"我自己的调用"，包不住产品已经缓存的引用。必须在**页面脚本运行前**
  把 `HTMLCanvasElement.prototype.getContext` 换掉，返回**已包装过**的上下文。

结合前十三节的已知事实：
  · 有窗口真浏览器同样衰减到 4.2fps ⇒ 产品缺陷，不是 headless 仪器；
  · 主线程 `(idle)` 占 72.6%、GC 0.3% ⇒ 时间在主线程之外，是"等 GPU"；
  · `UNMASKED_RENDERER` NVIDIA、无 context lost、堆平稳、强制 GC 无效；
  · 隐藏画布(display:none)、清 backdrop-filter、改 CSS 尺寸、缩 backing store 全都无效；
  · 全局禁 `backdrop-filter !important` 仍 3.0fps ⇒ 不是毛玻璃；
  · 单/双 WebGL 上下文的最小页都稳定 60fps ⇒ 不是上下文数量；
  · 源码里存在 `gl.readPixels(0,0,W,H,...)`（index.html:3025，整屏回读，8.8 MB/帧级别），
    且注释里明确写过"某些环境 readPixels 恒读到全空 ⇒ 每帧都拷一整屏却永远定不了案"。

判据（按每秒增量看，不累计）：
  · `readPixels` 每秒被调 >1 次且对应一整屏 ⇒ 就是它；
  · 若无 readPixels，但 `bufferData`/`texImage2D` 每秒成百上千次 ⇒ 是每帧重传几何/纹理；
  · 若 GL 调用次数极少而帧率仍 1fps ⇒ 命令下发不是瓶颈，问题在合成/呈现环节。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

INJECT = r"""
(function(){
  if(window.__glcnt) return;
  var C={readPixels:0, texImage2D:0, bufferData:0, drawElements:0, drawArrays:0,
         getParameter:0, getError:0, finish:0, flush:0, frames:0, framesByCtx:{}};
  window.__glcnt=C;
  var NAMES=Object.keys(C).filter(function(k){return k!=='frames'&&k!=='framesByCtx';});
  var orig=HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function(type){
    var ctx=orig.apply(this, arguments);
    if(!ctx) return ctx;
    if(!(type==='webgl'||type==='webgl2'||type==='experimental-webgl')) return ctx;
    if(ctx.__cntWrapped) return ctx;
    ctx.__cntWrapped=true;
    var idx=(window.__ctxSeq=(window.__ctxSeq||0)+1);
    NAMES.forEach(function(n){
      var f=ctx[n];
      if(typeof f!=='function') return;
      ctx[n]=function(){
        C[n]++;
        return f.apply(this, arguments);
      };
    });
    /* 每帧记账：包住 drawElements/drawArrays 之外，单独看 requestAnimationFrame 更直接，
       但这里用"每次 clear/beginFrame"太不通用，改用全局 rAF 计数放在产品无关处统计 */
    return ctx;
  };
})()
"""

COUNTER = r"""
(function(){
  if(window.__rafc) return 'ALREADY';
  window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,stalls:0};
  function loop(){
    var now=performance.now();
    if(window.__rafc.prev){ var g=now-window.__rafc.prev;
      if(g>window.__rafc.gapMax) window.__rafc.gapMax=g; if(g>200) window.__rafc.stalls++; }
    window.__rafc.prev=now; window.__rafc.n++; requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return 'OK';
})()
"""

READ = r"""
(function(){
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0};
  var c=window.__glcnt||{};
  var keys=['readPixels','texImage2D','bufferData','drawElements','drawArrays',
            'getParameter','getError','finish','flush'];
  var counts={}; keys.forEach(function(k){ counts[k]=c[k]||0; });
  return JSON.stringify({n:p.n, ms:+(performance.now()-p.t0).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    counts:counts, nCtx:window.__ctxSeq||0,
    cv:[].map.call(document.querySelectorAll('canvas'),function(x){
      return x.width+'x'+x.height;})});
})()
"""

TO_CARD = """var b=document.querySelector('#gOpt button[data-k=login]');
  if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();"""

TO_SHIP = """var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();"""


def main():
    pg = open_page(URL, win=(1400, 1000), tag='glc')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': INJECT})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4.0)
        print('装计数:', pg.ev(COUNTER),
              '| 注入的 GL 计数器存在:', pg.ev("String(!!window.__glcnt)"))
        pg.ev(TO_CARD)
        time.sleep(1.0)

        def snap():
            return json.loads(pg.ev(READ))

        print('  %-7s %-6s %-9s %-4s %-3s %-11s %-10s %-9s %-9s %-8s'
              % ('ms', 'n', 'gapMax', 'stl', 'ctx', 'readPixels', 'texImage2D',
                 'bufferData', 'drawElems', 'fps'))
        prev = snap()
        print('  %-7d %-6d %-9d %-4d %-3d %-11d %-10d %-9d %-9d'
              % (prev['ms'], prev['n'], prev['gapMax'], prev['stalls'], prev['nCtx'],
                 prev['counts']['readPixels'], prev['counts']['texImage2D'],
                 prev['counts']['bufferData'], prev['counts']['drawElements']))
        pg.ev(TO_SHIP)
        for _ in range(10):
            time.sleep(1.0)
            s = snap()
            dm = s['ms'] - prev['ms']
            f = (s['n'] - prev['n']) * 1000.0 / dm if dm else 0.0
            d = {k: s['counts'][k] - prev['counts'][k] for k in s['counts']}
            print('  %-7d %-6d %-9d %-4d %-3d %-11d %-10d %-9d %-9d %.1f'
                  % (s['ms'], s['n'], s['gapMax'], s['stalls'], s['nCtx'],
                     d['readPixels'], d['texImage2D'], d['bufferData'],
                     d['drawElements'], f))
            prev = s
        print('  ⇒ 每秒增量见上（不是累计值）')
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
