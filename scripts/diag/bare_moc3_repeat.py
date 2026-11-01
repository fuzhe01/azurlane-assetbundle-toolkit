# -*- coding: utf-8 -*-
"""bare_moc3_repeat.py — 不经页面、不经渲染，直接 fromMoc + update() 重复 N 次。

目的：把「部件不透明度在 0/1 之间双峰摆动」的嫌疑从页面逻辑里摘出去。
页面侧已用「582 参数向量回放」排除参数驱动；本脚本再排除页面/DOM/渲染，
只剩「同一个 moc3 的多次加载」这一个变量。

判据：
  - 若 N 次里 op[256..277] 有时 1 有时 0  → 根因在核心库/加载路径，页面无关
  - 若 N 次恒为同一值                   → 双峰来自页面/渲染，需要回到页面侧继续查

用法: py -3 scripts/diag/bare_moc3_repeat.py [--n=6]
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

N = 6
for a in sys.argv[1:]:
    if a.startswith('--n='):
        N = int(a.split('=', 1)[1])

URL = 'http://127.0.0.1:8778/gallery_v2/_bare_moc3.html'


def main():
    vals = []
    for i in range(N):
        pg = Page(9490 + i, os.path.join(ROOT, '.diag', 'chrome_bare%d' % i), URL, (600, 600))
        try:
            ok = False
            for _ in range(40):
                time.sleep(0.5)
                t = pg.ev("document.title")
                if t in ('DONE', 'ERR'):
                    ok = True
                    break
            r = pg.ev("window.__RESULT")
            print('--- 第 %d/%d 次 (title=%s) ---' % (i + 1, N, t))
            print(r if r else '(无结果)')
            if ok and r:
                for line in str(r).split('\n'):
                    if line.startswith('update#1'):
                        seg = line.split('op[256..277]=')[1].split(' ')[0]
                        vals.append([float(x) for x in seg.split(',')])
        finally:
            pg.close()
    print('\n=== 汇总（%d 次） ===' % len(vals))
    if not vals:
        print('无有效数据'); return 2
    n = len(vals[0])
    for j in range(n):
        col = [v[j] for v in vals]
        if len(set(col)) > 1:
            print('  idx %d (drawable %d): %s  ← 不一致' % (j, 256 + j, col))
    if all(len(set([v[j] for v in vals])) == 1 for j in range(n)):
        print('  全部一致：核心库加载路径稳定 ⇒ 双峰来自页面/渲染侧')
        return 0
    print('  存在不一致：核心库/加载路径本身不稳定')
    return 1


if __name__ == '__main__':
    sys.exit(main())
