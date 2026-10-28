"""第十二层取证（决定性）：帧率衰减是**headless 独有**，还是**真实产品性能缺陷**。

这一层的动机来自一条自相矛盾的读数：
  · `stall_trigger_step_diag`：点舰船卡后 1.9 fps，且停顿计数此后单调增长，不再恢复；
  · `new_canvas_stall_audit`：同样点舰船卡，**60 秒内先 59.5 fps**，要过几秒才归位到 1fps；
  · `two_glctx_stall_diag` D4：点舰船卡后立刻 `loseContext`，**全程 60fps 满 6 秒**。
  ⇒ 同一操作、同一页面，三种结局。**"会不会衰减"本身就不稳定**，
    这已经不是"某个产品代码慢"，而是「某条件满足后浏览器停止排帧」的开关行为。

对项目的后果完全不同，必须先分清：
  · 若真机（有窗口）也衰减 ⇒ 用户看到的画廊本身就是 1fps 的残废页面，这是**产品缺陷**，
    所有围绕热区/装扮的结论都建立在坏环境上，优先级要重排；
  · 若只有 headless 衰减 ⇒ 是**仪器缺陷**，产品无恙，但本轮所有逐帧判据都必须加前置体检，
    并且 `render_entry_verify.py` 的不稳定就有了统一解释（它读的就是逐帧样本数）。

做法：同一台机、同一 URL、同一套点击与取样，**只切换 `--headless=new` 这一个开关**。
浏览器一律走 `chrome_tree.launch()`（项目硬规则：不许裸 `subprocess.Popen`），
有窗口模式额外把窗口移到屏幕外，避免抢焦点/干扰用户。

判据：headless 侧衰减、headful 侧稳定 ⇒ 仪器问题；两侧都衰减 ⇒ 产品缺陷。
"""
import json
import os
import random
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')
sys.path.insert(0, r'd:\azur\scripts')

import websocket  # noqa: E402

import chrome_tree  # noqa: E402
import paths as P  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

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

READ = r"""
(function(){
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0};
  return JSON.stringify({n:p.n, ms:+(performance.now()-p.t0).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    vis:document.visibilityState, focus:document.hasFocus(),
    cv:[].map.call(document.querySelectorAll('canvas'),function(c){return c.width+'x'+c.height;})});
})()
"""

TO_CARD = """var b=document.querySelector('#gOpt button[data-k=login]');
  if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();
  var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();"""


class Sess:
    def __init__(self, headless, tag):
        port = random.randint(9510, 9899)
        profile = os.path.join(r'd:\azur\.diag', 'chrome_%s_%d' % (tag, port))
        flags = [P.CHROME]
        if headless:
            flags += ['--headless=new']
        flags += ['--remote-debugging-port=%d' % port, '--remote-allow-origins=*',
                  '--user-data-dir=%s' % profile, '--no-first-run',
                  '--no-default-browser-check', '--disable-background-timer-throttling',
                  '--window-size=1400,1000', '--window-position=-32000,-32000',
                  URL]
        self.proc = chrome_tree.launch(flags, profile=profile,
                                       stdout=None, stderr=None)
        ws = None
        for _ in range(120):
            try:
                tabs = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json' % port))
                m = [t for t in tabs if 'gallery_v2' in t.get('url', '')
                     and t.get('webSocketDebuggerUrl')]
                if m:
                    ws = m[0]['webSocketDebuggerUrl']
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        if not ws:
            raise RuntimeError('no CDP tab (headless=%s)' % headless)
        self.ws = websocket.create_connection(ws, timeout=180, max_size=None)
        self._id = 0
        self.cmd('Page.enable')
        self.cmd('Runtime.enable')
        try:
            self.cmd('Emulation.setFocusEmulationEnabled', {'enabled': True})
        except Exception:  # noqa: BLE001
            pass

    def cmd(self, m, p=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
        self.ws.settimeout(180)
        while True:
            r = json.loads(self.ws.recv())
            if r.get('id') == mid:
                return r.get('result', {})

    def ev(self, expr):
        r = self.cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True,
                                          'awaitPromise': True})
        return r.get('result', {}).get('value')

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            chrome_tree.kill_tree(self.proc, profile_of_popen=None)
        except TypeError:
            try:
                chrome_tree.kill_tree(self.proc)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass


def measure(pg, label, sec=5.0):
    time.sleep(0.6)
    a = json.loads(pg.ev(READ))
    time.sleep(sec)
    b = json.loads(pg.ev(READ))
    dm = b['ms'] - a['ms']
    f = (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0
    print('  %-24s %6.1f fps  gapMax=%-5d 停顿=%-2d vis=%-7s focus=%-5s canvas=%s'
          % (label, f, b['gapMax'], b['stalls'], b['vis'], b['focus'], b['cv']))
    return f


def run(headless, tag):
    print('\n===== %s（headless=%s） =====' % ('headless' if headless else '有窗口', headless))
    pg = Sess(headless, tag)
    try:
        time.sleep(4.0)
        print('装计数:', pg.ev(COUNTER))
        print('  %-24s %s' % ('阶段', '读数'))
        f0 = measure(pg, 'B0 初载')
        pg.ev(TO_CARD)
        f1 = measure(pg, 'B1 点舰船卡后 5s')
        f2 = measure(pg, 'B2 再等 5s')
        f3 = measure(pg, 'B3 再等 5s')
        print('  ⇒ 初载 %.1f → %.1f → %.1f → %.1f fps' % (f0, f1, f2, f3))
    finally:
        pg.close()


def main():
    run(True, 'hl')
    run(False, 'hf')
    return 0


if __name__ == '__main__':
    sys.exit(main())
