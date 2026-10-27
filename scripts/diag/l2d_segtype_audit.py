# -*- coding: utf-8 -*-
"""l2d_segtype_audit.py — 逐曲线比对「官方发行包 motion3」与「本仓库自产 motion3」的段类型码。

为什么需要：用户报「动作中左脚/右手消失」。根因已定位到 Param31 这类**离散换装参数**
在官方包里是 Stepped(2)、在我们产物里被写成 Linear(0)：线性插值让参数在 1→0 的
3.58 秒里全程停在 (0,1) 死带，两侧部件组都不绘制。本脚本量化影响面：
  * 哪些参数被官方标为 Stepped 而我们写成 Linear（按参数名聚合）
  * 这些参数的值集是否都是小整数枚举（判定「枚举参数」这一假设是否成立）
  * 涉及多少 clip / 多长死带窗口

Segments 布局（Cubism motion3 规范）：
  首对 (time, value) 2 元素
  之后每段先一个类型码：0=Linear 3元素 / 1=Bezier 7元素 / 2=Stepped 1元素 / 3=InverseStepped 3元素
  ⇒ 末帧值 = seg[-1]

用法:
  py -3 scripts/diag/l2d_segtype_audit.py                 # 全模型汇总
  py -3 scripts/diag/l2d_segtype_audit.py --models ougen_8,aersasi_3
  py -3 scripts/diag/l2d_segtype_audit.py --param Param31 --detail
"""
import os
import sys
import json
import argparse
import collections

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

OFFICIAL = r'D:\Azur Lane Assets\Output\Live2D'
OURS = os.path.join(ROOT, 'Output', 'Live2D')

# 类型码之后的数据长度（Cubism motion3 规范：Stepped 也显式带终点值）
SEG_LEN = {0: 3, 1: 7, 2: 3, 3: 3}
SEG_NAME = {0: 'Linear', 1: 'Bezier', 2: 'Stepped', 3: 'InverseStepped'}


def parse_curve_segments(seg):
    """返回 [(type_code, t_start, v_start, t_end, v_end), ...]；布局异常抛 ValueError。"""
    out = []
    if len(seg) < 2:
        return out
    t_prev, v_prev = float(seg[0]), float(seg[1])
    i = 2
    while i < len(seg):
        code = int(seg[i])
        n = SEG_LEN.get(code)
        if n is None:
            raise ValueError('未知段类型码 %r at %d' % (code, i))
        if i + n > len(seg):
            raise ValueError('段截断 code=%d i=%d len=%d' % (code, i, len(seg)))
        t_end, v_end = float(seg[i + n - 2]), float(seg[i + n - 1])
        out.append((code, t_prev, v_prev, t_end, v_end))
        t_prev, v_prev = t_end, v_end
        i += n
    return out


def load_curves(path):
    """返回 {Id: (segments, Meta)}。解析失败返回 None。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except Exception as e:
        return None, 'ERR:%s' % e
    out = {}
    for c in d.get('Curves', []):
        out[c['Id']] = c.get('Segments') or []
    return out, d.get('Meta', {})


def scan_model(model, want_param, detail):
    off_dir = os.path.join(OFFICIAL, model, 'motions')
    if not os.path.isdir(off_dir):
        off_dir = os.path.join(OFFICIAL, model, 'motion')
    our_dir = os.path.join(OURS, model, 'motion')
    if not (os.path.isdir(off_dir) and os.path.isdir(our_dir)):
        return None
    report = {'model': model, 'clips': 0, 'clips_cmp': 0, 'param_seg': collections.Counter(),
              'param_clips': collections.defaultdict(set), 'downgraded': collections.Counter(),
              'value_sets': collections.defaultdict(set), 'miss_clip': [], 'bad_layout': []}
    off_files = {f[:-len('.motion3.json')]: os.path.join(off_dir, f)
                 for f in os.listdir(off_dir) if f.endswith('.motion3.json')}
    our_files = {f[:-len('.motion3.json')]: os.path.join(our_dir, f)
                 for f in os.listdir(our_dir) if f.endswith('.motion3.json')}
    report['clips'] = len(off_files)
    for clip in sorted(off_files):
        if clip not in our_files:
            report['miss_clip'].append(clip)
            continue
        oc, _ = load_curves(off_files[clip])
        nc, _ = load_curves(our_files[clip])
        if oc is None or nc is None or not oc:
            report['bad_layout'].append(clip)
            continue
        report['clips_cmp'] += 1
        for pid in sorted(oc):
            if want_param and pid != want_param:
                continue
            oseg = oc[pid]
            nseg = nc.get(pid)
            try:
                o_list = parse_curve_segments(oseg)
            except ValueError as e:
                report['bad_layout'].append('%s/%s OFF %s' % (clip, pid, e))
                continue
            if nseg is None:
                continue
            try:
                n_list = parse_curve_segments(nseg)
            except ValueError as e:
                report['bad_layout'].append('%s/%s OURS %s' % (clip, pid, e))
                continue
            o_codes = collections.Counter(s[0] for s in o_list)
            n_codes = collections.Counter(s[0] for s in n_list)
            if not o_codes.get(2) and not o_codes.get(3):
                continue
            report['param_seg'][pid] += o_codes.get(2, 0) + o_codes.get(3, 0)
            report['param_clips'][pid].add(clip)
            # 「被降级」判定：官方有阶梯段，我们同名曲线一条阶梯都没有
            if not n_codes.get(2) and not n_codes.get(3):
                report['downgraded'][pid] += 1
            for s in o_list:
                report['value_sets'][pid].add(round(s[2], 4))
            if detail or (want_param and pid == want_param):
                print('  %-12s %-10s OFF %s  OURS %s' % (
                    clip, pid,
                    ' '.join('%s=%d' % (SEG_NAME[k], v) for k, v in sorted(o_codes.items())),
                    ' '.join('%s=%d' % (SEG_NAME[k], v) for k, v in sorted(n_codes.items()))))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', default='')
    ap.add_argument('--param', default='')
    ap.add_argument('--detail', action='store_true')
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(',') if m.strip()] or sorted(
        m for m in os.listdir(OFFICIAL) if os.path.isdir(os.path.join(OFFICIAL, m)))

    agg_seg = collections.Counter()
    agg_clips = collections.defaultdict(set)
    agg_down = collections.Counter()
    agg_vals = collections.defaultdict(set)
    agg_models = collections.defaultdict(set)
    total_clips = total_cmp = 0
    miss = bad = 0
    for m in models:
        r = scan_model(m, a.param, a.detail)
        if r is None:
            print('%s  SKIP (缺一侧目录)' % m)
            continue
        total_clips += r['clips']
        total_cmp += r['clips_cmp']
        miss += len(r['miss_clip'])
        bad += len(r['bad_layout'])
        for p, n in r['param_seg'].items():
            agg_seg[p] += n
            agg_clips[p] |= {(m, c) for c in r['param_clips'][p]}
            agg_models[p].add(m)
        for p, n in r['downgraded'].items():
            agg_down[p] += n
        for p, vs in r['value_sets'].items():
            agg_vals[p] |= vs
        if r['bad_layout']:
            print('%s  布局异常 %d 条: %s' % (m, len(r['bad_layout']), r['bad_layout'][:4]))
        if r['miss_clip']:
            print('%s  仅官方有 %d 个 clip: %s' % (m, len(r['miss_clip']), r['miss_clip'][:6]))

    print('\n=== 官方标了阶梯段、我们完全没有阶梯段的参数（按 clip 数排序）===')
    print('%-14s %-9s %-7s %-7s %-6s %s' % ('参数', '官方阶梯段', '被降级clip', '涉及clip', '模型数', '官方值集'))
    rows = sorted(agg_down.items(), key=lambda kv: -kv[1])
    for p, nd in rows:
        vs = sorted(agg_vals[p])
        vshow = ','.join('%g' % v for v in vs[:10]) + ('...' if len(vs) > 10 else '')
        is_enum = all(abs(v - round(v)) < 1e-6 for v in vs)
        print('%-14s %-11d %-10d %-9d %-7d %s %s' % (
            p, agg_seg[p], nd, len(agg_clips[p]), len(agg_models[p]), vshow,
            '<<整数枚举' if is_enum else ''))
    print('\n汇总: 比对了 %d 个模型 / %d 个 clip（官方 clip 总数 %d；仅官方有 %d；布局异常 %d）'
          % (len(models), total_cmp, total_clips, miss, bad))
    if rows:
        print('受影响参数 %d 个，其中值集为整数枚举的 %d 个'
              % (len(rows), sum(1 for p, _ in rows
                                if all(abs(v - round(v)) < 1e-6 for v in agg_vals[p]))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
