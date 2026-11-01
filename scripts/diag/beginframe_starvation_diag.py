"""第八层取证：主线程**空闲 72.6%** 却只有 1fps ⇒ 帧根本没被发出来（BeginFrame 被饿死），
不是「算不过来」。这一步换判别维度：找「从哪一刻起不再发帧」。

上一节 `cpu_profile_stall_diag` 的关键读数：
  · 自身耗时占比 `(idle)` = 72.6%，`(program)` = 1.8%，GC = 0.3%；
  · 真正在产品代码里的最高项只有 5.6%（cubism core 的日志包装），
    再往下都是 1–1.8% 的小函数。
  ⇒ 主线程有大把空闲却不渲染。**排除法到此为止**（能想到的产品侧原因已全部否证），
    剩下的只能是一个"某条件成立后浏览器就不再排帧"的开关。

本节两组，只改一个变量：
  G0 画廊页**初载**（login 界面，不做任何点击，也不进任何舰船）→ 若同样衰减，
     说明开关在「页面一打开」就成立，与舰船/Live2D/装扮全无关；
  G1 极简页改用 **http://**（另起一个 http.server 服务 `scripts/diag/`），
     → 若 http 下也稳，排除「file:// vs http://」；若 http 下也衰减，
     则与 URL 协议有关，需要回到 gallery_ui_shots 的启动参数。

判据：G0 衰减 + G1 稳定 ⇒ 页内某物（初载就有）导致不再排帧；
      G0 稳定 ⇒ 衰减由"进入舰船视图"触发，需要在这个动作上做前后对照。
"""
import json
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
DIAG_PORT = 8779
DIAG_ROOT = r'd:\azur\scripts\diag'

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


def fps_between(a, b):
    dm = b['ms'] - a['ms']
    return (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0


def series(pg, rounds=11):
    print('  %-7s %-6s %-9s %-7s %s' % ('ms', 'n', 'gapMax', 'stalls', 'fps'))
    prev = None
    for _ in range(rounds):
        s = json.loads(pg.ev(READ))
        f = fps_between(prev, s) if prev else 0.0
        print('  %-7d %-6d %-9d %-7d %s' % (s['ms'], s['n'], s['gapMax'], s['stalls'],
                                             ('%.1f' % f) if prev else ''))
        prev = s
        time.sleep(1.0)
    return prev


def g0_fresh_gallery():
    print('\n===== G0 画廊初载（login 界面，不做任何点击） =====')
    pg = open_page(URL, win=(1400, 1000), tag='g0')
    try:
        time.sleep(3.0)
        print('装计数:', pg.ev(COUNTER))
        series(pg)
        print('  canvas:', pg.ev(
            "JSON.stringify([].map.call(document.querySelectorAll('canvas'),"
            "function(c){return c.width+'x'+c.height;}))"))
        print('  判据：同样衰减 ⇒ 开关在初载就成立，与舰船/Live2D/装扮无关')
    finally:
        pg.close()


def g1_mini_over_http():
    print('\n===== G1 极简页改走 http（服务目录 scripts/diag/） =====')
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(DIAG_PORT),
                            '--bind', '127.0.0.1', '--directory', DIAG_ROOT],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = False
        for _ in range(40):
            try:
                with socket.create_connection(('127.0.0.1', DIAG_PORT), timeout=0.5):
                    ok = True
                    break
            except OSError:
                time.sleep(0.25)
        print('  http.server 就绪:', ok)
        pg = open_page('http://127.0.0.1:%d/glmin.html#gallery_v2' % DIAG_PORT,
                       win=(1400, 1000), tag='g1')
        try:
            time.sleep(2.0)
            print('装计数:', pg.ev(COUNTER))
            print('  gl:', pg.ev("String(window.__info)"))
            series(pg)
            print('  判据：稳定 60 ⇒ 与 http 无关；衰减 ⇒ 与协议/服务器有关')
        finally:
            pg.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass


def main():
    g0_fresh_gallery()
    g1_mini_over_http()
    return 0


if __name__ == '__main__':
    sys.exit(main())
