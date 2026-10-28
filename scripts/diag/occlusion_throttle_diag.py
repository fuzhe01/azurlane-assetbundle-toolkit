"""根因验证：**1023 ms 精确间隔 = Chrome「窗口被遮挡（occlusion）」节流到 1 Hz**。

前一支探针（`long_run_decay_diag.py`）已经证伪了本轮前十三节的共同前提：
  不含任何产品代码的极简 WebGL 页（800x600 / 视口×dpr），**第 18–23 秒也衰减到 1fps**，
  gapMax 精确固定在 1023–1025 ms。
⇒ 「极简页稳定 60fps」只在 10 秒观测窗口内成立；所有靠它撑起来的排除法结论作废。

1023 ms 这个数字的来历：Chromium 判定窗口被完全遮挡（`CalculateNativeWinOcclusion`，
Windows 上的 `IsWindowVisible` / 覆盖检测）后，把该渲染器的 BeginFrame 源切到
**1 Hz**。这可以解释本轮每一处互相矛盾的读数：
  · 主线程 CPU 采样 `(idle)` 72.6% —— 帧根本没被排出来，不是算不过来；
  · `medA(core.update)=6ms / medB(render)=11ms` 全程平稳 —— 每帧成本没变；
  · 衰减是**渐进、延迟 15–25 秒**发生 —— 遮挡判定由 `IsWindowVisible` 轮询得出，
    不是加载即判，所以短窗口观测看不到；
  · `Emulation.setFocusEmulationEnabled` 有效但不够 —— 它伪造的是 **focus**，
    遮挡判定走的是另一条路（Windows 原生窗口可见性），伪造不到；
  · 有窗口真浏览器也衰减（4.2fps）—— 因为我把窗口起在控制台**后面**，
    对 Chrome 来说它就是被遮挡的。

A/B 三组（其余 flag 完全相同，只改遮挡判定）：
  T1 现状基线                      —— 预期衰减
  T2 基线 + `--disable-features=CalculateNativeWinOcclusion`
                                   —— 若不再衰减 ⇒ 遮挡判定是唯一成因，定根因
  T3 去掉 `--headless=new`（真窗口）—— 区分"无头特有问题"与"遮挡问题"

判据落在 **t=40 秒时的 fps**（远超 18–25 秒潜伏期），并要求同时看 `visibilityState`
与 `hasFocus` 作旁证（若二者仍为 visible/true 却 1fps，说明不是文档可见性问题）。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, r'd:\azur\scripts\diag')

import chrome_tree  # noqa: E402
import websocket  # noqa: E402

CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
URL = 'file:///D:/azur/scripts/diag/glmin_size.html?w=800&h=600#gallery_v2'
WATCH = 45

READ = r"""
(function(){
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0};
  return JSON.stringify({n:p.n, ms:+(performance.now()-(p.t0||0)).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    vis:document.visibilityState, foc:document.hasFocus(),
    hid:document.hidden});
})()
"""


class Mini:
    """最小 CDP 封装（`gallery_ui_shots.Page` 写死了 `--headless=new`，这里要能换）。"""

    def __init__(self, flags, port, profile):
        self.proc = chrome_tree.launch(
            [CHROME] + flags + ['--remote-debugging-port=%d' % port,
                                '--remote-allow-origins=*',
                                '--user-data-dir=' + profile,
                                '--no-first-run', '--no-default-browser-check',
                                '--window-size=1400,1000', URL],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws = None
        for _ in range(120):
            try:
                tabs = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json' % port))
                m = [t for t in tabs
                     if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
                if m:
                    ws = m[0]['webSocketDebuggerUrl']
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws:
            raise RuntimeError('no CDP tab')
        self.ws = websocket.create_connection(ws, timeout=180, max_size=None)
        self._id = 0
        self.cmd('Page.enable')
        self.cmd('Runtime.enable')

    def cmd(self, m, p=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
        self.ws.settimeout(180)
        while True:
            r = json.loads(self.ws.recv())
            if r.get('id') == mid:
                return r.get('result', {})

    def ev(self, js):
        r = self.cmd('Runtime.evaluate', {'expression': js, 'returnByValue': True})
        return r.get('result', {}).get('value')

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        chrome_tree.kill_tree(self.proc.pid, verify=False)


BASE_FLAGS = ['--disable-background-timer-throttling',
              '--disable-renderer-backgrounding',
              '--disable-backgrounding-occluded-windows']


def run(tag, extra, port, headless=True):
    label = 'T%d %s' % (port - 9390, tag)
    flags = list(BASE_FLAGS) + list(extra)
    if headless:
        flags = ['--headless=new'] + flags
    prof = r'D:\azur\.diag\occ_prof_%d' % port
    print('\n===== %s =====' % label)
    print('  flags: %s' % ' '.join(flags))
    pg = Mini(flags, port, prof)
    marks = {}
    try:
        time.sleep(1.5)
        prev = json.loads(pg.ev(READ))
        pg.cmd('Emulation.setFocusEmulationEnabled', {'enabled': True})
        for i in range(WATCH):
            s = json.loads(pg.ev(READ))
            dm = s['ms'] - prev['ms']
            f = (s['n'] - prev['n']) * 1000.0 / dm if dm else 0.0
            for t in (10, 20, 30, 40):
                if abs(s['ms'] - t * 1000) <= 600 and t not in marks:
                    marks[t] = f
            if i % 3 == 0 or f < 30:
                print('   %-6d fps=%-6.1f gapMax=%-6d stalls=%-3d vis=%-7s foc=%s'
                      % (s['ms'], f, s['gapMax'], s['stalls'], s['vis'], s['foc']))
            prev = s
            time.sleep(1.0)
    finally:
        pg.close()
    tail = marks.get(40, -1.0)
    print('  ⇒ t=10s fps=%.1f | t=20s %.1f | t=30s %.1f | **t=40s %.1f**'
          % (marks.get(10, -1.0), marks.get(20, -1.0), marks.get(30, -1.0), tail))
    return tail


def main():
    r = {}
    r['T1 基线'] = run('基线（现状 flag）', [], 9391)
    r['T2 禁遮挡判定'] = run('禁 CalculateNativeWinOcclusion',
                        ['--disable-features=CalculateNativeWinOcclusion'], 9392)
    r['T3 真窗口'] = run('真窗口（去掉 --headless=new）', [], 9393, headless=False)
    print('\n===== 汇总（t=40 秒 fps，≥55 才算不衰减）=====')
    for k, v in r.items():
        print('  %-16s %6.1f  %s' % (k, v, 'OK 不衰减' if v >= 55 else '衰减'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
