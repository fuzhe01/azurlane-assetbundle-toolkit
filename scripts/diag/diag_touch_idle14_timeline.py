# -*- coding: utf-8 -*-
"""诊断 touch_idle14 全过程：逐时间点采样各参数姿态，并与 idle9 / idle10 / idle11 首帧对比。

目的：用户指出「衔接 touch_idle14 末帧的就应该是 idle9」。本脚本不看截图，
纯用 motion3 曲线把动作从 0% 到 100% 摊开，判断：
  1) touch_idle14 的 Meta（Duration / Loop / FadeIn / FadeOut）
  2) 动作各参数在各时间点的值 vs 末端值（找出「末帧突然跳变」的参数）
  3) 动作末帧 vs 各 idle 首帧的逐参数差异（区分「真匹配」与「双方都是 0 造成的假匹配」）
"""
import json
import os
import sys

LIVE2D = r'D:\azur\Output\Live2D\ougen_8'
GROUP = 'touch_idle14'
IDLES = ['idle', 'idle2', 'idle3', 'idle4', 'idle5', 'idle6', 'idle7', 'idle8',
         'idle9', 'idle10', 'idle11', 'idle12', 'idle13']


def load_motion3(group):
    m3 = None
    for p in os.listdir(LIVE2D):
        if p.endswith('.model3.json'):
            m3 = os.path.join(LIVE2D, p)
    d = json.load(open(m3, encoding='utf-8'))
    ent = (d.get('FileReferences') or {}).get('Motions', {}).get(group)
    if not ent:
        return None, None
    f = os.path.join(LIVE2D, ent[0]['File'])
    if not os.path.isfile(f):
        return None, None
    return json.load(open(f, encoding='utf-8')), f


def is_const_seg(seg):
    return (len(seg) == 5 and seg[2] == 0) or (len(seg) == 4 and seg[2] == 2)


def seg_value_at(seg, t):
    """在时间 t 处求值。Cubism motion3 段格式：
    [time, value, 0]                        线性
    [time, value, 1, c0, c1, t0, t1]        贝塞尔
    [time, value, 2, t]                     阶梯（保持到 t 切换）
    [time, value, 3, slope]                 阶梯斜率
    """
    if len(seg) < 3:
        return seg[1] if len(seg) > 1 else 0.0
    typ = seg[2]
    if typ == 0:
        return float(seg[1])
    if typ == 2:
        return float(seg[1])
    return float(seg[1])


def curve_at(curves, t):
    """返回 {param: value}，t 处的值（线性插值）。"""
    out = {}
    for c in curves:
        if c.get('Target') != 'Parameter':
            continue
        pid = c.get('Id')
        seg = c.get('Segments') or []
        if len(seg) < 2 or pid is None:
            continue
        if len(seg) == 2:
            out[pid] = float(seg[1])
            continue
        # 构造关键点列表 (time, value)，忽略贝塞尔控制点用端点近似
        pts = []
        i = 0
        while i + 1 < len(seg):
            tm = float(seg[i])
            val = float(seg[i + 1])
            pts.append((tm, val))
            if i + 2 >= len(seg):
                break
            typ = seg[i + 2]
            if typ == 0:
                i += 3
            elif typ == 1:
                i += 7
            elif typ == 2:
                i += 4
            elif typ == 3:
                i += 4
            else:
                i += 3
        if not pts:
            continue
        if t <= pts[0][0]:
            out[pid] = pts[0][1]
        elif t >= pts[-1][0]:
            out[pid] = pts[-1][1]
        else:
            for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
                if t0 <= t <= t1:
                    if t1 - t0 < 1e-9:
                        out[pid] = v1
                    else:
                        r = (t - t0) / (t1 - t0)
                        out[pid] = v0 + (v1 - v0) * r
                    break
    return out


def ends(curves):
    """返回 {param: (start, end)}。"""
    out = {}
    for c in curves:
        if c.get('Target') != 'Parameter':
            continue
        pid = c.get('Id')
        seg = c.get('Segments') or []
        if len(seg) < 2 or pid is None:
            continue
        out[pid] = (float(seg[1]), float(seg[-1]))
    return out


def main():
    j, fpath = load_motion3(GROUP)
    if not j:
        print(f'!! 找不到 {GROUP}')
        return 1
    meta = j.get('Meta') or {}
    dur = meta.get('Duration', 0)
    curves = j.get('Curves') or []
    print(f'=== {GROUP} ===')
    print(f'文件: {fpath}')
    print(f'Meta: Loop={meta.get("Loop")} Duration={dur} FadeIn={meta.get("FadeInTime")} '
          f'FadeOut={meta.get("FadeOutTime")}')
    print(f'曲线数: {len(curves)}')
    ends_a = ends(curves)
    print(f'参数数: {len(ends_a)}')

    # 1) 时间轴采样：看哪些参数在末端突变
    print('\n--- 时间轴采样（相对 0~100%）---')
    marks = [0.0, 0.10, 0.25, 0.40, 0.50, 0.60, 0.75, 0.90, 0.95, 1.0]
    samples = []
    for m in marks:
        t = dur * m
        samples.append(curve_at(curves, t))
    # 找变化最大的参数
    allp = set()
    for s in samples:
        allp |= set(s.keys())
    # 对每个参数，看其采样序列在全过程中的变化幅度
    rows = []
    for p in allp:
        vals = [s.get(p) for s in samples]
        if any(v is None for v in vals):
            continue
        mn, mx = min(vals), max(vals)
        rows.append((mx - mn, p, vals))
    rows.sort(reverse=True)
    print('全过程中摆动最大的 15 个参数（末值 = 100% 处）：')
    print(f'{"param":28s} ' + ' '.join(f'{m*100:>6.0f}%' for m in marks))
    for rng, p, vals in rows[:15]:
        print(f'{p:28s} ' + ' '.join(f'{v:7.2f}' for v in vals))

    print('\n末帧附近（90% → 100%）变化最大的 15 个参数（找「末端跳变」）：')
    jump = []
    for p in allp:
        v90 = samples[-3].get(p)   # 95%
        v100 = samples[-1].get(p)
        if v90 is None or v100 is None:
            continue
        jump.append((abs(v100 - v90), p, v90, v100))
    jump.sort(reverse=True)
    for d, p, a, b in jump[:15]:
        print(f'  {p:28s} 95%={a:8.2f} → 100%={b:8.2f}   Δ={b-a:8.2f}')

    # 2) 末帧 vs 各 idle 首帧，区分「真匹配」与「双方都为 0」
    print('\n--- 末帧 vs 各 idle 首帧 ---')
    print(f'{"idle":8s} {"共同":>5s} {"SSE":>10s} {"覆盖":>7s} {"共同中末值非0":>12s} {"共同中首值非0":>12s}')
    res = []
    for g in IDLES:
        ij, _ = load_motion3(g)
        if not ij:
            continue
        ic = ij.get('Curves') or []
        istart = {p: v[0] for p, v in ends(ic).items()}
        common = [p for p in ends_a if p in istart]
        sse = 0.0
        nz_end = nz_start = 0
        for p in common:
            d = ends_a[p][1] - istart[p]
            sse += d * d
            if abs(ends_a[p][1]) > 1e-9:
                nz_end += 1
            if abs(istart[p]) > 1e-9:
                nz_start += 1
        cov = len(common) / len(ends_a) if ends_a else 0
        res.append((sse, g, len(common), cov, nz_end, nz_start))
        print(f'{g:8s} {len(common):5d} {sse:10.2f} {cov*100:6.1f}% '
              f'{nz_end:12d} {nz_start:12d}')
    res.sort()
    print(f'\nSSE 排序前 5: ' + ', '.join(f'{g}({s:.0f})' for s, g, *_ in res[:5]))

    # 3) idle9 自身：首帧 vs 稳态（mean）——首帧是否是它自己的「正常姿势」
    print('\n--- idle9 自身内部：首帧 vs 全程均值（看首帧是否是过渡态）---')
    i9, f9 = load_motion3('idle9')
    c9 = i9.get('Curves') or []
    d9 = (i9.get('Meta') or {}).get('Duration', 0)
    s9 = [curve_at(c9, d9 * m) for m in [0.0, 0.25, 0.5, 0.75, 1.0]]
    p9 = set()
    for s in s9:
        p9 |= set(s.keys())
    big = []
    for p in p9:
        vs = [s.get(p) for s in s9]
        if any(v is None for v in vs):
            continue
        big.append((max(vs) - min(vs), p, vs))
    big.sort(reverse=True)
    print(f'idle9 Duration={d9} Loop={(i9.get("Meta") or {}).get("Loop")} 曲线数={len(c9)}')
    print(f'{"param":28s} ' + ' '.join(f'{m*100:>6.0f}%' for m in [0, .25, .5, .75, 1.0]))
    for rng, p, vs in big[:15]:
        print(f'{p:28s} ' + ' '.join(f'{v:7.2f}' for v in vs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
