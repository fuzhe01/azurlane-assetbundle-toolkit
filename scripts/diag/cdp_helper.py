"""CDP 会话助手：带端口清理与重试，避免反复 no CDP tab。

问题（2026-10-24 反复踩）：gallery_ui_shots.Page 直接 Popen Edge，
若同端口已有残留实例，/json 列表里找不到目标 tab 就抛 'no CDP tab'。
每次排查都要手动 taskkill，浪费大量轮次。

本模块做法：
  1. 开跑前杀掉占用该调试端口的残留 Edge（按 CommandLine 匹配）
  2. 换用随机高位端口（避免固定端口撞车）
  3. Page 初始化失败时自动重试 3 次

用法: from cdp_helper import open_page
      pg = open_page(URL)
"""
import os
import random
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402


def kill_stale(port=None):
    """杀掉占用调试端口的残留 Edge 进程。port 为 None 时清理所有 94xx/95xx。"""
    pat = ('remote-debugging-port=%d' % port) if port else 'remote-debugging-port=9'
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "Where-Object { $_.CommandLine -like '*%s*' } | "
             "Select-Object -ExpandProperty ProcessId" % pat],
            capture_output=True, text=True, timeout=40).stdout
        pids = [x.strip() for x in out.splitlines() if x.strip().isdigit()]
        for pid in pids:
            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=15)
        if pids:
            time.sleep(1.5)
        return len(pids)
    except Exception:  # noqa: BLE001
        return 0


def open_page(url, win=(1400, 1000), tries=3, tag='cdp'):
    """打开一个可用的 CDP 页面；失败自动换端口重试。"""
    last_err = None
    for i in range(tries):
        port = random.randint(9510, 9899)
        kill_stale(port)
        profile = os.path.join(ROOT, '.diag', 'chrome_%s_%d' % (tag, port))
        try:
            pg = Page(port, profile, url, win)
            return pg
        except Exception as e:  # noqa: BLE001
            last_err = e
            kill_stale(port)
            time.sleep(1.5)
    raise RuntimeError('CDP 打开失败（重试 %d 次）: %s' % (tries, last_err))
