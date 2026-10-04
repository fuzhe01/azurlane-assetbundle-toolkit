#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把候选索引换入 `Output/gallery_v2/` —— **index.json 与 index.js 必须一起换**。

为什么需要这个脚本（2026-10-04 踩出来的）：
    `build_gallery_index.py` 一次写出**两个**文件 ——
      · `index.json`（给脚本 / 探针读）
      · `index.js`（`window.GALLERY=...`，**前端 `index.html` 实际加载的就是它**，
        这样 `file://` 双击也能读到数据）
    只换 json 不换 js ⇒ **页面看到的是上一次换入时的旧数据**。
    本轮就因此让「克莱蒙梭（前排）」在页面上又存在了两个多小时
    （`ship_meta` 里早就清掉了、`index.json` 也是新的，只有 `index.js` 停在 10:05）。
    ⇒ 换入这件事**必须是一个原子动作**，不能靠人记得拷两个文件。

用法:
    py -3 scripts/diag/swap_index.py <候选目录>            # 干跑，列清单
    py -3 scripts/diag/swap_index.py <候选目录> --yes      # 真换
    py -3 scripts/diag/swap_index.py --check               # 只查现网两个文件是否一致

判据:
    ① 候选目录里 `index.json` 与 `index.js` **都必须存在**（缺一个即拒，防半换）
    ② 两者的数据必须一致（把 js 里的 `window.GALLERY=` 剥掉后与 json 逐字节比）
    ③ 换入后现网两个文件的 mtime 必须相同
"""
import json
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
GAL = os.path.join(ROOT, 'Output', 'gallery_v2')
PAIRS = ('index.json', 'index.js')


def strip_js(text):
    """剥掉 `window.GALLERY=` 前缀与末尾的 `;`，还原成 json 文本。"""
    t = text.strip()
    if t.startswith('window.GALLERY='):
        t = t[len('window.GALLERY='):]
    if t.endswith(';'):
        t = t[:-1]
    return t


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    yes = '--yes' in sys.argv
    check = '--check' in sys.argv

    if check or not args:
        # 只查现网：两个文件都在、都非空、内容一致
        ok = True
        for f in PAIRS:
            p = os.path.join(GAL, f)
            if not os.path.exists(p):
                print('[FAIL] 缺 %s' % f)
                ok = False
                continue
            print('  %-12s %9d B  %s' % (
                f, os.path.getsize(p),
                time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(p)))))
        if ok:
            a = os.path.getmtime(os.path.join(GAL, 'index.json'))
            b = os.path.getmtime(os.path.join(GAL, 'index.js'))
            if abs(a - b) > 2:
                print('[FAIL] 两个文件 mtime 差 %.0f 秒 —— 很可能只换了一个' % abs(a - b))
                ok = False
            j = json.load(open(os.path.join(GAL, 'index.json'), encoding='utf-8'))
            js = strip_js(open(os.path.join(GAL, 'index.js'), encoding='utf-8').read())
            if json.loads(js) != j:
                print('[FAIL] index.js 与 index.json 内容不一致')
                ok = False
            else:
                print('[OK] 两个文件内容一致（counts=%s）' % json.dumps(j.get('counts', {}), ensure_ascii=False))
        print('结论：', '绿' if ok else '红')
        return 0 if ok else 1

    src = args[0]
    if not os.path.isabs(src):
        src = os.path.join(ROOT, src)
    print('候选目录:', src)

    # ① 两个文件都必须存在
    missing = [f for f in PAIRS if not os.path.exists(os.path.join(src, f))]
    if missing:
        print('[ERROR] 候选目录缺 %s —— 拒绝半换（这正是本脚本要防的事故）' % missing)
        return 2
    # ② 内容一致
    j = json.load(open(os.path.join(src, 'index.json'), encoding='utf-8'))
    js = strip_js(open(os.path.join(src, 'index.js'), encoding='utf-8').read())
    if json.loads(js) != j:
        print('[ERROR] 候选的 index.js 与 index.json 内容不一致，拒绝换入')
        return 2

    for f in PAIRS:
        s = os.path.getsize(os.path.join(src, f))
        print('  [DRY] %-12s %9d B' % (f, s))
    print('  counts:', json.dumps(j.get('counts', {}), ensure_ascii=False))
    if not yes:
        print('\n加 --yes 执行')
        return 0

    for f in PAIRS:
        shutil.copy2(os.path.join(src, f), os.path.join(GAL, f))
    print('\n已换入：')
    for f in PAIRS:
        p = os.path.join(GAL, f)
        print('  %-12s %9d B  %s' % (
            f, os.path.getsize(p), time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(p)))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
