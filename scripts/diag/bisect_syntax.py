"""二分定位主 script 块里的语法错误行。

做法：把块按行切成前半段，逐段编译（Function 构造器），首个编译失败的区段里
再逐行扩大窗口，最终定位到具体行。

用法: py -3 scripts/diag/bisect_syntax.py
"""
import json
import os
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

PORT = 9483
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'


def main():
    html = open(os.path.join(ROOT, 'Output', 'gallery_v2', 'index.html'),
                encoding='utf-8').read()
    blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', html, re.S)
    big = max(blocks, key=len)
    lines = big.split('\n')
    print('主块 %d 行' % len(lines))

    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_bi%d' % PORT), URL, (1200, 800))

    def compiles(src):
        payload = json.dumps(src)
        r = pg.ev("(function(){try{ new Function(%s); return 'OK'; }"
                  "catch(e){ return 'ERR:'+String(e.message); }})()" % payload)
        return r == 'OK', r

    try:
        # 在 HTML 里的起始行号（便于回报）
        start_in_html = html[:html.find(big)].count('\n') + 1

        lo, hi = 0, len(lines)
        # 找最小的失败前缀
        while hi - lo > 1:
            mid = (lo + hi) // 2
            ok, msg = compiles('\n'.join(lines[:mid]))
            if ok:
                lo = mid
            else:
                hi = mid
        print('\n首个失败前缀长度: %d 行（HTML 第 %d 行附近）' % (hi, start_in_html + hi - 1))
        # 打印该行附近内容
        for i in range(max(0, hi - 4), min(len(lines), hi + 2)):
            mark = '>>>' if i == hi - 1 else '   '
            print('%s %5d| %s' % (mark, start_in_html + i, lines[i][:160]))
        _, msg = compiles('\n'.join(lines[:hi]))
        print('\n错误信息:', msg)

        # 再尝试只用最后一行编译（定位）
        last = lines[hi - 1]
        ok2, msg2 = compiles(last)
        print('单行编译:', msg2)
        print('该行内容:', last[:300])
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())