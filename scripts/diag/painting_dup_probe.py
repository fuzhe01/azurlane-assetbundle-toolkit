#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针：同一 painting 有多行时，`build_indexes` 的「首行胜出」会选错哪几行。

背景：皮肤表里 142 个 painting 值对应多行（剧情/NPC 行 + 后来自机化新增的行同号段）。
`build_ship_meta.build_indexes()` 用 `painting2skin.setdefault(p, v)`，即**迭代序里第一行胜出**，
而第一行往往是剧情那行（`voice_actor=-1`、`ship_group` 指向无 stats 的 NPC 组）⇒ 已自机化的
META 卡在画廊显示成「无阵营 + 无语音」。

本脚本做三件事，全程不写任何文件：
  1. 列出全部冲突 painting 与各自的候选行；
  2. 用候选规则重算胜者，逐字段比对**是否有任何一条变得更空**（零回退闸门）；
  3. 打印「修好多少 / 改判多少 / 回退多少」，退出码即结论。

用法: py -3 scripts/diag/painting_dup_probe.py [--rule cvstats|stats,cv|name]
"""
import argparse
import collections
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import build_ship_meta as B  # noqa: E402  复用正本的加载与索引逻辑


def rows_by_painting(skin):
    """painting(原样) -> [(id, row)]，按皮肤表迭代序，与 build_indexes 看到的一致。"""
    by = collections.defaultdict(list)
    for v in skin.values():
        p = v.get('painting')
        if p:
            by[p].append(v)
    return by


def group_has_stats(skin, stats):
    """ship_group -> 该组在 ship_data_statistics 里有没有行（= 有舰级字段可解析）。"""
    skinid2skin = {v['id']: v for v in skin.values() if 'id' in v}
    gs = set()
    for sv in stats.values():
        g = skinid2skin.get(sv.get('skin_id'), {}).get('ship_group')
        if g is not None:
            gs.add(g)
    return gs


PLACEHOLDER = ('？', '?', '{namecode:', '')


def is_named(v):
    s = str(v or '').strip()
    return bool(s) and not any(t in s for t in PLACEHOLDER)


def key_for(row, has_stats, rule):
    """规则越小越优先。

    ⚠️ 默认只用 `cvstats` 一档：候选行**同时**满足「有配音」且「ship_group 查得到 stats 行」，
    而现状行不满足时才改判。曾经加过 `id`（取大）当 tie-break，实测会把
    `qiye_dark`（企业 cv31 → `？？？？？`）和 `linghangyuan1_5`（超级AI-TC → `？？`）一起改判——
    那两类是**不同实体复用同一 painting**，号段大小不代表哪条是该目录的归属。
    """
    k = []
    for part in rule.split(','):
        if part == 'cvstats':
            good = (row.get('voice_actor') or -1) > 0 and row.get('ship_group') in has_stats
            k.append(0 if good else 1)
        elif part == 'stats':
            k.append(0 if row.get('ship_group') in has_stats else 1)
        elif part == 'cv':
            k.append(0 if (row.get('voice_actor') or -1) > 0 else 1)
        elif part == 'name':
            k.append(0 if is_named(row.get('name')) else 1)
        else:
            raise SystemExit(f'未知规则档: {part}')
    return tuple(k)


def emptier(a, b):
    """a 相对 b 是否更空（b=现状，a=改后）。占位名（`？？？`/`{namecode:N}`）算无名。"""
    def norm(r, f):
        if f == 'name':
            return is_named(r.get('name'))
        v = r.get(f)
        return '' if v in (None, -1, 0) else str(v)
    out = []
    if norm(a, 'name') is False and norm(b, 'name') is True:
        out.append('name')
    if norm(a, 'ship_group') == '' and norm(b, 'ship_group') != '':
        out.append('ship_group')
    if norm(a, 'voice_actor') == '' and norm(b, 'voice_actor') != '':
        out.append('voice_actor')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rule', default='cvstats')
    ap.add_argument('--all', action='store_true', help='打印全部改判组（默认只打前 30 组）')
    args = ap.parse_args()

    skin, stats, _wiki = B.load()
    by = rows_by_painting(skin)
    dup = {p: rs for p, rs in by.items() if len(rs) > 1}
    has_stats = group_has_stats(skin, stats)

    cur = {p: rs[0] for p, rs in dup.items()}                 # 现状：首行胜出
    # min() 在同键时返回**第一个**，所以并列即维持现状 —— 这是"零回退"的那半保障
    new = {p: min(rs, key=lambda r: key_for(r, has_stats, args.rule)) for p, rs in dup.items()}

    changed = [p for p in dup if cur[p].get('id') != new[p].get('id')]
    regress = [(p, emptier(new[p], cur[p])) for p in changed if emptier(new[p], cur[p])]
    fixed_cv = [p for p in changed
                if (cur[p].get('voice_actor') or -1) <= 0 < (new[p].get('voice_actor') or -1)]
    lost_cv = [p for p in changed
               if (cur[p].get('voice_actor') or -1) > 0 >= (new[p].get('voice_actor') or -1)]
    fixed_stats = [p for p in changed
                   if cur[p].get('ship_group') not in has_stats
                   and new[p].get('ship_group') in has_stats]

    def brief(r):
        return (r.get('id'), r.get('name'), r.get('voice_actor'), r.get('ship_group'),
                '有stats' if r.get('ship_group') in has_stats else '无stats')

    print(f'皮肤表 {len(skin)} 行 / painting 冲突 {len(dup)} 组（涉及 {sum(len(r) for r in dup.values())} 行）')
    print(f'规则 {args.rule} ⇒ 改判 {len(changed)} 组 | 补回 cv {len(fixed_cv)} | '
          f'丢 cv {len(lost_cv)} | 补回 stats {len(fixed_stats)} | 字段变空 {len(regress)}')
    print()
    cap = len(changed) if args.all else 30
    for i, p in enumerate(sorted(changed)):
        if i >= cap:
            print(f'  …还有 {len(changed) - cap} 组未显示（--all 看全量）')
            break
        print(f'  {p}\n    现 {brief(cur[p])}\n    改 {brief(new[p])}')
    if lost_cv or regress:
        print('\n❌ 有回退：')
        for p in lost_cv:
            print(f'   丢 cv: {p}')
        for p, f in regress:
            print(f'   变空: {p} {f}')
        return 1
    print('\n✅ 零回退：改判只把「更空的行」换成「更实的行」')
    return 0


if __name__ == '__main__':
    sys.exit(main())
