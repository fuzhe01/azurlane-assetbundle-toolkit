#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针：`stats.id == ship_skin_template.id` 这个配对信号，能补回/改判哪几条元数据。

为什么要单独数：`build_ship_meta` 的桥是
`磁盘 stem → 基 painting → 皮肤行 → skin.ship_group → stats_by_group → 舰级字段`。
900xxx 段（剧情/新实体）的游戏约定是 **stats.id 与 skin.id 同号**（`qiye_dark` 两侧都是
900072/900135），但有少数行的 `skin_id` 写歪了：

  · `aisaikesi_alter`：皮肤行 id 900406（name 埃塞克斯·META），stats 行 id 也是 900406
    （name 埃塞克斯·META / nationality=97 META / 航母 / 超稀有），可它的 `skin_id` 指向 900550
    ⇒ 按 ship_group **永远查不到**，卡片既无阵营也不独立成卡；
  · 同一处写歪的另一头：组 900550 里 id=900406 与 id=900550 两条 stats 的
    (nationality,type,rarity) **完全相同**，`min(id)` 让 900406 胜出 ⇒ 「埃塞克斯·META」
    这个名字被顶在 `npcsalatuojia_alter.png` 上，而那张图与 `salatuojia_alter.png`
    md5 逐字节相同（就是萨拉托加·META 的图）。

本探针不写文件，只数两件事并给出退出码：
 1) **救援集**：`ship_group` 查不到 stats 的皮肤行里，有多少条能靠「id 同号 + 清洗后同名」补回舰级。
    ⚠️ 救援集 ≠ 落进元数据：同一 painting 往往还有另一行（自机化新增的 970xxx 行）被 `painting2skin`
    选中，那些救援行是**惰性**的（实测 53 条里 51 条惰性，只有 `aisaikesi_alter`、`nina_wjz` 生效）。
 2) **并列改判集**：加了「id==基皮肤 配对行优先」之后，有多少组的代表行会变（实测 1 组：900550）。

反向对照（逐条放宽一个必要条件，看候选集涨多少）：`nationality` 这条在当前数据上是**冗余**的
（放宽后 53→53，它不裁任何东西，只是"没有舰级值的行拿来没用"的保险）；真正在裁的是
「清洗后同名」（198→53）与「组内本就查不到 stats」（111→53）。

用法: py -3 scripts/diag/meta_idpair_probe.py [--max-flip 5] [--max-gain 5]
退出码：生效救援条数超过 `--max-gain`，或并列改判组数超过 `--max-flip`（默认各 5）时 1。
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
import skin_table  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-flip', type=int, default=5,
                    help='「配对行优先」允许改判的最大组数，超过即判红（默认 5）')
    ap.add_argument('--max-gain', type=int, default=5,
                    help='真正落到 ship_meta 的救援条数上限，超过即判红（默认 5）')
    a = ap.parse_args()

    skin = skin_table.load()
    stats = B.load()[1]
    p2s, pci, sbg, sbid = B.build_indexes(skin, stats)
    sid2skin = {v['id']: v for v in skin.values() if 'id' in v}
    stats_by_id = {v['id']: v for v in stats.values() if 'id' in v}
    fails = []

    # ---- 1) 救援集 ----
    # 救援行只在「该 painting 被选中的正是这一行」时才真正落到 ship_meta；
    # 同一 painting 另有带 stats 的行时（970xxx 自机行胜出），救援集是惰性的。
    print('救援集（组内查不到 stats，改用 id 同号 + 同名那一行）共 %d 条：' % len(sbid))
    live = []
    for sid, sv in sorted(sbid.items()):
        sk = sid2skin[sid]
        paint = str(sk.get('painting') or '')
        eff = (p2s.get(paint) or {}).get('id') == sid      # 真正生效：选中的就是这一行
        if eff:
            live.append(paint)
        print('  %-22s skin.id=%-8s stats.id=%-8s %-14s nat=%s type=%s rar=%s  %s'
              % (paint, sid, sv['id'], B.clean_ship_name(sv.get('name') or ''),
                 sv.get('nationality'), sv.get('type'), sv.get('rarity'),
                 '生效' if eff else '惰性(该 painting 另有被选中的行)'))
    print('其中真正落到 ship_meta 的 %d 条: %s' % (len(live), ' '.join(sorted(live))))

    # 阴性对照：把三个必要条件**分别单独放宽**，看候选集涨多少；顺带硬断言
    # 探针复算的救援集 == 正本 build_indexes 的救援集（不复算就是在给不存在的规则盖章）。
    def sel(need_nat=True, need_name=True, need_group_empty=True):
        out = {}
        for sv in stats.values():
            sk = sid2skin.get(sv.get('id'))
            if not sk:
                continue
            if need_group_empty and sk.get('ship_group') in sbg:
                continue
            if need_nat and not sv.get('nationality'):
                continue
            n1 = B.clean_ship_name(sv.get('name') or '')
            if need_name and (not n1 or n1 != B.clean_ship_name(sk.get('name') or '')):
                continue
            out[sk['id']] = sv
        return out

    print('阴性对照（单独放宽一条条件后的候选集大小，正本=%d）：'
          '去 nationality 要求=%d / 去同名要求=%d / 去「组内无 stats」=%d'
          % (len(sbid), len(sel(need_nat=False)), len(sel(need_name=False)),
             len(sel(need_group_empty=False))))
    if set(sel()) != set(sbid):
        fails.append('探针复算的救援集与正本 build_indexes 不一致（%d vs %d）'
                     % (len(sel()), len(sbid)))

    # ---- 2) 配对行优先的改判集 ----
    id2skin = sid2skin
    grp = collections.defaultdict(list)
    for x in stats.values():
        g = id2skin.get(x.get('skin_id'), {}).get('ship_group')
        if g is not None:
            grp[g].append(x)
    base_of = {}
    for v in skin.values():
        g = v.get('ship_group')
        if g in grp and (g not in base_of or v['id'] < base_of[g]):
            base_of[g] = v['id']
    flip = []
    for g, rs in grp.items():
        cand = [r for r in rs if r.get('skin_id') == base_of.get(g)] or rs
        prev = B.pick_stats_row(cand, None)
        new = B.pick_stats_row(cand, base_of.get(g))
        if prev['id'] != new['id']:
            flip.append((g, prev, new))
    print('\n「id==基皮肤 配对行优先」改判 %d 组：' % len(flip))
    for g, prev, new in sorted(flip):
        print('  group %-8s 旧 id=%-8s %-14s -> 新 id=%-8s %-14s'
              % (g, prev['id'], prev.get('name'), new['id'], new.get('name')))
    if len(flip) > a.max_flip:
        fails.append('改判组数 %d 超过上限 %d' % (len(flip), a.max_flip))

    print('\n受影响 painting: %s' % ' '.join(sorted(set(live))))
    if len(live) > a.max_gain:
        fails.append('落到 ship_meta 的救援条数 %d 超过上限 %d' % (len(live), a.max_gain))
    if fails:
        for f in fails:
            print('❌ %s' % f)
        return 1
    print('✅ 救援集与改判集都在预期内（生效 %d 条 / 改判 %d 组）' % (len(live), len(flip)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
