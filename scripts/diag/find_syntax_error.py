"""定位「Invalid regular expression flags」的真正来源。

做法：把页面里每个 <script> 块单独喂给浏览器的 Function 构造器编译，
报错的那个块就是问题所在；再在其中二分定位行号。

用法: py -3 scripts/diag/find_syntax_error.py
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

PORT = 9482
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'


def main():
    html = open(os.path.join(ROOT, 'Output', 'gallery_v2', 'index.html'),
                encoding='utf-8').read()
    blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', html, re.S)
    print('script 块数:', len(blocks))

    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_syn%d' % PORT), URL, (1200, 800))
    try:
        for idx, b in enumerate(blocks):
            # 用 JSON 传源码，避免转义问题
            payload = json.dumps(b)
            r = pg.ev(
                "(function(){var src=%s;"
                "try{ new Function(src); return 'OK'; }"
                "catch(e){ return 'ERR:'+String(e.message); }})()" % payload)
            print('块%-2d 长度%-7d %s' % (idx, len(b), r))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())