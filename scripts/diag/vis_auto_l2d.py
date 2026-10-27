# -*- coding: utf-8 -*-
"""CDP 验证：打开 l2d_visual.html(带 clip)，不手动调 play，只等页面 setTimeout 700ms 自动播，
   采样参数看动作是否真的在播放。结果写文件."""
import sys, os, json, time, base64, subprocess, urllib.request
import websocket
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..')):
    _p = os.path.abspath(_p)
    if _p not in sys.path: sys.path.insert(0, _p)

root = r'D:\Azur Lane Assets'
OUT = os.path.join(root, '.diag', '_vis_auto_out.txt')
CHROME = r'C:/Program Files/Google/Chrome/Application/chrome.exe'
EDGE = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
if not os.path.isfile(CHROME):
    CHROME = EDGE
PORT = 9339
DEBUG_DIR = os.path.join(root, '.diag', 'chrome_l2d_visual')
PAGE = 'http://127.0.0.1:8777/l2d_visual.html'
lines = []
# 先清掉占用 9339 的残留 headless chrome
try:
    r = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and ':9339' in parts[1] and parts[3].strip().upper() == 'LISTENING':
            subprocess.run(['taskkill', '/PID', parts[4], '/F'], capture_output=True)
except Exception:
    pass


def go(name, clip):
    m = f'Live2D/{name}/{name}.model3.json'
    url = f'{PAGE}?m={m}&clip={clip}&idx=0&v=20261016e'
    proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
        '--remote-allow-origins=*', f'--user-data-dir={DEBUG_DIR}', '--no-first-run',
        '--no-default-browser-check', '--disable-background-timer-throttling',
        '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--window-size=1200,1000', url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc = chrome_tree.install(proc)
    ws = None
    for _ in range(80):
        try:
            for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json')):
                if 'l2d_visual.html' in t.get('url', '') and t.get('webSocketDebuggerUrl'):
                    ws = websocket.create_connection(t['webSocketDebuggerUrl'], timeout=90); break
        except Exception:
            pass
        if ws:
            break
        time.sleep(0.5)
    if not ws:
        lines.append(f'[{name} {clip}] CDP 未就绪'); proc.kill(); return
    _id = 0
    def cmd(method, params=None):
        nonlocal _id; _id += 1
        ws.send(json.dumps({'id': _id, 'method': method, 'params': params or {}}))
        while True:
            m = json.loads(ws.recv())
            if m.get('id') == _id:
                if 'error' in m:
                    raise RuntimeError(json.dumps(m['error'])[:150])
                return m.get('result', {})
    def ev(expr):
        r = cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        if r.get('exceptionDetails'):
            return None
        x = r.get('result', {}); return x.get('value')
    for _ in range(150):
        st = ev('window.__AB && window.__AB.ready')
        if st:
            break
        time.sleep(0.4)
    else:
        lines.append(f'[{name} {clip}] 模型未就绪 err={ev("window.__AB&&window.__AB.err")}'); proc.kill(); return
    time.sleep(2.6)  # 等 setTimeout 700ms 自动播放 + 动作推进
    grp = ev('window.__AB.clip + "|" + window.__AB.group')
    ids = json.loads(ev('JSON.stringify(window.__AB.ids)') or '[]')
    samples = []
    for _ in range(20):
        s = ev('JSON.stringify(window.__AB.sample())')
        try:
            samples.append(json.loads(s))
        except Exception:
            pass
        time.sleep(0.13)
    amps = []
    for i, pid in enumerate(ids):
        vals = [r['v'][i] for r in samples if r and isinstance(r['v'][i], (int, float))]
        if len(vals) >= 3:
            a = max(vals) - min(vals)
            if a > 0.05:
                amps.append((round(a, 2), pid))
    amps.sort(key=lambda x: -x[0])
    lines.append(f'[{name} {clip}] 自动播放: clip/group={grp} 动作参数(amp>0.05)={len(amps)} 顶部={", ".join(f"{p}={a}" for a,p in amps[:8])}')
    proc.kill()


os.makedirs(DEBUG_DIR, exist_ok=True)
for spec in sys.argv[1:] or ['aersasi_2:home', 'aersasi_2:idle3', 'ougen_8:main_1']:
    n, c = spec.split(':', 1)
    go(n, c)
with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('done')