# -*- coding: utf-8 -*-
"""扫全库：每个动作 -> 其 best idle 缺失的姿态参数（"断崖参数"）规模。

用户 2026-10-24 确认 touch_idle14 -> idle9 是正确的（末帧 SSE=0 精确对齐铁证），
之前"回落闪回默认 idle"的真因是 idle9 缺 305 个姿态参数、回落时被 loadParameters
从默认值重置。本脚本量化这个问题在 42 个动作组 / 全库里的分布，
为"回落 pin 断崖参数"的修法确定影响面。
"""
import json
import os
import re
import sys

LIVE2D_OUT = r'D:\azur\Output\Live2D'
IDLE_RE = re.compile(r'^idle(\d*)$')


def load_motions(model_dir):
    m3 = None
    for p in sorted(os.listdir(model_dir)):
        if p.endswith('.model3.json'):
            m3 = os.path.join(model_dir, p)
            break
    if not m3:
        return None
    d = json.load(open(m3, encoding='utf-8'))
    return (d.get('FileReferences') or {}).get('Motions')


def load_curves(model_dir, motions, group):
    ent = motions.get(group) or []
    if not ent or not ent[0].get('File'):
        return None
    f = os.path.join(model_dir, ent[0]['File'])
    if not os.path.isfile(f):
        return None
    try:
        j = json.load(open(f, encoding='utf-8'))
    except Exception:
        return None
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
    models = [d for d in sorted(os.listdir(LIVE2D_OUT))
              if os.path.isdir(os.path.join(LIVE2D_OUT, d))]
    tot_g = tot_cliff = 0
    for m in models:
        md = os.path.join(LIVE2D_OUT, m)
        motions = load_motions(md)
        if not motions:
            continue
        groups = list(motions.keys())
        idles = [g for g in groups if IDLE_RE.match(g)]
        actions = [g for g in groups if not IDLE_RE.match(g)]
        if not idles:
            continue
        full = {}
        for g in groups:
            cf = load_curves(md, motions, g)
            if cf:
                full[g] = cf
        if not full:
            continue
        idle_full = {g: c for g, c in full.items() if IDLE_RE.match(g)}
        print(f'=== {m} ===  idle={len(idle_full)} actions={len([a for a in actions if a in full])}')

        # 复刻 build_motion_chain_map.py 的 raw_sse 计分（唯一口径）
        rows = []
        for a in actions:
            af = full.get(a)
            if not af:
                continue
            end = {p: v[1] for p, v in af.items()}
            cands = []
            for g, ce in idle_full.items():
                s = 0.0
                n_common = 0
                for p, ev in end.items():
                    if p in ce:
                        d = ev - ce[p][0]
                        s += d * d
                        n_common += 1
                    else:
                        s += ev * ev      # 缺失参数：按复位到 0 的断崖计入
                cands.append((s, g, n_common))
            cands.sort()
            best_sse, best_g, n_common = cands[0]
            cov = n_common / len(end) if end else 0.0
            # 断崖参数 = 末值非零 且 best idle 无曲线
            cs = idle_full[best_g]
            cliff = [p for p, ev in end.items()
                     if p not in cs and abs(ev) > 0.5]
            cliff_energy = sum(end[p] ** 2 for p in cliff)
            rows.append((a, best_g, best_sse, cov, len(end), len(cliff), cliff_energy))

        rows.sort(key=lambda r: -r[6])
        tot_g += len(rows)
        n_bad = sum(1 for r in rows if r[6] > 100)
        tot_cliff += n_bad
        print(f'  断崖能量>100 的动作组: {n_bad}/{len(rows)}')
        print(f'  {"action":22s} {"best":8s} {"SSE":>9s} {"cov":>6s} {"nParam":>6s} '
              f'{"cliff":>5s} {"cliffE":>9s}')
        for a, bg, sse, cov, npar, nc, ce in rows[:8]:
            print(f'  {a:22s} {bg:8s} {sse:9.1f} {cov*100:5.1f}% {npar:6d} {nc:5d} {ce:9.1f}')
        print()

    print(f'[汇总] 动作组总数={tot_g}  断崖能量>100 的={tot_cliff} '
          f'({tot_cliff/max(tot_g,1)*100:.1f}%)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
