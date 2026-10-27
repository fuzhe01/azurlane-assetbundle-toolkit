"""用浏览器编译当前部署的 JS 主块，定位语法错误。

之前失败原因：CDP 端口冲突（no CDP tab）。这里用 cdp_helper 自动换端口+清理重试，
并对比 HEAD 版本，确认错误是否由本轮改动引入。

用法: py -3 scripts/diag/compile_check.py
"""
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import cdp_helper  # noqa: E402
from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'


def main_block_text(s):
    blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', s, re.S)
    return max(blocks, key=len)


def main_block(path):
    return main_block_text(io.open(path, encoding='utf-8').read())


def head_main_block():
    """取 git HEAD 里 `gallery_src/index.html` 的主 script 块当基线。

    ⚠️ 别再用 `.diag/head_index.html` 这种磁盘快照：它是手工拷的，会过时
    （2026-10-25 实测快照 152991 字符 vs HEAD 真实 169614）。基线过时会把
    「本轮引入」判成「老问题」或反之，两种都让这个工具失去意义。
    """
    try:
        r = subprocess.run(['git', 'show', 'HEAD:gallery_src/index.html'],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=60)
        if r.returncode == 0 and r.stdout:
            return main_block_text(r.stdout)
    except Exception:  # noqa: BLE001
        pass
    p = os.path.join(ROOT, '.diag', 'head_index.html')
    return main_block(p) if os.path.exists(p) else None


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    cur = main_block(os.path.join(ROOT, 'Output', 'gallery_v2', 'index.html'))
    head = head_main_block()
    print('当前主块 %d 字符；HEAD 主块 %s' % (len(cur), len(head) if head else 'N/A'))

    pg = open_page(URL, tag='cc')
    try:
        def compile_js(src):
            return pg.ev("(function(){try{ new Function(%s); return 'OK'; }"
                         "catch(e){ return 'ERR:'+String(e.message); }})()" % json.dumps(src))

        r_cur = compile_js(cur)
        print('当前版本:', r_cur)
        if head:
            r_head = compile_js(head)
            print('HEAD 版本:', r_head)
            if r_head == 'OK' and r_cur.startswith('ERR'):
                print('\n=> 语法错误由本轮改动引入')
            elif r_head != 'OK':
                print('\n=> HEAD 版本本身就有问题（说明是老问题）')
        return 0 if r_cur == 'OK' else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())