#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2d_poly_truth_verdict.py — 以 Unity 原始三次多项式为真值，裁定两组 motion3.json 谁忠实。

为什么需要这个工具（2026-10-25 定性）：
    「我们发的段类型和官方不一样」这种差异，**不能用段类型偏好判定谁对**。
    官方导出器会把真贝塞尔降级成 Linear（丢掉曲率），所以「官方发 Linear」经常是
    官方错、我方对。唯一真值在 AssetBundle 里：m_StreamedClip 每个键定义
        v(τ) = A·τ³ + B·τ² + C·τ + D ,  τ = t − t_起点键
    逐点求值即为真值，谁离真值近谁忠实。

实测判例（aersasi_3/touch_body，官方 Linear vs 我方 Bezier，dur=6.017s，401 点）：
    Param152  我方 max=9.4e-07   官方 max=0.84
    Param153  我方 max=2.8e-06   官方 max=1.41
    All_X3    我方 max=6.8e-09   官方 max=0.010
    All_Y3    我方 max=2.2e-08   官方 max=0.013
    Param15   我方 max=6.9e-07   官方 max=1.00
  ⇒ 差距 4~7 个数量级，我方忠实、官方降级损失曲率。同批 5 模型抽样（每模型 6 clip
     × 12 曲线 × 51 点）：我方平均 3.3e-07 / 超 0.5 的曲线 0 条；生产组 0.510 / 145 条；
    官方 0.453 / 126 条。**官方自己也有一半曲线超阈**（smoothstep 降 Linear）。

用法:
    # 指定模型 / clip / 曲线，两两对照
    py -3 scripts/diag/l2d_poly_truth_verdict.py --model=aersasi_3 --clip=touch_body \
        --ids=Param152,Param153,All_X3,All_Y3 --bases=D:\\azur\\.diag\\meta\\E,D:\\azur\\Output\\_ab\\official

    # 不指定 --ids 时按「指定组之间的段类型不同」自动挑曲线
    py -3 scripts/diag/l2d_poly_truth_verdict.py --model=benningdun_2 --clip=idle --bases=A,B

    # 抽样模式：每模型随机抽 N clip、每 clip 抽 M 曲线，给整体偏差分布
    py -3 scripts/diag/l2d_poly_truth_verdict.py --sample --bases=E,PR,OFF

退出码：0 = 已给出裁定；1 = 无法裁定（缺数据 / 模型读取失败）
"""

import argparse
import bisect
import importlib.util
import io
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402

try:
    import UnityPy
    from UnityPy import config
    config.FALLBACK_UNITY_VERSION = '2022.3.62f3'
except ImportError:
    print('[ERROR] 需要 UnityPy: pip install UnityPy')
    sys.exit(1)

# 复用正本里的解析与 Curve 求值器——不复制实现，避免两套口径漂移
_EM = importlib.util.spec_from_file_location(
    'EM', os.path.join(ROOT, 'scripts', 'extract_motions.py'))
EM = importlib.util.module_from_spec(_EM)
_EM.loader.exec_module(EM)

_AU = importlib.util.spec_from_file_location(
    'AU', os.path.join(HERE, 'l2d_motion_fidelity_audit.py'))
AU = importlib.util.module_from_spec(_AU)
_AU.loader.exec_module(AU)

SAMPLE_POINTS = 51          # 均匀采样点数
BOUND_EPS = 1e-5            # 剔除贴段边界的采样点（float32 时间戳 vs 十进制序列化差 ~1e-7）
BAD_UNIT = 0.5              # 单条曲线「明显不忠实」的偏差门限（参数值单位）


def eval_truth(pts, t):
    """按 Unity 三次多项式求值（真值）。pts = 按时间升序的 [(t, A, B, C, D)]。"""
    if t <= pts[0][0]:
        return pts[0][4]
    if t >= pts[-1][0]:
        return pts[-1][4]
    k = bisect.bisect_right([p[0] for p in pts], t) - 1
    A, B, C, D = pts[k][1], pts[k][2], pts[k][3], pts[k][4]
    tau = t - pts[k][0]
    return A * tau ** 3 + B * tau ** 2 + C * tau + D


def _near_bound(times, t, eps=BOUND_EPS):
    i = bisect.bisect_left(times, t)
    for k in (i - 1, i):
        if 0 <= k < len(times) and abs(t - times[k]) <= eps:
            return True
    return False


def find_bundle(asset_root, model):
    """源包在 `files/AssetBundles/live2d/` 下是**无扩展名单文件**（不是目录）。
    先试 `<root>/<model>`、再试 `<root>/<model>.bundle`，都失败才返回 None。"""
    for cand in (model, model + '.bundle'):
        p = os.path.join(asset_root, cand)
        if os.path.exists(p):
            return p
    return None


def open_model(bundle_path):
    """读 AssetBundle；lookup 只算一次（每个模型都要用，别放进 clip 循环里重算）。"""
    env = UnityPy.load(bundle_path)
    return env, EM.collect_go_name_hashes(env)


def load_clip_raw(env, lookup, clip_name):
    """返回 (targets, series)。

    series[curve_idx] = [(t, A, B, C, D), ...]，是**真值**的唯一来源。
    ⚠️ build_binding_targets 的第二参数必须是 collect_go_name_hashes 的 **CRC 查找表**
       （gb[i].path = crc32("<前缀>/<名>")），传 {path_id: 名} 会得到全 None。
    """
    target = None
    for o in env.objects:
        if o.type.name != 'AnimationClip':
            continue
        d = o.read()
        if (d.m_Name or '') == clip_name:
            target = d
            break
    if target is None:
        return None
    targets, _unresolved = EM.build_binding_targets(target, lookup)
    frames = EM.parse_streamed_clip(target.m_MuscleClip.m_Clip.data.m_StreamedClip)
    series = {}
    for t, keys in frames:
        if t < -EM.REF_POSE_EPS:      # 参考姿态帧没有多项式，不是真值键
            continue
        tt = 0.0 if abs(t) < 1e-6 else t
        for idx, A, B, C, v in keys:
            series.setdefault(idx, []).append((tt, A, B, C, v))
    return targets, series


def name_to_idx(targets, series):
    """(Target, Id) → curve idx，只保留真值里存在的。"""
    out = {}
    for idx, tg in enumerate(targets):
        if not tg or idx not in series:
            continue
        if tg[0] != 'Parameter':
            continue
        out.setdefault(tg[1], idx)
    return out


def load_curves(bd, model, clip_name):
    """读某 base 目录下该 clip 的 {曲线名: Segments}；文件缺失返回 None。"""
    p = os.path.join(bd, model, 'motion', clip_name + '.motion3.json')
    if not os.path.isfile(p):
        return None
    j = json.load(io.open(p, encoding='utf-8'))
    out = {}
    for c in j.get('Curves', []):
        cid = c.get('Id')
        if isinstance(cid, dict):
            cid = cid.get('string')
        if c.get('Target') == 'Parameter' and cid:
            out[cid] = c['Segments']
    return out


def segtypes(segments):
    return [s[0] for s in AU.parse_segments(segments)]


def verdict_one(name, pts, seg_by_base, bases):
    """对单条曲线：各 base 的偏差 + 段类型。返回 (rows, best_base)。"""
    dur = pts[-1][0]
    if dur <= 0:
        return None, None
    times = [p[0] for p in pts]
    rows = []
    for b in bases:
        segs_raw = seg_by_base.get(b, {}).get(name)
        if segs_raw is None:
            rows.append((b, None, None, None, None))
            continue
        try:
            segs = AU.parse_segments(segs_raw)
            cur = AU.Curve(segs)
        except Exception as e:            # 结构损坏也要报，不能静默跳过
            rows.append((b, None, None, None, '解析失败: %s' % e))
            continue
        mx, s, n = 0.0, 0.0, 0
        for k in range(SAMPLE_POINTS):
            t = dur * k / (SAMPLE_POINTS - 1)
            if _near_bound(times, t):
                continue
            av = cur.at(t)
            if av is None:
                continue
            d = abs(av - eval_truth(pts, t))
            mx = max(mx, d)
            s += d
            n += 1
        rows.append((b, mx, (s / n if n else None), n, [x[0] for x in segs]))
    scored = [(r[1], r[0]) for r in rows if r[1] is not None]
    best = min(scored)[1] if scored else None
    return rows, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='aersasi_3')
    ap.add_argument('--clip', default='touch_body')
    ap.add_argument('--ids', default='', help='逗号分隔曲线名；留空=自动挑段类型不同的曲线')
    ap.add_argument('--bases', default='',
                    help='逗号分隔的产物目录；支持相对仓库根的路径。'
                         '默认 .diag/meta/E,Output/_ab/official')
    ap.add_argument('--assets', default=None, help='AssetBundle 根（默认 paths.LIVE2D_SRC）')
    ap.add_argument('--sample', action='store_true', help='抽样模式：整体偏差分布')
    ap.add_argument('--models', default='', help='抽样模式的模型列表（逗号分隔）')
    ap.add_argument('--clips-per-model', type=int, default=6)
    ap.add_argument('--curves-per-clip', type=int, default=12)
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()

    raw_bases = [b.strip() for b in args.bases.split(',') if b.strip()] or \
                [os.path.join('.diag', 'meta', 'E'), os.path.join('Output', '_ab', 'official')]
    bases = []
    for b in raw_bases:
        p = b if os.path.isabs(b) else os.path.abspath(os.path.join(ROOT, b))
        if not os.path.isdir(p):
            ap.error('base 目录不存在: %s（相对路径按仓库根 %s 解析）' % (p, ROOT))
        bases.append(p)
    labels = [os.path.basename(os.path.normpath(b)) or b for b in bases]
    asset_root = args.assets or P.LIVE2D_SRC
    models = [m.strip() for m in args.models.split(',') if m.strip()] if args.models else \
             [args.model]

    if not args.sample:
        return run_single(ap, args, bases, labels, asset_root, models[0])

    rnd = random.Random(args.seed)
    agg = {lb: {'n': 0, 'sum': 0.0, 'max': 0.0, 'bad': 0, 'curves': 0} for lb in labels}
    for model in models:
        bundle = find_bundle(asset_root, model)
        if not bundle:
            print('[skip] 模型源包缺失: %s/%s' % (asset_root, model))
            continue
        env, lookup = open_model(bundle)
        clip_names = sorted({o.read().m_Name for o in env.objects
                             if o.type.name == 'AnimationClip'})
        rnd.shuffle(clip_names)
        for cn in clip_names[:args.clips_per_model]:
            raw = load_clip_raw(env, lookup, cn)
            if not raw:
                continue
            targets, series = raw
            nm2idx = name_to_idx(targets, series)
            cur_by_base = {}
            for b, lb in zip(bases, labels):
                c = load_curves(b, model, cn)
                if c is not None:
                    cur_by_base[lb] = c
            if len(cur_by_base) < len(labels):
                continue
            common = set(nm2idx)
            for c in cur_by_base.values():
                common &= set(c)
            if not common:
                continue
            for name in sorted(common)[:args.curves_per_clip * 3]:
                pts = sorted(series[nm2idx[name]], key=lambda x: x[0])
                if len(pts) < 3:
                    continue
                rows, best = verdict_one(name, pts, cur_by_base, labels)
                if not rows:
                    continue
                for b, mx, mean, n, kinds in rows:
                    if mx is None:
                        continue
                    agg[b]['n'] += n
                    agg[b]['sum'] += mean * n
                    agg[b]['max'] = max(agg[b]['max'], mx)
                    if mx > BAD_UNIT:
                        agg[b]['bad'] += 1
                for b in labels:
                    agg[b]['curves'] += 1

    print('== 相对 Unity 原始三次多项式的偏差（抽样：%d 模型 × %d clip × 曲线）=='
          % (len(models), args.clips_per_model))
    print('%-8s %-10s %-14s %-14s %-10s' % ('base', '采样点', '平均偏差', '最大偏差', '超 %.1f 曲线' % BAD_UNIT))
    ok = True
    for b in labels:
        v = agg[b]
        if not v['n']:
            print('%-8s 无数据' % b)
            continue
        print('%-8s %-10d %-14.6g %-14.6g %-10d'
              % (b, v['n'], v['sum'] / v['n'], v['max'], v['bad']))
        if v['bad']:
            ok = False
    best = None
    cand = [(agg[b]['sum'] / agg[b]['n'], b) for b in labels if agg[b]['n']]
    if not cand:
        print('\n[WARN] 没有任何模型产出数据——检查 --assets 指向的源包根（默认 paths.LIVE2D_SRC）')
        return 1
    best = min(cand)
    print('\n【裁定】最忠实 = %s（平均偏差 %.3g）' % (best[1], best[0]))
    others = [(agg[b]['sum'] / agg[b]['n'], b) for b in labels if agg[b]['n'] and b != best[1]]
    for m, b in others:
        print('        %s 差 %.1f 倍' % (b, m / best[0] if best[0] else float('inf')))
    return 0 if ok or best else 1


def run_single(ap, args, bases, labels, asset_root, model):
    bundle = find_bundle(asset_root, model)
    if not bundle:
        ap.error('模型源包缺失: %s/%s' % (asset_root, model))
    env, lookup = open_model(bundle)
    raw = load_clip_raw(env, lookup, args.clip)
    if not raw:
        ap.error('模型 %s 里找不到 clip %r（或解不出曲线）' % (model, args.clip))
    targets, series = raw
    nm2idx = name_to_idx(targets, series)
    cur_by_base = {}
    for b, lb in zip(bases, labels):
        c = load_curves(b, model, args.clip)
        if c is None:
            print('[warn] %s 缺该 clip 文件，跳过' % lb)
            continue
        cur_by_base[lb] = c
    if not cur_by_base:
        ap.error('没有任何 base 提供该 clip')

    want = [s.strip() for s in args.ids.split(',') if s.strip()]
    if not want:
        common = set(nm2idx)
        for c in cur_by_base.values():
            common &= set(c)
        for name in sorted(common):
            kinds_per = {lb: segtypes(cur_by_base[lb][name]) for lb in cur_by_base}
            if len({tuple(k) for k in kinds_per.values()}) > 1:
                want.append(name)
        if not want:
            print('两组的段类型完全一致，无需裁定。')
            return 0
        print('[自动挑选] 段类型不同的曲线 %d 条: %s' % (len(want), ','.join(want)))

    print('\n模型 %s / clip %s | 真值来源 = m_StreamedClip 三次多项式 | 采样 %d 点（剔段边界）\n'
          % (model, args.clip, SAMPLE_POINTS))
    fail = 0
    for name in want:
        idx = nm2idx.get(name)
        if idx is None:
            print('%-14s 真值缺失（该曲线不在 Parameter 绑定或无非参考键）' % name)
            fail += 1
            continue
        pts = sorted(series[idx], key=lambda x: x[0])
        if len(pts) < 2:
            print('%-14s 真值键过少（%d）' % (name, len(pts)))
            fail += 1
            continue
        rows, best = verdict_one(name, pts, cur_by_base, labels)
        print('%-14s dur=%.4fs  裁定: %s' % (name, pts[-1][0], best or '不可判'))
        for b, mx, mean, n, kinds in rows:
            if mx is None:
                print('    %-8s  %s' % (b, kinds))
                continue
            print('    %-8s  max=%-12.6g mean=%-12.6g n=%-4d kinds=%s%s'
                  % (b, mx, mean, n, kinds, '   <<< 最忠实' if b == best else ''))
        print()
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
