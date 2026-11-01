#!/usr/bin/env python3
"""一次性探针：读 ougen_8 的 mail/mission 原始 AnimationClip，打印 Param31 的
   每个关键帧 (time, value, 三次多项式系数 A/B/C)，判定 Unity 原数据到底是
   「阶梯式常量切线」还是「真线性」——用来区分「我们导出器把阶梯写成了线性」
   与「官方数据本来就是线性」。

用法: py -3 scripts/diag/probe_p31_raw.py [model] [clip名...]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import paths as P
import UnityPy
from UnityPy import config
config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

import extract_motions as EM

model = sys.argv[1] if len(sys.argv) > 1 else "ougen_8"
want = sys.argv[2:] or ["mail", "mission", "idle"]

bundle = os.path.join(P.LIVE2D_SRC, model)
env = UnityPy.load(bundle)
targets_lookup = EM.collect_go_name_hashes(env)
print(f"模型={model}  targets={len(targets_lookup)}")

for obj in env.objects:
    if obj.type.name != "AnimationClip":
        continue
    clip = obj.read()
    name = getattr(clip, "m_Name", "")
    if name not in want:
        continue
    targets, _ = EM.build_binding_targets(clip, targets_lookup)
    idx = [i for i, t in enumerate(targets) if t and t[1] == "Param31"]
    print(f"\n===== clip={name}  Param31 curveIdx={idx}  targets={len(targets)} =====")
    if not idx:
        continue
    cd = clip.m_MuscleClip.m_Clip.data
    frames = EM.parse_streamed_clip(cd.m_StreamedClip)
    print(f"  frames={len(frames)}  constantClip={len(list(cd.m_ConstantClip.data or []))}"
          f"  denseCurves={cd.m_DenseClip.m_CurveCount}")
    for i in idx:
        pts = []
        base = None
        for t, keys in frames:
            for k_i, v, a1, a2, a3 in keys:   # 现在的 parse_streamed_clip 返回 (idx, A, B, C, D)
                if k_i != i:
                    continue
                if t < -EM.REF_POSE_EPS:
                    base = v
                else:
                    pts.append((t, v, (a1, a2, a3)))
        print(f"  --- curveIdx={i} 参考姿态值={base} 关键帧数={len(pts)}")
        for t, v, coef in sorted(pts):
            c = "  ".join("%12.6g" % x for x in coef)
            print(f"      t={t:9.4f}  v={v:10.6f}  coef(A,B,C)={c}")
