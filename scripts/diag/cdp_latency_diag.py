"""量化 CDP 往返延迟，并把「仪器慢」与「产品重」分开（2026-10-29）。

为什么需要
----------
`l2d_click_prep_diag.py` 实测（2026-10-29）：同一台机、同一条画廊页，
`Input.dispatchMouseEvent` 的 **mousePressed 与 mouseReleased 之间隔了 17 秒**，
而 `Runtime.evaluate('JSON.stringify({...几个字段})')` 也要 **2.4 秒**。
在这个量级上，任何「点击 → 读参数」的探针都不成立：
按下时命中的几何和抬起时命中的几何已经是两个不同的姿态，
而产品自己的 `onDown`/`onUp` 就靠这两个时刻判命中 ⇒ 必然读到「三条分支都没进」。
⇒ 这类 FAIL **必须先证明仪器不掉帧，才允许归因到产品**。

三类延迟必须分开测，否则会把「浏览器沙箱慢」误判成「页面卡」：
  · `1+1`（不含任何产品代码）        = 传输 + 调度基线
  · `document.title`（碰 DOM）        = DOM/主线程排队
  · `__l2ModelRef()`（碰 Live2D 对象）= 页面主线程是否被渲染吃掉

判据（延迟分档，参照 2026-10-28 的 rAF 1 Hz 事故里同一套阈值）
  · 基线 `1+1` < 50 ms 且 `document.title` < 100 ms ⇒ 传输层健康
  · 若 `1+1` 就 > 500 ms ⇒ **传输/进程层慢**（机器负载、profile 残留、Chrome 复用了坏实例）
  · 若 `1+1` 快而 `__l2ModelRef()` 慢 ⇒ **主线程被渲染吃掉**（属产品真实成本，可用）

用法:
  py -3 scripts/diag/cdp_latency_diag.py [keepalive 0|1] [轮数]
  py -3 scripts/diag/cdp_latency_diag.py 1 8
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from gallery_ui_shots import Page  # noqa: E402

KA = (sys.argv[1] if len(sys.argv) > 1 else '1') != '0'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 8
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = 9410
PROF = r'D:\azur\.diag\cdplat_prof' if KA else r'D:\azur\.diag\cdplat_noka_prof'

PROBES = [('1+1', '1+1'),
          ('title', 'document.title.length'),
          ('l2ref', '(window.__l2ModelRef&&__l2ModelRef())?1:0')]


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP %s' % r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达: %s' % e); return 2

    print('keepalive=%s 轮数=%d' % (KA, N))
    pg = Page(PORT, PROF, BASE, (1400, 1000), gpu=True, keepalive=KA)
    try:
        time.sleep(4)
        lat = {name: [] for name, _ in PROBES}
        # 加载完立刻测一遍与等 30 秒后再测一遍，才能区分「启动期抖动」与「稳态」
        for phase, wait in (('加载后 4s', 0), ('加载后 40s', 34)):
            if wait:
                time.sleep(wait)
            print('\n--- %s ---' % phase)
            for name, expr in PROBES:
                for i in range(N):
                    t0 = time.time()
                    pg.ev(expr)
                    lat[name].append(int((time.time() - t0) * 1000))
                v = sorted(lat[name])
                print('  %-6s n=%d  min %d / mid %d / max %d ms'
                      % (name, N, v[0], v[len(v) // 2], v[-1]))
            print('  帧源: %s' % pg.detach_frames(60))

        # 派发一次点击，量「按下→抬起」之间的真实间隔
        print('\n--- 点击派发间隔 ---')
        t0 = time.time()
        pg.cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': 600, 'y': 400,
                                           'button': 'left', 'clickCount': 1})
        d1 = (time.time() - t0) * 1000
        time.sleep(0.08)
        t1 = time.time()
        pg.cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': 600, 'y': 400,
                                           'button': 'left', 'clickCount': 1})
        d2 = (time.time() - t1) * 1000
        print('  mousePressed %.0f ms / mouseReleased %.0f ms ⇒ 按下→抬起墙钟间隔 %.0f ms'
              % (d1, d2, d1 + 80 + d2))

        # 关键对照：加载 Live2D 模型 + detach_frames 之后再测一次。
        # 若延迟从 ms 级跳到秒级 ⇒ 慢的是**探针自己注入的推帧泵**，不是 CDP、也不是产品。
        print('\n--- 加载 Live2D 模型后 ---')
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('  开卡:', pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key==='ougen_8';});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK';})()"""))
        time.sleep(1.6)
        print('  选肤:', pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k==='ougen_8';}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""))
        time.sleep(1.3)
        print('  切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
        for _ in range(60):
            if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") == 1:
                break
            time.sleep(1.0)
        lat2 = {name: [] for name, _ in PROBES}
        for name, expr in PROBES:
            for i in range(N):
                t0 = time.time(); pg.ev(expr); lat2[name].append(int((time.time() - t0) * 1000))
            v = sorted(lat2[name])
            print('  %-6s（未 detach）min %d / mid %d / max %d ms' % (name, v[0], v[len(v) // 2], v[-1]))
        print('  帧源: %s' % pg.detach_frames(60))
        time.sleep(1.5)
        lat3 = {name: [] for name, _ in PROBES}
        for name, expr in PROBES:
            for i in range(N):
                t0 = time.time(); pg.ev(expr); lat3[name].append(int((time.time() - t0) * 1000))
            v = sorted(lat3[name])
            print('  %-6s（已 detach）min %d / mid %d / max %d ms' % (name, v[0], v[len(v) // 2], v[-1]))
        print('  detach 后 fps: %.1f' % pg.require_frames(2.0))
        t0 = time.time()
        pg.cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': 600, 'y': 400,
                                           'button': 'left', 'clickCount': 1})
        d3 = (time.time() - t0) * 1000
        time.sleep(0.08)
        t1 = time.time()
        pg.cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': 600, 'y': 400,
                                           'button': 'left', 'clickCount': 1})
        d4 = (time.time() - t1) * 1000
        print('  detach 后 mousePressed %.0f ms / mouseReleased %.0f ms ⇒ 间隔 %.0f ms'
              % (d3, d4, d3 + 80 + d4))
        pump = pg.ev("(function(){return window.__framePump?JSON.stringify({"
                     "n:window.__framePump.n,ticks:window.__framePump.ticks,"
                     "cost:window.__framePump.cost,maxItv:window.__framePump.maxItv}):'NONE';})()")
        print('  推帧泵自述:', pump)

        bad = []
        for name, _ in PROBES:
            mid = sorted(lat[name])[len(lat[name]) // 2]
            if name == '1+1' and mid > 500:
                bad.append('传输层慢（1+1 mid=%d ms）' % mid)
            elif name == 'title' and mid > 1000:
                bad.append('DOM 排队慢（title mid=%d ms）' % mid)
        print('\n结论:', '；'.join(bad) if bad else '延迟健康，探针读数可归因产品')
        return 0 if not bad else 3
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
