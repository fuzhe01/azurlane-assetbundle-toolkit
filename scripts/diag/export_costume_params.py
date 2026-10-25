# -*- coding: utf-8 -*-
"""把「值域扫描 + drawable 映射」的结果导出成前端可直接消费的换装参数表。

输出 Output/gallery_v2/costume_params.json：
  { 模型key: [ {id, label, kind, lo, hi, def, n_drawables}, ... ] }

判据（2026-10-24 定案，替代旧判据）：
  旧判据「不同动作间被锁成不同档位」对纯互动参数失效——Cloth1-3/Stock1-2/ShoseOff/Paramring
  在全部 45 个动作里恒为 0.0，值集合只有 {0.0}，会被 `len(set(vals))>=2` 全部过滤掉。
  新判据：**值域** max-min > 0.5（有可调空间）+ 名称语义命中（Cloth/Stock/Shose/Ring/Eye…）
          + 几何映射证明它确实驱动局部 drawable（见 map_param_to_drawables.py）

输入：.diag/costume_scan/costume_by_range.json（值域+语义）
      .diag/param_drawables/map.json（参数→drawable 映射）
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

SCAN = os.path.join(ROOT, '.diag', 'costume_scan', 'costume_by_range.json')
MAP = os.path.join(ROOT, '.diag', 'param_drawables', 'map.json')
DST = os.path.join(ROOT, 'Output', 'gallery_v2', 'costume_params.json')

# 明确排除：动作/视线/呼吸逐帧驱动
EXCLUDE = ('eyeball', 'eyeopen', 'eyelopen', 'eyeropen', 'breath', 'angle',
           'bodyangle', 'cheek', 'brow', 'mouthform', 'eyeform', 'paramangle')

n_moved = {}
if os.path.exists(MAP):
    try:
        m = json.load(open(MAP, encoding='utf-8'))
        for pid, v in m.items():
            n_moved[pid] = v.get('n_moved', 0)
    except Exception:
        pass

if not os.path.exists(SCAN):
    raise SystemExit('缺 %s —— 先跑 scan_costume_by_range.py' % SCAN)

scan = json.load(open(SCAN, encoding='utf-8'))
out = {}
tot = 0
for model, params in scan.items():
    rows = []
    for pid, info in params.items():
        low = pid.lower()
        if any(x in low for x in EXCLUDE):
            continue
        span = float(info['hi']) - float(info['lo'])
        if span <= 0.5:
            continue
        rows.append({
            'id': pid,
            'label': info.get('label') or pid,
            'kind': info.get('kind') or ('switch' if span <= 1.0001 else 'slider'),
            'lo': info['lo'],
            'hi': info['hi'],
            'def': info.get('def', 0),
            'n_drawables': n_moved.get(pid, None),
        })
    rows.sort(key=lambda r: (r['label'], r['id']))
    if rows:
        out[model] = rows
        tot += len(rows)

os.makedirs(os.path.dirname(DST), exist_ok=True)
json.dump(out, open(DST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print('模型数 %d，参数总计 %d -> %s' % (len(out), tot, DST))
for model, rows in out.items():
    print('  %-14s %d 个: %s' % (model, len(rows), [r['id'] for r in rows]))
