# -*- coding: utf-8 -*-
"""l2d_segtype_confusion.py — 段类型混淆矩阵（含「贴弦贝塞尔 = 线性」等价折叠）。

为什么需要它：`l2d_motion_fidelity_audit.py` 的 C1~C6 全部 PASS 无法区分 E/F —— 因为 C6 的
「同类型档」只比较**两侧段类型相同**的采样点，段类型一旦不同就落进「跨类型」桶，而跨类型桶
被大量无关曲线（`Paramwuli`/`ParamOPRX4` 等）刷成 max≈5.77 的常数，E 与 F 的跨类型最大值
几乎相同（5.77352 vs 5.77212）⇒ 该轴无判别力。

真正有判别力的是：**同一时刻，我方段的语义与官方段是否等价**。而「等价」必须先把
「贴弦贝塞尔」（控制点落在弦的 1/3、2/3 处，数学上精确等于线性线段）折叠成「线性」，
否则会把官方去冗余当成差异。

三类折叠后的语义标签：
  L — 线性（原生 Linear/Stepped 两端同值，或**贴弦贝塞尔**）
  B — 真曲率贝塞尔（段中点偏离弦 = 0.09375·dv，即 smoothstep）
  S — 阶梯（Stepped / InverseStepped，段内有真跳变）

判据（所有文件均 `AreBeziersRestricted=True` ⇒ 控制点时间坐标受限）：
  弦的三等分点：ey1 = v0 + (v1-v0)/3 , ey2 = v1 - (v1-v0)/3
  dev = max(|c1y - ey1|, |c2y - ey2|)
  dev → 0 表示控制点贴弦（数学上精确等价线性）；≈ (1/3)·|dv| 表示真曲率
  阈值：等价若 dev <= max(1.5e-3, 1e-3·|dv|)

❌ **不能用「段中点偏离」判**（本轮实测到的空判据）：零切线 smoothstep 段
   (v0→v1, c1y=v0, c2y=v1) 的段中点**精确等于**线性中点
   (0.125·v0+0.375·v0+0.375·v1+0.125·v1 = 0.5·(v0+v1))，
   即 |mid_bez - mid_lin| 恒为 0 —— 该判据对「对称真曲率」完全失效，
   会把 E 的保真 smoothstep 与 F 的降级线性判成同一类。必须按控制点位置判。

⚠️ 本脚本自己解析 raw `Segments`（因为 `aud.parse_segments` 丢弃了时间控制点 c1t/c2t），
   所以**必须先与正本 `aud.parse_segments` 对拍**（用 `--verify` 或内置断言），
   否则段长表写错会产出「看似有结论」的垃圾。

用法:
  py -3 scripts/diag/l2d_segtype_confusion.py --ours Output/_ab/E --models ougen_8,aersasi_2
  py -3 scripts/diag/l2d_segtype_confusion.py --ours Output/_ab/F --gt Output/_ab/official
  py -3 scripts/diag/l2d_segtype_confusion.py --ours Output/_ab/E --gt Output/_ab/F   # 直接两组对拍
"""
import io
import json
import os
import sys
import collections
import argparse

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)

import l2d_motion_fidelity_audit as aud  # noqa: E402

DEFAULT_GT = r'D:\Azur Lane Assets\Output\Live2D'
CHORD_ABS = 1.5e-3        # 「贴弦」绝对容差（覆盖官方 3 位小数量化：最大实测 3.33e-4）
CHORD_REL = 1e-3          # 「贴弦」相对容差（相对 |dv|）
SMOOTHSTEP_K = 0.3333333  # 零切线贝塞尔的控制点相对弦三等分点的偏离系数


def parse_raw(seg):
    """raw -> [(T, t0, v0, t1, v1, c1t, c1v, c2t, c2v)]；布局异常抛 ValueError。

    ⚠️ 与 aud.parse_segments 对拍过：返回值里 (T,t0,v0,t1,v1,c1v,c2v) 必须逐段相同。
    ⚠️ 段长表直接复用 aud.SEG_LEN（类型码之后的数据长度），绝不再手写。
    """
    out = []
    if len(seg) < 2:
        return out
    t0, v0 = float(seg[0]), float(seg[1])
    i, n = 2, len(seg)
    while i < n:
        T = int(seg[i])
        L = aud.SEG_LEN.get(T)
        if L is None or i + L > n:
            raise ValueError('bad segment layout type=%r at %d of %d' % (T, i, n))
        if T == 1:
            c1t, c1v, c2t, c2v, t1, v1 = (float(x) for x in seg[i + 1:i + 7])
        else:
            t1, v1 = float(seg[i + 1]), float(seg[i + 2])
            c1t = c1v = c2t = c2v = None
        out.append((T, t0, v0, t1, v1, c1t, c1v, c2t, c2v))
        t0, v0 = t1, v1
        i += L
    return out


def verify_against_aud(seg):
    """对拍：raw 解析 vs 正本 parse_segments，任一段不一致就抛错。"""
    raw = parse_raw(seg)
    ref = aud.parse_segments(seg)
    if len(raw) != len(ref):
        raise ValueError('段数不一致 raw=%d aud=%d' % (len(raw), len(ref)))
    for a, b in zip(raw, ref):
        if a[0] != b[0] or abs(a[1] - b[1]) > 0 or abs(a[2] - b[2]) > 0 \
                or abs(a[3] - b[3]) > 0 or abs(a[4] - b[4]) > 0:
            raise ValueError('段字段不一致 raw=%r aud=%r' % (a[:5], b[:5]))
        if a[0] == 1:
            if a[6] != b[5] or a[8] != b[6]:
                raise ValueError('贝塞尔控制点不一致 raw=%r aud=%r' % (a, b))
    return raw


def kind_of(s):
    """折叠语义标签：L / B / S。返回 (标签, 偏离量, |dv|, 偏离比)。"""
    T, t0, v0, t1, v1, c1t, c1v, c2t, c2v = s
    dv = v1 - v0
    if T == 0 or T == 2 or T == 3:
        if T == 0:
            return 'L', 0.0, abs(dv), 0.0
        # Stepped/InverseStepped：两端值相同则与线性等价，否则是真阶梯
        if abs(dv) <= CHORD_ABS:
            return 'L', 0.0, abs(dv), 0.0
        return 'S', abs(dv), abs(dv), 1.0
    # 控制点 vs 弦三等分点（不能用段中点判，见模块 docstring）
    ey1 = v0 + dv / 3.0
    ey2 = v1 - dv / 3.0
    dev = max(abs(c1v - ey1), abs(c2v - ey2))
    tol = max(CHORD_ABS, CHORD_REL * abs(dv))
    ratio = dev / abs(dv) if abs(dv) > 1e-9 else 0.0
    if dev <= tol:
        return 'L', dev, abs(dv), ratio
    return 'B', dev, abs(dv), ratio


def load_motions(base, model):
    for sub in ('motion', 'motions'):
        d = os.path.join(base, model, sub)
        if os.path.isdir(d):
            return {fn: os.path.join(d, fn) for fn in sorted(os.listdir(d))
                    if fn.endswith('.motion3.json')}
    return {}


def index_curves(p):
    j = json.loads(io.open(p, encoding='utf-8').read())
    out = {}
    for c in j.get('Curves', []):
        out[c.get('Id')] = c.get('Segments') or []
    return out


def selftest():
    """判别力自检：贴弦贝塞尔须判 L，零切线 smoothstep 须判 B。

    这条自检存在的理由：上一版判据（段中点偏离）对对称 smoothstep 恒返回 0，
    属于「零字段判据」式的空判据 —— 用两个必须给出**不同**答案的用例锁死它。
    """
    v0, v1 = 0.0, 3.0
    dv = v1 - v0
    chord = (1, 0.0, v0, 1.0, v1, 0.5, v0 + dv / 3.0, 1.5, v1 - dv / 3.0)
    smooth = (1, 0.0, v0, 1.0, v1, 0.5, v0, 1.5, v1)
    kl = kind_of(chord)
    kb = kind_of(smooth)
    print('贴弦贝塞尔（控制点在三等分点）-> %s  dev=%.4g' % (kl[0], kl[1]))
    print('零切线 smoothstep（c1y=v0,c2y=v1）-> %s  dev=%.4g ratio=%.4f'
          % (kb[0], kb[1], kb[3]))
    if kl[0] != 'L' or kb[0] != 'B':
        print('[FAIL] 判据无判别力：贴弦应判 L、真曲率应判 B')
        return 1
    if abs(kb[3] - SMOOTHSTEP_K) > 1e-3:
        print('[FAIL] 真曲率偏离比 %.4f != 理论 %.4f' % (kb[3], SMOOTHSTEP_K))
        return 1
    print('自检通过：两类贝塞尔被区分，偏离比命中理论值 %.4f' % SMOOTHSTEP_K)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ours', required=True)
    ap.add_argument('--gt', default=DEFAULT_GT)
    ap.add_argument('--models', default='')
    ap.add_argument('--verify', action='store_true', help='只做 raw vs aud 对拍')
    ap.add_argument('--selftest', action='store_true', help='只跑判据判别力自检')
    ap.add_argument('--show-worst', type=int, default=8)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    ours = args.ours if os.path.isabs(args.ours) else os.path.abspath(
        os.path.join(ROOT, args.ours))
    gt = args.gt if os.path.isabs(args.gt) else os.path.abspath(os.path.join(ROOT, args.gt))

    models = [m.strip() for m in args.models.split(',') if m.strip()]
    if not models:
        models = sorted(d for d in os.listdir(ours)
                        if os.path.isdir(os.path.join(ours, d)))

    conf = collections.Counter()                 # (ours_kind, gt_kind) -> 计数
    worst = []                                   # 不一致段里偏离最大的
    n_curves = 0
    n_segs = 0
    if args.verify:
        n_ok = 0
        for model in models:
            for fn, p in sorted(load_motions(ours, model).items()):
                for cid, seg in sorted(index_curves(p).items()):
                    verify_against_aud(seg)
                    n_ok += 1
        print('对拍通过：%d 条曲线 raw 解析 == aud.parse_segments' % n_ok)
        return 0

    for model in models:
        mine = load_motions(ours, model)
        theirs = load_motions(gt, model)
        if not theirs:
            print('[WARN] 参考库缺模型 %s（跳过）' % model)
            continue
        for fn in sorted(set(mine) & set(theirs)):
            mc = index_curves(mine[fn])
            oc = index_curves(theirs[fn])
            for cid in sorted(set(mc) & set(oc)):
                ms, os_ = mc[cid], oc[cid]
                try:
                    mraw = verify_against_aud(ms)
                    oraw = verify_against_aud(os_)
                except ValueError as e:
                    print('[ERR] %s/%s %s: %s' % (model, fn, cid, e))
                    return 2
                n_curves += 1
                k = 0
                for a in mraw:
                    best = None
                    j = k
                    while j < len(oraw):
                        d = abs(oraw[j][1] - a[1])
                        if best is None or d < best[0]:
                            best = (d, j)
                        if oraw[j][1] > a[1] + aud.TIME_TOL:
                            break
                        j += 1
                    if best is None or best[0] > max(aud.TIME_TOL, 2e-2):
                        continue
                    b = oraw[best[1]]
                    k = best[1]
                    ka, dev_a, dva, _ra = kind_of(a)
                    kb, _dev_b, _dvb, _rb = kind_of(b)
                    conf[(ka, kb)] += 1
                    n_segs += 1
                    if ka != kb:
                        worst.append((max(dev_a, abs(dva)), '%s/%s' % (model, fn), cid,
                                      ka, kb, dva))

    print('ours=%s\ngt  =%s' % (ours, gt))
    print('模型=%s  共有曲线=%d  配到段=%d\n' % (','.join(models), n_curves, n_segs))
    labels = ['L', 'B', 'S']
    print('段类型混淆矩阵（行=我方折叠语义，列=参考折叠语义）:')
    print('        %8s %8s %8s' % tuple('gt=' + x for x in labels))
    for a in labels:
        print('  ours=%-2s %8d %8d %8d' % (a, conf[(a, 'L')], conf[(a, 'B')], conf[(a, 'S')]))
    tot = sum(conf.values()) or 1
    agree = sum(v for (x, y), v in conf.items() if x == y)
    print('\n折叠语义一致率 = %d/%d = %.4f%%' % (agree, tot, 100.0 * agree / tot))
    print('我方=真曲率(B) 而参考=线性(L) 的段数 = %d   <-- 我方的曲率是「多给的」'
          % conf[('B', 'L')])
    print('我方=线性(L) 而参考=真曲率(B) 的段数 = %d   <-- 我方丢曲率' % conf[('L', 'B')])
    print('我方=阶梯(S) 而参考=线性(L)  = %d ; 我方=L 参考=S = %d'
          % (conf[('S', 'L')], conf[('L', 'S')]))

    worst.sort(reverse=True)
    if args.show_worst and worst:
        print('\n不一致段里 [我方偏离量, 曲线] top%d:' % args.show_worst)
        for dev, where, cid, ka, kb, dva in worst[:args.show_worst]:
            print('   ours=%s gt=%s dev=%.4f dv=%.4f  %s :: %s' % (ka, kb, dev, dva, where, cid))
    return 0


if __name__ == '__main__':
    sys.exit(main())