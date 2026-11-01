"""帧源解耦的**最终验收**：所有速率都在页内用 `performance.now()` 算，宿主往返延迟不再进入读数。

本轮仪器侧已连续踩四个坑，每一个都给出过"看起来很有力"的假读数，故列在此以免重犯：
  ① `cdp_helper.open_page` 漏传 gpu ⇒ 全库 64 探针跑软件渲染；
  ② `keepalive` 只伪造 focus ⇒ 挡不住加载 18–30 秒后的 1 Hz 出帧节流；
  ③ 推帧器用累加器 ⇒ 每个 tick 都推，实测 430–2078 帧/秒；
  ④ 速率用 Python 侧时间基准算 ⇒ `ev()` 往返抖动被算成帧率（pump 与 raf 读数
     完全相等、都是 546–700，这是"两个数一样"这种巧合的物理解释：它们同一个 bug）。

本探针判据（每条都在页内自算，不给宿主留介入点）：
  A 产品页 + Live2D + 推帧 60 Hz，观测 40 秒：
     · 推帧率必须落在 **55–66**（旧 bug 会给出 >400）
     · `__l2TickerState().lastTime` 必须单调递增
     · `__framePumpStat.n` 必须与 `(now-t0)/step` 相差不超过 3 帧
  B 同时记录 rAF 侧读数：若 rAF 已停（0），仍 60 推帧 ⇒ 证明解耦真的生效；
     若 rAF 仍在 60，则本轮无衰减，本探针只证明"推帧不引入额外帧"。
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
  var p=window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,stalls:0,fps:0};
  (function loop(){ var now=performance.now();
    if(p.prev){ var g=now-p.prev; if(g>p.gapMax)p.gapMax=g; if(g>200)p.stalls++; }
    p.prev=now; p.n++;
    p.fps=+(p.n/((now-p.t0)/1000)).toFixed(1);
    requestAnimationFrame(loop); })();
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
  var p=window.__framePumpStat||{n:0,t0:performance.now(),fps:60,push:0};
  var r=window.__rafc||{n:0,gapMax:0,fps:0};
  var t=window.__l2TickerState&&window.__l2TickerState();
  var el=(performance.now()-p.t0)/1000;
  return JSON.stringify({pn:p.n, pel:+el.toFixed(2), push:p.push,
    drift:+(p.n-el*p.fps).toFixed(1),
    rafn:r.n, rafAvg:r.fps, gapMax:r.gapMax||0,
    lastTime:t?t.lastTime:0, err:p.err||null, vis:document.visibilityState});
}catch(e){return JSON.stringify({err:''+e});}})()"""


def main():
    pg = Page(9402, r'D:\azur\.diag\pump2_prof', URL, (1400, 1000),
              gpu=True, keepalive=False)
    fails = []
    try:
        pg.ev(RAF)
        time.sleep(1.5)
        print('切 Live2D:', pg.ev(OPEN_L2D))
        time.sleep(3.0)
        print('解耦:', pg.detach_frames(60))
        time.sleep(1.0)
        a = json.loads(pg.ev(BOTH))
        rows = []
        for i in range(WATCH):
            time.sleep(1.0)
            b = json.loads(pg.ev(BOTH))
            d_el = b['pel'] - a['pel']
            rate = (b['pn'] - a['pn']) / d_el if d_el > 0 else 0.0
            raf_rate = (b['rafn'] - a['rafn']) / d_el if d_el > 0 else 0.0
            mono = b['lastTime'] > a['lastTime']
            rows.append((i + 1, rate, raf_rate, mono, b['drift']))
            print('  %2ds pump=%-5.1f raf=%-5.1f mono=%-5s drift=%-5.1f vis=%s err=%s'
                  % (i + 1, rate, raf_rate, mono, b['drift'], b['vis'], b['err']))
            if not mono:
                fails.append('第 %ds lastTime 未推进' % (i + 1))
            if abs(b['drift']) > 3:
                fails.append('第 %ds 漂移 %.1f 帧' % (i + 1, b['drift']))
            a = b
        steady = [r[1] for r in rows[5:]]
        rafs = [r[2] for r in rows[5:]]
        lo, hi = min(steady), max(steady)
        print('\n===== 判据 =====')
        print('  稳态推帧（丢前 5 秒）：min %.1f / avg %.1f / max %.1f'
              % (lo, sum(steady) / len(steady), hi))
        print('  同期 rAF：avg %.1f（=0 说明 rAF 已停而推帧未停，解耦生效）'
              % (sum(rafs) / len(rafs)))
        ok_rate = lo >= 55 and hi <= 66
        print('  ① 推帧率在 55–66：%s' % ('PASS' if ok_rate else 'FAIL'))
        if not ok_rate:
            fails.append('推帧率越界 %.1f–%.1f' % (lo, hi))
        print('  ② lastTime 单调 & 漂移 ≤3：%s' % ('PASS' if not fails else 'FAIL %s' % fails))
        print('  总判：%s' % ('PASS' if ok_rate and not fails else 'FAIL'))
    finally:
        pg.close()
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
