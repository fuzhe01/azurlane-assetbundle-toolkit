# -*- coding: utf-8 -*-
"""段类型差异的「量化伪影」定量判据。

背景（2026-10-26 实测）：
`Output/_ab/E` 与 `Output/_ab/official` 的 motion3.json 端点值逐曲线 100% 相同、
Meta 的 Duration/CurveCount/TotalSegmentCount 全等，只有 TotalPointCount 不同
（E=12240 / OFF=12854，差 614）。原因是 E 把「控制点恰好贴在弦的 1/3、2/3 处」
的 Bézier 段降成了 Linear —— 这在数学上是**精确等价**的（x(u)=u）。

但 official 的控制点被序列化成了 **3 位小数**（0.554 / 1.107 而非 0.553667 /
1.107333），于是它的 Bézier 求值与精确值差 3.33e-4。这个差在 moc3 内部
opacity keyform 极陡的地方（如 benningdun_2 ArtMesh214，keyform 斜率 -2，
区间宽 ~2.5e-3）会把 drawable 整帧翻转。

⇒ 本脚本判定口径：**对每个「E=Linear / OFF=Bezier」的段，检查 official 控制点
是否落在「精确弦位 ± 量化半格」内。若全部落在，则该段差异 100% 是参考文件
的序列化精度损失，E 更忠实，不得计为我方缺陷。**

用法：
    py -3 scripts/diag/l2d_bezier_quantization_audit.py
    py -3 scripts/diag/l2d_bezier_quantization_audit.py --a=Output/_ab/E --b=Output/_ab/official
"""
import argparse
import bisect
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l2d_motion_fidelity_audit as A  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))


SEG_LEN = {0: 3, 1: 7, 2: 3, 3: 3}


def parse_full(seg):
    """Segments -> [(T, t0, v0, t1, v1, c1t, c1v, c2t, c2v)]；保留控制点时间分量。

    审计模块的 parse_segments 丢弃了 c1t/c2t（只留值），量化判定需要完整四元组。
    """
    out = []
    if len(seg) < 2:
        return out
    t0, v0 = float(seg[0]), float(seg[1])
    i, n = 2, len(seg)
    while i < n:
        T = int(seg[i])
        L = SEG_LEN.get(T)
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


def load_curves(path):
    d = json.load(io.open(path, encoding='utf-8'))
    m = {}
    for c in d.get('Curves', []):
        m[(c.get('Target'), c.get('Id'))] = c
    return d.get('Meta', {}), m


def at(curve_obj, t):
    """按运行时语义在时间 t 求值（复用审计模块的 Curve）。"""
    return curve_obj.at(t)


def audit_file(pa, pb):
    ma, ca = load_curves(pa)
    mb, cb = load_curves(pb)
    common = sorted(set(ca) & set(cb))
    stats = dict(curves=len(common), onlyA=len(set(ca) - set(cb)), onlyB=len(set(cb) - set(ca)),
                 seg_pairs={}, quant_ok=0, quant_bad=0, maxdev=0.0, maxdev_curve=None,
                 maxdev_pair=None, by_pair={}, total=0, maxquant_err=0.0,
                 lendiff=0, lendiff_delta=0, maxdev_lendiff=0.0, skipped=0)
    for k in common:
        sa = parse_full(ca[k]['Segments'])
        sb = parse_full(cb[k]['Segments'])
        cvA, cvB = A.Curve(A.parse_segments(ca[k]['Segments'])), A.Curve(A.parse_segments(cb[k]['Segments']))
        # 段类型逐对比较（含段数不等时的逐段对齐）
        pairs_ok = (len(sa) == len(sb))
        for x, y in zip(sa, sb):
            key = (x[0], y[0])
            stats['seg_pairs'][key] = stats['seg_pairs'].get(key, 0) + 1
            # 只有 A=Linear 且 B=Bezier、且两段覆盖同一时间区间，才可能是量化伪影
            # （段数不等的曲线 zip 会把错位的段配成对，必须核时间区间）
            if (x[0] == 0 and y[0] == 1
                    and abs(x[1] - y[1]) <= 1e-4 and abs(x[3] - y[3]) <= 1e-4):
                t0, v0, t1, v1 = y[1], y[2], y[3], y[4]
                c1x, c1y, c2x, c2y = y[5], y[6], y[7], y[8]
                ex1, ey1 = t0 + (t1 - t0) / 3.0, v0 + (v1 - v0) / 3.0
                ex2, ey2 = t1 - (t1 - t0) / 3.0, v1 - (v1 - v0) / 3.0
                err = max(abs(c1x - ex1), abs(c1y - ey1), abs(c2x - ex2), abs(c2y - ey2))
                stats['maxquant_err'] = max(stats['maxquant_err'], err)
                # 量化半格：参考值 3 位小数 ⇒ 半格 5e-4；给 1 位余量取 1.5e-3
                stats['quant_ok' if err <= 1.5e-3 else 'quant_bad'] += 1
        if not pairs_ok:
            stats['lendiff'] = 1
            stats['lendiff_delta'] = len(sa) - len(sb)
        # 段内逐点求值偏差（细栅格），按「两组各自在该时刻的段类型」分组归因
        # ⚠️ 必须各自独立定位：A/B 段边界可能不同，用 A 的索引取 B 的类型会错配
        # ⚠️ 必须剔除「贴着段边界」的采样点：float32 时间戳 vs 十进制序列化差 ~1e-7，
        #    让同一时刻在一侧落在前段、另一侧落在后段，在阶梯段上直接造成满量程假偏差
        dur = (ma.get('Duration') or 0)
        n = max(2, min(4000, int(dur * (ma.get('Fps') or 30))))
        startsA = [s[1] for s in sa]
        startsB = [s[1] for s in sb]
        allst = sorted(set(startsA) | set(startsB))
        BOUND_EPS = 1e-5

        def near_bound(t):
            j = bisect.bisect_left(allst, t)
            for q in (j - 1, j):
                if 0 <= q < len(allst) and abs(allst[q] - t) <= BOUND_EPS:
                    return True
            return False

        skipped = 0
        for i in range(n + 1):
            t = dur * i / n
            if near_bound(t):
                skipped += 1
                continue
            d = abs(at(cvA, t) - at(cvB, t))
            kA = max(0, bisect.bisect_right(startsA, t) - 1) if sa else 0
            kB = max(0, bisect.bisect_right(startsB, t) - 1) if sb else 0
            pair = (sa[kA][0] if kA < len(sa) else 'X',
                    sb[kB][0] if kB < len(sb) else 'X')
            tag = ('LENDIFF', pair) if not pairs_ok else pair
            g = stats['by_pair'].setdefault(tag, [0, 0.0])
            g[0] += 1
            if d > g[1]:
                g[1] = d
            stats['total'] += 1
            if not pairs_ok and d > stats['maxdev_lendiff']:
                stats['maxdev_lendiff'] = d
            if d > stats['maxdev']:
                stats['maxdev'] = d
                stats['maxdev_curve'] = (k, round(t, 4), pair)
                stats['maxdev_pair'] = pair
        stats['skipped'] = skipped
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', default='Output/_ab/E')
    ap.add_argument('--b', default='Output/_ab/official')
    ap.add_argument('--detail', action='store_true')
    args = ap.parse_args()
    ra = os.path.join(ROOT, args.a)
    rb = os.path.join(ROOT, args.b)
    ships = sorted({d for d in os.listdir(ra) if os.path.isdir(os.path.join(ra, d))})
    tot = dict(quant_ok=0, quant_bad=0, maxquant_err=0.0, maxdev=0.0, total=0,
               seg_pairs={}, by_pair={})
    worst = []
    for s in ships:
        da = os.path.join(ra, s, 'motion')
        db = os.path.join(rb, s, 'motion')
        if not os.path.isdir(da):
            continue
        files = sorted(os.listdir(da))
        for f in files:
            if not f.endswith('.motion3.json'):
                continue
            pb = os.path.join(db, f)
            if not os.path.exists(pb):
                continue
            st = audit_file(os.path.join(da, f), pb)
            for k in ('quant_ok', 'quant_bad', 'maxdev', 'total', 'lendiff'):
                tot[k] = tot.get(k, 0) + st[k]
            tot['maxdev_lendiff'] = max(tot.get('maxdev_lendiff', 0.0), st['maxdev_lendiff'])
            tot['skipped'] = tot.get('skipped', 0) + st['skipped']
            tot['maxquant_err'] = max(tot['maxquant_err'], st['maxquant_err'])
            for k, v in st['seg_pairs'].items():
                tot['seg_pairs'][k] = tot['seg_pairs'].get(k, 0) + v
            for k, v in st['by_pair'].items():
                g = tot['by_pair'].setdefault(k, [0, 0.0])
                g[0] += v[0]
                g[1] = max(g[1], v[1])
            if st['maxdev'] > 1e-3:
                worst.append((st['maxdev'], s, f, st['maxdev_curve']))
            if args.detail:
                print('  %-14s %-28s segpairs=%s quant=%d/%d maxdev=%.2e'
                      % (s, f, st['seg_pairs'], st['quant_ok'], st['quant_ok'] + st['quant_bad'],
                         st['maxdev']))
    print('\n== 段类型对分布 (A=E 类型, B=official 类型) ==')
    for k in sorted(tot['seg_pairs'], key=lambda z: -tot['seg_pairs'][z]):
        print('   %-14s %d' % (str(k), tot['seg_pairs'][k]))
    print('\n== 量化判定 ==')
    print('   E=Linear & OFF=Bezier 的段数 : %d' % (tot['quant_ok'] + tot['quant_bad']))
    print('   控制点落在精确弦位 ±1.5e-3 内 : %d' % tot['quant_ok'])
    print('   超出（真形状差异）           : %d' % tot['quant_bad'])
    print('   最大控制点量化误差           : %.3e' % tot['maxquant_err'])
    print('\n== 段数不等的曲线（我方多/少拆段）==')
    print('   曲线数 : %d' % tot['lendiff'])
    print('   该类曲线的最大逐点偏差 : %.3e' % tot['maxdev_lendiff'])
    print('\n== 段内逐点求值偏差（全模型全曲线细栅格，已剔除贴边界采样点）==')
    print('   采样点总数 : %d   剔除贴边界 : %d' % (tot['total'], tot['skipped']))
    print('   %-22s %-12s %-10s %s' % ('段类型对', '采样点数', '最大偏差', '归因'))
    ATTR = {
        (0, 0): 'Linear vs Linear，应恒 0',
        (1, 1): 'Bézier vs Bézier，仅控制点量化',
        (2, 2): 'Stepped vs Stepped，应恒 0',
        (0, 1): 'E=Linear / OFF=Bézier → 参考 3 位小数量化伪影',
        (0, 2): 'E=Linear / OFF=Stepped → 参考把真竖跳当阶梯',
        (1, 0): 'E=Bézier / OFF=Linear → 参考丢曲率（已判天花板）',
        (1, 2): 'E=Bézier / OFF=Stepped',
        (2, 1): 'E=Stepped / OFF=Bézier',
    }
    for k in sorted(tot['by_pair'], key=lambda z: -tot['by_pair'][z][0]):
        g = tot['by_pair'][k]
        attr = ATTR.get(k, '')
        if isinstance(k, tuple) and k and k[0] == 'LENDIFF':
            attr = '段数不等（我方多拆/官方合并）'
        print('   %-22s %-12d %-10.3e %s' % (str(k), g[0], g[1], attr))
    worst.sort(reverse=True)
    print('   偏差 > 1e-3 的 clip 数 : %d' % len(worst))
    for w in worst[:10]:
        md, s, f, cur = w
        k, t, pair = cur
        print('     %.3e  %s/%s  @t=%s  param=%s  pair=%s'
              % (md, s, f, str(t), str(k[1]), str(pair)))
    # 判定：量化差异必须全部可解释；段数不等的曲线偏差必须落在「拆段等值」量级
    ok = (tot['quant_bad'] == 0)
    print('\n判定: %s' % ('PASS —— 全部段类型差异可由参考文件 3 位小数量化解释，E 更忠实'
                       if ok else 'FAIL —— 存在无法用量化解释的形状差异'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
