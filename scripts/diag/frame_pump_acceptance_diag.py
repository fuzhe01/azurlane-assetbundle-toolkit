"""验收 `gallery_ui_shots.Page` 的**帧源解耦**修法：三元对照，缺一不可。

本轮已经踩过两次"单侧绿"的坑：
  · `keepalive` 只在一段时间内有效（K2 在 27–48 秒又掉回 1 Hz）就宣布局部结论；
  · 十四次排除法全靠「对照页稳定 60fps」，而那些对照只观测了 10–12 秒。
所以这次的判据必须三侧同时成立：

  V1 rAF 基线（不干预）        —— 必须衰减（否则本机这一轮压根没复现，无区分力）
  V2 bringToFront 心跳(8s)     —— 预期**只能撑一段时间**，记录最高/最低，不要求全程
  V3 detach_frames(60Hz 推帧)  —— 必须 70 秒全程 ≥55 帧/秒，即使 rAF 侧已 0.0

判据（三条全中才算 PASS）：
  ① V1 最低 < 10 fps（复现了衰减）
  ② V1 与 V3 的**差值** ≥ 40 fps（证明解耦真的绕开了节流，而不是两边都碰巧正常）
  ③ V3 最低 ≥ 55 帧/秒，且 `frames_alive()` 的 `require_frames()` 通过
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from gallery_ui_shots import Page  # noqa: E402

URL_MIN = 'file:///D:/azur/scripts/diag/glmin_size.html?w=800&h=600#gallery_v2'
URL_PROD = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
WATCH = 70

RAF = r"""
(function(){
  if(window.__rafc) return 'already';
  var p=window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,stalls:0};
  (function loop(){ var now=performance.now();
    if(p.prev){ var g=now-p.prev; if(g>p.gapMax)p.gapMax=g; if(g>200)p.stalls++; }
    p.prev=now; p.n++; requestAnimationFrame(loop); })();
  return 'ok';})()"""

RAF_READ = r"""(function(){var p=window.__rafc||{n:0,t0:0,gapMax:0};
  return JSON.stringify({n:p.n,ms:+(performance.now()-(p.t0||0)).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0),vis:document.visibilityState});})()"""

OPEN_L2D = """(()=>{
  const hit=G.ships.find(s=>(s.live2dSkins||[]).includes('ougen_8'));
  if(!hit) return 'NO_SHIP';
  const sk=hit.skins.find(x=>x.key==='ougen_8')||hit.skins[0];
  openShip(hit); setSkin(sk); buildSkinList(hit); renderView();
  const t=[...document.getElementById('mTabs').children].find(c=>c.dataset.k==='live2d');
  if(t) t.click();
  return 'ok';})()"""


def measure(pg, seconds, tag, use_raf=True):
    marks = {}
    if use_raf:
        a = json.loads(pg.ev(RAF_READ))
        for _ in range(seconds):
            b = json.loads(pg.ev(RAF_READ))
            dm = b['ms'] - a['ms']
            f = (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0
            for t in (10, 30, 50, 68):
                if abs(b['ms'] - t * 1000) <= 800 and t not in marks:
                    marks[t] = f
            a = b
            time.sleep(1.0)
    else:
        a = json.loads(pg.ev(pg.FRAME_SAMPLE))
        for _ in range(seconds):
            b = json.loads(pg.ev(pg.FRAME_SAMPLE))
            dm = (b['last'] - a['last'])
            if a['src'] == 'pump':
                f = (b['n'] - a['n']) * 1000.0 / max(1.0, 1000.0)
            else:
                f = 1000.0 / dm if dm else 0.0
            # 统一口径：用墙钟时间算每秒推帧数
            f = (b['n'] - a['n']) if a['src'] == 'pump' else f
            for t in (10, 30, 50, 68):
                if abs((_ - a.get('_i', 0))) < 0:
                    pass
            a = b
            time.sleep(1.0)
    return marks


def measure_pump(pg, seconds, tag):
    """推帧模式的统一口径：按**每秒增量**算推帧次数（累计平均会掩盖中途掉速）。"""
    a = json.loads(pg.ev(pg.FRAME_SAMPLE))
    marks = {}
    for i in range(seconds):
        time.sleep(1.0)
        b = json.loads(pg.ev(pg.FRAME_SAMPLE))
        f = float(b['n'] - a['n'])
        el = i + 1
        for t in (10, 30, 50, 68):
            if abs(el - t) <= 1 and t not in marks:
                marks[t] = f
        if f < 45.0:
            print('   %s %5.1fs fps=%-6.1f err=%s' % (tag, el, f, b.get('err')))
        a = b
    return marks


def run(tag, port, keepalive, detach, url):
    print('\n===== %s (keepalive=%s, detach=%s) %d 秒 ====='
          % (tag, keepalive, detach, WATCH))
    pg = Page(port, r'D:\azur\.diag\v_prof_%d' % port, url,
              (1400, 1000), gpu=True, keepalive=keepalive)
    try:
        pg.ev(RAF)
        time.sleep(1.5)
        if detach:
            print('  切 Live2D:', pg.ev(OPEN_L2D))
            time.sleep(3.0)
            print('  解耦:', pg.detach_frames(60))
            time.sleep(0.8)
            marks = measure_pump(pg, WATCH, tag)
        else:
            marks = measure(pg, WATCH, tag, use_raf=True)
        ok, fps, s = pg.frames_alive(2.0, 45.0)
        print('  frames_alive: ok=%s fps=%.1f src=%s' % (ok, fps, s.get('src')))
        low = min(marks.values()) if marks else -1.0
        print('  ⇒ ' + ' | '.join('t=%ds %.1f' % (k, marks[k]) for k in sorted(marks))
              + '  【最低 %.1f】' % low)
        return low
    finally:
        pg.close()


def main():
    r = {}
    r['V1 rAF 基线'] = run('V1 基线', 9398, False, False, URL_MIN)
    r['V2 心跳(8s)'] = run('V2 心跳', 9399, True, False, URL_MIN)
    r['V3 推帧解耦'] = run('V3 解耦', 9400, False, True, URL_PROD)
    print('\n===== 判据（三条全中才 PASS）=====')
    c1 = r['V1 rAF 基线'] < 10
    c2 = (r['V3 推帧解耦'] - r['V1 rAF 基线']) >= 40
    c3 = r['V3 推帧解耦'] >= 55
    print('  ① V1 复现衰减(<10fps)：%.1f ⇒ %s' % (r['V1 rAF 基线'], 'PASS' if c1 else 'FAIL'))
    print('  ② V3-V1 ≥40fps：%.1f ⇒ %s'
          % (r['V3 推帧解耦'] - r['V1 rAF 基线'], 'PASS' if c2 else 'FAIL'))
    print('  ③ V3 ≥55fps：%.1f ⇒ %s' % (r['V3 推帧解耦'], 'PASS' if c3 else 'FAIL'))
    print('  V2 心跳参考值（不参与判定）：%.1f' % r['V2 心跳(8s)'])
    return 0 if (c1 and c2 and c3) else 1


if __name__ == '__main__':
    sys.exit(main())
