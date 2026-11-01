# -*- coding: utf-8 -*-
"""只读审计：确认 extract_motions 是否漏读 m_DenseClip。

结论已成（阅读 extract_motions.py 源码 408~452 行）：m_DenseClip 曲线只被 count
（`dense_curves += _cd.m_DenseClip.m_CurveCount`）从不导出；build_motion 只解
m_StreamedClip + （可选）m_ConstantClip。本脚本用 UnityPy 实测各 AnimationClip 的
三容器曲线数，量化「被丢弃的 dense 曲线」到底有多少，作为是否值得补读的证据。

用法:
  py -3 scripts/diag/l2d_dense_audit.py aersasi_2|ougen_8   # 只读，不写任何产物
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths as P  # noqa: E402

try:
    import UnityPy
    from UnityPy import config
    config.FALLBACK_UNITY_VERSION = "2022.3.62f3"
except ImportError:
    print('需 pip install UnityPy')
    sys.exit(2)


def main(name):
    bundle = os.path.join(P.AB, 'live2d', name)
    if not os.path.isfile(bundle):
        print(f'!! bundle 不存在: {bundle}')
        sys.exit(2)
    env = UnityPy.load(bundle)
    tot_s = tot_d = tot_c = 0
    n = 0
    for obj in env.objects:
        if obj.type.name != 'AnimationClip':
            continue
        try:
            clip = obj.read()
        except Exception as e:
            print(f'  ! clip 读取失败: {e}')
            continue
        mm = getattr(clip, 'm_MuscleClip', None)
        cd = getattr(getattr(mm, 'm_Clip', None), 'data', None) or getattr(mm, 'm_Clip', None)
        if not cd:
            continue
        s = getattr(getattr(cd, 'm_StreamedClip', None), 'curveCount', 0) or 0
        d = getattr(getattr(cd, 'm_DenseClip', None), 'm_CurveCount', 0) or 0
        c = len(getattr(getattr(cd, 'm_ConstantClip', None), 'data', None) or [])
        tot_s += s
        tot_d += d
        tot_c += c
        n += 1
        if n <= 6 or d:
            print(f'  {getattr(clip,"m_Name",""):<18} streamed={s:<4} DENSE={d:<4} constant={c:<4}')
    print(f'--- 合计 {n} 个 clip | streamed={tot_s} dense={tot_d} constant={tot_c}')
    print(f'    当前 extract_motions 只解 streamed(+可选constant)，'
          f'每个 clip 若有 dense>0 即被丢弃；本模型 dense 总计={tot_d}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
