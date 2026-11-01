"""第七层仪器故障取证：用 V8 CPU 采样 profile 直接看「1 秒停顿」那一刻在跑什么。

排除台账（前六节实测，全部真 GPU、同机同时段）：
  后端不变(NVIDIA) / 无上下文丢失 / 无节流 / 每帧工作平稳(6ms+11ms) /
  少取样也掉 / 不调 Network 也掉 / 静态立绘页也掉 / 堆不涨且强制 GC 无效 /
  画布 800×600、视口×dpr、视口×dpr×2 全部稳定 60fps / 极简页稳定 60fps

⇒ 排除法已走到尽头，剩下的可能都藏在**产品页自身的脚本**里。
  本节不再"排除"，改为直接取证：`Profiler.start` 采 12 秒（足够跨过衰减起点），
  按 `hitCount` 聚合**自身耗时**（self time），列出占比最高的函数及其所在脚本 URL。

判据：
  · 若热点集中在某一个产品函数（如逐帧 resize / 遍历 / 布局读写）⇒ 该函数就是病灶；
  · 若热点全在 `(program)`/`(garbage collector)`/`(idle)` 而帧率仍掉 ⇒ 时间不在 JS，
    必须转向合成器/GPU 侧（届时改测 CDP Tracing 的类别直方图，不再采 JS）；
  · 若热点在 extension/开发者工具注入脚本（CDP 自身）⇒ 仍是仪器问题。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

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

READ = ("JSON.stringify({n:window.__rafc.n, ms:+(performance.now()-window.__rafc.t0).toFixed(0),"
        " gapMax:+window.__rafc.gapMax.toFixed(0), stalls:window.__rafc.stalls})")


def top_self(profile, limit=28):
    nodes = {n['id']: n for n in profile['nodes']}
    parent = {}
    for n in profile['nodes']:
        for c in n.get('children', []):
            parent[c] = n['id']
    # hitCount 只统计自身样本
    rows = []
    for n in profile['nodes']:
        h = n.get('hitCount', 0)
        if h <= 0:
            continue
        cf = n['callFrame']
        name = cf.get('functionName') or '(anonymous)'
        url = cf.get('url') or ''
        url = url.replace('http://127.0.0.1:8778/gallery_v2/', '').replace('file:///D:/azur/', '')
        rows.append((h, name, url, cf.get('lineNumber', -1) + 1))
    rows.sort(reverse=True)
    total = sum(r[0] for r in rows) or 1
    print('  采样总数(自身) = %d' % total)
    print('  %-6s %-7s %-34s %-26s %s' % ('hit', 'share', 'function', 'script', 'line'))
    for h, name, url, ln in rows[:limit]:
        print('  %-6d %-7s %-34s %-26s %s'
              % (h, '%.1f%%' % (100.0 * h / total), name[:34], url[-26:] or '-', ln))
    return total


def main():
    pg = open_page(URL, win=(1400, 1000), tag='prof')
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
        pg.cmd('Profiler.enable')
        pg.cmd('Profiler.setSamplingInterval', {'interval': 200})
        pg.cmd('Profiler.start')
        print('\n采集中（12 秒，静置不点击）…')
        prev = None
        for _ in range(6):
            time.sleep(2.0)
            s = json.loads(pg.ev(READ))
            f = ((s['n'] - prev['n']) * 1000.0 / (s['ms'] - prev['ms'])) if prev else 0.0
            print('  t=%-6d n=%-5d gapMax=%-6d stalls=%-3d %s'
                  % (s['ms'], s['n'], s['gapMax'], s['stalls'],
                     ('%.1f fps' % f) if prev else ''))
            prev = s
        prof = pg.cmd('Profiler.stop', {})
        prof = prof.get('profile') or prof
        print('\n--- 采样期内最耗自身时间的函数 ---')
        top_self(prof)
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
