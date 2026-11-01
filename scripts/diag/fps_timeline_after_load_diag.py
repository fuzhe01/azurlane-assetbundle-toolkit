"""量帧率时间线：在"加载后等 2.5 秒再点击"这个场景下，页面到底跑多少 fps。

背景：`update_entry_flaky_diag` 在同一场景下 3 次只采到 11/14/55 个 update 样本，
而 `tween_visible_at_update_diag`（模型就绪后立即打桩）同一位置 3.7 秒采到 216 个（58fps）。
两次的差别只有「模型就绪后是否额外等 2.5 秒」。这个差别要么是帧率真的掉了，
要么只是采样窗口不同 —— 必须先分清，否则会去改产品，而问题其实在仪器。

三条独立判据（同一时刻同时取，任何一条单独都不足以定性）：
  ① ticker：`__l2TickerState()` 的 lastTime 是否推进、FPS 读数；
  ② rAF：注入的 requestAnimationFrame 计数器是否推进（ticker 可能仍跑但 rAF 停了）；
  ③ core.update 调用计数（打桩 `update()` 入口）。
  `document.visibilityState` 与 `hasFocus` 一并记录 —— 上一轮已证明它们不足以判定
  （"visible + hasFocus=true" 时 rAF 仍曾停摆），但仍是排除项。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
CTR = r"""
(function(){
  if(window.__ctrInstalled) return 'ALREADY';
  window.__ctrInstalled=true;
  window.__raf=0; window.__upd=0; window.__t0=performance.now();
  (function loop(){ window.__raf++; requestAnimationFrame(loop); })();
  var m=window.__l2ModelRef&&window.__l2ModelRef();
  if(m&&m.internalModel&&!m.internalModel.coreModel.__ctrw){
    var c=m.internalModel.coreModel; c.__ctrw=true;
    var iu=c.update.bind(c); c.update=function(){ window.__upd++; return iu.apply(this,arguments); };
  }
  return 'OK';
})()
"""
SAMPLE = r"""
JSON.stringify({
  ms: +(performance.now()-window.__t0).toFixed(0),
  raf: window.__raf, upd: window.__upd,
  vis: document.visibilityState, focus: document.hasFocus(),
  ticker: window.__l2TickerState?__l2TickerState():null
})
"""


def main():
    pg = open_page(URL, win=(1400, 1000), tag='fps')
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()""")
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k=='ougen_8';}); if(d) d.click(); return 1;})()""")
        time.sleep(1.3)
        print('切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k=='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('装计数器:', pg.ev(CTR))
        print('\n  %-7s %-6s %-6s %-8s %-7s %-9s %s'
              % ('ms', 'raf', 'upd', 'vis', 'focus', 'tk.lastTime', 'tk.FPS'))
        prev = None
        for i in range(12):
            s = json.loads(pg.ev(SAMPLE))
            tk = s.get('ticker') or {}
            print('  %-7d %-6d %-6d %-8s %-7s %-9s %s'
                  % (s['ms'], s['raf'], s['upd'], s['vis'], s['focus'],
                     tk.get('lastTime'), tk.get('fps')))
            if prev:
                dr = s['raf'] - prev['raf']
                du = s['upd'] - prev['upd']
                dm = s['ms'] - prev['ms']
                if dm:
                    print('         ↑ %d ms 内 Δraf=%d Δupd=%d → %.1f / %.1f fps'
                          % (dm, dr, du, dr * 1000.0 / dm, du * 1000.0 / dm))
            prev = s
            time.sleep(1.0)
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
