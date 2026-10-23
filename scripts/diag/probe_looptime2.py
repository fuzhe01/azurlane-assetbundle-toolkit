"""专门核对 login 及其他关键 clip 的 m_LoopTime，与我们导出的 Meta.Loop 对照。

用法: py -3 .diag/probe_looptime2.py ougen_8
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

import UnityPy  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
BUNDLE = os.path.join(ROOT, 'files', 'AssetBundles', 'live2d', KEY)
MD = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')
OLD = os.path.join(r'D:\Azur Lane Assets\Output\Live2D', KEY, 'motion')

env = UnityPy.load(BUNDLE)
truth = {}
for obj in env.objects:
    if obj.type.name != 'AnimationClip':
        continue
    try:
        d = obj.read()
        nm = getattr(d, 'm_Name', None)
        mus = getattr(d, 'm_MuscleClip', None)
        lt = getattr(mus, 'm_LoopTime', None) if mus is not None else None
        if nm:
            truth[nm] = lt
    except Exception:  # noqa: BLE001
        pass

print('bundle 内 AnimationClip 数:', len(truth))
print()
print('%-24s %-10s %-10s %-10s' % ('clip', 'Unity真值', '我们导出', '旧画廊'))
bad = []
for nm in ('login', 'idle', 'touch_body', 'effect', 'home', 'main_1'):
    pn = os.path.join(MD, nm + '.motion3.json')
    po = os.path.join(OLD, nm + '.motion3.json')
    our = json.load(open(pn, encoding='utf-8')).get('Meta', {}).get('Loop') if os.path.exists(pn) else None
    old = json.load(open(po, encoding='utf-8')).get('Meta', {}).get('Loop') if os.path.exists(po) else None
    t = truth.get(nm)
    mark = ''
    if t is not None and our is not None and t != our:
        mark = '  <<< 不一致'
        bad.append(nm)
    print('%-24s %-10s %-10s %-10s%s' % (nm, t, our, old, mark))

print('\n=== 全量统计：我们的导出 vs Unity 真值 ===')
mis = 0; ok = 0
for fn in sorted(os.listdir(MD)):
    if not fn.endswith('.motion3.json'):
        continue
    nm = fn[:-len('.motion3.json')]
    if nm not in truth:
        continue
    our = json.load(open(os.path.join(MD, fn), encoding='utf-8')).get('Meta', {}).get('Loop')
    if our is None:
        continue
    if bool(truth[nm]) != bool(our):
        mis += 1
    else:
        ok += 1
print('  与 Unity m_LoopTime 一致: %d   不一致: %d' % (ok, mis))

print('\n=== 旧画廊 vs Unity 真值 ===')
mis2 = 0; ok2 = 0
for fn in sorted(os.listdir(OLD)):
    if not fn.endswith('.motion3.json'):
        continue
    nm = fn[:-len('.motion3.json')]
    if nm not in truth:
        continue
    old = json.load(open(os.path.join(OLD, fn), encoding='utf-8')).get('Meta', {}).get('Loop')
    if old is None:
        continue
    if bool(truth[nm]) != bool(old):
        mis2 += 1
    else:
        ok2 += 1
print('  与 Unity m_LoopTime 一致: %d   不一致: %d' % (ok2, mis2))