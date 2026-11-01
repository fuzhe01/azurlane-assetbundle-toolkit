# -*- coding: utf-8 -*-
"""l2d_motion_fidelity_audit.py — 逐模型比对「官方发行包 motion3」与「自产 motion3」的保真度。

五条判据（C1~C4 不达标即解析 bug，C5 看分层数值分布）：

  C1 曲线数一致     我方曲线数 == 官方曲线数（缺 = 丢曲线），Id 集合零差异。
                    **豁免只有一种**：运行时根本不求值的 Model 级曲线（vendor 只认
                    EyeBlink/LipSync）。「恒等」不是豁免依据 —— 定值曲线正是切动作时的
                    复位指令，漏掉它参数就停在上个动作的值上（见 missing_reason）。
                    段数**不**作为 C1 判据：官方导出器会做关键帧简化（把多个相邻键压成
                    一段 InverseStepped/Stepped），实测 ougen_8 只有 2 条曲线段数不同、
                    合计多出 2 个关键帧，几何差可忽略。段数差异只作 INFO 报出。
  C2 关键帧一致     正确口径是**官方关键帧 ⊆ 我方关键帧**，不是逐段 zip：
                      官方有、我方同时间点没有 → 真错（丢关键帧）
                      同时间点但值不同           → 真错（值错位）
                      我方多出                   → 官方简化掉的，无害（仅 INFO 计数）
                    逐段 zip 在段数不同时必然错位，会造出上百条假「不一致」
                    （实测 685 条假警报全是这种错位，且 dt 只有 1e-7 量级）。
                    对齐必须是**贪心保序子序列**，不能是「bisect 最近邻」：最近邻在
                    官方简化的密集区会把多个官方键吸到同一个我方键上。
                    容差按**官方 JSON 序列化精度**定（TIME_TOL/VAL_TOL ≤ 2e-3，覆盖
                    官方 3 位小数截断），按我方 float32 精度（1e-6）定会把整体对齐错开一格。
  C3 Bezier 控制点  官方判为 Bezier 的段，其 c1/c2 控制点应 100% 命中（容差 CP_TOL）
  C4 Stepped 召回   分母必须是「官方 Stepped 且 |dv| > JUMP_TOL」的真跳变段
                    （官方 Stepped 段绝大多数 dv==0，与线性恒等；拿全部当分母会把
                      100% 算成 0.23% 假警报 —— 见 docs/TROUBLESHOOTING.md）
                    官方 type=3 InverseStepped 单列统计：本方管线不产出 type=3，
                    需报出官方有多少条、我们写成了什么、几何差多少
  C5 几何偏差       按 (官方段型, 我方段型) 分层报。必须分层，因为官方导出器把
                    smoothstep 多项式压成 Linear，实测官方 Linear 段偏离源多项式中位
                    2.13e-02 / p99 1.92 / max 5.76；混成一个 p99 会把官方的问题算成我们的 bug。
  C6 固定时间栅格求值 C5 用**段内归一化参数 u** 采样（必须，否则官方时间截断会造假偏差），
                    代价是段边界被刻意回避 ⇒ 「段数不等」的曲线根本不会互相踩到，
                    形状差异被结构性掩盖。C6 补这一面：按 dt=1/60s 在整条曲线上逐点求值，
                    并与运行时语义一致地剔除贴段边界采样点。判读分两档（见 c6_grid_compare）：
                      两侧段类型相同 → 求值语义相同，偏差必须 ≈0，**硬判据**
                      两侧段类型不同 → 段类型选择差异，不计 PASS/FAIL，交由
                        l2d_bezier_quantization_audit.py（量化伪影）与
                        l2d_lendiff_classify.py（原始多项式真值裁定）定性

C5 的判读规则（重要）：
  off_type0/our_type1 这一档的偏差 **不是本方 bug**。Unity 运行时播的是 m_StreamedClip 里的
  三次多项式 v(τ)=A·τ³+B·τ²+C·τ+D，官方 motion3 把它压成直线丢了曲率。我们保留曲率
  ⇒ 更忠实于游戏实际表现。且该压平**无法从源数据复现**：被压平段的多项式系数 A,B 非零，
  源包里没有任何标记说明它当初被导出成 Linear ⇒ 「官方对齐模式」不可实现，保留曲率是唯一有据选择。
  真正要盯的是 off_type1/our_type1：应 ≈1e-7（float32 往返噪声）量级。

用法:
  py -3 scripts/diag/l2d_motion_fidelity_audit.py
  py -3 scripts/diag/l2d_motion_fidelity_audit.py --ours .diag/meta/E --models ougen_8
  py -3 scripts/diag/l2d_motion_fidelity_audit.py --detail     # 打印漏掉的 Stepped / 偏的控制点

退出码：C1~C4 / C6 任一不达标 → 1
"""
import os
import sys
import json
import bisect
import argparse
import collections

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

DEFAULT_OFFICIAL = r'D:\Azur Lane Assets\Output\Live2D'
SEG_LEN = {0: 3, 1: 7, 2: 3, 3: 3}   # 类型码之后的数据长度

# 🔴 容差必须按「官方 JSON 的序列化精度」定，不能按「我方 float32 精度」定。
# 官方参考库的 motion3.json 实数只保留 1~3 位小数（实测 3 位占 84%、2 位 9%、1 位 7%），
# 时间/值都被截断到 ≤5e-4 量级误差；我方写的是 float32 全精度（如 1.9670000076293945）。
# 若把时间容差写成 1e-6，bisect 会把官方 1.967 落到我方 1.967 之前的那一段，产生成百条
# 「值错位 / Stepped 漏召」假警报（实测 ougen_8：686 条值错位 + 19 条漏召，全属此因）。
TIME_TOL = 2e-3        # 段起点对齐容差（覆盖官方 3 位小数截断 ≤5e-4）
VAL_TOL = 1e-3         # 关键帧值比对容差（同上，覆盖官方值截断）
JUMP_TOL = 1e-3        # Stepped 真跳变门限（|dv| 小于它视为与线性恒等）
CP_TOL = 5e-3          # 贝塞尔控制点命中容差
SAMPLES = 9            # 每段内部采样点数（不含端点）
DEV_BUCKET_CAP = 400000                # 单档采样数上限，超出抽稀（防跨模型聚合爆内存）

# 🔴 末点时间不能写死容差：官方把末点按 Meta.Duration 的写法截断（实测 Duration=6.02 时
# 末点也是 6.02，而我方 float32 给 6.017，差 3e-3 > TIME_TOL）。固定容差会把它判成「丢关键帧」
# （实测 aersasi_2 65 条 / aersasi_3 321 条假警报）。改为按官方末点的**有效小数位**推容差：
# 两倍末位单位，下限 TIME_TOL。
#   上限 END_TOL_MAX=2e-2 有 1 个数量级安全余量——实测官方参数曲线最小 dt = 0.016s。
END_TOL_MAX = 2e-2

# 🔴 C1 的「缺曲线」必须先看这条曲线是否**恒等**、以及运行时**求不求值它**。
# Cubism 运行时只对 Target=="Model" 且 Id ∈ {EyeBlink, LipSync} 的曲线做计算
# （vendor L1704-1730：`curves[c].id == this._modelCurveIdEyeBlink / _modelCurveIdLipSync`），
# 其余 Model 级曲线（Opacity/EyeBlinkScale 等）解析后直接丢弃。实测全库
# Model/Opacity 1033 条、Model/EyeBlink 179 条**全部恒 1.0**；唯一会变的是 Model/LipSync
# （1332 条里 1175 条可变），而生产 5 模型里 0 条 ⇒ 漏导它们零视觉影响。
RUNTIME_MODEL_IDS = ('EyeBlink', 'LipSync')

# 🔴 C6：段内形状必须按「固定时间栅格逐点求值」验，C1~C5 全 PASS 不代表形状对。
#   C2 只验关键帧（端点）、C3/C4 只验段类型与召回、C5 虽分层但用**段内归一化参数 u** 采样
#   （因为官方时间被截断，用绝对时间会造伪影）。归一化采样的问题是：段边界被刻意回避，
#   「段数不等」的曲线根本不会互相踩到 ⇒ 形状差异被结构性掩盖。C6 补的就是这一面。
C6_DT = 1.0 / 60.0     # 时间栅格步长（=60fps 帧长，运行时真实推进粒度）
C6_BOUND_EPS = 1e-5    # 剔除贴段边界采样点（float32 时间戳 vs 十进制序列化差 ~1e-7，
                       # 同一时刻在一侧落前段另一侧落后段，在阶梯段上直接造成满量程假偏差）
C6_EXACT_TOL = 1e-3    # 「两侧段类型相同时应恒等」的容差（覆盖官方控制点 3 位小数量化）
C6_SAMPLES_CAP = 200000000  # 全库采样点上限（防病态 clip 跑爆）；超限后退化为按整条曲线跳过并报数
#   ⚠️ 实测 5 模型全库 45523034 点，旧的 4e7 会在中段静默截断 ⇒ 后面的模型 C6 全成 n=0 假 PASS。
#      取 2e8 留 4 倍余量；若换更大的模型库仍撞上限，必须先报数再决定抬阈或分模型跑。


def parse_segments(seg):
    """Segments 数组 -> [(T, t0, v0, t1, v1, c1v, c2v), ...]；布局异常抛 ValueError。"""
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
            c1v = c2v = None
        out.append((T, t0, v0, t1, v1, c1v, c2v))
        t0, v0 = t1, v1
        i += L
    return out


class Curve(object):
    """按段起点时间建索引 + 二分定位（线性扫描在百万段规模上会退化）。"""

    def __init__(self, segs):
        self.segs = segs
        self.starts = [s[1] for s in segs]

    def at(self, t):
        segs = self.segs
        if not segs:
            return 0.0
        k = bisect.bisect_right(self.starts, t) - 1
        if k < 0:
            k = 0
        T, t0, v0, t1, v1, c1v, c2v = segs[k]
        dt = t1 - t0
        if dt <= 0:
            return v1
        u = (t - t0) / dt
        if u <= 0.0:
            return v0
        if u >= 1.0:
            return v1
        if T == 1:
            w = 1.0 - u
            return (w * w * w * v0 + 3.0 * u * w * w * c1v
                    + 3.0 * u * u * w * c2v + u * u * u * v1)
        if T == 2:
            return v0                     # Stepped：段内保持起点值
        if T == 3:
            return v1                     # InverseStepped：段内保持终点值（起点处硬翻）
        return v0 + (v1 - v0) * u


def load_dir(path):
    if not os.path.isdir(path):
        return {}
    return {fn: os.path.join(path, fn) for fn in sorted(os.listdir(path))
            if fn.endswith('.motion3.json')}


def resolve_model_dir(base, model):
    """官方库目录名可能是 motion/ 或 motions/。"""
    for sub in ('motion', 'motions'):
        d = os.path.join(base, model, sub)
        if os.path.isdir(d):
            return d
    return os.path.join(base, model, 'motion')


def new_acc():
    acc = collections.defaultdict(int)
    acc['dev'] = collections.defaultdict(list)
    acc['layout_error'] = []
    acc['cp_samples'] = []
    acc['step_miss'] = []
    acc['key_samples'] = []
    acc['id_missing_samples'] = []
    acc['id_missing_detail'] = []
    acc['dev_top'] = ''
    acc['dev_max'] = -1.0
    # C6：固定时间栅格逐点求值偏差（按「两侧段类型对」分层）
    acc['c6_dev'] = collections.defaultdict(list)
    acc['c6_runs'] = []          # [(maxdev, 标签)] 超阈曲线的样本
    acc['c6_same_max'] = -1.0    # 段类型相同档的最大偏差（理论上应 ≈ C6_EXACT_TOL 内）
    acc['c6_same_top'] = ''
    acc['c6_samples'] = 0
    return acc


def add_dev(acc, key, d, meta):
    bucket = acc['dev'][key]
    if len(bucket) < DEV_BUCKET_CAP:
        bucket.append(d)
    if d > acc['dev_max']:
        acc['dev_max'] = d
        if meta is not None:
            acc['dev_top'] = meta


def _near_bound(starts, t, eps):
    """t 是否贴着某个段边界（含段起点）。阶梯段上跨边界 1e-7 就是满量程偏差。"""
    i = bisect.bisect_left(starts, t)
    for k in (i - 1, i):
        if 0 <= k < len(starts) and abs(t - starts[k]) <= eps:
            return True
    return False


def c6_grid_compare(acc, fn, cid, ocurve, ncurve, dur):
    """C6：固定时间栅格逐点求值对照（官方 vs 我方）。

    与 C5 的区别是本判据**不回避段边界、也不按段配对**——它模拟运行时「给定时刻求值」
    的真实语义。于是「段数不等」的曲线在这里会真正互相踩到，形状差异无处可藏。

    判读分两类，绝不能混：
      · 同一时刻两侧段类型相同 → 求值语义相同 ⇒ 偏差必须 ≈0（只容得下官方 JSON 的
        3 位小数量化误差）。这一档是**硬判据**。
      · 同一时刻两侧段类型不同 → 偏差来自「段类型选择差异」，官方把 smoothstep 压成
        Linear（丢曲率）、或将短真斜坡压成 InverseStepped（抹平）。这一档**不计入
        PASS/FAIL**，但要逐曲线报出，交由 `l2d_bezier_quantization_audit.py`（量化伪影）
        与 `l2d_lendiff_classify.py`（以 Unity 原始多项式为真值裁定）定性。
    """
    osegs, nsegs = ocurve.segs, ncurve.segs
    if not osegs or not nsegs or dur <= 0:
        return
    o_starts, n_starts = ocurve.starts, ncurve.starts
    n_pt = int(dur / C6_DT)
    if n_pt <= 1:
        return
    if acc['c6_samples'] > C6_SAMPLES_CAP:
        return
    acc['c6_samples'] += n_pt

    max_same = -1.0
    max_cross = -1.0
    cross_pts = 0
    first_same = ''
    for i in range(n_pt + 1):
        t = i * C6_DT
        if t > dur:
            break
        if _near_bound(o_starts, t, C6_BOUND_EPS) or _near_bound(n_starts, t, C6_BOUND_EPS):
            continue                     # 段边界采样点剔除（见 C6_BOUND_EPS 注释）
        ko = bisect.bisect_right(o_starts, t) - 1
        kn = bisect.bisect_right(n_starts, t) - 1
        ko = 0 if ko < 0 else ko
        kn = 0 if kn < 0 else kn
        d = abs(ncurve.at(t) - ocurve.at(t))
        to, tn = osegs[ko][0], nsegs[kn][0]
        if to == tn:
            if d > max_same:
                max_same = d
                first_same = 't=%.4f type=%d off=%.6f our=%.6f' % (
                    t, to, ocurve.at(t), ncurve.at(t))
        else:
            cross_pts += 1
            if d > max_cross:
                max_cross = d
    if max_same >= 0.0:
        acc['c6_dev']['same'].append(max_same)
        if max_same > acc['c6_same_max']:
            acc['c6_same_max'] = max_same
            acc['c6_same_top'] = 'd=%.3e %s %s %s' % (max_same, fn, cid, first_same)
    if max_cross >= 0.0:
        acc['c6_dev']['cross'].append(max_cross)
        if len(acc['c6_runs']) < 3000:
            acc['c6_runs'].append((max_cross, cross_pts,
                                   '%s %s prev=%d' % (fn, cid, acc['segcount_diff'])))


def keyframes(segs):
    """Segments -> [(t, v)] 关键帧序列（段终点即关键帧）。"""
    return [(s[3], s[4]) for s in segs]


def _dec_places(x):
    """float 的「有效小数位数」。

    json.load 后 repr 给出的是最短往返表示，能把官方原始字面量的位数还原回来
    （22.72 → 2 位、6.283 → 3 位），所以不需要去读原始文本。
    """
    s = repr(abs(float(x)))
    if 'e' in s or 'E' in s:
        mant, exp = s.lower().split('e')
        exp = int(exp)
        d = len(mant.split('.')[1]) if '.' in mant else 0
        return max(0, d - exp)
    return len(s.split('.')[1]) if '.' in s else 0


def serialization_tol(x):
    """按官方某个时间值的写法推「末点对齐容差」。

    官方把曲线的末点钉在 `Meta.Duration` 上，而 Duration 的写法精度不固定（实测
    `22.72` / `6.02` / `16.083` / `6.283` 各是 2~3 位小数）。所以末点误差上限 = 该写法
    的末位单位，不是固定常数。
    """
    return min(END_TOL_MAX, max(TIME_TOL, 10.0 ** (-_dec_places(x))))


def is_const_curve(c):
    """该曲线是否**恒等**（整条只取同一个值）。"""
    try:
        segs = parse_segments(c.get('Segments') or [])
    except ValueError:
        return False
    seen = set()
    for T, t0, v0, t1, v1, c1v, c2v in segs:
        if T == 1:
            if abs(c1v - v0) > VAL_TOL or abs(c2v - v1) > VAL_TOL:
                return False
        seen.add(round(v0, 6))
        seen.add(round(v1, 6))
        if len(seen) > 1:
            return False
    return True


def missing_reason(curve, cid):
    """「官方有、我方缺」的曲线 → 豁免原因；返回 None 表示**真缺**。

    🔴 判据只能来自「运行时是否求值它」，不能来自「它是不是恒等」。
    Skill 里那条铁律：**定值曲线不是惰性的**——Cubism 只对本 clip 有曲线的参数施加权重，
    缺曲线的参数会停在上个动作留下的值上。所以一条恒等于 5.0 的 `Parameter/Xxx` 曲线
    恰恰是「把 Xxx 复位到 5.0」的指令，漏了它就复位不了。拿"恒等"当豁免依据会把这个
    bug 放过去（这正是 <2026-10-26 之前的口径漏洞）。

    唯一站得住的豁免是运行时**根本不看**这条曲线：
    vendor L1704-1730 里 `Target=="Model"` 只认 `EyeBlink` / `LipSync` 两个 Id，其余
    Model 级曲线（Opacity / EyeBlinkScale …）解析后直接丢弃。
    """
    if curve.get('Target') == 'Model' and cid not in RUNTIME_MODEL_IDS:
        return 'noeval'          # 运行时不求值
    return None                  # 其余一律真缺（含 Target=Parameter / PartOpacity 的定值曲线）



def align_kfs(oks, nks, tol, end_tol=None):
    """官方关键帧 → 我方关键帧的**保序子序列对齐**（返回 list[(oi, ni|None)] 覆盖全部官方键）。

    必须是贪心保序对齐，不能是「bisect 最近邻」：官方会做关键帧简化（把多个相邻键压成一段
    InverseStepped），此时官方键是我方键的**稀疏子集**，用最近邻会在密集区把 n 个官方键
    全吸到同一个我方键上，还会因截断误差落到前一段去。

    `end_tol`：官方**最后一个键**单独用的容差（见 serialization_tol，末点被钉在 Duration 上）。
    """
    out = []
    j = 0
    last = len(oks) - 1
    for oi, (t, v) in enumerate(oks):
        lim = end_tol if (oi == last and end_tol is not None) else tol
        best = None
        k = j
        while k < len(nks):
            dt = nks[k][0] - t
            if dt < -lim:            # 我方这个键在官方键之前，跳过
                k += 1
                continue
            if dt > lim:             # 已经越过官方键，没对上
                break
            best = k
            break
        if best is None:
            out.append((oi, None))
        else:
            out.append((oi, best))
            j = best + 1             # 保序：下一个官方键只能从我方后续键里找
    return out


def pair_segments(osr, nsr, tol, end_tol=None):
    """官方段 → 我方段 的保序对齐（按段起点+终点时间）。返回 list[(oi, ni|None)]。

    `end_tol`：官方**最后一段的终点**单独用的容差（末点被钉在 Meta.Duration 上，
    见 serialization_tol）。
    """
    out = []
    j = 0
    last = len(osr) - 1
    for oi, b in enumerate(osr):
        t0, t1 = b[1], b[3]
        lim = end_tol if (oi == last and end_tol is not None) else tol
        best = None
        k = j
        while k < len(nsr):
            a = nsr[k]
            if a[3] < t0 - tol:      # 我方这段整段在官方段起点之前
                k += 1
                continue
            if abs(a[1] - t0) <= tol and abs(a[3] - t1) <= lim:
                best = k
                break
            if a[1] > t0 + tol:      # 我方起点已越过，没对上
                break
            k += 1
        if best is None:
            out.append((oi, None))
        else:
            out.append((oi, best))
            j = best + 1
    return out


def compare_file(ours_p, off_p, acc, detail):
    fn = os.path.basename(off_p)
    nd = json.load(open(ours_p, encoding='utf-8'))
    od = json.load(open(off_p, encoding='utf-8'))
    oc = {c['Id']: c for c in od.get('Curves', [])}
    nc = {c['Id']: c for c in nd.get('Curves', [])}
    acc['files'] += 1
    acc['curves_ours'] += len(nc)
    acc['curves_off'] += len(oc)

    # C1 豁免：官方有、我方没有的曲线，先分类再决定算不算「缺」。
    #   a) Target=="Model" 且 Id 不在运行时求值名单里 ⇒ 运行时根本不看，计 id_missing_noeval
    #   b) 其余一律计入 id_missing —— **「恒等」不再是豁免依据**（见 missing_reason 注释）
    # 恒等与否只作为标注打出来，供人判断影响面，不参与 PASS/FAIL。
    for cid in sorted(set(oc) - set(nc)):
        c = oc[cid]
        tgt = c.get('Target')
        reason = missing_reason(c, cid)
        tag = '恒等' if is_const_curve(c) else '非常量'
        if reason == 'noeval':
            acc['id_missing_noeval'] += 1
            if detail and len(acc['id_missing_samples']) < 12:
                acc['id_missing_samples'].append(
                    '%s %s [运行时不求值/%s] Target=Model Segments=%s'
                    % (fn, cid, tag, json.dumps(c.get('Segments'))[:90]))
        else:
            acc['id_missing'] += 1
            if len(acc['id_missing_detail']) < 20:
                acc['id_missing_detail'].append(
                    '%s %s Target=%r %s Segments=%s'
                    % (fn, cid, tgt, tag, json.dumps(c.get('Segments'))[:110]))
            if detail and len(acc['id_missing_samples']) < 12:
                acc['id_missing_samples'].append(
                    '%s %s [真缺/%s] Target=%r Segments=%s'
                    % (fn, cid, tag, tgt, json.dumps(c.get('Segments'))[:90]))
    acc['id_extra'] += len(set(nc) - set(oc))

    # 末点容差按官方 Meta.Duration 的写法定（见 serialization_tol）
    end_tol = serialization_tol(od.get('Meta', {}).get('Duration') or 0.0)
    dur = float(od.get('Meta', {}).get('Duration') or 0.0)
    if dur <= 0.0:
        for _c in od.get('Curves', []):
            _s = _c.get('Segments') or []
            if len(_s) > 2 and float(_s[-2]) > dur:
                dur = float(_s[-2])

    for cid in sorted(set(oc) & set(nc)):
        try:
            osr = parse_segments(oc[cid]['Segments'])
            nsr = parse_segments(nc[cid]['Segments'])
        except ValueError as e:
            acc['layout_error'].append('%s %s: %s' % (fn, cid, e))
            continue
        acc['segs_off'] += len(osr)
        acc['segs_ours'] += len(nsr)

        # C2：官方关键帧必须 ⊆ 我方关键帧（贪心保序子序列对齐，见 align_kfs 注释）
        oks, nks = keyframes(osr), keyframes(nsr)
        pairs = align_kfs(oks, nks, TIME_TOL, end_tol)
        for oi, ni in pairs:
            t, v = oks[oi]
            if ni is None:
                acc['key_missing'] += 1
                if detail and len(acc['key_samples']) < 10:
                    acc['key_samples'].append(
                        '%s %s 丢关键帧 t=%.6f v=%.4f' % (fn, cid, t, v))
            elif abs(nks[ni][1] - v) > VAL_TOL:
                acc['key_value_bad'] += 1
                if detail and len(acc['key_samples']) < 10:
                    acc['key_samples'].append(
                        '%s %s 值错位 t=%.6f 官方=%.4f 我方=%.4f'
                        % (fn, cid, t, v, nks[ni][1]))
        extra = len(nks) - sum(1 for _o, ni in pairs if ni is not None)
        if extra > 0:
            acc['key_ours_extra'] += extra
        if len(osr) != len(nsr):
            acc['segcount_diff'] += 1
        if not nsr or not osr:
            continue

        # 段级判据：官方段 i ↔ 我方段 j（保序对齐，起点+终点都对上）
        spairs = pair_segments(osr, nsr, TIME_TOL, end_tol)
        for oi, ni in spairs:
            oT, t0, v0, t1, v1, oc1, oc2 = osr[oi]
            dt = t1 - t0
            if oT == 3:
                acc['off_invstep'] += 1
            if ni is None:
                if oT == 1:
                    acc['cp_unpaired'] += 1
                if oT == 2 and dt > 0 and abs(v1 - v0) > JUMP_TOL:
                    acc['step_real'] += 1
                continue
            a = nsr[ni]
            nT = a[0]

            if oT == 1:
                acc['off_bezier'] += 1
                if nT != 1:
                    acc['cp_linear_equiv'] += 1
                else:
                    ok1 = abs(a[5] - oc1) <= CP_TOL
                    ok2 = abs(a[6] - oc2) <= CP_TOL
                    acc['cp_c1_hit' if ok1 else 'cp_c1_miss'] += 1
                    acc['cp_c2_hit' if ok2 else 'cp_c2_miss'] += 1
                    if not (ok1 and ok2) and detail and len(acc['cp_samples']) < 10:
                        acc['cp_samples'].append(
                            '%s %s c1 %.5f/%.5f c2 %.5f/%.5f'
                            % (fn, cid, a[5], oc1, a[6], oc2))

            # C4：官方 Stepped 只有 |dv| > JUMP_TOL 才是真跳变，dv==0 与线性恒等不计入分母
            dv_real = oT == 2 and dt > 0 and abs(v1 - v0) > JUMP_TOL
            if dv_real:
                acc['step_real'] += 1
                if nT == 2:
                    acc['step_hit'] += 1
                elif detail and len(acc['step_miss']) < 10:
                    acc['step_miss'].append(
                        '%s %s t0=%.3f dt=%.4f v0=%.3f v1=%.3f ours_type=%d'
                        % (fn, cid, t0, dt, v0, v1, nT))
            if nT == 2 and not dv_real:
                acc['step_false_pos'] += 1

            # C5：几何偏差分层。必须按**段内归一化参数 u** 采样，不能用绝对时间：
            # 官方时间被截断到 3 位小数（≤5e-4），按绝对时间采样会把这点截断放大成假偏差
            # （实测 off_type0/our_type0 被这一点污染出 max 4.94）。
            if dt <= 0:
                continue
            ndt = a[3] - a[1]
            if ndt <= 0:
                continue
            where = '%s %s off_type=%d our_type=%d t0=%.4f dt=%.4f v0=%.3f v1=%.3f' % (
                fn, cid, oT, nT, t0, dt, v0, v1)
            ocurve, ncurve = Curve([osr[oi]]), Curve([a])
            for i in range(1, SAMPLES + 1):
                u = i / (SAMPLES + 1.0)
                d = abs(ncurve.at(a[1] + ndt * u) - ocurve.at(t0 + dt * u))
                _push(acc, (oT, nT), d, detail, where)

        # C6：固定时间栅格逐点求值。必须在**整条曲线**上做（不是逐段配对），
        # 这是唯一能暴露「段数不等/段边界错位」形状差异的口径。
        c6_grid_compare(acc, fn, cid, Curve(osr), Curve(nsr), dur)


def _push(acc, key, d, detail, where):
    bucket = acc['dev'][key]
    if len(bucket) < DEV_BUCKET_CAP:
        bucket.append(d)
    if d > acc['dev_max']:
        acc['dev_max'] = d
        if detail:
            acc['dev_top'] = 'd=%.3f %s' % (d, where)

def pct(a, b):
    return 'n/a' if b == 0 else '%.2f%% (%d/%d)' % (100.0 * a / b, a, b)


def report(model, acc):
    print('-' * 78)
    print('模型 %s | 比对 clip %d | 官方 curve %d / 我方 curve %d'
          % (model, acc['files'], acc['curves_off'], acc['curves_ours']))
    ok = True

    # 曲线数判据：豁免只有一种 —— 运行时根本不求值的 Model 级曲线。
    # 「恒等」不是豁免依据（定值曲线正是切动作时的复位指令，见 missing_reason 注释）。
    c1 = (acc['curves_ours'] == acc['curves_off'] - acc['id_missing_noeval']
          and acc['id_missing'] == 0 and acc['id_extra'] == 0)
    print('  C1 曲线数一致         : %s  (真缺 %d / 多 %d)'
          % ('PASS' if c1 else 'FAIL', acc['id_missing'], acc['id_extra']))
    print('     [INFO] 唯一豁免：运行时求值名单外的 Model 曲线 %d 条'
          '（vendor 只认 EyeBlink/LipSync）' % acc['id_missing_noeval'])
    if acc['id_missing']:
        for line in acc['id_missing_detail']:
            print('     [缺] ' + line)
    print('     [INFO] 段数不同的曲线 %d 条，我方多出关键帧 %d 个（官方简化，无害）'
          % (acc['segcount_diff'], acc['key_ours_extra']))
    ok = ok and c1

    c2 = acc['key_missing'] == 0 and acc['key_value_bad'] == 0 and not acc['layout_error']
    print('  C2 关键帧包含         : %s  (官方键缺失 %d / 值错位 %d / 布局异常 %d)'
          % ('PASS' if c2 else 'FAIL', acc['key_missing'], acc['key_value_bad'],
             len(acc['layout_error'])))
    ok = ok and c2

    den = acc['cp_c1_hit'] + acc['cp_c1_miss']
    c3 = acc['cp_c1_miss'] == 0 and acc['cp_c2_miss'] == 0
    print('  C3 Bezier 控制点      : %s  c1 %s | c2 %s'
          % ('PASS' if c3 else 'FAIL', pct(acc['cp_c1_hit'], den),
             pct(acc['cp_c2_hit'], den)))
    print('     [INFO] 官方发 Bezier 而我方发 Linear 的段 %d 条 —— 源多项式 A=B=0 时两种写法'
          '几何等价（C5 该档偏差 max 见下），非缺陷' % acc['cp_linear_equiv'])
    ok = ok and c3

    c4 = acc['step_hit'] == acc['step_real'] and acc['step_false_pos'] == 0
    print('  C4 Stepped 召回(dv≠0) : %s  %s | 多报 %d | 官方 InverseStepped(type3) 段 %d 条'
          % ('PASS' if c4 else 'FAIL', pct(acc['step_hit'], acc['step_real']),
             acc['step_false_pos'], acc['off_invstep']))
    ok = ok and c4

    print('  C5 几何偏差（off_type/our_type 分层，unit=参数值）:')
    for key in sorted(acc['dev']):
        arr = sorted(acc['dev'][key])
        n = len(arr)
        if not n:
            continue
        note = ''
        if key == (0, 1):
            note = '  <- 官方压平成 Linear 丢曲率，非本方 bug'
        elif key == (1, 1):
            note = '  <- 必须 ≈1e-7（float32 噪声）'
        print('     off_type%d/our_type%d  n=%8d 中位=%.3e p99=%.5f max=%.5f%s'
              % (key[0], key[1], n, arr[n // 2], arr[int(n * 0.99)], arr[-1], note))
    print('  C6 固定时间栅格求值偏差（dt=%.6fs，剔除段边界采样点）:' % C6_DT)
    same = sorted(acc['c6_dev']['same'])
    cross = sorted(acc['c6_dev']['cross'])
    c6 = acc['c6_same_max'] <= C6_EXACT_TOL
    print('     同一时刻两侧段类型相同 : %s  n=%d 中位=%.3e max=%.3e (阈值 %.0e)'
          % ('PASS' if c6 else 'FAIL', len(same),
             (same[len(same) // 2] if same else 0.0), acc['c6_same_max'], C6_EXACT_TOL))
    if not c6 or acc['c6_same_top']:
        print('        [max] ' + acc['c6_same_top'])
    print('     同一时刻两侧段类型不同 : n=%d 中位=%.3e max=%.5f  <- 段类型选择差异，'
          '由 l2d_bezier_quantization_audit / l2d_lendiff_classify 定性，不计 PASS/FAIL'
          % (len(cross), (cross[len(cross) // 2] if cross else 0.0),
             (cross[-1] if cross else 0.0)))
    if acc['c6_runs']:
        tops = sorted(acc['c6_runs'], reverse=True)[:8]
        for d, npt, where in tops:
            print('        [跨类型 max=%.5f pts=%d] %s' % (d, npt, where))
    print('     [INFO] 采样点总数 %d' % acc['c6_samples'])
    ok = ok and c6
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ours', default=os.path.join('.diag', 'meta', 'E'))
    ap.add_argument('--official', default=DEFAULT_OFFICIAL)
    ap.add_argument('--models', default='')
    ap.add_argument('--detail', action='store_true')
    args = ap.parse_args()

    ours = args.ours if os.path.isabs(args.ours) else os.path.abspath(
        os.path.join(ROOT, args.ours))
    # 相对路径按**仓库根**解析（不是 CWD）——写错会得到 `D:\Output\Live2D` 这种目录，
    # 报 os.listdir 的 FileNotFoundError 时看不出是路径口径问题，所以先显式判存在。
    if not os.path.isdir(ours):
        ap.error('--ours 目录不存在: %s（相对路径按仓库根 %s 解析，不是当前目录）'
                 % (ours, ROOT))
    off_base = args.official
    if args.models:
        models = [m.strip() for m in args.models.split(',') if m.strip()]
    else:
        models = sorted(m for m in os.listdir(ours) if os.path.isdir(os.path.join(ours, m)))

    print('ours=%s\nofficial=%s\nmodels=%s\n' % (ours, off_base, ','.join(models)))

    all_ok, ran = True, 0
    total = new_acc()
    for m in models:
        nd = load_dir(resolve_model_dir(ours, m))
        od = load_dir(resolve_model_dir(off_base, m))
        if not od:
            print('模型 %s: 官方库缺失，跳过' % m)
            continue
        if not nd:
            print('模型 %s: 我方产物缺失，跳过' % m)
            continue
        ran += 1
        acc = new_acc()
        for fn in sorted(set(nd) & set(od)):
            compare_file(nd[fn], od[fn], acc, args.detail)
        if args.detail:
            for s in acc['id_missing_samples']:
                print('     [缺曲线] ' + s)
            for s in acc['step_miss']:
                print('     [Stepped 漏] ' + s)
            for s in acc['cp_samples']:
                print('     [控制点偏] ' + s)
        all_ok = report(m, acc) and all_ok
        for k, v in acc.items():
            if isinstance(v, int):
                total[k] += v
        for key, arr in acc['dev'].items():
            total['dev'][key].extend(arr)
        # C6 的分布与极值也必须聚合，否则 ALL 行永远是 `n=0 / max=-1`（假 PASS）。
        for key, arr in acc['c6_dev'].items():
            total['c6_dev'][key].extend(arr)
        if acc['c6_same_max'] > total['c6_same_max']:
            total['c6_same_max'] = acc['c6_same_max']
            total['c6_same_top'] = '%s <- %s' % (m, acc['c6_same_top'])
        if len(total['c6_runs']) < 3000:
            total['c6_runs'].extend(acc['c6_runs'][:3000 - len(total['c6_runs'])])

    print('=' * 78)
    if ran > 1:
        print('【跨模型聚合 VIEW】仅供参考 —— 各模型数字必须分开看，聚合会掩盖单模型失败')
        report('ALL', total)
    print('【结论】%s  (已比对模型数 %d)' % ('PASS' if all_ok else 'FAIL', ran))
    if not all_ok:
        print('提示：C5 的 off_type0/our_type1 偏差来自「官方导出器丢曲率」，见文件头注释。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
