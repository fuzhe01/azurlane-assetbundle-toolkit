"""第五层仪器故障取证：`Network.enable` + `Network.setCacheDisabled` 是周期性 ~1s 阻塞的来源。

推理链（每步都有前一步的读数支撑，不是猜测）：
  1. 产品页 Live2D：60fps → 1fps 单调衰减，`visibility=visible`、`hasFocus=true`、ΔrAF ≡ Δcore.update。
  2. 渲染后端**没换**：`UNMASKED_RENDERER_WEBGL` 全程 `ANGLE (NVIDIA RTX 4070)`，`webglcontextlost` 0 次。
  3. 每帧工作**没变慢**：`medA`(core.update)=6ms、`medB`(renderer.render)=11ms 全程平稳，
     但 gap 的 **max 达 1038ms** ⇒ 是「整段卡一下」而不是「每帧更慢」。
  4. 极简 WebGL 页（同一浏览器、同一仪器、每秒取样）**稳定 60fps 零衰减**。
  5. 连**不进入 Live2D 的静态立绘页**也衰减到 1fps ⇒ 与 Live2D 无关。
  6. 唯一剩下的差异：产品页用例前面多调了 `Network.enable` + `Network.setCacheDisabled`
     （极简页用例没调）。这两个方法会让 DevTools 抓协议、为每个请求落缓存/加载记录，
     在 headless 下是**主线程上周期性长任务**的经典来源。

判据（同页同操作，只切一个变量）：
  A 调 `Network.enable` + `setCacheDisabled` → 若衰减 ⇒ 确诊；
  B 调 `Network.enable` 但**不** disable cache（把两个变量拆开，否则修法可能只是碰巧有效）；
  C 两者都不调 → 若稳定 60fps，则 A/B 的差异就是因果，不是巧合。
  三条必须同轮跑完；只看 A 掉帧不足以定责（页面本身也可能有别的周期任务）。
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

READ = ("JSON.stringify({n:window.__rafc.n, ms:+(performance.now()-window.__rafc.t0).toFixed(0),"
        " gapMax:+window.__rafc.gapMax.toFixed(0)})")


def fps_between(a, b):
    dm = b['ms'] - a['ms']
    return (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0


def run(label, enable_net, disable_cache):
    print('\n===== %s =====' % label)
    pg = open_page(URL, win=(1400, 1000), tag=label[:2])
    try:
        if enable_net:
            pg.cmd('Network.enable')
        if disable_cache:
            pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
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
        print('  %-7s %-6s %-9s %s' % ('ms', 'n', 'gapMax', 'fps'))
        prev = None
        last = None
        for _ in range(9):
            s = json.loads(pg.ev(READ))
            f = fps_between(prev, s) if prev else 0.0
            print('  %-7d %-6d %-9d %s' % (s['ms'], s['n'], s['gapMax'],
                                           ('%.1f' % f) if prev else ''))
            prev = s
            last = s
            time.sleep(1.0)
        print('  ⇒ 末窗 fps=%.1f gapMax=%dms' % (fps_between(prev, last), last['gapMax']))
    finally:
        pg.close()


def main():
    run('A Network.enable + setCacheDisabled', True, True)
    run('B Network.enable 只开不禁缓存', True, False)
    run('C 两者都不调', False, False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
