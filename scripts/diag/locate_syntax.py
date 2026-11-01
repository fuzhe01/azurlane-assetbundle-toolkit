"""正确的方式找语法错误：整块编译 + 用浏览器的 error 定位。

二分法在多行注释/字符串上会误报（截断必然不闭合）。
改用：整块编译失败时，让浏览器报出具体的 lineNumber（SourceURL + new Function 不给行列，
所以改用 Blob URL + 动态 import，错误里带行列）。

用法: py -3 scripts/diag/locate_syntax.py
"""
import json
import os
import re
import sys
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

PORT = 9484
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'


def main():
    html = open(os.path.join(ROOT, 'Output', 'gallery_v2', 'index.html'),
                encoding='utf-8').read()
    blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', html, re.S)
    big = max(blocks, key=len)
    # 该块在 HTML 中的起始行
    base_line = html[:html.index(big)].count('\n') + 1
    print('主块起始于 HTML 第 %d 行，共 %d 行' % (base_line, big.count('\n') + 1))

    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_ls%d' % PORT), URL, (1200, 800))
    try:
        # 用 Blob + import() 让浏览器报出精确行列
        payload = json.dumps(big)
        js = (
            "(async function(){"
            "  var src=%s;"
            "  var url=URL.createObjectURL(new Blob([src],{type:'text/javascript'}));"
            "  try{ await import(url); return 'IMPORTED'; }"
            "  catch(e){"
            "    var m=String(e && e.message || e);"
            "    var st=String(e && e.stack || '');"
            "    var mm=st.match(/:(\\d+):(\\d+)/);"
            "    return JSON.stringify({msg:m, line:mm?parseInt(mm[1],10):null,"
            "                             col:mm?parseInt(mm[2],10):null, stack:st.slice(0,400)});"
            "  }"
            "})()"
        ) % payload
        raw = pg.ev(js)
        print('\n结果:', raw)
        try:
            d = json.loads(raw)
            ln = d.get('line')
            if ln:
                html_line = base_line + ln - 1
                print('\n>>> 出错位置：HTML 第 %d 行，第 %s 列' % (html_line, d.get('col')))
                src_lines = html.split('\n')
                for i in range(max(0, html_line - 4), min(len(src_lines), html_line + 2)):
                    mark = '>>>' if i == html_line - 1 else '   '
                    print('%s %5d| %s' % (mark, i + 1, src_lines[i][:170]))
        except Exception:  # noqa: BLE001
            pass
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())