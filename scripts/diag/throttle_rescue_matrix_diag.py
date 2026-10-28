"""在**已衰减**状态下逐个施救，用「谁能把它救回来」定根因（不是继续做排除法）。

为什么改用恢复矩阵：本轮前十四节一直在加 flag 做 A/B 排除，产出十四次"无效"，
却不清楚衰减到底是什么状态。而 `occlusion_throttle_diag` 的读数暴露了两件新事实：
  · 衰减是**爆发式**的：t=30s 读数 1.0fps，t=37s 又回到 59.9fps（可自行恢复）；
  · `--disable-features=CalculateNativeWinOcclusion` **无效**（T2 仍衰减）。
⇒ 不是遮挡判定。而 `visibilityState=visible` / `hasFocus=true` 却精确 1 Hz 排出帧，
是**进程级节流**（Windows EcoQoS 对后台进程）或**窗口可见状态被周期性重算**的形态。

做法：先用极简页（无产品代码）跑到衰减，确认已进入 <10fps，**再**逐项施救，每项给 8 秒观察：
  R1 `Page.bringToFront`                     —— 真·前置窗口（不是伪造 focus）
  R2 再调 `Emulation.setFocusEmulationEnabled` —— 伪造 focus 的二次确认（预期无效）
  R3 `Input.dispatchMouseEvent`（真实输入事件）—— 输入通常会让渲染器退出节流
  R4 `Page.reload`（对照：重载后应先回 60fps 再衰减 ⇒ 说明是时间/状态驱动）
  R5 什么都不做（空白对照，必须仍 1fps，否则读数不可信）

判据：
  · 只有 R1/R3 能救回 ⇒ 窗口/输入侧状态机，修法是在探针里周期性地"喂"一下；
  · R5 也莫名其妙回 60fps ⇒ 本探针的"已衰减"判据不可靠，作废重测；
  · 全都救不回 ⇒ 进程级节流，转 EcoQoS 方向（`UseEcoQoSForBackgroundProcess`）。
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

READ = r"""
(function(){
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0};
  return JSON.stringify({n:p.n, ms:+(performance.now()-(p.t0||0)).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    vis:document.visibilityState, foc:document.hasFocus()});
})()
"""


class Mini:
    def __init__(self, port, profile, headless=True):
        flags = [CHROME]
        if headless:
            flags.append('--headless=new')
        flags += ['--disable-background-timer-throttling',
                  '--disable-renderer-backgrounding',
                  '--disable-backgrounding-occluded-windows',
                  '--remote-debugging-port=%d' % port,
                  '--remote-allow-origins=*',
                  '--user-data-dir=' + profile,
                  '--no-first-run', '--no-default-browser-check',
                  '--window-size=1400,1000', URL]
        self.proc = chrome_tree.launch(flags, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
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
        self.cmd('Emulation.setFocusEmulationEnabled', {'enabled': True})

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
        return self.cmd('Runtime.evaluate', {'expression': js,
                                             'returnByValue': True}
                        ).get('result', {}).get('value')

    def fps_over(self, seconds):
        a = json.loads(self.ev(READ))
        time.sleep(seconds)
        b = json.loads(self.ev(READ))
        dm = b['ms'] - a['ms']
        return ((b['n'] - a['n']) * 1000.0 / dm if dm else 0.0), b

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        chrome_tree.kill_tree(self.proc.pid, verify=False)


def rescue(tag, action, pg):
    f0, st = pg.fps_over(2.0)
    if action:
        try:
            action(pg)
        except Exception as e:
            print('  %-30s 施救异常: %s' % (tag, e))
        time.sleep(0.5)
    f1, st1 = pg.fps_over(8.0)
    print('  %-30s 前 %5.1f → 后 %5.1f fps   vis=%-7s foc=%s stalls=%d'
          % (tag, f0, f1, st1['vis'], st1['foc'], st1['stalls']))
    return f1


def main():
    prof = r'D:\azur\.diag\rescue_prof'
    print('启动极简页并等待衰减…')
    pg = Mini(9391, prof)
    try:
        t0 = time.time()
        while time.time() - t0 < 90:
            f, st = pg.fps_over(2.0)
            print('   t=%5.1fs fps=%5.1f gapMax=%-5d' % (time.time() - t0, f, st['gapMax']))
            if f < 10.0:
                break
        else:
            print('  90 秒内未衰减 ⇒ 本次无法做恢复矩阵（说明衰减本身不稳定，需另查）')
            return 1
        print('\n已进入衰减（<10fps），开始逐项施救（每项观察 8 秒）')
        r = {}
        r['R1 bringToFront'] = rescue('R1 Page.bringToFront',
                                      lambda p: p.cmd('Page.bringToFront'), pg)
        r['R2 再伪造 focus'] = rescue('R2 setFocusEmulationEnabled',
                                 lambda p: p.cmd('Emulation.setFocusEmulationEnabled',
                                                 {'enabled': True}), pg)
        r['R3 真实鼠标事件'] = rescue(
            'R3 dispatchMouseEvent',
            lambda p: (p.cmd('Input.dispatchMouseEvent',
                             {'type': 'mouseMoved', 'x': 100, 'y': 100}),
                       p.cmd('Input.dispatchMouseEvent',
                             {'type': 'mousePressed', 'x': 100, 'y': 100,
                              'button': 'left', 'clickCount': 1}),
                       p.cmd('Input.dispatchMouseEvent',
                             {'type': 'mouseReleased', 'x': 100, 'y': 100,
                              'button': 'left', 'clickCount': 1})), pg)
        r['R4 reload'] = rescue('R4 Page.reload',
                                lambda p: p.cmd('Page.reload'), pg)
        r['R5 空白对照'] = rescue('R5 什么都不做', None, pg)

        print('\n===== 汇总（施救后 fps；≥55 视为救回）=====')
        for k, v in r.items():
            print('  %-20s %6.1f  %s' % (k, v, '救回' if v >= 55 else '无效'))
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
