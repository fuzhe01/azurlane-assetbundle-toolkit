# -*- coding: utf-8 -*-
"""只读探针：核对 ougen_8 每个动作的「三容器曲线数 vs genericBindings vs 磁盘曲线数」。

针对性检查用户报的缺陷①：动作播放中部件消失。
假设：磁盘 motion3.json 缺了控制目标部件的曲线（尤其 PartOpacity / 姿势参数），
导致这些部件在动作中没被驱动，停在上个动作/默认值。

用法: py -3 scripts/diag/probe_mail_bindings.py [模型名] [--dump=动作名]
"""
import os
import sys
import json
import binascii

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import paths as P  # noqa: E402

import UnityPy  # noqa: E402
from UnityPy import config  # noqa: E402
config.FALLBACK_UNITY_VERSION = "2022.3.62f3"

NAME = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 'ougen_8'
DUMP = None
for a in sys.argv[1:]:
    if a.startswith('--dump='):
        DUMP = a.split('=', 1)[1]

BUNDLE = os.path.join(P.AB, 'live2d', NAME)
MOT_DIR = os.path.join(ROOT, 'Output', 'Live2D', NAME, 'motion')

ATTR_PARAM = 3702945584
ATTR_PART = 2353026298


def crc(s):
    return binascii.crc32(s.encode('utf-8')) & 0xFFFFFFFF


def main():
    env = UnityPy.load(BUNDLE)
    clips = []
    for obj in env.objects:
        if obj.type.name != 'AnimationClip':
            continue
        try:
            clips.append(obj.read())
        except Exception as e:
            print(f'  ! clip 读失败: {e}')
    print(f'模型={NAME} clip 总数={len(clips)}  bundle={BUNDLE}')
    print()

    rows = []
    bad = 0
    for clip in clips:
        nm = getattr(clip, 'm_Name', '')
        mm = getattr(clip, 'm_MuscleClip', None)
        cd = getattr(getattr(mm, 'm_Clip', None), 'data', None)
        if not cd:
            continue
        streamed = getattr(getattr(cd, 'm_StreamedClip', None), 'curveCount', 0) or 0
        dense = getattr(getattr(cd, 'm_DenseClip', None), 'm_CurveCount', 0) or 0
        const = len(getattr(getattr(cd, 'm_ConstantClip', None), 'data', None) or [])

        # m_ClipBindingConstant 挂在 AnimationClip 上，不是 Clip 的 data 上
        bc = getattr(clip, 'm_ClipBindingConstant', None)
        gb = list(getattr(bc, 'genericBindings', None) or [])
        nbind = len(gb)
        tot = streamed + dense + const
        ok = (tot == nbind)
        if not ok:
            bad += 1

        disk_n = None
        disk_parts = 0
        disk_params = set()
        fp = os.path.join(MOT_DIR, nm + '.motion3.json')
        if os.path.isfile(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                cvs = d.get('Curves') or []
                disk_n = len(cvs)
                for c in cvs:
                    cid = c.get('Id', '')
                    if cid.startswith('PartOpacity'):
                        disk_parts += 1
                    else:
                        disk_params.add(cid)
            except Exception as e:
                disk_n = f'ERR:{e}'

        rows.append(dict(name=nm, streamed=streamed, dense=dense, const=const,
                         nbind=nbind, tot=tot, ok=ok, disk_n=disk_n,
                         disk_parts=disk_parts, disk_params=disk_params, gb=gb, cd=cd))

    print('=== 断言：streamed + dense + constant == len(genericBindings) ===')
    print(f'{"动作组":<20} {"str":>5} {"dns":>4} {"cst":>5} {"sum":>5} {"bind":>5} {"断言":>6} {"磁盘曲线":>8}')
    for r in rows:
        flag = 'OK' if r['ok'] else 'FAIL'
        print(f'{r["name"]:<20} {r["streamed"]:>5} {r["dense"]:>4} {r["const"]:>5} '
              f'{r["tot"]:>5} {r["nbind"]:>5} {flag:>6} {str(r["disk_n"]):>8}')
    print(f'\n断言违例数 = {bad} / {len(rows)}')

    # 逐组：bindings 数 vs 磁盘曲线数
    print('\n=== 断言二：磁盘曲线数 == bindings 总数（每组合法即文件完整）===')
    short = 0
    for r in rows:
        if isinstance(r['disk_n'], int) and r['disk_n'] != r['nbind']:
            short += 1
            print(f'  !! {r["name"]:<18} 磁盘={r["disk_n"]:<5} bindings={r["nbind"]:<5} '
                  f'缺 {r["nbind"] - r["disk_n"]} 条（{100.0 * r["disk_n"] / max(1, r["nbind"]):.1f}% 已导）')
    print(f'曲线数不符的组数 = {short} / {len(rows)}')
    if short == 0:
        print('  => 磁盘曲线数与 bindings 完全一致，本条假设（丢曲线）不成立')

    # 关注：由 constant 容器覆盖的组（定值复位曲线）
    print('\n=== constant 容器分布（定值曲线的来源）===')
    const_groups = [r for r in rows if r['const'] > 0]
    print(f'  含 constant 曲线的组: {len(const_groups)} / {len(rows)}')
    for r in const_groups[:20]:
        print(f'    {r["name"]:<18} const={r["const"]}')

    if DUMP:
        dump_target(rows, DUMP)


def dump_target(rows, target):
    """细看单个动作：bindings 里有哪些曲线名，与磁盘曲线名的差集是什么。"""
    r = next((x for x in rows if x['name'] == target), None)
    if not r:
        print(f'\n!! 找不到动作组 {target}')
        return
    print(f'\n=== 细查 {target} ===')
    print(f'streamed={r["streamed"]} dense={r["dense"]} const={r["const"]} '
          f'bindings={r["nbind"]} 磁盘曲线={r["disk_n"]}')
    print(f'磁盘 PartOpacity 曲线数 = {r["disk_parts"]}')

    # 从 bindings 反查曲线名：遍历 primitives 拿 path 哈希 → crc 反查
    gb = r['gb']
    names = []
    for b in gb:
        pattr = getattr(b, 'attribute', None)
        phash = getattr(b, 'path', None)
        names.append((pattr, phash))
    print(f'bindings 条目数 = {len(names)}（前 5 条：{names[:5]}）')
    uniq_attr = {}
    for a, _ in names:
        uniq_attr[a] = uniq_attr.get(a, 0) + 1
    print(f'按 attribute 分布: {uniq_attr}')
    print(f'  ATTR_PARAM={ATTR_PARAM} (Parameters/) 条数={uniq_attr.get(ATTR_PARAM, 0)}')
    print(f'  ATTR_PART={ATTR_PART} (Parts/) 条数={uniq_attr.get(ATTR_PART, 0)}')


if __name__ == '__main__':
    main()
