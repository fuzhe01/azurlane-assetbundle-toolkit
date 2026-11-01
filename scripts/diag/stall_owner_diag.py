"""定位「周期性 ~1s 整段阻塞」到底由产品页的哪个物件触发。

已用同一套仪器测出的对照（全部真 GPU、同一台机、同一时段）：

  | 用例 | 页面 | 取样 | 结果 |
  |---|---|---|---|
  | C2 极简 WebGL | `file:///…/glmin.html`（80 行内，只有 canvas+rAF） | 每秒 | **稳定 60fps，10 秒零衰减** |
  | C3 产品页 | 画廊 Live2D | 每秒 | 60 → 31.8 → 2.5 → 1fps |
  | C1 产品页 | 同上 | **只取两次** | 20 秒间 11.6fps（gapMax 1034ms）⇒ 不是观测造成的 |
  | C4 产品页 + 全屏 2D 扫刷 | 同上，盖一层自建 canvas 每帧重画 | 每秒 | 仍 1fps；扫刷自身 medCost=0ms |

⇒ 排除：SwiftShader 回退、上下文丢失、浏览器节流、CDP 取样、Pixi 渲染耗时、宿主合成器
   （宿主在 C2 里能稳定跑满 60）。
⇒ 剩下必须分辨的**产品侧**差异，本节逐个加/减：

  P1 baseline    ：Live2D 页（已知 1fps）+ 记录 `canvas` 数量与各自尺寸
  P2 关掉模型    ：停掉 ticker（`app.ticker.stop()`），看 rAF 是否回 60
     → 若回 60，说明阻塞由**每帧 Cubism/Pixi 工作触发**，不是页面结构
  P3 隐藏模型层  ：`dx.canvas.style.display='none'`（让主线程继续跑但不合成），同上测
  P4 静态立绘页  ：同舰船但不切 Live2D（只有普通 DOM+img）→ 分「Live2D 特有」还是「任何页都衰减」

判据落点：只有 P1/P3 衰减而 P2/P4 不衰减，才把阻塞归到 Live2D 的每帧工作；
         若 P2（ticker 停）仍衰减，说明阻塞来自页面里**与渲染无关的周期任务**；
         若 P4 也衰减，说明与本项目产品无关（宿主/尺寸/装饰）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

STEP_L2D = [
    ("""var b=document.querySelector('#gOpt button[data-k=login]');
        if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();""", 0.9),
    ("""var s=(window.GALLERY.ships||[]).find(function(x){
          return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
        var c=[...document.querySelectorAll('.card')].find(function(e){
          return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();""", 1.6),
    ("""var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
          return e.dataset.k=='ougen_8';}); if(d) d.click();""", 1.3),
]
STEP_L2D_ON = STEP_L2D + [
    ("""var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
          return e.dataset.k=='live2d';}); if(t&&!t.classList.contains('dis')) t.click();""", 0),
]

COUNTER = r"""
(function(){
  if(window.__rafc) return 'ALREADY';
  window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0};
  function loop(){
    var now=performance.now();
    if(window.__rafc.prev){ var g=now-window.__rafc.prev; if(g>window.__rafc.gapMax) window.__rafc.gapMax=g; }
    window.__rafc.prev=now; window.__rafc.n++; requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return 'OK';
})()
"""

READ = "JSON.stringify({n:window.__rafc.n, ms:+(performance.now()-window.__rafc.t0).toFixed(0), gapMax:+window.__rafc.gapMax.toFixed(0)})"

CV_INFO = r"""
(function(){
  var a=[].map.call(document.querySelectorAll('canvas'), function(c){
    return {w:c.width, h:c.height, disp:(c.style&&c.style.display)||'',
            vis:c.offsetParent!==null, z:(getComputedStyle(c).zIndex||'')}; });
  return JSON.stringify({n:a.length, list:a.slice(0,6)});
})()
"""


def fps_between(a, b):
    dm = b['ms'] - a['ms']
    return (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0


def nav(pg, steps):
    pg.cmd('Network.enable')
    pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
    pg.cmd('Page.navigate', {'url': URL})
    time.sleep(4)
    for js, wait in steps:
        pg.ev(js)
        if wait:
            time.sleep(wait)


def wait_model(pg, sec=90):
    t0 = time.time()
    while time.time() - t0 < sec:
        if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
            return True
        time.sleep(1.0)
    return False


def series(pg, label='', rounds=9):
    print('  %-7s %-6s %-9s %s' % ('ms', 'n', 'gapMax', 'fps'))
    prev = None
    for _ in range(rounds):
        s = json.loads(pg.ev(READ))
        f = fps_between(prev, s) if prev else 0.0
        print('  %-7d %-6d %-9d %s' % (s['ms'], s['n'], s['gapMax'],
                                       ('%.1f' % f) if prev else ''))
        prev = s
        time.sleep(1.0)
    return prev


def p1_baseline():
    print('\n===== P1 baseline：Live2D 页 =====')
    pg = open_page(URL, win=(1400, 1000), tag='p1')
    try:
        nav(pg, STEP_L2D_ON)
        ok = wait_model(pg)
        print('模型就绪:', ok, '| canvas:', pg.ev(CV_INFO))
        print('装计数:', pg.ev(COUNTER))
        series(pg)
    finally:
        pg.close()


def p2_ticker_stop():
    print('\n===== P2 停 ticker（不做每帧 Cubism/Pixi 工作） =====')
    pg = open_page(URL, win=(1400, 1000), tag='p2')
    try:
        nav(pg, STEP_L2D_ON)
        ok = wait_model(pg)
        print('模型就绪:', ok)
        print('装计数:', pg.ev(COUNTER))
        time.sleep(2.0)
        print('停 ticker:', pg.ev("""(function(){
            var a=window.__l2ModelRef&&window.__l2ModelRef();
            var app=a&&a.parent&&a.parent.parent;
            try{ app.ticker.stop(); return 'STOPPED'; }catch(e){ return 'ERR '+e; }
        })()"""))
        series(pg)
    finally:
        pg.close()


def p3_hide_layer():
    print('\n===== P3 隐藏 Live2D 画布（主线程照跑，不合成） =====')
    pg = open_page(URL, win=(1400, 1000), tag='p3')
    try:
        nav(pg, STEP_L2D_ON)
        ok = wait_model(pg)
        print('模型就绪:', ok)
        print('装计数:', pg.ev(COUNTER))
        time.sleep(2.0)
        print('隐藏画布:', pg.ev("""(function(){
            var m=window.__l2ModelRef&&window.__l2ModelRef();
            var v=m&&m.parent&&m.parent.parent&&m.parent.parent.view;
            if(!v) return 'NO_VIEW';
            v.style.display='none'; return 'HIDDEN '+v.width+'x'+v.height;
        })()"""))
        series(pg)
    finally:
        pg.close()


def p4_static():
    print('\n===== P4 静态立绘页（不切 Live2D） =====')
    pg = open_page(URL, win=(1400, 1000), tag='p4')
    try:
        nav(pg, STEP_L2D)
        time.sleep(1.0)
        print('canvas:', pg.ev(CV_INFO))
        print('装计数:', pg.ev(COUNTER))
        series(pg)
    finally:
        pg.close()


def main():
    p1_baseline()
    p2_ticker_stop()
    p3_hide_layer()
    p4_static()
    return 0


if __name__ == '__main__':
    sys.exit(main())
