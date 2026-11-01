r"""清点「标记件在、动作组不在、但会被回退到别的组」的区域（也就是「点了有反应但反应不对」）。

这是与「没有对应动作组（点不出任何东西）」**不同**的一类问题：
有反应，所以用户不会觉得"这里坏"，但播的是**别人的动作** —— 更难发现。

判定规则（照抄前端 `dragGroupOf`，一行不改，保证口径一致）：

    dragGroupOf(n):
      1) groups 里有 n            → n
      2) groups 里有 touch_drag<k> → 它
      3) 否则 ds = 所有 touch_drag* 组，取 ds[(k-1) % ds.length]

    ⇒ 只要该模型有任意 `touch_drag*` 组，**每个** TouchDragN 标记都会落到某个组上，
       哪怕 dtouch_dragN 根本不存在。这就是"回退"。

判据来自文件本身（model3.json 的 HitAreas/Motions + moc3 字节里的 Touch* 名），
不需要浏览器。

用法：
  py -3 scripts/diag/hitarea_drag_fallback_audit.py            # 只列有回退的模型
  py -3 scripts/diag/hitarea_drag_fallback_audit.py --all      # 全部模型都打印
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L2D = os.path.join(ROOT, 'Output', 'Live2D')
SHOW_ALL = '--all' in sys.argv


def drag_group_of(name, groups):
    """与前端 dragGroupOf 逐行对应的 Python 版。"""
    if name in groups:
        return name, 'exact'
    m = re.match(r'^touchdrag(\d+)$', name, re.I)
    alt = 'touch_drag' + m.group(1) if m else None
    if alt and alt in groups:
        return alt, 'alt'
    k = int(m.group(1)) if m else 1
    ds = [g for g in groups if re.match(r'^touch_drag\d+$', g)]
    if not ds:
        return None, 'none'
    return ds[(k - 1) % len(ds)], 'fallback'


def main():
    models = sorted(d for d in os.listdir(L2D) if os.path.isdir(os.path.join(L2D, d)))
    grand = {'exact': 0, 'alt': 0, 'fallback': 0, 'none': 0}
    per_model = []
    for name in models:
        m3 = os.path.join(L2D, name, name + '.model3.json')
        mc = os.path.join(L2D, name, name + '.moc3')
        if not os.path.isfile(m3):
            continue
        d = json.load(open(m3, encoding='utf-8'))
        groups = list((d.get('FileReferences') or {}).get('Motions', {}).keys())
        gset = set(groups)
        ds = sorted(g for g in groups if re.match(r'^touch_drag\d+$', g))
        try:
            raw = open(mc, 'rb').read()
        except OSError:
            raw = b''
        touch = sorted(set(m.group(0).decode('ascii', 'ignore')
                           for m in re.finditer(rb'Touch[ -~]{1,20}?(?=[^\x20-\x7e])', raw)))

        rows = []
        for tid in touch:
            # 前端会把 TouchDragN 归一成 touchdragN 参与判区
            low = tid.lower()
            if not re.match(r'^touchdrag\d+$', low):
                continue
            target, how = drag_group_of(low, gset)
            rows.append((tid, target, how))
            grand[how if how else 'none'] += 1
        if rows:
            per_model.append((name, ds, rows))

    print('=== TouchDrag* 标记的落点（规则照抄前端 dragGroupOf）')
    print('    各模型可用的 touch_drag 组：')
    for name, ds, rows in per_model:
        print('      %-14s %s' % (name, ds if ds else '(无)'))
    print('\n=== 合计（跨 %d 个模型的 %d 个 TouchDrag 标记）'
          % (len(per_model), sum(grand.values())))
    print('    ① 同名组存在（exact + alt）: %d' % (grand['exact'] + grand['alt']))
    print('    ② ★回退到别的组（fallback）: %d  ← 点了有反应但播的是别人的动作' % grand['fallback'])
    print('    ③ 无处可回退（none）       : %d  ← 点了完全没反应' % grand['none'])

    print('\n=== 逐模型明细')
    for name, ds, rows in per_model:
        fb = [r for r in rows if r[2] == 'fallback']
        if not fb and not SHOW_ALL:
            continue
        print('\n  %-14s 标记 %d 个，回退 %d 个（可用组 %s）'
              % (name, len(rows), len(fb), ds))
        for tid, target, how in rows:
            if how == 'fallback' or SHOW_ALL:
                tag = {'exact': '同名', 'alt': '下划线同名', 'fallback': '★回退', 'none': '★无组'}[how]
                print('     %-16s → %-16s %s' % (tid, target or '(无)', tag))
    return 0


if __name__ == '__main__':
    sys.exit(main())
