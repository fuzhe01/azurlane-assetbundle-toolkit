# -*- coding: utf-8 -*-
"""可靠重启 8777 server(全python, 绕开shell集成), 并用带斜杠请求自验证, 结果写文件."""
import sys, subprocess, time
import urllib.request, urllib.error, os

ROOT = r'D:\Azur Lane Assets'
SERVE = os.path.join(ROOT, 'scripts', 'diag', 'serve_live2d.py')
OUTLOg = os.path.join(ROOT, '.diag', '_serve_full.log')
OUT = os.path.join(ROOT, '.diag', '_getchk_out.txt')
BASE = 'http://127.0.0.1:8777'

lines = []

def get(p):
    try:
        r = urllib.request.urlopen(BASE + p, timeout=6)
        return f'[{r.status}] len={r.headers.get("Content-Length")}'
    except urllib.error.HTTPError as e:
        return f'[{e.code}]'
    except Exception as e:
        return f'[ERR] {e}'

# 1. 把 8777 上所有 LISTENING 进程反复杀干净(HTTPServer allow_reuse_address 可能残留)，再总是用最新代码起新 server
def kill_port(port, tries=5):
    for _ in range(tries):
        r = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True)
        pids = set()
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and (':' + str(port)) in parts[1] and parts[3].strip().upper() == 'LISTENING':
                pids.add(parts[4])
        if not pids:
            return
        for pid in pids:
            subprocess.run(['taskkill', '/PID', pid, '/F'], capture_output=True)
            lines.append('killed pid=' + pid)
        time.sleep(1.5)

kill_port(8777)
time.sleep(1)
logf = open(OUTLOg, 'w', encoding='utf-8')
p = subprocess.Popen(
    [sys.executable, '-X', 'utf8', SERVE],
    cwd=os.path.join(ROOT, 'Output'),
    stdout=logf, stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) or 0x08000000,
)
lines.append(f'spawned pid={p.pid}')
time.sleep(5)

# 2. 自验证
checks = [
    'Live2D/ougen_8/ougen_8.model3.json/',
    'Live2D/ougen_8/ougen_8.model3.json',
    'Live2D/ougen_8/ougen_8.model3.json/ougen_8.moc3',
    'Live2D/ougen_8/ougen_8.model3.json/texture_00.png',
    'Live2D/ougen_8/ougen_8.model3.json/texture_01.png',
    'Live2D/ougen_8/ougen_8.model3.json/ougen_8.physics3.json',
    'Live2D/ougen_8/ougen_8.model3.json/motion/idle3.motion3.json',
    'Live2D/ougen_8/ougen_8.moc3/',
    'Live2D/ougen_8/motion/idle3.motion3.json/',
]
for c in checks:
    lines.append(f'  {c} -> {get("/" + c)}')

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('done')