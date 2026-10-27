# -*- coding: utf-8 -*-
"""Live2D 动作数据组离线对账（只读本地，不联网）。

用途：在 E / F / official / 生产 四组 motion3.json 之间做**纯本地**逐文件与逐采样点比对，
为「哪一组是终态」提供可复现数字。设计上刻意不碰网络与 8778，避免与 l2d_ref_diff.py
的网络长尾耦合（那个工具的 L2D_REF_BASE 支持 file://，但它有 urlopen/缓存语义）。

三档判据，逐档独立报数（见 docs/WORKFLOWS.md WF-43「判据自标定」）：
  ① 文件级  —— 逐文件 md5 相同 / 不同（回答「生产是不是已经是某组」）
  ② 曲线集  —— 曲线 Id 集合差异（少了就是丢曲线）
  ③ 采样级  —— 按运行时语义逐点求值比偏差（中位 / 最大 / 超阈曲线数）

⚠️ 采样求值必须复用正本 `l2d_motion_fidelity_audit.parse_segments` + `Curve.at`，
不要在这里手写段长表（历史事故：手写 SEG 把 Bezier 段长写成 7、把 t1/v1 索引写反，
统计全错且不报错）。正本段长表 `{0:3,1:7,2:3,3:3}`、指针从 2 起；自产 motion3 的段长表
是 `{0:2,1:7,2:1,3:3}`，两套不可混用 —— 这里比的是**已parse 的 JSON**，用 Curve.at 即可。

用法:
  py -3 scripts/diag/l2d_group_cmp.py --files                 # 只做①文件级
  py -3 scripts/diag/l2d_group_cmp.py --sample                # ①②③全做
  py -3 scripts/diag/l2d_group_cmp.py --sample --models antu_2
  py -3 scripts/diag/l2d_group_cmp.py --sample --groups E,F   # 只比这两组对 official
"""
import argparse
import glob
import hashlib
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from l2d_motion_fidelity_audit import parse_segments, Curve  # noqa: E402

GROUPS = {
    'prod': os.path.join(ROOT, 'Output', 'Live2D'),
    'E': os.path.join(ROOT, 'Output', '_ab', 'E'),
    'F': os.path.join(ROOT, 'Output', '_ab', 'F'),
    'official': os.path.join(ROOT, 'Output', '_ab', 'official'),
}

FRACS = (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875)


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def group_files(root):
    """{相对路径: 绝对路径}，相对路径形如 ougen_8/motion/home.motion3.json"""
    d = {}
    for sub in ('motion', 'motions'):        # 官方参考库两种子目录都存在
        for p in glob.glob(os.path.join(root, '*', sub, '*.motion3.json')):
            d[os.path.relpath(p, root).replace('\\', '/')] = p
    return d


def file_level(groups):
    print('=== ① 文件级（逐文件 md5）===')
    cache = {g: {k: md5(v) for k, v in group_files(r).items()} for g, r in groups.items()}
    names = list(cache)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = cache[names[i]], cache[names[j]]
            common = set(a) & set(b)
            same = sum(1 for k in common if a[k] == b[k])
            print(f'{names[i]:>9} vs {names[j]:<9}: '
                  f'共同={len(common):4d}  same={same:4d}  diff={len(common) - same:4d}'
                  f'  only_left={len(set(a) - set(b))}  only_right={len(set(b) - set(a))}')
    return cache


def load(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def curves_by_id(doc):
    return {c['Id']: c for c in doc.get('Curves', [])}


def span(segs):
    """(首段起点时间, 末段终点时间)。空段返回 None。"""
    if not segs:
        return None
    return segs[0][1], segs[-1][3]


def sample_dev(a_curves, b_curves, ids):
    """逐曲线按 frac 采样求绝对偏差，返回 [每曲线最差偏差]。

    ⚠️ 时间锚点取**任一侧都没被截断**的公共区间 [max(t0), min(t1)]，否则一条曲线比另一条短
    （官方会做关键帧简化）时，超出短侧末段时间的采样点会被 `Curve.at` 钳到末值，
    偏差里混进「比长度」而不是「比形状」的噪声。
    """
    devs = []
    for cid in ids:
        segs_a = parse_segments(a_curves[cid]['Segments'])
        segs_b = parse_segments(b_curves[cid]['Segments'])
        sa, sb = span(segs_a), span(segs_b)
        if not sa or not sb:
            continue
        t0 = max(sa[0], sb[0])
        t1 = min(sa[1], sb[1])
        if t1 <= t0:
            continue
        ca, cb = Curve(segs_a), Curve(segs_b)
        worst = 0.0
        for f in FRACS:
            tp = t0 + (t1 - t0) * f
            worst = max(worst, abs(ca.at(tp) - cb.at(tp)))
        devs.append(worst)
    return devs


def sample_level(groups, models, ref='official'):
    print(f'\n=== ②③ 曲线集 + 采样级（参考 = {ref}）===')
    ref_files = group_files(groups[ref])
    meta = {'group': [], 'files': [], 'curves': [], 'median': [], 'max': [],
            'over': [], 'checked': []}
    for g, root in groups.items():
        if g == ref:
            continue
        gf = group_files(root)
        rows = []
        for rel, rp in sorted(gf.items()):
            if models and rel.split('/')[0] not in models:
                continue
            if rel not in ref_files:
                continue
            try:
                da, db = load(rp), load(ref_files[rel])
            except (OSError, ValueError):
                continue
            ca, cb = curves_by_id(da), curves_by_id(db)
            common = sorted(set(ca) & set(cb))
            if not common:
                continue
            devs = sample_dev(ca, cb, common)
            if not devs:
                continue
            rows.append((rel, len(ca), len(cb), len(set(ca) - set(cb)),
                         statistics.median(devs), max(devs),
                         sum(1 for d in devs if d > 0.5), len(devs)))
        if not rows:
            print(f'{g}: 无可比文件（模型过滤或参考缺失）')
            continue
        tot_checked = sum(r[7] for r in rows)
        all_dev = [r[5] for r in rows]
        print(f'{g}: files={len(rows)} checked_curves={tot_checked} '
              f'中位(逐文件最差的中位)={statistics.median([r[4] for r in rows]):.6g} '
              f'全局最大={max(all_dev):.6g} '
              f'超0.5曲线={sum(r[6] for r in rows)}')
        worst = max(rows, key=lambda r: r[5])
        print(f'    最差文件 {worst[0]}  曲线={worst[1]}/{worst[2]}  缺曲线={worst[3]}  '
              f'max={worst[5]:.6g}  超0.5={worst[6]}/{worst[7]}')
        meta['group'].append(g)
        meta['files'].append(len(rows))
        meta['curves'].append(tot_checked)
        meta['median'].append(statistics.median([r[4] for r in rows]))
        meta['max'].append(max(all_dev))
        meta['over'].append(sum(r[6] for r in rows))
        meta['checked'].append(tot_checked)
    if not meta['group']:
        print('\n[FAIL] 无任何可比样本 —— 检查 --groups / --models / 路径是否存在')
        return 1
    print('\n| 组 | 文件 | 采样曲线 | 中位偏差 | 最大偏差 | 超0.5曲线 |')
    print('|---|---|---|---|---|---|')
    for i, g in enumerate(meta['group']):
        print(f'| {g} | {meta["files"][i]} | {meta["checked"][i]} | '
              f'{meta["median"][i]:.6g} | {meta["max"][i]:.6g} | {meta["over"][i]} |')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--files', action='store_true', help='只做文件级 md5 对账')
    ap.add_argument('--sample', action='store_true', help='做曲线集 + 逐点采样对账')
    ap.add_argument('--groups', default='prod,E,F,official',
                    help='参与对账的组（逗号分隔），默认 prod,E,F,official')
    ap.add_argument('--models', default='', help='模型过滤（逗号分隔），默认全部')
    ap.add_argument('--ref', default='official', help='参考组，默认 official')
    a = ap.parse_args()
    if not (a.files or a.sample):
        ap.error('至少给 --files 或 --sample')
    sel = [g.strip() for g in a.groups.split(',') if g.strip()]
    bad = [g for g in sel if g not in GROUPS]
    if bad:
        ap.error(f'未知组 {bad}；可选 {list(GROUPS)}')
    groups = {g: GROUPS[g] for g in sel}
    for g, r in groups.items():
        if not os.path.isdir(r):
            print(f'[WARN] {g} 路径不存在: {r}')
    models = {m.strip() for m in a.models.split(',') if m.strip()}
    if a.files:
        file_level(groups)
    rc = 0
    if a.sample:
        rc = sample_level(groups, models, ref=a.ref)
    return rc


if __name__ == '__main__':
    sys.exit(main())
