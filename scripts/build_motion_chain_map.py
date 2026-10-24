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

待机候选组的判定（仅纯 idle 变体；home/main_*/login 归「场景/长动画」，播完回默认 idle，不参与循环）
  - 独立组变体（aersasi_2）：idle / idle2 / idle3 / idle5
  - 同前缀编号变体（aersasi_3）：idle / idle1~idle21
  正则：^(idle\d*)$

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

IDLE_RE = re.compile(r'^(idle\d*)$')

# pose_keep 的排除项（2026-10-24）：这些参数由**运行时每帧驱动**，锁死会破坏实时表现。
#   · ParamEyeL/R/BOpen、ParamEyeBallX/Y：EyeBlink 与 focusController 每帧写
#     → pin 成 1.0 会让模型永远不眨眼（实测 touch_idle14 会带出 ParamEyeLOpen=1.0）
#   · ParamMouthOpenY/Form：LipSync 写
#   · ParamBreath、ParamAngleX/Y/Z、ParamBodyAngleX：CubismBreath 每帧加性写入
#     ⚠️ 注意 ParamAngleX 同时是**真实姿态参数**（touch_idle14 末帧 -18.367 是身体转向），
#        呼吸只是叠加小偏移。所以 ParamAngle* 不排除，靠 pin 覆盖呼吸偏移是预期行为
POSE_KEEP_SKIP_RE = re.compile(
    r'^(ParamEyeL?Open|ParamEyeROpen|ParamEyeLOpen|ParamEyeBallX|ParamEyeBallY|'
    r'ParamMouthOpenY|ParamMouthForm|ParamBreath)$')

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


def parse_curve_full(curves):
    """同 parse_curve_ends，但额外识别「单段定值」：{pid: {'start','end','const'}}。

    const = 定值（None 表示动画曲线）。判据：整条曲线恰一个类型段且为
    InverseStepped(0)/Stepped(2)，首尾值相同（[0,v,0,dur,v] / [t,v,2,v] 形态）。
    §134 续：ConstantClip 姿势层全是这种段——形态开关参数（0/N 两态）靠它识别。
    """
    out = {}
    for c in curves or []:
        if c.get('Target') != 'Parameter':
            continue
        pid = c.get('Id')
        seg = c.get('Segments') or []
        if len(seg) < 2 or pid is None:
            continue
        v0, v1 = float(seg[1]), float(seg[-1])
        is_const = ((len(seg) == 5 and seg[2] == 0) or (len(seg) == 4 and seg[2] == 2))
        out[pid] = {'start': v0, 'end': v1,
                    'const': (v0 if (is_const and abs(v0 - v1) < 1e-9) else None)}
    return out


def find_switch_params(full_by_group, min_groups=5):
    """识别「形态开关」参数（§134 续回落修法的数据侧判据）。

    判据：在 ≥min_groups 个组里以定值出现，且全部定值恰两种：零态 + 唯一非零态 V。
    实锤案例 antu_2/Param148：48 组定值 ∈ {0, 10}（装饰/形态切换）——idle11 无曲线，
    drag 末态 10 回落 idle11 被拉回 0 → 装饰瞬间消失（现行 norm 计分对此完全盲）。
    摆动参数（-20↔+20 动画、16 组定值全 0）不满足「唯一非零态」→ 不误判。
    返回 {pid: 非零态值 V}。
    """
    const_vals = {}
    for _g, curves in full_by_group.items():
        for pid, c in curves.items():
            v = c.get('const')
            if v is not None:
                const_vals.setdefault(pid, []).append(round(v, 4))
    switches = {}
    for pid, vals in const_vals.items():
        if len(vals) < min_groups:
            continue
        distinct = sorted(set(vals))
        nonzero = [v for v in distinct if abs(v) > 0.5]
        zeroish = [v for v in distinct if abs(v) <= 0.5]
        if len(nonzero) == 1 and zeroish:
            switches[pid] = nonzero[0]
    return switches


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

    def load_full(g):
        entries = motions.get(g) or []
        if not entries or not entries[0].get('File'):
            return None
        f = os.path.join(model_dir, entries[0]['File'])
        if not os.path.isfile(f):
            return None
        try:
            j = json.load(open(f, encoding='utf-8'))
        except Exception:
            return None
        return parse_curve_full(j.get('Curves'))

    # 每个动作组的时长（Meta.Duration）：前端需要它在动作播完后定时回落。
    # 为什么前端要自己回落：库的自动回落条件实测不成立（详见 index.html 里的注释），
    # 且 definitions 里只有 File、拿不到 duration，所以时长必须在建表时一起带出去。
    durations = {}
    for g in groups:
        entries = motions.get(g) or []
        if not entries or not entries[0].get('File'):
            continue
        fp = os.path.join(model_dir, entries[0]['File'])
        if not os.path.isfile(fp):
            continue
        try:
            meta = (json.load(open(fp, encoding='utf-8')).get('Meta') or {})
            dur = meta.get('Duration')
            if isinstance(dur, (int, float)) and dur > 0:
                durations[g] = round(float(dur), 3)
        except Exception:
            pass

    full = {}
    for g in groups:
        cf = load_full(g)
        if cf:
            full[g] = cf
    idle_full = {g: cf for g, cf in full.items() if IDLE_RE.match(g)}

    # 形态开关集（§134 续）：两态定值参数。硬约束——候选 idle 的开关值必须等于动作末值。
    switches = find_switch_params(full)

    # 每个参数在全部待机候选首帧中的量纲（max-min），用于归一化
    param_range = {}
    for ce in idle_full.values():
        for p, c in ce.items():
            r = param_range.get(p)
            s = c['start']
            param_range[p] = (s, s) if r is None else (min(r[0], s), max(r[1], s))

    chain = {}
    for a in actions:
        a_full = full.get(a)
        if not a_full:
            continue
        end_val = {p: c['end'] for p, c in a_full.items()}
        n_action = len(end_val)
        # 开关参数交集（仅统计用）：前端 restTick 豁免这些参数（状态保持语义），
        # 它们在 score 里也按「保持」计（无断崖），见 score 注释。
        a_switches = {p: v for p, v in switches.items() if p in end_val}

        def score(g):
            """全参数计分。漏参数（idle 无曲线）按 (end - 0)² 计入——切回后被 restTick
            拉回 0 的断崖；**开关参数例外**（前端 restTick 豁免，值保持 end，断崖=0）。"""
            ce = idle_full[g]
            raw = norm = 0.0
            n_miss_rng = n_common = 0
            for p, ev_ in end_val.items():
                if p in ce:
                    sv = ce[p]['start']
                    n_common += 1
                elif p in switches:
                    continue          # 开关参数：前端保持不复位，无断崖、无差异
                else:
                    sv = 0.0          # 摆动/姿势残留：restTick 拉回 0 的断崖
                d = ev_ - sv
                raw += d * d
                lo, hi = param_range.get(p, (sv, sv))
                rng = hi - lo
                if rng > 1e-9:
                    norm += (d / rng) ** 2
                else:
                    n_miss_rng += 1
            denom = n_action - n_miss_rng
            norm = (norm / denom) if denom else float('inf')
            return {'group': g, 'raw_sse': round(raw, 4),
                    'norm': round(norm, 4), 'n_params': n_common,
                    'n_leak': n_action - n_common}

        cands = [score(g) for g in idle_full]
        if not cands:
            continue

        # 计分口径：**全库统一 raw_sse**（2026-10-23 用户拍板，见 §138）。
        # 原先是 touch_drag* 用 raw_sse、touch_idle* 用 norm，但 norm = Σ(d/range)²/N 会让
        # 「实际几何差异最大的候选」拿到最小值得选：实测 ougen_8/touch_idle14 里
        # idle5 raw 排名 11 / norm 排名 1（被选中），而用户在游戏里确认正确答案 idle9
        # raw 排名 1（raw=680，最小）/ norm 排名 11。两种排序完全背离。
        # 全库影响面：touch_idle* 共 1945 条，口径切换后 363 条(18.7%)候选变化，用户确认切换。
        metric = 'raw_sse'
        cands.sort(key=lambda x: (x[metric], -x['n_params'],
                                  LEGACY_PREF.index(x['group'])
                                  if x['group'] in LEGACY_PREF else 99))
        best = cands[0]
        best_m = best[metric]
        fb = (best_m == float('inf'))

        # ---------- pose_keep：回落时要保住的姿态参数（2026-10-24 用户定案） ----------
        # 问题：idle 变体可能只是「呼吸层」——例如 ougen_8 的 idle9 只有 109 条曲线，
        # 108 条首尾闭合的细微摆动参数，一条姿态曲线都没有。touch_idle14 末帧的
        # ParamAngleX=-18.367 / Param194=10 / Param207=-8.2 等 305 个参数在 idle9 里无曲线，
        # 回落瞬间被 model.loadParameters() 按 moc3 默认值复位成 0 → 视角瞬间回正，
        # 用户看到的就是「回落成功后立马闪回初始默认 idle」。
        # 前端自己的 restTick 还会主动把这类参数（动作驱动过、idle 不驱动、非开关）
        # 在 400ms 后花 700ms 线性拉回默认值，二次抹掉姿势。
        #
        # 解法：把「动作末帧有值、目标 idle 无曲线」的参数记下来，回落时 pin 住。
        # 判据：
        #   · 只取末帧值非零（|v|>0.5）的——末值≈0 本来就和默认值一致，pin 没有意义
        #   · 排除开关参数——它们走 switchParams 的保持语义，前端 restTick 已豁免
        #   · 排除目标 idle 有曲线的参数——那些由 idle 自己驱动，不该锁死
        #   · 排除运行时驱动的参数（POSE_KEEP_SKIP_RE）——锁死会让模型不眨眼/不口型
        pose_keep, pose_energy = {}, 0.0
        if not fb:
            ce_best = idle_full.get(best['group']) or {}
            for p, ev_ in end_val.items():
                if p in ce_best or p in switches:
                    continue
                if abs(ev_) <= 0.5:
                    continue
                if POSE_KEEP_SKIP_RE.match(p):
                    continue
                pose_keep[p] = round(ev_, 4)
                pose_energy += ev_ * ev_

        chain[a] = {
            'best': None if fb else best['group'],
            'best_norm': None if fb else best_m,
            'metric': metric,
            'fallback': fb,
            'n_idle_cands': len(idle_groups),
            'n_action_params': n_action,
            'best_coverage': round((best['n_params'] / n_action) if n_action else 0.0, 3),
            'leak_n_params': (n_action - best['n_params']) if not fb else None,
            'n_switch_params': len(a_switches),
            'pose_keep': pose_keep,
            'pose_energy': round(pose_energy, 2),
            'n_pose_keep': len(pose_keep),

            'runners_up': [{'group': c['group'],
                            'norm': None if c['norm'] == float('inf') else c['norm'],
                            'raw_sse': c['raw_sse'],
                            'n_params': c['n_params']} for c in cands[:5]],
        }
    return {'model': model, 'idle_groups': idle_groups,
            'switch_params': switches,
            'durations': durations,
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
        payload = {'version': 2,
                   'idle_re': IDLE_RE.pattern,
                   'models': {m: {'idle_groups': r['idle_groups'],
                                  'switch_params': r.get('switch_params', {}),
                                  'durations': r.get('durations', {}),
                                  'chain': r['chain']}
                              for m, r in results.items()}}
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        print(f'[chain] 已写 {out} （{len(results)} 模型）')


if __name__ == '__main__':
    main()
