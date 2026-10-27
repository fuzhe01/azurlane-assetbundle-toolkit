#!/usr/bin/env python3
"""
extract_motions.py - 从 Unity AnimationClip 提取真实动作数据到 motion3.json

权威映射（2026-09-21 重新逆向确定，见 docs/TROUBLESHOOTING.md §17）:
    m_StreamedClip 的 curve index 与 AnimationClip.m_ClipBindingConstant.genericBindings
    **同序**；genericBindings[i].path = crc32("<前缀>/<GameObject 名>")，
    前缀 Parameters/ → Target=Parameter，Parts/ → Target=PartOpacity（部件可见性=官方换装拼接逻辑）。
    CubismParameter 组件的 m_Name 为空，真名挂在 GameObject 上；_unmanagedIndex 是 moc3 参数序号。

历史教训（本文件旧实现的两处致命错误）:
    1. 护栏 `num_keys > 100` 误杀帧 0。帧 0 是 time=-3.4e38 的“参考姿态帧”，一帧合法写完
       全部曲线（碧蓝大模型 200~800 参数 → 一帧 380~520 个 key），于是整条 clip 被判无数据，
       调用方静默保留 reconstruct 生成的 "Curves":[] 空壳 → 5037/8154 clip 是空壳。
    2. 用 env.objects 顺序 + 组件 m_Name 当参数名（实际为空）→ 回落成假 ID `Param_N`；
       旧产物另有一版按「curve idx == moc3 参数序号（从 0 连续）」取名，实测 0/8154 clip 满足
       dense 前提 → 3117 个“非空壳”文件的曲线名**全部错位**（眼睛数据写进眉毛参数等）。

用法:
    py -3 scripts/extract_motions.py --test lingbo          # 单模型（打印每条 clip 结果）
    py -3 scripts/extract_motions.py --all                  # 全量（写入 Output/Live2D）
    L2D_OUT_DIR=<目录> ... --all                             # 全量写到临时目录，不动正式产物
    L2D_MOTION_LINEAR=1 ...                                 # 强制线性插值（关闭贝塞尔）

退出码: 0 全部成功；1 存在“解出 0 条曲线”的 clip（绝不静默）。
"""

import os
import sys
import json
import struct
import binascii
import argparse
from datetime import datetime
import sys as _p_sys, os as _p_os
_p_sys.path.insert(0, _p_os.path.dirname(_p_os.path.abspath(__file__)))
import paths as P  # 仓库根与外部工具位置：见 scripts/paths.py（AL_ASSETS_ROOT 可覆盖）

try:
    import UnityPy
    from UnityPy import config
    config.FALLBACK_UNITY_VERSION = "2022.3.62f3"
except ImportError:
    print("[ERROR] 需要安装 UnityPy: pip install UnityPy")
    sys.exit(2)

LIVE2D_DIR = P.LIVE2D_SRC
OUTPUT_DIR = os.environ.get("L2D_OUT_DIR") or P.LIVE2D_OUT
ERROR_LOG = P.ERRORS_LOG

# 默认启用线性插值（关键帧 + 线性），**已验收的正确配方**——消灭贝塞尔，杜绝肢体乱摆。
#   ⚠️ 历史根因（2026-09-23 定性、2026-10 由 aersasi_2/3 对照实锤）：旧默认把贝塞尔控制点写成
#      归一化分数 (1/3,2/3)，Cubism Web 运行时按**绝对 (时间,值)** 直读 → 每条贝塞尔先猛蹿到
#      0.6/0.8 再跳回目标 → 肢体乱摆（用户报的"像刚学建模的人做的"）。
#   ⚠️ 原默认保持归一化贝塞尔是为了"既有产物逐字节不变"，但那产物本身就是乱摆的坏产物，已作废。
#   显式关闭方式：L2D_MOTION_LINEAR=0（且未开 ABSOLUTE_CP 时，统一退化为绝对贝塞尔）。
USE_LINEAR = os.environ.get("L2D_MOTION_LINEAR", "1") not in ("0", "false", "False")
# 贝塞尔控制点裁剪阈值（历史护栏）：仅在显式关闭线性后仍对贝塞尔幅度 >3 的段退回线性。
#   注意：它过去是"掩盖归一化分数格式错误"的补丁，如今默认线性不用它；保留只为显式实验时代护栏。
BEZIER_CLIP = float(os.environ.get("L2D_MOTION_BEZIER_CLIP", "3.0"))
# ⚠️ 兼容说明：ABSOLUTE_CP=1 曾用于"Cubism 规范绝对 (时间,值) 控制点"的实验开关，但实测未过已被
#   权威基准验收（安土 88/278 偏差>0.5，Unity 密集键切线本就不该当 Hermite 切线用）。
#   现在的无条件规则：**只要没走 USE_LINEAR，贝塞尔一律按绝对 (时间,值) 控制点写**（见下方生成段），
#   绝不再产生归一化分数。故本开关保留仅为向后兼容、无损语义（真值都由下方生成逻辑统一处理）。
ABSOLUTE_CP = bool(os.environ.get("L2D_MOTION_ABSOLUTE_CP"))
# 是否把 m_ConstantClip 里的「整段定值」曲线也导出（参考版 idle 曲线数 278 = 98 动画 + 180 定值）。
# 作用：切动作时这些参数会被显式拉回该 clip 的定值，而不是停在上一个动作留下的值上。
EMIT_CONST = bool(os.environ.get("L2D_MOTION_EMIT_CONST"))
# 段类型还原（2026-10-24 判据定稿）：把真阶梯写成 Cubism type=2、真直线写成 type=0，
# 其余**一律 Bezier**（含官方原本写成 Linear 的 smoothstep 段——贝塞尔表达与之逐点等价）。
#   判据（相对容差，见下方 SEG_TOL）：用段内三次多项式系数 A/B/C 判「段内有无变化」，
#   **不能用 `== 0.0`** —— 切线由大数相消算得，浮点消去误差使「理论为 0」的段只有 4.78%
#   精确等于 0.0。
#   实测 5 模型 817984 段：官方 Stepped 真跳变段召回 **4420/4420 = 100%**、多报 0；
#   与官方段类型名义一致率 70.03%，其中「官方 Linear → 我们 Bezier」354429 段是**几何等价**
#   的同一曲线（官方 Linear 段 99.94% 精确等于 smoothstep 多项式，其贝塞尔即 c1=v0,c2=v1）。
# 为什么必须还原 Stepped：LINEAR 把 Param31 这类**多档位开关**的硬翻压成 3.58 秒缓降，
#   全程落在 (0,1) 死带 → 18 件 ArtMesh 整段不画（用户报的「左脚/右手掌消失」）。
SEGTYPE = os.environ.get("L2D_MOTION_SEGTYPE", "0") not in ("0", "false", "False")
# 贝塞尔还原（2026-10-24 公式定稿，对起点键系数 100.00% 精确）：
#   **系数挂在段起点键上**（τ = t − 起点时间）：
#       m0 = C、m1 = 3A·dt² + 2B·dt + C ⇒ c1y = v0 + m0·dt/3、c2y = v1 − m1·dt/3
#   实测 ougen_8 243474 段 / 官方 168168 段贝塞尔：起点键口径 c1、c2 **双 100.00%**；
#   参考姿态帧带 4 个 0.0 正是因为「它没有下一段」。
#   ❌ 已证伪的两种口径（勿再采用）：
#      · 终点键系数：c1 74.15% / c2 74.64%，几何偏差最高 2e10
#      · c2y = v1 − C(终点键)·dt/3：91.32%
BEZIER = os.environ.get("L2D_MOTION_BEZIER", "0") not in ("0", "false", "False")
# 段类型判据的相对容差：scale 取该段各系数的量纲归一化最大值，系数贡献低于 SEG_TOL
# 即视为「该阶无变化」。1e-6 对应 float32 的有效精度下限（float32 eps ≈ 1.19e-7）。
SEG_TOL = float(os.environ.get("L2D_MOTION_SEG_TOL", "1e-6"))

PARAM_PREFIX = "Parameters/"
PART_PREFIX = "Parts/"

# Unity 参考姿态帧的时间是 -FLT_MAX（约 -3.4e38），不是真实时间
REF_POSE_EPS = 1e30


def log_warn(name, msg):
    try:
        os.makedirs(os.path.dirname(ERROR_LOG), exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] [MOTION] {name}: {msg}\n")
    except Exception:
        pass


def _crc(s):
    return binascii.crc32(s.encode("utf-8")) & 0xFFFFFFFF


# ============================================================
# genericBindings → 权威目标表
# ============================================================

def build_binding_targets(clip, go_names_by_pathid):
    """返回 [(Target, Id), ...]，下标即 m_StreamedClip 的 curve index。

    解析不到的绑定返回 (None, None) 并计数——这类目标（实测为某第三类属性哈希，
    疑 Drawable 颜色/透明度）Cubism Web 运行时无对应 motion target，跳过并记录。
    """
    targets = []
    unresolved = 0
    bc = getattr(clip, "m_ClipBindingConstant", None)
    gb = list(getattr(bc, "genericBindings", None) or []) if bc else []
    for b in gb:
        ph = getattr(b, "path", 0) & 0xFFFFFFFF
        nm = go_names_by_pathid.get(ph)
        if nm:
            targets.append(nm)
        else:
            targets.append(None)
            unresolved += 1
    return targets, unresolved


def collect_go_name_hashes(env):
    """GameObject 名 → 两种前缀的 crc32 路径哈希 → (Target, Id)。

    只认真的挂了 CubismParameter / CubismPart 组件的对象，避免与同名 Drawable/Transform 混淆。
    """
    go_pathid_to_name = {}
    for obj in env.objects:
        if obj.type.name == "GameObject":
            try:
                go_pathid_to_name[obj.path_id] = obj.read().m_Name
            except Exception:
                pass

    comp_go = {"CubismParameter": set(), "CubismPart": set()}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        sr = getattr(data, "m_Script", None)
        if not sr:
            continue
        try:
            sname = getattr(sr.read(), "m_Name", "")
        except Exception:
            continue
        if sname not in comp_go:
            continue
        try:
            tt = obj.read_typetree()
        except Exception:
            continue
        goid = tt.get("m_GameObject", {}).get("m_PathID")
        nm = go_pathid_to_name.get(goid)
        if nm:
            comp_go[sname].add(nm)

    lookup = {}
    for nm in comp_go["CubismParameter"]:
        lookup[_crc(PARAM_PREFIX + nm)] = ("Parameter", nm)
    for nm in comp_go["CubismPart"]:
        lookup[_crc(PART_PREFIX + nm)] = ("PartOpacity", nm)
    return lookup


# ============================================================
# StreamedClip 解析（无护栏版）
# ============================================================

def parse_streamed_clip(streamed_clip):
    """解 m_StreamedClip.data → 帧列表 [(time, [(idx, A, B, C, D), ...]), ...]。

    帧格式: time(f32) + numKeys(i32) + numKeys × [index(i32) + 4×f32]
    终止符: time = +inf。缓冲区越界即停，**不设 numKeys 上限**。

    ⚠️ 4 个 float 是**段内三次多项式系数**，不是「噪声/切线/值」：
        v(τ) = A·τ³ + B·τ² + C·τ + D      （τ = t − 段起点时间，单位秒）
        D = 段起点键的值（= 该关键帧的值）
        C = 段起点的切线（值/秒）⇒ 出侧控制点 c1y = D + C·dt/3，**由定义恒等，非拟合**
        A · B = 曲率项，段终点切线 m1 = 3A·dt² + 2B·dt + C

    自证：poly(dt) 与官方终点值比对 813565/817984 = 99.46%（残余 4419 段全是官方
    Stepped 段——它们把终点值写成跳变后值，而多项式保持起点值，这是 Stepped 的定义）。

    ❌ 已被证伪的旧结论（2026-10 一度写进本 docstring，勿再采用）：
       - 「f1/f2 是巨值噪声，不可当切线用」——完全错误。A/B 量级巨大（例
         A=-112386.3984、B=19723.8301）是 dv/dt³ 在小 dt 下的**量纲放大**，不是脏数据。
       - 「f3 是唯一真切线字段，入侧取终点键 f3」——终点键的 C 是**下一段**的起点切线，
         不是本段入切线；旧公式 c2y = v1 − f3(end)·dt/3 最差偏差 39248（现为 0.003）。
    """
    data = getattr(streamed_clip, "data", None) or []
    if not data:
        return []
    buf = b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in data)

    frames = []
    pos = 0
    while pos + 8 <= len(buf):
        t = struct.unpack_from("<f", buf, pos)[0]
        pos += 4
        if t == float("inf"):
            break
        n = struct.unpack_from("<i", buf, pos)[0]
        pos += 4
        if n < 0 or pos + n * 20 > len(buf):
            break
        keys = []
        for _ in range(n):
            idx = struct.unpack_from("<i", buf, pos)[0]
            A, B, C, D = struct.unpack_from("<4f", buf, pos + 4)
            pos += 20
            keys.append((idx, A, B, C, D))  # (curve_index, A, B, C, D) 段内三次多项式系数
        frames.append((t, keys))
    return frames


def build_motion(clip, targets, verbose=False, const_info=None):
    """AnimationClip → motion3.json dict；解不出任何曲线返回 None（调用方必须报错）。

    const_info = (起始下标, 定值列表)：m_ConstantClip 里的「整段保持定值」曲线。
    参考实现（l2d.su 权威导出）把它们一并写入 motion3.json —— 它们不是惰性的：
    切动作时 Cubism 只对「本 clip 有曲线的」参数施加权重，缺曲线就**停在上一个
    动作留下的值上**，于是被 touch_* 动过的手臂等参数回不到静止位 → 部件互相错位。
    """
    muscle = getattr(clip, "m_MuscleClip", None)
    if not muscle or not getattr(muscle, "m_Clip", None):
        return None
    cdata = muscle.m_Clip.data
    streamed = getattr(cdata, "m_StreamedClip", None)
    frames = parse_streamed_clip(streamed) if streamed else []
    if not frames:
        return None

    base = {}     # curve idx -> 参考姿态值（帧 time=-FLT_MAX）
    series = {}   # curve idx -> [(t, A, B, C, D), ...]
    for t, keys in frames:
        if t < -REF_POSE_EPS:
            for idx, _A, _B, _C, v in keys:
                base.setdefault(idx, v)
            continue
        tt = 0.0 if abs(t) < 1e-6 else t
        for idx, A, B, C, v in keys:
            series.setdefault(idx, []).append((tt, A, B, C, v))

    curves = []
    total_seg = total_pts = total_bezier = total_step = 0
    for idx in sorted(series.keys()):
        tgt = targets[idx] if idx < len(targets) else None
        if tgt is None:
            continue
        target, pid = tgt
        pts = sorted(series[idx], key=lambda x: x[0])
        if not pts:
            continue

        # 参考姿态值作为 t=0 起点（若真实关键帧未覆盖 t=0）
        # ⚠️ 这支合成键没有多项式系数，一律填 NaN 并在下面**显式按线性段处理**：
        #    NaN 参与任何比较都为 False，若靠判据自然落空会流到贝塞尔分支，把 NaN 当切线
        #    写进控制点 → json 里出现非法 `NaN` 字面量，浏览器 JSON.parse 直接抛错。
        synth_first = False
        if pts[0][0] > 1e-6 and idx in base:
            v0 = base[idx]
            nan = float("nan")
            pts.insert(0, (0.0, nan, nan, nan, v0))
            synth_first = True

        segs = []
        n_pts = 1          # 曲线首对 (time,value) 也占一个 point 槽
        for i, (t, E, _x, _y, D) in enumerate(pts):
            if i == 0:
                segs.extend([t, D])
                continue
            t0 = pts[i - 1][0]
            dt = t - t0
            if dt <= 1e-6:
                continue
            if synth_first and i == 1:
                # 参考姿态 → 首个真实关键帧：没有多项式系数可用，只能按线性插。
                segs.extend([0, t, D])
                total_seg += 1
                n_pts += 1
                continue
            # ⚠️⚠️ 多项式系数挂在**段起点键**上，不是终点键。实测（ougen_8 243474 段、
            #    官方 168168 段贝塞尔可对齐）：
            #      起点键系数在 τ=dt 处求值 == 终点值 v1 → 99.98%
            #      c1 = v0 + C(起点)·dt/3            → 100.00%
            #      c2 = v1 − m1(起点)·dt/3           → 100.00%
            #    误用终点键系数则 c1 74.15% / c2 74.64%，几何偏差最高报到 2e10。
            #    这也解释了参考姿态帧为什么带 4 个 0.0——它没有「后一段」。
            A, B, C = pts[i - 1][1], pts[i - 1][2], pts[i - 1][3]
            v0 = pts[i - 1][4]
            v1 = D
            dv = v1 - v0
            # ---- 段类型判定（2026-10 定稿：只降级「真常量/真阶梯/真直线」，其余一律贝塞尔）----
            # 判据全部来自「官方 motion3.json ⇄ StreamedClip 多项式系数」同一段的逐段对照
            # （5 模型 817984 段）：
            #   ① A·dt³、B·dt²、C 三者皆为 0（相对容差）→ 段内无变化
            #        · dv!=0 → Stepped（官方 type=2 的真跳变段 **4420/4420 = 100% 命中**，0 多报）
            #        · dv==0 → Linear （整段定值，两者值恒等）
            #   ② 只剩曲率项为 0（A=B=0，C!=0）→ 真直线 → Linear
            #   ③ 其余一律 → **Bezier**，两个控制点由多项式精确给出
            #
            # ⚠️ 为什么不再输出「官方那样」的 Linear：官方导出器遇到两端切线都为 0 的段会写
            #    Linear 并**丢掉曲率**（官方 Linear 段 99.94% 精确等于 smoothstep 多项式
            #    A=-2dv/dt³ / B=3dv/dt² / C=0）。这种段用贝塞尔表达即 c1=v0、c2=v1，
            #    曲线**逐点等价**，零信息损失；而按官方口径判 Linear 反而在「官方 Linear 与
            #    我们 Bezier」之间引入 354429 段的类型噪声，且实测几何最大偏差 12.845。
            #    本方案实测几何偏差中位 1.5e-07 / p99 1.2e-05 / max 0.0033（float32 读数量级）。
            #
            # ⚠️ 容差判据是必须的，不能用 `== 0.0`：m1 = 3A·dt²+2B·dt+C 由大数相消得出，
            #    浮点消去误差使「理论为 0」的段实测只有 4.78% 精确等于 0.0。
            scale = max(abs(dv) / dt, abs(A) * dt * dt, abs(B) * dt, abs(C), 1e-6)
            const_A = abs(A) * dt ** 3 <= SEG_TOL * scale
            const_B = abs(B) * dt * dt <= SEG_TOL * scale
            const_C = abs(C) <= SEG_TOL * scale
            if SEGTYPE and const_A and const_B and const_C:
                if abs(dv) > SEG_TOL * scale * dt:
                    segs.extend([2, t, v1])   # 阶梯：值在本段保持 v0，到 t 瞬间跳到 v1
                    total_seg += 1
                    total_step += 1
                    n_pts += 1
                    continue
                segs.extend([0, t, v1])       # 整段定值：线性与阶梯值恒等，取线性
                total_seg += 1
                n_pts += 1
                continue
            if USE_LINEAR and not BEZIER:
                segs.extend([0, t, v1])
                total_seg += 1
                n_pts += 1
                continue
            if const_A and const_B:
                segs.extend([0, t, v1])       # 真直线：贝塞尔退化即直线，写线性省体积
                total_seg += 1
                n_pts += 1
                continue
            # Unity 三次多项式系数 → Cubism **绝对 (时间,值)** 贝塞尔控制点。
            # ⚠️ 官方段序（实测校验运行时 pixi-live2d-display 的解析器）：
            #    [type=1, 控制点1x, 控制点1y, 控制点2x, 控制点2y, 终点time, 终点value]
            #    运行时按 points[base+1..base+3] = (c1, c2, dest) 取 3 个点对、l+=7，
            #    并用 basePointIndex+3 定位下一段起点 → 终点必须在**最后**。
            #    多插一个"interpolation=0"或把终点写前面，都会整体错位并撑爆按
            #    TotalSegmentCount 预分配的 segments 数组（报 basePointIndex undefined）。
            # ⚠️⚠️ 段格式（2026-09-23 用权威导出反查 + 运行时解析器源码双重证实）：
            #    Cubism motion3.json 的贝塞尔控制点是**绝对 (时间, 值)**，运行时直读、
            #    不做任何归一化还原。旧实现写归一化分数（0.333/by1/0.667/by2）→ 控制点
            #    被当成「t=0.333 秒、值=0.667」，落在段外 → 每条贝塞尔先猛蹿到 0 再跳回
            #    目标值 → 部件乱摆（用户报的「像刚学建模的人做的」）。
            # 正确写法 = 段内三次多项式的精确等价控制多边形（2026-10 定稿，替代旧 Hermite）：
            #        出切线 m0 = C
            #        入切线 m1 = 3A·dt² + 2B·dt + C
            #        c1 = (t0 + dt/3, v0 + m0·dt/3)
            #        c2 = (t1 − dt/3, v1 − m1·dt/3)
            # 实测对官方 176240 段贝塞尔：控制点**双 100.00% 命中**、中位误差 0.000000、max 0.003。
            # ❌ 旧公式 c2y = v1 − C(终点键)·dt/3 命中共 89.83%、最差偏差 **39248**——终点键的 C
            #    是下一段的起点切线，与本段入切线无关。勿再采用。
            m0 = C
            m1 = 3.0 * A * dt * dt + 2.0 * B * dt + C
            c1x = t0 + dt / 3.0
            c1y = v0 + m0 * dt / 3.0
            c2x = t - dt / 3.0
            c2y = v1 - m1 * dt / 3.0
            segs.extend([1, c1x, c1y, c2x, c2y, t, v1])
            total_seg += 1
            n_pts += 3
            total_bezier += 1
            continue

        if len(segs) < 4:
            continue
        total_pts += n_pts
        curves.append({"Target": target, "Id": pid, "Segments": segs})

    if not curves:
        return None

    # 结构自检：按运行时的消费方式重放一遍（segments 是按 TotalSegmentCount 预分配的，
    # 少算一位就会在浏览器里炸成 "basePointIndex of undefined"，且只表现为"这个模型不动"）。
    o = a = 0
    for c in curves:
        segs = c["Segments"]
        l = 0
        while l < len(segs):
            if l == 0:
                o_seg_base, a = a, a + 1
                l += 2
            else:
                o_seg_base = a - 1
            typ = segs[l]
            if typ == 1:
                l += 7
                a += 3
            else:
                l += 3
                a += 1
            o += 1
        if o > total_seg or a > total_pts:
            raise ValueError(f"Meta 计数不足: segments {o}>{total_seg} points {a}>{total_pts} @ {c['Id']}")
    if o != total_seg or a != total_pts:
        raise ValueError(f"Meta 计数与曲线不符: {o}!={total_seg} / {a}!={total_pts}")

    real_t = [t for t, _ in frames if t >= -REF_POSE_EPS]
    duration = round(max(real_t) if real_t else 0.0, 3)
    if duration <= 0:
        st = getattr(muscle, "m_StartTime", 0.0) or 0.0
        sp = getattr(muscle, "m_StopTime", 0.0) or 0.0
        duration = round(sp - st, 3) if sp > st else 0.0

    # 定值曲线：整段保持该 clip 指定的值（1 段线性 = 2 点），让参数在切换动作时回到静止位
    n_const = 0
    if EMIT_CONST and const_info and duration > 0:
        ci, cvals = const_info
        for k, val in enumerate(cvals):
            gi = ci + k
            tgt = targets[gi] if gi < len(targets) else None
            if not tgt:
                continue
            target, pid = tgt
            curves.append({"Target": target, "Id": pid,
                           "Segments": [0.0, float(val), 0, duration, float(val)]})
            total_seg += 1
            total_pts += 2
            n_const += 1

    sample_rate = getattr(clip, "m_SampleRate", 0.0) or 30.0
    return {
        "Version": 3,
        "Meta": {
            "Duration": duration,
            "Fps": float(sample_rate),
            "Loop": bool(getattr(muscle, "m_LoopTime", False)),
            # ★ 必须显式写 0.0：运行时 ACubismMotion._fadeInSeconds 初值是 -1，
            #   而 vendor L210463 在 `json.getMotionFadeInTime() === void 0` 时
            #   退回 config.motionFadingDuration（默认 0.5s）→ 动作前 0.5s 处于
            #   跨动作混合态。官方 motion3.json 这两个字段恒为 0.0（硬切），
            #   缺失会让 home/touch_head 的可见件统计偏离官方（tailOff 79 vs 19）。
            "FadeInTime": 0.0,
            "FadeOutTime": 0.0,
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": total_seg,
            "TotalPointCount": total_pts,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": curves,
        "UserData": [],
        "Physics": None,
    }


def process_model(model_name, verbose=False):
    """返回 (ok, 摘要, 失败 clip 列表)"""
    bundle_path = os.path.join(LIVE2D_DIR, model_name)
    if not os.path.isfile(bundle_path):
        bundle_path = os.path.join(LIVE2D_DIR, model_name + ".bundle")
    if not os.path.isfile(bundle_path):
        return False, "Bundle 文件不存在", []

    model_dir = os.path.join(OUTPUT_DIR, model_name)
    motion_dir = os.path.join(model_dir, "motion")

    try:
        env = UnityPy.load(bundle_path)
    except Exception as e:
        return False, f"加载失败: {e}", []

    targets_lookup = collect_go_name_hashes(env)

    clips = []
    for obj in env.objects:
        if obj.type.name == "AnimationClip":
            try:
                clips.append(obj.read())
            except Exception:
                pass
    if not clips:
        return False, "无 AnimationClip", []

    os.makedirs(motion_dir, exist_ok=True)
    ok = fail = 0
    failed = []
    skipped_targets = 0
    dense_curves = 0
    n_part = 0
    for clip in clips:
        name = getattr(clip, "m_Name", "")
        if not name:
            continue
        targets, unresolved = build_binding_targets(clip, targets_lookup)
        skipped_targets += unresolved
        # genericBindings 的分段顺序 = [streamed][dense][constant]（实测 98+0+180=278 且名字零冲突）
        const_info = None
        if EMIT_CONST:
            try:
                _cd = clip.m_MuscleClip.m_Clip.data
                _off = _cd.m_StreamedClip.curveCount + _cd.m_DenseClip.m_CurveCount
                _vals = list(_cd.m_ConstantClip.data or [])
                if _vals:
                    const_info = (_off, _vals)
                if _cd.m_DenseClip.m_CurveCount:
                    dense_curves += _cd.m_DenseClip.m_CurveCount
            except Exception:
                pass
        try:
            motion = build_motion(clip, targets, verbose=verbose, const_info=const_info)
        except Exception as e:
            motion = None
            detail = f"{type(e).__name__}: {e}"
            log_warn(f"{model_name}/{name}", f"build_motion 异常: {detail}")
            if verbose:
                print(f"    [!] {name}: build_motion 异常 {detail}")
        if not motion:
            fail += 1
            failed.append(name)
            log_warn(f"{model_name}/{name}", "解出 0 条曲线（不再写空壳占位文件）")
            continue
        n_part += sum(1 for c in motion["Curves"] if c["Target"] == "PartOpacity")
        with open(os.path.join(motion_dir, f"{name}.motion3.json"), "w", encoding="utf-8") as f:
            json.dump(motion, f, ensure_ascii=False)
        ok += 1
        if verbose:
            m = motion["Meta"]
            print(f"    {name:<22} curves={m['CurveCount']:<5} dur={m['Duration']:<8} loop={m['Loop']}")

    msg = f"成功 {ok} / 失败 {fail}" + (f" / PartOpacity曲线 {n_part}" if n_part else "")
    if dense_curves:
        msg += f" / ⚠️未导出的 dense 曲线 {dense_curves}"
    if skipped_targets:
        msg += f" / 跳过不可解析绑定 {skipped_targets}"
    return (fail == 0 and ok > 0), msg, failed


def main():
    ap = argparse.ArgumentParser(description="提取 Live2D 动作数据（权威 genericBindings 映射）")
    ap.add_argument("--name", help="指定模型名称")
    ap.add_argument("--test", help="单模型，打印每条 clip 明细")
    ap.add_argument("--all", action="store_true", help="处理全部模型")
    ap.add_argument("--out", help="输出目录。**推荐用它而不是 L2D_OUT_DIR 环境变量**："
                                   "Start-Process 脱离进程下环境变量是否被子进程读到不可复现，"
                                   "2026-09-24 就因此把 269 个模型直接覆写进了正式目录（见 TROUBLESHOOTING §24）")
    ap.add_argument("--into-production", action="store_true",
                    help="显式确认写进 Output/Live2D（--all 且不指定 --out/L2D_OUT_DIR 时必须给这个）")
    args = ap.parse_args()

    if args.out:
        globals()["OUTPUT_DIR"] = os.path.abspath(args.out)
    elif not os.environ.get("L2D_OUT_DIR"):
        if args.all and not args.into_production:
            print("[ERROR] --all 未指定 --out：默认目标就是正式目录 Output/Live2D，会原地覆写 motion 且没有备份。\n"
                  "        正规流程是先 --out .diag/<临时目录> → 审计 → apply_live2d_motions.py --yes 换入。\n"
                  "        确实要直接写正式目录时再加 --into-production。")
            return 2
        globals()["OUTPUT_DIR"] = P.LIVE2D_OUT

    if not os.path.isdir(LIVE2D_DIR):
        print(f"[ERROR] Live2D 目录不存在: {LIVE2D_DIR}")
        return 2

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"[*] 输出目录: {OUTPUT_DIR}" + ("  (临时)" if os.environ.get("L2D_OUT_DIR") else ""))
    if BEZIER:
        print("[*] L2D_MOTION_BEZIER=1 → 贝塞尔按绝对(时间,值)写，控制点由多项式精确给出"
              "（c1y=v0+C·dt/3，c2y=v1−(3A·dt²+2B·dt+C)·dt/3）")
    else:
        print("[*] 线性插值（L2D_MOTION_BEZIER 未置1）")
    if SEGTYPE:
        print("[*] L2D_MOTION_SEGTYPE=1 → 还原 Stepped 段（判据：A·dt³、B·dt²、C 相对容差为 0 且 dv≠0）")
    if ABSOLUTE_CP:
        print("[*] L2D_MOTION_ABSOLUTE_CP=1 → 兼容提示：贝塞尔已无条件按绝对(时间,值)写，本开关保留无损语义")
    if EMIT_CONST:
        print("[*] L2D_MOTION_EMIT_CONST=1 → 一并导出 m_ConstantClip 定值曲线")

    if args.test:
        models, verbose = [args.test], True
    elif args.name:
        models, verbose = [args.name], True
    elif args.all:
        models, verbose = sorted(os.listdir(LIVE2D_DIR)), False
    else:
        print(__doc__)
        return 2

    bad_models = []
    # 全量要跑 ~20 分钟且常以脱离进程（Start-Process 重定向）方式启动 → stdout 是块缓冲的。
    # 不带 flush 与 [i/n] 进度行，日志会长时间空白，就无法区分「慢」和「死/被截断」。
    models = [m for m in models if os.path.isfile(os.path.join(LIVE2D_DIR, m))]
    total = len(models)
    for i, m in enumerate(models, 1):
        ok, msg, failed = process_model(m, verbose=verbose)
        print(f"[{i}/{total}] " + ("[+]" if ok else "[-]") + f" {m:<24} {msg}", flush=True)
        if not ok or failed:
            bad_models.append((m, failed))

    print("\n" + "=" * 46, flush=True)
    # 终判行：成功与失败都打同一可 grep 字面量，判定「跑完没有」只认这一行的计数，不认退出码
    #（有解不出的 clip 时退出码本就是 1，见 §2.5 的 7 条资产层真为空 clip）。
    print(f"[SUMMARY] 模型 {total}/{total} 处理完 | 有解不出 clip 的模型 {len(bad_models)} | 输出 {OUTPUT_DIR}",
          flush=True)
    if bad_models:
        print("[!] 明细（前 20）:")
        for m, fl in bad_models[:20]:
            print(f"    {m}: {fl}")
        return 1
    print("[+] 全部 clip 均解出非空曲线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
