"""第五层仪器故障取证（续）：`gapMax` 单调增长 20→34→88→491→1455ms ⇒ 逐帧累积。

已排除（同轮同仪器，逐条有读数）：
  · SwiftShader 回退 / 上下文丢失 / 浏览器节流 / ΔrAF≡Δcore.update —— 见 gl_backend_switch_diag；
  · 每帧工作变慢 —— medA=6ms、medB=11ms 平稳，只有偶发整段停顿 —— 见 frame_cost_split_diag；
  · CDP 每秒取样本身 —— 20 秒只取两次仍 11.6fps —— 见 stall_attribution_diag C1；
  · `Network.enable` / `setCacheDisabled` —— A/B/C 三组全衰减 —— 见 network_cdp_stall_ab；
  · 「Live2D 特有」—— **不切 Live2D 的静态立绘页也衰减到 1fps** —— 见 stall_owner_diag P4；
  · 宿主/合成器 —— 极简 WebGL 页同浏览器稳定 60fps 零衰减 —— 见 stall_attribution_diag C2。

⇒ 本节的假设（可一次验掉）：**V8 堆逐帧累积 → 主 GC 越跑越久**。
  判据三条同时取：
    ① 每秒读 `performance.memory.usedJSHeapSize`：若单调上升，假设成立一半；
    ② 中途调 `HeapProfiler.collectGarbage`：若帧率立刻回到 60 再慢慢衰减 ⇒ 因果确认；
    ③ 对照组：极简页同法读堆，若堆平且不衰减 ⇒ 差异确实是「产品页在逐帧分配」。
  只做 ① 不够 —— 堆上涨也可能只是缓存预热，必须看 ② 能否把帧率救回来。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
MINI = 'file:///D:/azur/scripts/diag/glmin.html#gallery_v2'

STEP_L2D_ON = [
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
  window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,marks:[]};
  function loop(){
    var now=performance.now();
    if(window.__rafc.prev){
      var g=now-window.__rafc.prev;
      if(g>window.__rafc.gapMax) window.__rafc.gapMax=g;
      if(g>200) window.__rafc.marks.push({t:+(now-window.__rafc.t0).toFixed(0), g:+g.toFixed(0)});
    }
    window.__rafc.prev=now; window.__rafc.n++; requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return 'OK';
})()
"""

READ = r"""
(function(){
  var p=window.__rafc, m=performance.memory||{};
  return JSON.stringify({n:p.n, ms:+(performance.now()-p.t0).toFixed(0),
    gapMax:+p.gapMax.toFixed(0),
    heapMB:+(m.usedJSHeapSize/1048576).toFixed(1),
    totalMB:+(m.totalJSHeapSize/1048576).toFixed(1),
    limitMB:+(m.jsHeapSizeLimit/1048576).toFixed(0),
    nStalls:(p.marks||[]).length,
    lastMarks:(p.marks||[]).slice(-3)});
})()
"""


def fps_between(a, b):
    dm = b['ms'] - a['ms']
    return (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0


def line(prev, s):
    f = fps_between(prev, s) if prev else 0.0
    print('  %-7d %-6d %-8d %-11s %-8s %-6s %s'
          % (s['ms'], s['n'], s['gapMax'], s['heapMB'], s['totalMB'],
             s['nStalls'], ('%.1f fps' % f) if prev else ''))
    if s['lastMarks']:
        print('         近三次 >200ms 停顿:', s['lastMarks'])


def product_with_gc():
    print('\n===== H1 产品页：读堆 + 中途强制 GC =====')
    pg = open_page(URL, win=(1400, 1000), tag='h1')
    try:
        time.sleep(4)
        for js, wait in STEP_L2D_ON:
            pg.ev(js)
            if wait:
                time.sleep(wait)
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('装计数:', pg.ev(COUNTER))
        try:
            pg.cmd('HeapProfiler.enable')
        except Exception as e:  # noqa: BLE001
            print('  HeapProfiler.enable 失败（不影响读堆）:', e)
        print('  %-7s %-6s %-8s %-11s %-8s %-6s %s'
              % ('ms', 'n', 'gapMax', 'heapMB', 'totalMB', 'stalls', 'fps'))
        prev = None
        for i in range(16):
            if i == 8:
                try:
                    pg.cmd('HeapProfiler.collectGarbage')
                    print('  --- 已强制 GC ---')
                except Exception as e:  # noqa: BLE001
                    print('  强制 GC 失败:', e)
            s = json.loads(pg.ev(READ))
            line(prev, s)
            prev = s
            time.sleep(1.0)
        print('  判据：GC 后 fps 回 60 再衰减 ⇒ 主因是堆累积；堆平却仍衰减 ⇒ 假设作废')
    finally:
        pg.close()


def mini_control():
    print('\n===== H2 对照：极简页读堆 =====')
    pg = open_page(MINI, win=(1400, 1000), tag='h2')
    try:
        time.sleep(2.5)
        print('装计数:', pg.ev(COUNTER))
        print('  %-7s %-6s %-8s %-11s %-8s %-6s %s'
              % ('ms', 'n', 'gapMax', 'heapMB', 'totalMB', 'stalls', 'fps'))
        prev = None
        for _ in range(10):
            s = json.loads(pg.ev(READ))
            line(prev, s)
            prev = s
            time.sleep(1.0)
    finally:
        pg.close()


def main():
    product_with_gc()
    mini_control()
    return 0


if __name__ == '__main__':
    sys.exit(main())
