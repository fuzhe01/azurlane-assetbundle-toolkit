"""ensure_servers.py — 保证新旧画廊服务在线（幂等，可反复调用）。

背景（2026-10-23 反复踩）：8778/8777 的 python 服务进程会被回收或随会话切换消失，
探测脚本于是读到白屏并给出「差 0.00」这类假结论。所有验证脚本应在开头调用本模块，
而不是假定服务还活着。

用法:
  py -3 scripts/diag/ensure_servers.py            # 检查并拉起两个服务
  py -3 scripts/diag/ensure_servers.py --new      # 只保证本项目 8778
"""
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

SERVERS = {
    'new': {
        'port': 8778,
        'url': 'http://127.0.0.1:8778/gallery_v2/index.html',
        'cwd': ROOT,
        'script': os.path.join(ROOT, 'scripts', 'diag', 'serve_gallery_8778.py'),
    },
    'old': {
        'port': 8777,
        'url': 'http://127.0.0.1:8777/gallery_v2/index.html',
        'cwd': r'D:\Azur Lane Assets\Output\gallery_v2',
        'script': os.path.join(r'D:\Azur Lane Assets\Output\gallery_v2', '_gallery_server.py'),
    },
}


def reachable(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ensure(name, tries=10):
    cfg = SERVERS[name]
    if reachable(cfg['url']):
        return True, 'already-up'
    if not os.path.exists(cfg['script']):
        return False, 'script-missing:%s' % cfg['script']
    subprocess.Popen([sys.executable, cfg['script']], cwd=cfg['cwd'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0))
    for _ in range(tries):
        time.sleep(1.0)
        if reachable(cfg['url']):
            return True, 'started'
    return False, 'started-but-unreachable'


def ensure_all(only=None):
    names = [only] if only else list(SERVERS)
    out = {}
    for n in names:
        ok, why = ensure(n)
        out[n] = (ok, why)
        print('  %-4s %-3s %s' % (n, 'OK' if ok else 'FAIL', why))
    return out


if __name__ == '__main__':
    only = 'new' if '--new' in sys.argv else None
    res = ensure_all(only)
    sys.exit(0 if all(ok for ok, _ in res.values()) else 1)
