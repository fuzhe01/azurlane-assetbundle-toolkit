#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全库扫描：prefab 层级里的**真实绘制序** vs 画廊现在用的 `layer_order` 名字启发式。

**为什么要这份扫描**（2026-10-05 天津风皮肤2「空中那份天津风没显示」）：
`build_gallery_index.py:layer_order()` 按层名后缀分桶（B<M<T、其余落进 M 桶），
把「本体层」和「M 层」塞进同一个桶、桶内再按 parts.json 的**任意顺序**排 ——
而 parts.json 的层序来自 `skel_layers()` 遍历 bundle 对象表的顺序，**不是** Unity 的
渲染顺序。实测 `tianjinfeng_2`：
  真实序  tianjinfeng_2B < 2B2 < 2M < **2(本体)** < 2T
  现在    tianjinfeng_2B < **2(本体)** < 2B2 < 2M < 2T   ← 本体被不透明房间层盖住
⇒ 只有把「渲染序」从 prefab 的 RectTransform 层级里取出来，才是权威修法；
   继续在名字后缀上打补丁 = 第 4 次猜。

**本脚本只读**：不改 parts.json / index.json，只打印差异清单。

判据（为什么 DFS 先序 = 渲染序）：Unity UI 按 transform 层级深度优先、
子节点按 `m_Children` 顺序绘制，先绘制者在后绘制者之下。

用法:
    py -3 scripts/diag/spine_render_order_scan.py            # 全库
    py -3 scripts/diag/spine_render_order_scan.py tianjinfeng_2 moermansike_3
    py -3 scripts/diag/spine_render_order_scan.py --json out.json
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)

import paths as P  # noqa: E402
import UnityPy  # noqa: E402
from UnityPy import config  # noqa: E402

config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

SPINE = os.path.join(ROOT, 'Output', 'Spine_v2')


def layer_order(name):
    """照抄 build_gallery_index.py 的现行判据（改了那边要同步这里，否则扫描在量一个不存在的东西）。"""
    if '_bg' in name or name.endswith('bg'):
        return 0
    if name.endswith('B') or 'B_' in name:
        return 1
    if name.endswith('M') or 'M_' in name:
        return 2
    if name.endswith('T') or 'T_' in name:
        return 3
    return 2


def render_order(prefab_bundle, wanted):
    """真实绘制序 = `skel_layers()` 给的 renderIndex 升序（**与写 parts.json 的同一份读法**）。"""
    import compose_paintings_v2 as C
    nds = [nd for nd in C.skel_layers(prefab_bundle) if nd['layer']]
    if not nds:
        return None, 'prefab 里没有可解析的 SkeletonGraphic 层'
    idx = {nd['layer']: nd.get('renderIndex', -1) for nd in nds}
    if any(idx.get(l, -1) < 0 for l in wanted):
        return None, '有层读不到 renderIndex: %s' % [l for l in wanted if idx.get(l, -1) < 0]
    return sorted(wanted, key=lambda l: idx[l]), '节点映射: %s' % {
        nd['layer']: nd['node'] for nd in nds} if len(wanted) < 12 else '...'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('only', nargs='*')
    ap.add_argument('--json')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    dirs = sorted(d for d in os.listdir(SPINE) if os.path.isfile(os.path.join(SPINE, d, 'parts.json')))
    if a.only:
        dirs = [d for d in dirs if d in a.only]
    diff, same, fail = [], [], []
    for n, stem in enumerate(dirs, 1):
        pj = json.load(open(os.path.join(SPINE, stem, 'parts.json'), encoding='utf-8'))
        layers = [l['layer'] for l in pj['layers'] if l.get('active') is not False]
        cur = sorted(layers, key=layer_order)                     # 现行：稳定排序
        real, why = render_order('spinepainting/' + stem, layers)
        if real is None:
            fail.append((stem, why)); continue
        if real == cur:
            same.append(stem)
        else:
            diff.append({'stem': stem, 'cur': cur, 'real': real,
                         'moves': [l for l in layers if cur.index(l) != real.index(l)]})
        if not a.quiet and n % 20 == 0:
            print('  ... %d/%d（差异 %d）' % (n, len(dirs), len(diff)), file=sys.stderr)
    print('扫描 %d 个目录：绘制序一致 %d ｜ 不一致 %d ｜ 读不到 %d'
          % (len(dirs), len(same), len(diff), len(fail)))
    for d in diff:
        print('  [序不同] %-22s 现行=%s  真实=%s' % (d['stem'], ' < '.join(x.replace(d['stem'], '·') for x in d['cur']),
                                                     ' < '.join(x.replace(d['stem'], '·') for x in d['real'])))
    for stem, why in fail:
        print('  [读不到] %-22s %s' % (stem, why))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'diff': diff, 'same': same, 'fail': [s for s, _ in fail]}, f,
                      ensure_ascii=False, indent=1)
        print('JSON -> %s' % a.json)
    return 0 if not fail else 1


if __name__ == '__main__':
    sys.exit(main())
