# -*- coding: utf-8 -*-
"""LENDIFF（段数不等）曲线的裁定仪器：拿 Unity 原始多项式当真值，判谁忠实。

背景（2026-10-26）：
`Output/_ab/E` 与 `Output/_ab/official` 逐曲线端点值 100% 相同、Meta 全等，
但有 72 条曲线段数不等（`LENDIFF`）。`l2d_bezier_quantization_audit.py` 只能报
"这些曲线偏差大"，报不出"谁对"。

🔴 判据不能靠"时间段宽度"或"段类型偏好"猜，必须拿**源数据**当真值：
   `m_StreamedClip` 的每个键在段内定义一条三次多项式
       v(τ) = A·τ³ + B·τ² + C·τ + D      （τ = t − 该键时间）
   ⇒ 这是 Unity 引擎**实际求值的东西**，任何导出工具的写法都只是它的一种编码。
   对每条 LENDIFF 曲线，把 A（我方 E）与 B（官方）分别与真值逐点比：
       max|A − GT|  vs  max|B − GT|

实测判例（antu_2/touch_idle34 Param124）：
   GT   : [1.567,1.577] A=19968676 B=-299529.84 C=-1.5692 D=10 → v(0.010)=0 精确
   官方 : T=3 [1.567→1.583] 10→0（InverseStepped，段内恒返终点值 0）⇒ 抹平了 10ms 真斜坡
   我方 : T=1 [1.567→1.577] 10→0 + T=0 [1.577→1.583] 0→0          ⇒ 与 GT 一致
   ⇒ 我方忠实，官方丢信息。

用法：
    py -3 scripts/diag/l2d_lendiff_classify.py
    py -3 scripts/diag/l2d_lendiff_classify.py --b=Output/_ab/official --detail
退出码：存在「我方不忠实」的曲线 → 1
"""
import argparse
import bisect
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import l2d_motion_fidelity_audit as A  # noqa: E402

LENDIFF_DEV = 1e-3      # 判定「有差异」的采样门限
BOUND_EPS = 1e-5        # 剔除贴段边界采样点（float32 时间戳 vs 十进制序列化）
GRID_MS = 1             # 真值栅格步长（毫秒）；实测量级 1ms 足以覆盖 10ms 级斜坡


# ---------------------------------------------------------------- 真值：原始多项式
def load_raw_curves(model_dir):
    """→ {clip 名: {target 元组: [(t, A, B, C, D), ...]}}；只取真实帧，丢弃参考姿态帧。"""
    import UnityPy  # 延迟导入：只有需要真值时才付这个开销
    import extract_motions as EM

    p = model_dir
    if not os.path.isfile(p):
        p2 = model_dir + '.bundle'
        if not os.path.isfile(p2):
            return {}
        p = p2
    env = UnityPy.load(p)
    lookup = EM.collect_go_name_hashes(env)
    out = {}
    for obj in env.objects:
        if obj.type.name != 'AnimationClip':
            continue
        try:
            clip = obj.read()
        except Exception:
            continue
        name = getattr(clip, 'm_Name', '')
        if not name:
            continue
        targets, _ = EM.build_binding_targets(clip, lookup)
        try:
            frames = EM.parse_streamed_clip(clip.m_MuscleClip.m_Clip.data.m_StreamedClip)
        except Exception:
            continue
        per = {}
        for ft, keys in frames:
            if ft < -1e30:          # 参考姿态帧（-FLT_MAX），不是动画段起点
                continue
            for (ki, a, b, c, d) in keys:
                if 0 <= ki < len(targets) and targets[ki]:
                    per.setdefault(targets[ki], []).append((float(ft), a, b, c, d))
        for k in per:
            per[k].sort()
        out[name] = per
    return out


class GroundTruth(object):
    """按 Unity 段内三次多项式求值（这是引擎实际行为，不是任何一种 JSON 编码）。"""

    def __init__(self, keys):
        self.keys = keys
        self.starts = [k[0] for k in keys]

    def at(self, t):
        ks = self.keys
        if not ks:
            return 0.0
        j = bisect.bisect_right(self.starts, t) - 1
        if j < 0:
            j = 0
        t0, a, b, c, d = ks[j]
        tau = t - t0
        if tau <= 0.0:
            return d
        # 末点之后保持末值（Unity 对 clip 尾部同样如此）
        if j + 1 >= len(ks):
            return d
        return ((a * tau + b) * tau + c) * tau + d


# ---------------------------------------------------------------- 逐曲线裁定
def classify_curve(ca, cb, raw_keys, dur, fps):
    """→ dict(verdict=..., devA=..., devB=..., lo=..., hi=..., width=..., maxdev=...)"""
    sa = A.parse_segments(ca['Segments'])
    sb = A.parse_segments(cb['Segments'])
    cvA, cvB = A.Curve(sa), A.Curve(sb)
    gt = GroundTruth(raw_keys)

    bounds = sorted({s[1] for s in sa} | {s[1] for s in sb} | set(gt.starts))

    def near_bound(t):
        j = bisect.bisect_left(bounds, t)
        for q in (j - 1, j, j + 1):
            if 0 <= q < len(bounds) and abs(bounds[q] - t) <= BOUND_EPS:
                return True
        return False

    n = max(2, int(dur * 1000.0 / GRID_MS))
    devA = devB = maxdev = 0.0
    viol = []
    for i in range(n + 1):
        t = dur * i / n
        if near_bound(t):
            continue
        g = gt.at(t)
        da = abs(cvA.at(t) - g)
        db = abs(cvB.at(t) - g)
        devA = max(devA, da)
        devB = max(devB, db)
        maxdev = max(maxdev, abs(cvA.at(t) - cvB.at(t)))
        if da > LENDIFF_DEV or db > LENDIFF_DEV:
            viol.append(t)
    # 违规采样点聚成连续区间（栅格步长 = dur/n 秒）
    step = dur / n if n else 0.0
    runs = []
    if viol:
        lo = hi = viol[0]
        for t in viol[1:]:
            if t - hi > step * 1.5:
                runs.append((lo, hi))
                lo = hi = t
            else:
                hi = t
        runs.append((lo, hi))
    widest = max((h - l for l, h in runs), default=0.0)

    frame = 1.0 / (fps or 30.0)
    a_ok = devA <= LENDIFF_DEV
    b_ok = devB <= LENDIFF_DEV
    if a_ok and b_ok:
        verdict = 'BOTH_OK'
    elif a_ok:
        verdict = 'A_FAITHFUL'
    elif b_ok:
        verdict = 'B_FAITHFUL'
    else:
        verdict = 'NEITHER'
    return dict(verdict=verdict, devA=devA, devB=devB, maxdev=maxdev,
                nsegA=len(sa), nsegB=len(sb), runs=len(runs), widest=widest,
                subframe=(widest <= frame), frame=frame,
                first=runs[0][0] if runs else None)


def iter_models(root):
    for m in sorted(os.listdir(root)):
        d = os.path.join(root, m, 'motion')
        if os.path.isdir(d):
            yield m, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', default='Output/_ab/E')
    ap.add_argument('--b', default='Output/_ab/official')
    ap.add_argument('--bundle', default=os.path.join('files', 'AssetBundles', 'live2d'))
    ap.add_argument('--models', default='')
    ap.add_argument('--detail', action='store_true')
    args = ap.parse_args()

    ra = os.path.join(ROOT, args.a)
    rb = os.path.join(ROOT, args.b)
    bun = os.path.join(ROOT, args.bundle)
    want = {s for s in args.models.split(',') if s} or None

    rows = []
    for model, da in iter_models(ra):
        if want and model not in want:
            continue
        db = os.path.join(rb, model, 'motion')
        if not os.path.isdir(db):
            continue
        raw = load_raw_curves(os.path.join(bun, model))
        print('[%s] clips(raw)=%d' % (model, len(raw)))
        for f in sorted(os.listdir(da)):
            if not f.endswith('.motion3.json'):
                continue
            pb = os.path.join(db, f)
            if not os.path.exists(pb):
                continue
            ja = json.load(io.open(os.path.join(da, f), encoding='utf-8'))
            jb = json.load(io.open(pb, encoding='utf-8'))
            dur = float(ja.get('Meta', {}).get('Duration') or 0.0)
            fps = float(ja.get('Meta', {}).get('Fps') or 30.0)
            clip = f[:-len('.motion3.json')]
            rc = raw.get(clip, {})
            cbmap = {(c.get('Target'), c.get('Id')): c for c in jb.get('Curves', [])}
            for c in ja.get('Curves', []):
                k = (c.get('Target'), c.get('Id'))
                o = cbmap.get(k)
                if not o:
                    continue
                if len(A.parse_segments(c['Segments'])) == len(A.parse_segments(o['Segments'])):
                    continue
                keys = rc.get(k)
                if not keys:
                    rows.append((model, clip, k, None))
                    continue
                st = classify_curve(c, o, keys, dur, fps)
                rows.append((model, clip, k, st))
                if args.detail:
                    print('   %-9s %-30s segA=%2d segB=%2d devA=%.2e devB=%.2e %s'
                          % (st['verdict'], '%s/%s' % (clip, k[1]), st['nsegA'], st['nsegB'],
                             st['devA'], st['devB'], 'subframe' if st['subframe'] else 'WIDE'))

    got = [r for r in rows if r[3] is not None]
    noraw = [r for r in rows if r[3] is None]
    print('\n== LENDIFF 曲线总数 : %d（有原始键 %d / 无原始键 %d）=='
          % (len(rows), len(got), len(noraw)))
    for r in noraw[:20]:
        print('   无原始键  %s/%s %s' % (r[0], r[1], r[2]))

    tally = {}
    for r in got:
        tally[r[3]['verdict']] = tally.get(r[3]['verdict'], 0) + 1
    print('\n== 裁定分布（真值 = Unity 段内三次多项式）==')
    for k in sorted(tally, key=lambda z: -tally[z]):
        print('   %-12s %d' % (k, tally[k]))

    sub = [r for r in got if r[3]['verdict'] == 'A_FAITHFUL' and r[3]['subframe']]
    wide = [r for r in got if r[3]['verdict'] == 'A_FAITHFUL' and not r[3]['subframe']]
    print('   A_FAITHFUL 中：差异全落在 < 1 帧内 %d 条 / 跨帧 %d 条' % (len(sub), len(wide)))

    bad = [r for r in got if r[3]['verdict'] in ('B_FAITHFUL', 'NEITHER')]
    if bad:
        print('\n== ⚠️ 我方不忠实的曲线（必须修）==')
        for m, c, k, st in sorted(bad, key=lambda z: -z[3]['devA'])[:40]:
            print('   devA=%9.4f devB=%9.4f %-11s %s/%s %s segA=%d segB=%d'
                  % (st['devA'], st['devB'], st['verdict'], m, c, k[1], st['nsegA'], st['nsegB']))

    wide.sort(key=lambda z: -z[3]['devA'])
    if wide:
        print('\n== 跨帧但已证我方忠实（官方合并/丢信息）top-20 ==')
        for m, c, k, st in wide[:20]:
            print('   devA=%.2e devB=%8.4f 最宽=%.3fs %s/%s %s'
                  % (st['devA'], st['devB'], st['widest'], m, c, k[1]))

    ok = not bad
    print('\n判定: %s' % ('PASS —— 所有 LENDIFF 曲线我方均忠实于 Unity 原始多项式'
                        if ok else 'FAIL —— 存在我方不忠实的曲线，修 extract_motions.py'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
