# -*- coding: utf-8 -*-
r"""l2d_costume_table_merge.py — 把运行时反查结果合入产品表（换装参数 + 参数→部件映射）。

## 数据来源

`l2d_param_binding_export.py` 产出的 `.diag/costume_params_binding.json`：
每条参数在 min/max 两态下真的改变了哪些 drawable（不透明度/可见性/顶点包围盒任一变化）。

## 为什么不能直接用旧扫描（`l2d_costume_params_scan.py`）

旧判据是「在不同动作间被锁成不同档位 ⇒ 可调」，对装扮参数**恰好是反的**：
装扮参数在几乎所有动作里都是同一个值，于是被判成"无可调空间"剔除。
实测后果：`ougen_8` 只报出 4 条，漏掉鞋/衣服/戒指/项圈全部。

## 筛选规则（三条全满足才收）

1. **名字命中换装语义**：`shose|shoe|stock|cloth|glove|switch|transparen|ring|neck|money|wing|...`
2. **不是动画量**：排除 `Displacement|Finger|Animation|Transition|Layer|Change|Forearm|Hand|
   Angle|Darken|DecisionBox|Liquor|Mail_Transparency` —— 这些是手部姿势/材质渐变，
   由动作或物理逐帧驱动，做成互动区会与运行时抢参数。
3. **开关型**：值域跨度 ≤ 1.5（典型 0..1）。落到 `ShoseOff`（-1..1，三态）这类已人工确认的
   条目时保留其 slider 语义。

## 与既有产品表的关系

`ougen_8` 的 12 条是**人工逐条验收过**的（§166/§167/§169），一律**优先保留**，
不被本脚本覆盖；本脚本只做两件事：
  · 补上反查发现但产品表漏掉的条目（如 `ChestMoney`）；
  · 为原本没有表的模型（`benningdun_2`/`aersasi_2`/`aersasi_3`/`antu_2`）建表。

## 用法

    py -3 scripts/diag/l2d_costume_table_merge.py --dry     # 只报告，不写盘
    py -3 scripts/diag/l2d_costume_table_merge.py           # 写入产品表
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
BINDING = os.path.join(ROOT, '.diag', 'costume_params_binding.json')
COSTUME = os.path.join(ROOT, 'Output', 'gallery_v2', 'costume_params.json')
DRAWABLES = os.path.join(ROOT, 'Output', 'gallery_v2', 'param_drawables.json')

KEEP = re.compile(
    r'(shose|shoe|heels|boot|stock|sock|cloth|coat|jacket|skirt|apron|dress|'
    r'glove.*switch|glove.*transparen|wing|swing|ring|neck|money|glass|mask|'
    r'hat|crown|hairpin|earring|cape|veil|ribbon|belt|scarf|horn|tail)', re.I)

DROP = re.compile(
    r'(displacement|finger|animation|transition|layer|change|forearm|hand|'
    r'angle|darken|decisionbox|liquor|mail_transparen|_gg$|_size$|eyeball|'
    r'eyelopen|eyeropen|breath|brow|mouth|tear|cheek|sweat)', re.I)

#: 已人工验收的模型：这些模型的既有条目一律保留，不被覆盖
VERIFIED = {'ougen_8'}

LABEL_RULES = [
    (re.compile(r'glove', re.I), '手套'),
    (re.compile(r'shose|shoe|heels|boot', re.I), '鞋'),
    (re.compile(r'stock|sock', re.I), '丝袜'),
    (re.compile(r'cloth|coat|jacket|skirt|apron|dress', re.I), '衣服'),
    (re.compile(r'wing|swing', re.I), '翅膀'),
    (re.compile(r'ring', re.I), '戒指'),
    (re.compile(r'neck|money', re.I), '项链/项圈'),
    (re.compile(r'glass|mask', re.I), '眼睛/眼镜'),
]


def label_of(pid):
    for rx, lab in LABEL_RULES:
        if rx.search(pid):
            return lab
    return '其他'


def main():
    dry = '--dry' in sys.argv
    if not os.path.isfile(BINDING):
        raise SystemExit(f'缺 {BINDING} —— 先跑 l2d_param_binding_export.py')
    binding = json.load(open(BINDING, encoding='utf-8'))
    costume = json.load(open(COSTUME, encoding='utf-8')) if os.path.isfile(COSTUME) else {}
    drawables = json.load(open(DRAWABLES, encoding='utf-8')) if os.path.isfile(DRAWABLES) else {}

    added = {}
    for model, rows in binding.items():
        by_id = {r['id']: r for r in rows}
        cur = costume.get(model) or []
        cur_ids = {r['id'] for r in cur}
        cur_map = drawables.get(model) or {}
        new_rows, new_map = [], {}
        for r in rows:
            pid = r['id']
            if pid in cur_ids:
                continue                      # 已在产品表里（含人工验收过的 12 条）
            if not KEEP.search(pid) or DROP.search(pid):
                continue
            span = abs(r['hi'] - r['lo'])
            if span > 1.5:
                continue                      # 只收开关型；渐变型留待逐条人工确认
            idxs = r['idx']
            if not idxs:
                continue
            new_rows.append({'id': pid, 'label': label_of(pid), 'kind': 'switch',
                             'lo': r['lo'], 'hi': r['hi'], 'def': r['def'],
                             'n_drawables': len(idxs)})
            new_map[pid] = idxs
        if new_rows:
            added[model] = (new_rows, new_map)

    print('=== 拟新增条目')
    for model, (rows, mp) in added.items():
        print(f'  {model}: +{len(rows)} 条')
        for r in rows:
            print('      %-24s %-10s [%s..%s] 驱动%d件'
                  % (r['id'], r['label'], r['lo'], r['hi'], r['n_drawables']))
    if not added:
        print('  （无可新增条目）')
        return 0
    if dry:
        print('\n--dry：未写盘')
        return 0

    for model, (rows, mp) in added.items():
        cl = costume.setdefault(model, [])
        cl.extend(rows)
        # 开关型排前面、同类按 id 稳定排序（与既有导出侧一致）
        cl.sort(key=lambda x: (0 if x.get('kind') == 'switch' else 1, x['id'].lower()))
        drawables.setdefault(model, {}).update(mp)

    json.dump(costume, open(COSTUME, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    json.dump(drawables, open(DRAWABLES, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print(f'\n写出 {COSTUME}（{os.path.getsize(COSTUME)} B，{len(costume)} 个模型）')
    print(f'写出 {DRAWABLES}（{os.path.getsize(DRAWABLES)} B，{len(drawables)} 个模型）')
    for model in sorted(costume):
        print('  %-14s %2d 条参数 / %2d 条映射'
              % (model, len(costume[model]), len(drawables.get(model) or {})))
    return 0


if __name__ == '__main__':
    sys.exit(main())