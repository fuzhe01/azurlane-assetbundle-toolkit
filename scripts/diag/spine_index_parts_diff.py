#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比对两份 gallery 索引里每个 Spine 皮肤的 `spine.parts`（绘制序）—— 层序改动的**主判据**。

为什么主判据放在数据层而不是像素层（2026-10-05）：弹窗的 `pixelFit()` 用 readPixels 定机位，
机位受"那一刻哪几张贴图已上传"影响 ⇒ 同一份代码连拍两次会有亚像素级差异（实测 0.94% 像素），
逐字节比图根本做不到；而「哪些目录的绘制序变了」这件事在数据层是**精确可判**的。

判据：
  ① 两索引的 spine 皮肤集合必须相同（层集合由 parts.json 权威给出，不该因排序改动而变）；
  ② 打印 parts 数组不同的皮肤 —— 改动前后必须与预期清单一致（本轮预期 = 5 个）；
  ③ 除 skins[].spine.parts 之外的字段一个都不许变（防止"顺手"改了别的）。

用法:
    py -3 scripts/diag/spine_index_parts_diff.py .diag/index_before.json Output/gallery_v2/index.json
    py -3 scripts/diag/spine_index_parts_diff.py A.json B.json --expect tianjinfeng_2,wuzang
"""
import argparse
import json
import sys


def parts_of(ix):
    d = {}
    for s in ix.get('ships', []):
        for sk in (s.get('skins') or []):
            sp = sk.get('spine')
            if sp:
                d[sk.get('key') or sk.get('id')] = list(sp.get('parts') or [])
    return d


def strip_spine(ix):
    """把所有 spine 字段抹掉，用来验证「除绘制序之外没有别的改动」。"""
    for s in ix.get('ships', []):
        for sk in (s.get('skins') or []):
            if 'spine' in sk:
                sk['spine'] = '<stripped>'
    return ix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('--expect', default='', help='逗号分隔的预期变化清单；给了就当闸门用')
    a = ap.parse_args()
    ia = json.load(open(a.a, encoding='utf-8'))
    ib = json.load(open(a.b, encoding='utf-8'))
    pa, pb = parts_of(ia), parts_of(ib)
    rc = 0
    if set(pa) != set(pb):
        print('[红] spine 皮肤集合变了: %s' % (set(pa) ^ set(pb))); rc = 1
    ch = [k for k in pa if pa[k] != pb[k]]
    print('spine 皮肤 %d 个 ｜ parts 变化 %d 个' % (len(pa), len(ch)))
    for k in ch:
        print('  %-22s 改前 %s\n  %-22s 改后 %s' % (k, ' < '.join(pa[k]), '', ' < '.join(pb[k])))
    if a.expect:
        want = [x for x in a.expect.split(',') if x.strip()]
        if sorted(ch) != sorted(want):
            print('[红] 变化面与预期不符：预期 %s，实际 %s' % (sorted(want), sorted(ch))); rc = 1
        else:
            print('✓ 变化面与预期完全一致（%d 个）' % len(want))
    sa = json.dumps(strip_spine(json.load(open(a.a, encoding='utf-8'))), sort_keys=True, ensure_ascii=False)
    sb = json.dumps(strip_spine(json.load(open(a.b, encoding='utf-8'))), sort_keys=True, ensure_ascii=False)
    if sa != sb:
        print('[红] 抹掉 spine 字段后两份索引仍不相同 —— 有绘制序之外的改动混进来了'); rc = 1
    else:
        print('✓ 除 spine.parts 之外，两份索引逐字相同')
    return rc


if __name__ == '__main__':
    sys.exit(main())
