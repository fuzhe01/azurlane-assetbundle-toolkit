#!/usr/bin/env python3
"""方案 B 数据侧：非 idle 动作 → 最衔接 idle 待机变体组 的映射表预计算。

背景
  gallery_src/index.html 里 `mm.groups.idle=idleGroup`（L1319）+ `idleGroup=['idle','main','home']
  .find(...)`（L1285）让库在动作播完后**固定**回落 idle 组。方案 B：按「非 idle 动作末帧曲线 与
  各 idle 待机变体首帧曲线 的差异度」动态选最衔接的待机组回落。
  本脚本产出映射表（模型 → 动作组 → 最优待机组 + 差异度 + 候选排行）。

数据源（与前端 mm.definitions 同源，不另造清单）
  Output/Live2D/<model>/<model>.model3.json 的 FileReferences.Motions
    → dict: 组名 -> [{File, FadeInTime?, FadeOutTime?}]，File 形如 'motion/<组>.motion3.json'
  Output/Live2D/<model>/<File> 对应 motion3.json，Segments 解析规则见 parse_curve_ends()。

待机候选组的判定（覆盖两类实测组织）
  - 独立组变体（aersasi_2）：idle / idle2 / idle3 / idle5 / home / login / main_1~4
  - 同前缀编号变体（aersasi_3）：idle / idle1~idle21（另有 home / login / main_1~4）
  正则：^(idle\\d*|main_\\d+|home|login)$

差异度
  raw_sse  = Σ_{公共参数p} (动作末帧值[p] - 待机首帧值[p])²   —— 量纲不归一，仅供诊断
  norm_sse = Σ (Δp / range_p)² / N                            —— range_p 取该参数在全部待机候选
             首帧中的 max-min，落到 [0,1] 量纲，选 best 的依据；N=公共参数数（均值化，防止
             曲线多的动作天然分大）
  只统计「动作与待机都覆盖」的参数：运行时缺曲线的参数停在上一动作的值（不跳变），无差异可算。

用法
  py -3 scripts/build_motion_chain_map.py --diag [--models m1 m2]   # 只读打印样本/摘要，不写文件
  py -3 scripts/build_motion_chain_map.py --write [--models m1 m2]  # 写 Output/gallery_v2/motion_chain.json
"""
import argparse
import json
import os
import re
import sys
import glob

sys.stdout.reconfigure(encoding='utf-8')

from paths import LIVE2D_OUT, GALLERY_OUT  # noqa: E402

IDLE_RE = re.compile(r'^(idle\d*|main_\d+|home|login)$')

# 前端 idleGroup 的既定优先序（落到候选排序并列时的次选依据；首选项永远是"差异度最小"）
LEGACY_PREF = ['idle', 'main', 'home']


def parse_curve_ends(curves):
    """把 motion3.json 的 Curves 解析为 {参数Id: (首帧值, 末帧值)}。

    Segments 扁平数组规则（写入方 extract_motions.py L306-329 自检 + 技能
    live2d-motion-extraction-audit reference.md §3 双重锁定）：
      首对 (time, value)               —— 2 元素，曲线起点（无类型码）
      之后每段先一个类型码：
        0=Linear / 2=Stepped: [type, t, v]                    （3 元素）
        1=Bezier:             [type, c1t, c1v, c2t, c2v, t, v]（7 元素，终点在最后）
    ⇒ 首帧值 = seg[1]，末帧值 = seg[-1]（两种段型的终点都是 value）。
    """
    out = {}
    for c in curves or []:
        if c.get('Target') != 'Parameter':
            continue
        pid = c.get('Id')
        seg = c.get('Segments') or []
        if len(seg) < 2 or pid is None:
            continue
        out[pid] = (float(seg[1]), float(seg[-1]))
    return out


def load_model3(model_dir):
    """返回 (model3 文件路径, FileReferences.Motions dict) 或 None。"""
    cands = sorted(glob.glob(os.path.join(model_dir, '*.model3.json')))
    for p in cands:
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        motions = (d.get('FileReferences') or {}).get('Motions')
        if isinstance(motions, dict) and motions:
            return p, motions
    return None


def load_group_curve_ends(model_dir, motions, group):
    """读指定组的 motion3，返回 {参数Id: (start, end)}。缺文件返回 None。"""
    entries = motions.get(group) or []
    if not entries or not entries[0].get('File'):
        return None
    f = os.path.join(model_dir, entries[0]['File'])
    if not os.path.isfile(f):
        return None
    try:
        j = json.load(open(f, encoding='utf-8'))
    except Exception:
        return None
    return parse_curve_ends(j.get('Curves'))
def build_model_chain(model_dir, model):
    """单模型：返回 chain dict（含 idle_groups 与每个动作的候选排行）。失败返回 None。"""
    got = load_model3(model_dir)
    if not got:
        return None
    _, motions = got
    groups = list(motions.keys())
    idle_groups = [g for g in groups if IDLE_RE.match(g)]
    actions = [g for g in groups if not IDLE_RE.match(g)]
    if not idle_groups:
        return None

    idle_curves = {}
    for g in idle_groups:
        ce = load_group_curve_ends(model_dir, motions, g)
        if ce:
            idle_curves[g] = ce

    # 每个参数在全部待机候选首帧中的量纲（max-min），用于归一化
    param_range = {}
    for ce in idle_curves.values():
        for p, (s, _e) in ce.items():
            r = param_range.get(p)
            param_range[p] = (s, s) if r is None else (min(r[0], s), max(r[1], s))

    chain = {}
    for a in actions:
        a_end = load_group_curve_ends(model_dir, motions, a)
        if not a_end:
            continue
        end_val = {p: e for p, (_s, e) in a_end.items()}
        cands = []
        for g, ce in idle_curves.items():
            start_val = {p: s for p, (s, _e) in ce.items()}
            common = [p for p in start_val if p in end_val]
            if not common:
                continue
            raw = 0.0
            norm = 0.0
            n_miss_rng = 0
            for p in common:
                d = end_val[p] - start_val[p]
                raw += d * d
                lo, hi = param_range.get(p, (start_val[p], start_val[p]))
                rng = hi - lo
                if rng > 1e-9:
                    norm += (d / rng) ** 2
                else:
                    n_miss_rng += 1
            denom = len(common) - n_miss_rng
            norm = (norm / denom) if denom else float('inf')
            cands.append({'group': g, 'raw_sse': round(raw, 4),
                          'norm': round(norm, 4), 'n_params': len(common)})
        if not cands:
            continue
        cands.sort(key=lambda x: (x['norm'], x['n_params'], LEGACY_PREF.index(x['group'])
                                  if x['group'] in LEGACY_PREF else 99))
        fb = cands[0]['norm'] == float('inf')  # 与所有待机候选零公共参数
        chain[a] = {
            'best': None if fb else cands[0]['group'],
            'best_norm': None if fb else cands[0]['norm'],
            # 无衔接候选（无公共参数，如 effect）时前端回落默认 idleGroup
            'fallback': fb,
            'n_idle_cands': len(idle_groups),
            'leak_n_params': (len(a_end) - cands[0]['n_params']) if not fb else None,
            'runners_up': [{'group': c['group'],
                            'norm': None if c['norm'] == float('inf') else c['norm'],
                            'n_params': c['n_params']} for c in cands[:5]],
        }
    return {'model': model, 'idle_groups': idle_groups,
            'n_actions': len(chain), 'chain': chain}


def collect_models(models_arg):
    if models_arg:
        return [m for m in models_arg
                if os.path.isdir(os.path.join(LIVE2D_OUT, m))]
    return sorted(d for d in os.listdir(LIVE2D_OUT)
                  if os.path.isdir(os.path.join(LIVE2D_OUT, d)))


def main():
    ap = argparse.ArgumentParser(description='方案 B 映射表预计算（动作 → 最衔接 idle 待机组）')
    ap.add_argument('--diag', action='store_true', help='只读打印样本摘要（默认不开 --write 即此模式）')
    ap.add_argument('--write', action='store_true', help='写 Output/gallery_v2/motion_chain.json')
    ap.add_argument('--models', nargs='*', default=None, help='限定模型名（默认全部）')
    ap.add_argument('--show-params', action='store_true', help='每个动作额外打印差距最大的前 8 个参数')
    args = ap.parse_args()

    models = collect_models(args.models)
    print(f'[chain] 模型数: {len(models)}')

    results = {}
    n_fail = 0
    fail_models = []
    total_actions = total_fb = 0
    for m in models:
        r = build_model_chain(os.path.join(LIVE2D_OUT, m), m)
        if not r:
            n_fail += 1
            fail_models.append(m)
            continue
        results[m] = r
        fb = sum(1 for c in r['chain'].values() if c.get('fallback'))
        total_actions += r['n_actions']
        total_fb += fb
        if args.models or args.show_params:
            print(f'--- {m}: idle_groups={r["idle_groups"]} 动作数={r["n_actions"]} fallback={fb}')
            for a, c in sorted(r['chain'].items()):
                if c.get('fallback'):
                    print(f'  {a:22s} -> [FB] fallback 默认 idleGroup（无公共参数）')
                    continue
                ru = ', '.join(f'{x["group"]}={x["norm"]}' for x in c['runners_up'][:3])
                print(f'  {a:22s} -> {c["best"]:8s} (norm={c["best_norm"]}, '
                      f'leak={c["leak_n_params"]})  候补[{ru}]')
        else:
            print(f'{m:24s} 待机候选={len(r["idle_groups"]):3d} 动作={r["n_actions"]:3d} '
                  f'fallback={fb:3d}')

    print(f'[chain] 模型数={len(models)} 成功={len(results)} 失败={n_fail} '
          f'动作总数={total_actions} fallback 动作={total_fb}')
    if fail_models:
        print(f'[chain] 失败/跳过模型（无 FileReferences.Motions 或 -model3.json 缺失）:\n'
              f'  {", ".join(fail_models)}')

    if args.write:
        out = os.path.join(GALLERY_OUT, 'motion_chain.json')
        payload = {'version': 1,
                   'idle_re': IDLE_RE.pattern,
                   'models': {m: {'idle_groups': r['idle_groups'],
                                  'chain': r['chain']}
                              for m, r in results.items()}}
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        print(f'[chain] 已写 {out} （{len(results)} 模型）')


if __name__ == '__main__':
    main()
