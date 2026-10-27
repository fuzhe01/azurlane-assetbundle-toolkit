"""定位本轮引入的语法错误：在「HEAD 版本 + 逐步插入我的新增行」的过程中找失败点。

当前版本报 Invalid regular expression flags，HEAD 正常 ⇒ 错误在本轮新增的 ~40 行里。
做法：把我的新增块按「句」切分，逐句追加到 HEAD 之后编译，找到第一处失败。

用法: py -3 scripts/diag/find_added_syntax_error.py
"""
import io
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import cdp_helper  # noqa: E402
from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'


def block_of(path):
    s = io.open(path, encoding='utf-8').read()
    bs = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', s, re.S)
    return max(bs, key=len)


def head_block():
    """git HEAD 的 `gallery_src/index.html` 主块。

    ⚠️ 别用 `.diag/head_index.html` 磁盘快照：manual 拷贝会过时（2026-10-25 实测
    快照 152991 字符 vs HEAD 真实 169614），基线错位后「本轮新增行」整段都是错的。
    """
    r = subprocess.run(['git', 'show', 'HEAD:gallery_src/index.html'],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=60)
    if r.returncode != 0 or not r.stdout:
        raise SystemExit('! 取不到 git HEAD 的 gallery_src/index.html，无法建立基线')
    bs = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', r.stdout, re.S)
    return max(bs, key=len)


def main():
    head = head_block()
    cur = block_of(os.path.join(ROOT, 'Output', 'gallery_v2', 'index.html'))

    # 找出 cur 相对 head 的新增行（用行级 diff）
    import difflib
    hl = head.split('\n')
    cl = cur.split('\n')
    sm = difflib.SequenceMatcher(None, hl, cl, autojunk=False)
    added = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ('insert', 'replace'):
            for j in range(j1, j2):
                added.append((j + 1, cl[j]))
    print('新增/改动行数: %d' % len(added))
    for ln, txt in added[:50]:
        print('  L%-5d %s' % (ln, txt[:120]))
    return 0


if __name__ == '__main__':
    sys.exit(main())