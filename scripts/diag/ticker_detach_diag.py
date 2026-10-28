"""把「浏览器不发帧」与「产品每帧变慢」彻底分家的判据探针。

背景：本轮已定量证明两件事，且它们**互相独立**：
  · 出帧源被节流：加载 18–25 秒后 `gapMax` 从 193 ms 跳到 1016 ms（精确 1 Hz），
    极简页（零产品代码）同样发生 ⇒ 与产品无关；`Page.bringToFront` 能救回来几分钟，
    但救不过全程（K2 在 27–48 秒又掉到 1 Hz，说明是窗口状态机反复重算，不是一次性判定）；
  · 产品每帧成本平稳：`core.update` 中位 6 ms、`render` 中位 11 ms，全程不变。

⇒ 任何「逐帧」判据（参数是否收敛、tween 是否推进、热区是否命中）在 headless 下都不可信，
**除非把帧源从 rAF 解耦**。本探针就是那个解耦装置：

  D1 基线（rAF 驱动）—— 记录 70 秒真实帧率，作为「不干预会掉到多少」的对照；
  D2 解耦（`ticker.stop()` + 定时器 `ticker.update(now)` 固定 60 Hz 推帧）
     —— 判据：70 秒内推帧数必须 ≈ 4200（±2%），且 `__l2TickerState().lastTime` 单调递增。
     若 D2 全程稳定 ⇒ 仪器问题彻底解决，后续验收判据可以放心依赖逐帧行为；
     若 D2 也掉 ⇒ 说明产品真的在吃每帧成本，回到产品侧。

⚠️ 必须在 `close()` 前恢复 `ticker.start()`：页面与浏览器共用，不复位会让下一次
   打开同一 profile 的探针读到"ticker 停着"的假状态。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from gallery_ui_shots import Page  # noqa: E402

BASE = 'http://127.0.0.1:8778/gallery_v2'
URL = BASE + '/index.html#gallery_v2'

PROBE = r"""
(function(){
  var p=window.__rafc||(window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,stalls:0});
  return JSON.stringify({n:p.n, ms:+(performance.now()-(p.t0||0)).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    vis:document.visibilityState, foc:document.hasFocus(),
    tick:(function(){try{return window.__l2TickerState&&window.__l2TickerState();}
                     catch(e){return null;}})()});
})()
"""

# 页面自带的 rAF 计数器（产品页没有 __rafc，这里补一个最小版）
INSTALL_RAF = r"""
(function(){
  if(window.__rafc) return 'already';
  var p=window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,stalls:0};
  function loop(){ var now=performance.now();
    if(p.prev){ var g=now-p.prev; if(g>p.gapMax)p.gapMax=g; if(g>200)p.stalls++; }
    p.prev=now; p.n++; requestAnimationFrame(loop); }
  requestAnimationFrame(loop); return 'ok'; })()
"""

OPEN_L2D = """(()=>{
  const hit=G.ships.find(s=>(s.live2dSkins||[]).includes('ougen_8'));
  if(!hit) return 'NO_SHIP';
  const sk=hit.skins.find(x=>x.key==='ougen_8')||hit.skins[0];
  openShip(hit); setSkin(sk); buildSkinList(hit); renderView();
  const t=[...document.getElementById('mTabs').children].find(c=>c.dataset.k==='live2d');
  if(t) t.click();
  return 'ok';})()"""

DETACH = r"""
(function(){
  var tk=window.__l2Ticker&&window.__l2Ticker();
  if(!tk) return 'NO_TICKER';
  tk.autoStart=false; tk.stop();
  window.__det={n:0,t0:performance.now(),last:performance.now()};
  if(window.__detTimer) clearInterval(window.__detTimer);
  var step=1000/60;
  window.__detTimer=setInterval(function(){
    var now=performance.now(); var d=now-window.__det.last;
    if(d<step*0.5) return;
    window.__det.last=now; window.__det.n++;
    try{ tk.update(now, true); }catch(e){ window.__det.err=''+e; }
  }, 4);
  return 'ok';})()"""

REDETACH_STATE = r"""
(function(){ var d=window.__det;
  return JSON.stringify({n:d?d.n:0, ms:d?+(performance.now()-d.t0).toFixed(0):0,
    err:d&&d.err||null,
    tick:(function(){try{return window.__l2TickerState&&window.__l2TickerState();}
                     catch(e){return null;}})()}); })()"""

RESTORE = r"""
(function(){ if(window.__detTimer){clearInterval(window.__detTimer);window.__detTimer=0;} 
  var tk=window.__l2Ticker&&window.__l2Ticker(); if(tk){tk.autoStart=true;tk.start();}
  return 'ok';})()"""


def watch(pg, seconds, tag, marks=(10, 20, 30, 50, 68)):
    got = {}
    prev = json.loads(pg.ev(PROBE))
    for _ in range(seconds):
        s = json.loads(pg.ev(PROBE))
        dm = s['ms'] - prev['ms']
        f = (s['n'] - prev['n']) * 1000.0 / dm if dm else 0.0
        for t in marks:
            if abs(s['ms'] - t * 1000) <= 700 and t not in got:
                got[t] = f
        if f < 30.0:
            print('   %s %-6d fps=%-6.1f gapMax=%-5d vis=%-7s'
                  % (tag, s['ms'], f, s['gapMax'], s['vis']))
        prev = s
        time.sleep(1.0)
    return got


def main():
    # ---- D1：不干预基线（真页 + Live2D 模型） ----
    print('\n===== D1 基线（rAF，已切 ougen_8 的 Live2D）=====')
    pg = Page(9397, r'D:\azur\.diag\detach_prof', URL, (1400, 1000),
              gpu=True, keepalive=False)
    try:
        pg.ev(INSTALL_RAF)
        time.sleep(2)
        print('  切模型:', pg.ev(OPEN_L2D))
        time.sleep(3)
        print('  ticker:', pg.ev(PROBE)[:160])
        d1 = watch(pg, 30, 'D1')

        # ---- D2：同一条页面，改成定时器推帧 ----
        print('\n===== D2 解耦（ticker.stop + 定时器 60Hz）同页继续 =====')
        print('  解耦:', pg.ev(DETACH))
        time.sleep(1.0)
        a = json.loads(pg.ev(REDETACH_STATE))
        print('  起始推帧 n=%d' % a['n'])
        time.sleep(20)
        b = json.loads(pg.ev(REDETACH_STATE))
        dm = b['ms'] - a['ms']
        fp = (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0
        print('  D2 20 秒推帧 %d 次 ⇒ %.1f 帧/秒  err=%s' % (b['n'] - a['n'], fp, b['err']))
        print('  ticker.lastTime 单调: %s → %s'
              % (a['tick'] and a['tick']['lastTime'], b['tick'] and b['tick']['lastTime']))
        time.sleep(20)
        c = json.loads(pg.ev(REDETACH_STATE))
        dm = c['ms'] - b['ms']
        fp2 = (c['n'] - b['n']) * 1000.0 / dm if dm else 0.0
        print('  D2 再 20 秒 ⇒ %.1f 帧/秒（累计 n=%d）' % (fp2, c['n']))
        print('  恢复:', pg.ev(RESTORE))
    finally:
        pg.close()

    print('\n===== 判据 =====')
    print('  D1 基线 t=10s %.1f → t=30s %.1f（应衰减）'
          % (d1.get(10, -1), d1.get(30, -1)))
    print('  D2 解耦后应稳定 ≈60 帧/秒（不随 rAF 节流掉）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
