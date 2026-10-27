# -*- coding: utf-8 -*-
"""l2d_clip_param_diff.py — 对单个 (模型, 动作组) 逐帧逐曲线求两组产物的参数取值差，
按「最大偏差」排序点名。用于把运行时可见位翻转追溯到具体参数曲线。

背景：`vanish_matrix.py` 能报出「第 33 件在 t=3.567 只亮一帧」，但要说清
「是哪个参数把它的 opacity 顶上去的」，就得回到数据层看同一时刻两组的参数值差。

判据要点：
  · 必须按**运行时语义**求值（复用 l2d_motion_fidelity_audit.Curve），不能自己写插值
  · 采样时刻取 `(f+1)/FPS` 与 `_vanishcan.html` 的采样时刻对齐，否则会错开单帧尖峰
  · 只报共有曲线；只在单侧出现的曲线单独列出（那是曲线集合差异，不是取值差异）

用法:
  py -3 scripts/diag/l2d_clip_param_diff.py --clip=touch_body --model=aersasi_3
  py -3 scripts/diag/l2d_clip_param_diff.py --clip=touch_body --model=aersasi_3 --top=15
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import l2d_motion_fidelity_audit as A  # noqa: E402


def load(path):
    d = json.load(io.open(path, encoding='utf-8'))
    m = {}
    for c in d.get('Curves', []):
        m[c.get('Id')] = A.Curve(A.parse_segments(c.get('Segments') or []))
    return d.get('Meta', {}), m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', default='Output/_ab/E')
    ap.add_argument('--b', default='Output/_ab/official')
    ap.add_argument('--model', required=True)
    ap.add_argument('--clip', required=True)
    ap.add_argument('--top', type=int, default=12)
    ap.add_argument('--fps', type=float, default=30.0)
    args = ap.parse_args()

    pa = os.path.join(ROOT, args.a, args.model, 'motion', args.clip + '.motion3.json')
    pb = os.path.join(ROOT, args.b, args.model, 'motion', args.clip + '.motion3.json')
    ma, ca = load(pa)
    mb, cb = load(pb)
    print('A=%s  curves=%d  Meta.Duration=%s' % (args.a, len(ca), ma.get('Duration')))
    print('B=%s  curves=%d  Meta.Duration=%s' % (args.b, len(cb), mb.get('Duration')))
    only_a = sorted(set(ca) - set(cb))
    only_b = sorted(set(cb) - set(ca))
    if only_a:
        print('仅 A 有 (%d): %s' % (len(only_a), ', '.join(only_a[:20])))
    if only_b:
        print('仅 B 有 (%d): %s' % (len(only_b), ', '.join(only_b[:20])))

    dur = float(ma.get('Duration') or 0.0)
    frames = int(dur * args.fps)
    while frames > 1 and frames / args.fps >= dur:
        frames -= 1

    common = sorted(set(ca) & set(cb))
    worst = []
    for k in common:
        mx, mt = 0.0, 0.0
        for f in range(frames):
            t = (f + 1) / args.fps
            d = abs(ca[k].at(t) - cb[k].at(t))
            if d > mx:
                mx, mt = d, t
        worst.append((mx, k, mt, ca[k].at(mt), cb[k].at(mt)))
    worst.sort(reverse=True)
    print('\n== 逐曲线最大偏差 TOP %d（采样 (f+1)/FPS，共 %d 帧）==' % (args.top, frames))
    print('   %-28s %-12s %-8s %-14s %-14s' % ('参数', '最大偏差', '时刻', 'A值', 'B值'))
    for mx, k, mt, va, vb in worst[:args.top]:
        print('   %-28s %-12.4g %-8.3f %-14.6g %-14.6g' % (k, mx, mt, va, vb))
    over = [w for w in worst if w[0] > 0.5]
    print('\n偏差 > 0.5 的曲线数 : %d / %d' % (len(over), len(common)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
