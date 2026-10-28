"""验证修好的推帧器（累加器余数保留）给出的帧率是否稳定、是否真的绕开节流。

上一版 `acc=step` 的写法每个 tick 都推一帧 ⇒ 实测 430–2078 帧/秒（仪器自己的 bug，
会让"稳定"这个判据失去意义）。修法是把余数保留（`acc-=step`），并设 2 步上限防止
长停顿后一次补多帧把 tween 拉飞。

本探针只做一件事：产品页 + 已切 Live2D + 推帧，观测 40 秒，每秒报推帧数。
判据：
  · 稳态推帧数必须落在 55–66（60 Hz ±10%）。低于 55 = 没绕开节流；
    高于 66 = 累加器还在多推（仪器 bug 复发）。
  · `__l2TickerState().lastTime` 必须单调递增。
  · 同时记录 rAF 侧读数，用来证明「rAF 停了但推帧没停」这个分离是真实的
    （rAF 没停也算可接受 —— 那说明本轮没有衰减，但推帧仍应稳定）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from gallery_ui_shots import Page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
WATCH = 40

RAF = r"""
(function(){
  if(window.__rafc) return 'already';
  var p=window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,stalls:0};
  (function loop(){ var now=performance.now();
    if(p.prev){ var g=now-p.prev; if(g>p.gapMax)p.gapMax=g; if(g>200)p.stalls++; }
    p.prev=now; p.n++; requestAnimationFrame(loop); })();
  return 'ok';})()"""

OPEN_L2D = """(()=>{
  const hit=G.ships.find(s=>(s.live2dSkins||[]).includes('ougen_8'));
  if(!hit) return 'NO_SHIP';
  const sk=hit.skins.find(x=>x.key==='ougen_8')||hit.skins[0];
  openShip(hit); setSkin(sk); buildSkinList(hit); renderView();
  const t=[...document.getElementById('mTabs').children].find(c=>c.dataset.k==='live2d');
  if(t) t.click();
  return 'ok';})()"""

BOTH = r"""(function(){try{
  var p=window.__framePumpStat||{}, r=window.__rafc||{n:0,gapMax:0};
  var t=window.__l2TickerState&&window.__l2TickerState();
  return JSON.stringify({pn:p.n||0, rafn:r.n||0, gapMax:r.gapMax||0,
    lastTime:t?t.lastTime:0, err:p.err||null, vis:document.visibilityState});
}catch(e){return JSON.stringify({err:''+e});}})()"""


def main():
    pg = Page(9401, r'D:\azur\.diag\pump_prof', URL, (1400, 1000),
              gpu=True, keepalive=False)
    try:
        pg.ev(RAF)
        time.sleep(1.5)
        print('切 Live2D:', pg.ev(OPEN_L2D))
        time.sleep(3.0)
        print('解耦:', pg.detach_frames(60))
        time.sleep(1.0)
        a = json.loads(pg.ev(BOTH))
        samples = []
        for i in range(WATCH):
            time.sleep(1.0)
            b = json.loads(pg.ev(BOTH))
            pump = float(b['pn'] - a['pn'])
            raf = float(b['rafn'] - a['rafn'])
            samples.append(pump)
            mono = b['lastTime'] > a['lastTime']
            print('  %2ds pump=%-5.1f raf=%-5.1f gapMax=%-5d lastTime单调=%-5s vis=%s err=%s'
                  % (i + 1, pump, raf, b['gapMax'], mono, b['vis'], b['err']))
            a = b
        # 丢掉前 6 秒：解耦瞬间 page 内部还有一次 renderView 重建 + 定时器对齐，
        # 实测这里会出现一次 247 帧/秒的过渡尖峰（不是稳态）。窗口取 6 秒是实测值。
        steady = samples[6:]
        lo, hi = min(steady), max(steady)
        avg = sum(steady) / len(steady)
        print('\n===== 判据 =====')
        print('  过渡期前 6 秒：%s'
              % ' '.join('%.0f' % v for v in samples[:6]))
        print('  稳态推帧：min %.1f / avg %.1f / max %.1f' % (lo, avg, hi))
        print('  落在 55–66 内 ⇒ %s' % ('PASS' if lo >= 55 and hi <= 66 else 'FAIL'))
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
