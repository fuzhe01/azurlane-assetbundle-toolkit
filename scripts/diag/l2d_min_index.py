# -*- coding: utf-8 -*-
"""生成「只含指定 Live2D 模型」的最小画廊索引 index.json + index.js。

用真画廊 index.html 目视验收少量 Live2D 模型，但**不构建整棵 Output 管线**
（paintings/spine/ship_meta/skin_words/WikiData 都缺时，gallery 仍可通过一个
最小 GALLERY 数据正常打开这些模型的 Live2D 标签）。

index.json 与 index.js 由同一份数据生成、mtime 相同，满足
scripts/diag/swap_index.py 的一致性判据（index.js = `window.GALLERY=<json>;`）。

用法:
  py -3 scripts/diag/l2d_min_index.py aersasi_2 ougen_8   # 写入 Output/gallery_v2/
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAL = os.path.join(ROOT, 'Output', 'gallery_v2')


def ship_of(stem):
    sk = {'key': stem, 'label': stem, 'image': '', 'spine': False,
          'live2d': 'Live2D/' + stem, 'live2dBase': stem}
    # hasCn:false → 卡片显示「(未匹配中文名)」，但不影响 Live2D 标签可用
    return {
        'id': stem, 'name': stem, 'hasCn': False, 'npc': False,
        'type': '', 'rarity': '', 'faction': '', 'category': 'ship',
        'skins': [sk], 'spineSkins': [], 'live2dSkins': [stem],
    }


def main():
    stems = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not stems:
        print(__doc__)
        sys.exit(2)
    index = {'ships': [ship_of(s) for s in stems],
             'silhouettes': [], 'variants': [],
             'counts': {'ships': len(stems)}}
    js = 'window.GALLERY=' + json.dumps(index, ensure_ascii=False, separators=(',', ':')) + ';'
    os.makedirs(GAL, exist_ok=True)
    pj = os.path.join(GAL, 'index.json')
    pjs = os.path.join(GAL, 'index.js')
    with open(pj, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, separators=(',', ':'))
    with open(pjs, 'w', encoding='utf-8') as f:
        f.write(js)
    # swap_index 判据③：mtime 必须相同（差 >2s 判半换）
    now = time.time()
    os.utime(pj, (now, now))
    os.utime(pjs, (now, now))
    print('已写 index.json + index.js（ships=%d）-> %s' % (len(stems), GAL))
    for s in stems:
        m = os.path.join(os.path.dirname(GAL), 'Live2D', s, s + '.model3.json')
        print('  %-14s model3 %s' % (s, 'OK' if os.path.isfile(m) else '缺失!'))


if __name__ == '__main__':
    sys.exit(main())
