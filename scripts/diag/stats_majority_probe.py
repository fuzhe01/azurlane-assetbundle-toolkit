#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针：`stats_by_group` 从「组内 min(id)」改成「(nationality,type,rarity) 众数代表行」影响哪几组。

为什么需要：§56 修过一次「脏 stats 行钻 min(id) 空子」，但当时只补了「先要求 skin_id == 基皮肤」，
漏了一种情况——**脏行本身就是基皮肤行**。实测 `ship_data_statistics` 里
id=900399 把 加斯科涅 的 nationality 写成 2(皇家)、id=900398 把 弗兰德尔 的 type 写成 18(超巡)，
而同组其余 5 行都是 9(维希教廷)/5(战列) ⇒ min(id) 让单条 outlier 压掉 5 条一致行。

本脚本不写文件，逐组打印「min(id) 行 vs 众数代表行」，并给两条硬结论：
  · 分歧组数（期望很小；实测 11/969）；
  · 其中**众数并列**（拿不出多数）的组数 —— 这些组仍走 min(id)，不算改判。
退出码：有并列组、或探针算出的代表行与正本 `build_indexes` 实际选行不一致时 1。

用法: py -3 scripts/diag/stats_majority_probe.py [--show 99901 99902]
"""
import argparse
import collections
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import build_ship_meta as B  # noqa: E402

KEY = lambda r: (r.get('nationality'), r.get('type'), r.get('rarity'))


def picks(skin, stats):
    """复算 build_indexes 里的候选集，返回 group -> (min(id) 行, 众数代表行, 候选数, 众数支持度, 是否并列)。"""
    id2skin = {v['id']: v for v in skin.values() if 'id' in v}
    grp = collections.defaultdict(list)
    for x in stats.values():
        s = id2skin.get(x.get('skin_id'))
        if s:
            grp[s['ship_group']].append(x)
    base_of = {}
    for v in skin.values():
        g = v.get('ship_group')
        if g in grp and (g not in base_of or v['id'] < base_of[g]):
            base_of[g] = v['id']
    out = {}
    for g, rs in grp.items():
        cand = [r for r in rs if r.get('skin_id') == base_of.get(g)] or rs
        cur = min(cand, key=lambda r: r['id'])
        cnt = collections.Counter(KEY(r) for r in cand)
        modal, n = cnt.most_common(1)[0]
        tie = sum(1 for v in cnt.values() if v == n) > 1
        reps = [r for r in cand if KEY(r) == modal] or cand
        # 与正本同步：众数族内避开占位 english_name（`simulation` / 空）
        reps = [r for r in reps if str(r.get('english_name') or '').strip().lower()
                not in ('', 'simulation')] or reps
        out[g] = (cur, min(reps, key=lambda r: r['id']), len(cand), n, tie)
    return out


def brief(r):
    return 'id=%s %r nat=%s type=%s rar=%s' % (
        r.get('id'), r.get('name'), r.get('nationality'), r.get('type'), r.get('rarity'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--show', nargs='*', default=[], help='额外打印这些组的候选明细')
    a = ap.parse_args()

    skin, stats, _wiki = B.load()
    p = picks(skin, stats)
    # 探针自己算的"众数代表行"必须与正本 `build_indexes` 实际选中的行**逐组相同**，
    # 否则这份影响面报告说的就不是真要跑的那条路径（判据不能只对着复刻逻辑成立）。
    _p2s, _pci, sbg = B.build_indexes(skin, stats)
    drift = [g for g, v in p.items() if sbg.get(g) is not None and sbg[g]['id'] != v[1]['id']]
    diff = {g: v for g, v in p.items() if v[0]['id'] != v[1]['id']}
    ties = {g for g, v in diff.items() if v[4]}

    print('全库组数 %d | min(id) 与众数代表行分歧 %d 组 | 其中众数并列(不改判) %d 组 | '
          '与正本 build_indexes 选行不一致 %d 组（须为 0）'
          % (len(p), len(diff), len(ties), len(drift)))
    for g in drift[:10]:
        print('   ! 正本选了 %s，探针算的是 %s' % (brief(sbg[g]), brief(p[g][1])))
    for g, (cur, new, nc, n, tie) in sorted(diff.items()):
        print('  group %-8s 候选%d 众数支持%d%s\n     min(id): %s\n     众数代表: %s'
              % (g, nc, n, ' [并列]' if tie else '', brief(cur), brief(new)))
    for g in a.show:
        gg = int(g)
        if gg in p:
            cur, new, nc, n, tie = p[gg]
            print('  -- 明细 group %s: 候选 %d 行' % (gg, nc))
            id2skin = {v['id']: v for v in skin.values() if 'id' in v}
            for x in stats.values():
                s = id2skin.get(x.get('skin_id'))
                if s and s.get('ship_group') == gg:
                    print('       %s' % brief(x))
    if ties:
        print('\n❌ 有 %d 组众数并列，规则会退回 min(id) —— 需要人看' % len(ties))
        return 1
    print('\n✅ 无并列：分歧组的改判方向都是「单条 outlier → 多数一致行」')
    return 0


if __name__ == '__main__':
    sys.exit(main())
