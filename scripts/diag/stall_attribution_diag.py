"""给「周期性 ~1s 整段停顿」定责：产品侧 / CDP 取样侧 / 宿主环境侧。

已实测并排除（全部有读数，非推测）：
  · SwiftShader 回退 —— UNMASKED_RENDERER_WEBGL 全程 `ANGLE (NVIDIA RTX 4070)`；
  · WebGL 上下文丢失 —— `webglcontextlost` 0 次，`isContextLost()` 恒 false；
  · 浏览器节流 —— `visibilityState=visible`、`hasFocus=true`，ΔrAF 与 Δcore.update 恒等；
  · 每帧工作变慢 —— `frame_cost_split_diag`：medA=6ms(core.update)、medB=11ms(renderer.render)、
    medC(gap) 中位仅 17–64ms，但 **max 达 1038ms** ⇒ 是「整段卡一下」，不是「每帧更慢」。

⇒ 只剩三处可能：产品某段偶发重活 / CDP 每秒 Runtime.evaluate 自身 / 宿主与 headless 合成器。
本节三个用例各自隔离一个变量：

  C1 「少取样」：l2d 页装好计数器后**只取两次**（t≈2s 与 t≈20s），帧率由页面侧计数器算出。
     → 若同样掉到 1fps，CDP 取样不是成因；若恢复 60fps，说明停顿是**观测行为**制造的。
  C2 「极简页」：data: URL，只有一个 WebGL canvas + rAF 计数，不含任何产品代码，**每秒取样**。
     → 若同样衰减，成因在宿主/headless 合成器，与本项目产品无关。
  C3 「产品页 + 每秒取样」：作为 C1、C2 的同场景基线。

判据：只有 C3 衰减而 C1、C2 都不衰减，才能把停顿算到产品头上。
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
    ("""var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
          return e.dataset.k=='live2d';}); if(t&&!t.classList.contains('dis')) t.click();""", 0),
]

COUNTER = r"""
(function(){
  if(window.__rafc) return 'ALREADY';
  window.__rafc={n:0, marks:[], t0:performance.now(), gapMax:0, prev:0};
  function loop(){
    var now=performance.now();
    if(window.__rafc.prev){ var g=now-window.__rafc.prev;
      if(g>window.__rafc.gapMax) window.__rafc.gapMax=g; }
    window.__rafc.prev=now; window.__rafc.n++; requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return 'OK';
})()
"""

READ = "JSON.stringify({n:window.__rafc.n, ms:+(performance.now()-window.__rafc.t0).toFixed(0), gapMax:+window.__rafc.gapMax.toFixed(0)})"

MINI = 'file:///D:/azur/scripts/diag/glmin.html#gallery_v2'


def fps_between(a, b):
    dm = b['ms'] - a['ms']
    return (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0


def case_sparse():
    print('\n===== C1 产品页 / 只取两次（少取样） =====')
    pg = open_page(URL, win=(1400, 1000), tag='c1')
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        for js, wait in STEP_L2D:
            pg.ev(js)
            if wait:
                time.sleep(wait)
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('装计数:', pg.ev(COUNTER))
        time.sleep(2.0)
        a = json.loads(pg.ev(READ))
        print('  t=%.0fms n=%d' % (a['ms'], a['n']))
        time.sleep(16.0)
        b = json.loads(pg.ev(READ))
        print('  t=%.0fms n=%d' % (b['ms'], b['n']))
        print('  ⇒ 两次取样之间 %.1f fps（gapMax=%dms）' % (fps_between(a, b), b['gapMax']))
        print('  判据：接近 60 ⇒ 停顿由每秒取样本身造成；≈1 ⇒ 与取样无关')
    finally:
        pg.close()


def case_mini():
    print('\n===== C2 极简 WebGL 页 / 每秒取样 =====')
    pg = open_page(MINI, win=(1400, 1000), tag='c2')
    try:
        time.sleep(2.5)
        print('  gl:', pg.ev("String(window.__info)"))
        print('  %-7s %-6s %-10s %s' % ('ms', 'n', 'gapMax', 'fps'))
        prev = None
        for _ in range(10):
            s = json.loads(pg.ev(READ))
            f = fps_between(prev, s) if prev else 0.0
            print('  %-7d %-6d %-10d %s' % (s['ms'], s['n'], s['gapMax'],
                                            ('%.1f' % f) if prev else ''))
            prev = s
            time.sleep(1.0)
        print('  判据：同样衰减 ⇒ 宿主/headless 合成器问题，与产品无关')
    finally:
        pg.close()


def case_dense():
    print('\n===== C3 产品页 / 每秒取样（基线） =====')
    pg = open_page(URL, win=(1400, 1000), tag='c3')
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        for js, wait in STEP_L2D:
            pg.ev(js)
            if wait:
                time.sleep(wait)
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('装计数:', pg.ev(COUNTER))
        print('  %-7s %-6s %-10s %s' % ('ms', 'n', 'gapMax', 'fps'))
        prev = None
        for _ in range(12):
            s = json.loads(pg.ev(READ))
            f = fps_between(prev, s) if prev else 0.0
            print('  %-7d %-6d %-10d %s' % (s['ms'], s['n'], s['gapMax'],
                                            ('%.1f' % f) if prev else ''))
            prev = s
            time.sleep(1.0)
    finally:
        pg.close()


SWEEPER = r"""
(function(){
  /* 铺一层自建 2D canvas：刻意落在一块**不属于** Pixi 的大面积上（手绘覆盖），
     既盖住 Live2D，也不经过 Pixi 的合成路径。用来区分「时间花在 WebGL 合成」还是「任意大面积合成」。 */
  var d=document.createElement('canvas');
  d.id='__sweeper'; d.width=1400; d.height=1000;
  d.style.cssText='position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:99999;'
                 +'pointer-events:none;';
  document.body.appendChild(d);
  var x=d.getContext('2d'); var t0=performance.now(); window.__swp={frames:0,cost:[],gapMax:0,prev:0};
  (function loop(){
    var now=performance.now();
    if(window.__swp.prev){ var g=now-window.__swp.prev; if(g>window.__swp.gapMax) window.__swp.gapMax=g; }
    window.__swp.prev=now;
    var a=performance.now();
    x.fillStyle='#000'; x.fillRect(0,0,1400,1000);
    x.fillStyle='#0f0'; x.fillRect(20+((now-t0)/10)%600, 20, 60, 60);
    window.__swp.cost.push(+(performance.now()-a).toFixed(2));
    window.__swp.frames++;
    requestAnimationFrame(loop);
  })();
  return 'OK';
})()
"""

SWP_READ = r"""
(function(){
  var s=window.__swp||{frames:0,gapMax:0}; var c=s.cost||[];
  var b=c.slice(-40).sort(function(x,y){return x-y;});
  return JSON.stringify({ms:+performance.now().toFixed(0), n:s.frames,
    rafN:window.__rafc&&window.__rafc.n,
    gapMax:+s.gapMax.toFixed(0), medCost:b.length?b[b.length>>1]:null});
})()
"""


def case_sweeper():
    print('\n===== C4 产品页 + 全屏 2D 扫刷（强制逐帧合成） =====')
    pg = open_page(URL, win=(1400, 1000), tag='c4')
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        for js, wait in STEP_L2D:
            pg.ev(js)
            if wait:
                time.sleep(wait)
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('装计数:', pg.ev(COUNTER))
        time.sleep(2.0)
        a = json.loads(pg.ev(READ))
        print('铺扫刷前 t=%.0fms rafN=%d' % (a['ms'], a['n']))
        print('铺扫刷:', pg.ev(SWEEPER))
        print('  %-7s %-6s %-8s %-10s %-8s %s'
              % ('ms', 'n', 'rafN', 'gapMax', 'medCost', 'fps'))
        prev = None
        for _ in range(10):
            s = json.loads(pg.ev(SWP_READ))
            f = ''
            if prev:
                dm = s['ms'] - prev['ms']
                f = ('%.1f' % ((s['rafN'] - prev['rafN']) * 1000.0 / dm)) if dm else ''
            print('  %-7d %-6d %-8s %-10s %-8s %s'
                  % (s['ms'], s['n'], s['rafN'], s['gapMax'], s['medCost'], f))
            prev = s
            time.sleep(1.0)
        print('  判据：扫刷把整屏每帧重画后 rAF 恢复 ≈60 ⇒ 停顿是'
              '「该帧没有要求合成」的宿主行为，与产品无关')
    finally:
        pg.close()


def main():
    case_sparse()
    case_mini()
    case_sweeper()
    case_dense()
    return 0


if __name__ == '__main__':
    sys.exit(main())
