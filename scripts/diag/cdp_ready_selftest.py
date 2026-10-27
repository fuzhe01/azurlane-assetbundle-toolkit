# -*- coding: utf-8 -*-
r"""cdp_wait.wait_ready 的阴性对照自测——证明这道门槛**真的有拦截力**。

为什么必须单独做一个探针（2026-10-27 教训）：
`wait_ready()` 的存在理由是「`about:blank` 的 `readyState` 天生 complete，光看它会把
脚本打进空白页」。但"门槛返回 True"这件事本身**不能证明门槛有效**——如果某天有人把它
改回只看 readyState，页面正常时它照样返回 True，测试照样绿（这就是本轮此前
`verify_fallback_merge --poke` 那种「同绿 = 假绿灯，判据没有区分力」的形态）。

所以判据必须落在**阴性侧**：门槛在「上下文还在 about:blank」时**必须拒绝**。
本探针同时把"此刻 readyState 确实是 complete"打出来，证明这个陷阱在此环境真实存在，
而不是我凭空造的。跑法：

    py -3 scripts/diag/cdp_ready_selftest.py [画廊URL]

退出码：0 = 门槛有拦截力（阴性拒绝 + 阳性放行都成立） / 1 = 判据不成立
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.stdout.reconfigure(encoding='utf-8')
import cdp_slot        # noqa: E402
import cdp_wait        # noqa: E402
import chrome_tree     # noqa: E402

CHROME = os.environ.get(
    'CDP_CHROME', r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8778/gallery_v2/index.html'


class Session:
    """最小 CDP 会话：起 headless（**故意不给 URL**，停在 about:blank）→ 建 ws → cmd/ev。"""

    def __init__(self, tag):
        port, profile = cdp_slot.slot(ROOT, tag)
        self.proc = chrome_tree.install(subprocess.Popen(
            [CHROME, '--headless=new', f'--remote-debugging-port={port}',
             '--remote-allow-origins=*', f'--user-data-dir={profile}',
             '--no-first-run', '--no-default-browser-check',
             '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
             '--window-size=800,600', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        ws = None
        for _ in range(120):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                cand = [t for t in tabs if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]
                if cand:
                    ws = cand[0]['webSocketDebuggerUrl']
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws:
            raise SystemExit('[ERROR] 拿不到 CDP tab（探针故障）')
        import websocket
        self.ws = websocket.create_connection(ws, timeout=180, max_size=None)
        self._id = 0
        self.cmd('Page.enable')

    def cmd(self, m, p=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get('id') == mid:
                if 'error' in r:
                    raise RuntimeError(json.dumps(r['error'])[:150])
                return r.get('result', {})

    def ev(self, e):
        r = self.cmd('Runtime.evaluate',
                     {'expression': e, 'returnByValue': True, 'awaitPromise': True})
        if r.get('exceptionDetails'):
            return 'EVALERR ' + str(r['exceptionDetails'])[:200]
        return r.get('result', {}).get('value')

    def close(self):
        try:
            self.cmd('Browser.close')
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            chrome_tree.kill_tree(self.proc.pid, chrome_tree.profile_of(self.proc))


def main():
    print(f'目标页: {URL}')
    s = Session('cdpself')
    try:
        # ── 阴性侧：停在 about:blank，门槛必须拒绝 ───────────────────────────
        href = s.ev('location.href')
        rs = s.ev('document.readyState')
        print(f'\n[阴性] 上下文停在 {href!r}，document.readyState = {rs!r}')
        print('        ← 这一行就是陷阱本体：空白页的 readyState 天生 complete')
        # flag 用恒真值：把门槛里"与产品强耦合"的那一件摘掉，
        # 单独考"URL + readyState"这两件够不够 —— 也就是旧版的形态。
        ok_blank, secs, last = cdp_wait.wait_ready(s.ev, URL, budget=6, flag='1', poll=1.0)
        print(f'       wait_ready(flag=恒真, budget=6s) → ok={ok_blank} 用时 {secs}s  last={last}')
        neg_pass = (ok_blank is False)

        # ── 阳性侧：导航到真页，门槛必须放行 ────────────────────────────────
        s.cmd('Page.navigate', {'url': URL})
        ok_real, secs2, last2 = cdp_wait.wait_ready(s.ev, URL, budget=150)
        rh = s.ev('location.href')
        print(f'\n[阳性] wait_ready → ok={ok_real} 用时 {secs2}s  href={str(rh)[:70]}')
        pos_pass = (ok_real is True)
    finally:
        s.close()

    print('\n判据：')
    print(f'  ① 阴性（about:blank 必须被拒）: {"PASS" if neg_pass else "FAIL —— 门槛没有拦截力"}')
    print(f'  ② 阳性（真页必须放行）      : {"PASS" if pos_pass else "FAIL —— 门槛把好页面也拦了"}')
    if neg_pass and pos_pass:
        print('\n[PASS] wait_ready 的就绪门槛有拦截力')
        return 0
    print('\n[FAIL] 门槛机制不成立（注意：阳性单独绿 = 无区分力的假绿灯）')
    return 1


if __name__ == '__main__':
    sys.exit(main())
