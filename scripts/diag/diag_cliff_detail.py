# -*- coding: utf-8 -*-
"""列出 touch_idle14 -> idle9 的断崖参数明细，并验证"共同参数精确对齐"。

结论要落到两条硬证据上：
  A) touch_idle14 末帧 vs idle9 首帧：共同 108 参数，逐个差值是否为 0（是否制作方刻意对齐）
  B) 断崖参数（末值非零、idle9 无曲线）：是哪些、末值多大、回落时会被复位成什么
"""
import json
import os
import sys

LIVE2D = r'D:\azur\Output\Live2D\ougen_8'
ACTION = 'touch_idle14'
IDLE = 'idle9'


def motions_map(model_dir):
    for p in sorted(os.listdir(model_dir)):
        if p.endswith('.model3.json'):
            d = json.load(open(os.path.join(model_dir, p), encoding='utf-8'))
            return (d.get('FileReferences') or {}).get('Motions') or {}
    return {}


def curves_of(motions, group):
    ent = motions.get(group) or []
    if not ent:
        return None
    f = os.path.join(LIVE2D, ent[0]['File'])
    if not os.path.isfile(f):
        return None
    j = json.load(open(f, encoding='utf-8'))
    out = {}
    for c in j.get('Curves') or []:
        if c.get('Target') != 'Parameter':
            continue
        pid, seg = c.get('Id'), c.get('Segments') or []
        if pid is None or len(seg) < 2:
            continue
        out[pid] = (float(seg[1]), float(seg[-1]))
    return out


def main():
    mo = motions_map(LIVE2D)
    a = curves_of(mo, ACTION)
    i = curves_of(mo, IDLE)
    if not a or not i:
        print('!! 缺文件')
        return 1

    common = sorted(set(a) & set(i))
    only_a = sorted(set(a) - set(i))

    print(f'=== {ACTION} 末帧 vs {IDLE} 首帧 ===')
    print(f'动作参数={len(a)}  idle参数={len(i)}  共同={len(common)}  仅动作有={len(only_a)}')
    print(f'覆盖率 = {len(common)/len(a)*100:.1f}%')

    # A) 共同参数差值分布
    diffs = [(abs(a[p][1] - i[p][0]), p, a[p][1], i[p][0]) for p in common]
    diffs.sort(reverse=True)
    n_zero = sum(1 for d, *_ in diffs if d < 1e-9)
    n_tiny = sum(1 for d, *_ in diffs if d < 1e-6)
    print(f'\n--- A) 共同参数差值 ---')
    print(f'差值精确为 0 的: {n_zero}/{len(common)}')
    print(f'差值 < 1e-6 的 : {n_tiny}/{len(common)}')
    print(f'最大差值: {diffs[0][0]:.6g}  ({diffs[0][1]})')
    print('差值最大的 10 个（确认是否全为 0）:')
    for d, p, av, iv in diffs[:10]:
        print(f'  {p:28s} 末={av:9.4f}  首={iv:9.4f}  Δ={d:.3g}')

    # B) 断崖参数
    cliff = [(abs(a[p][1]), p, a[p][1]) for p in only_a if abs(a[p][1]) > 0.5]
    cliff.sort(reverse=True)
    nonz = [(abs(a[p][1]), p, a[p][1]) for p in only_a]
    nonz.sort(reverse=True)
    print(f'\n--- B) 断崖参数（仅动作有曲线，{IDLE} 无 → 回落时复位为默认 0）---')
    print(f'仅动作有的参数 {len(only_a)} 个，其中末值非零(|v|>0.5) {len(cliff)} 个')
    print(f'断崖能量 Σ末值² = {sum(v*v for _,_,v in cliff):.2f}')
    print(f'{"param":28s} {"动作末值":>10s} {"回落复位":>10s} {"断崖Δ":>10s}')
    for d, p, v in cliff:
        print(f'  {p:28s} {v:10.4f} {0.0:10.4f} {0-v:10.4f}')
    if len(nonz) > len(cliff):
        print(f'\n(另 {len(nonz)-len(cliff)} 个末值接近 0，断崖可忽略: '
              + ', '.join(f'{p}={v:.3f}' for _, p, v in nonz[len(cliff):len(cliff)+8]) + ')')

    # C) 交叉核对：idle9 首帧那 108 个共同参数，在 idle9 自身 Loop 里首尾是否相同
    same_ends = sum(1 for p in common if abs(i[p][0] - i[p][1]) < 1e-9)
    print(f'\n--- C) {IDLE} 自身 Loop 首尾一致性 ---')
    print(f'{IDLE} 的 {len(i)} 条曲线里，首值==末值（闭环循环）的: {same_ends}/{len(i)}')
    print(f'共同参数中 idle 首尾相同的: '
          f'{sum(1 for p in common if abs(i[p][0]-i[p][1])<1e-9)}/{len(common)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
