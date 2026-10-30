r"""验证判定区命名规则的**下划线形态**缺陷（真遗漏的那一类）。

已确认：128 个未登记 Touch* 里绝大多数是「该模型确实没有对应动作组」，丢弃是对的。
但诊断输出里出现了一个可疑形态：

    Touch_Body   → 候选 touch__body   （双下划线！）
    Touch_Drag1  → 候选 touch__drag1

根因：`fix_model3.py` 用 `re.sub(r'(?<!^)(?=[A-Z])', '_', tid[5:])` 插入下划线，
对 `Touch_Body` 这种**本身已带下划线**的名字，`tid[5:]` = `_Body`，
首字符就是 `_`，再拼 `touch_` 前缀 ⇒ `touch__body`，与真实组名 `touch_body` 差一个下划线。

本脚本量化这类「形态问题」有多少个，并验证修正后的候选能否命中动作组。
修正规则：先把连续下划线压成一个，再去掉首尾下划线。

用法：py -3 scripts/diag/hitarea_underscore_check.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L2D = os.path.join(ROOT, 'Output', 'Live2D')


def cand_old(tid):
    return ('touch_' + re.sub(r'(?<!^)(?=[A-Z])', '_', tid[5:]).lower()).replace('__', '_')


def cand_fixed(tid):
    """压掉多余下划线：Touch_Body → touch_body；TouchIdle6 → touch_idle6。"""
    body = re.sub(r'(?<!^)(?=[A-Z])', '_', tid[5:]).lower()
    body = re.sub(r'_+', '_', body).strip('_')
    return 'touch_' + body


def main():
    models = sorted(d for d in os.listdir(L2D) if os.path.isdir(os.path.join(L2D, d)))
    total_gain = 0
    for name in models:
        m3 = os.path.join(L2D, name, name + '.model3.json')
        mc = os.path.join(L2D, name, name + '.moc3')
        if not os.path.isfile(m3):
            continue
        d = json.load(open(m3, encoding='utf-8'))
        gset = set((d.get('FileReferences') or {}).get('Motions', {}).keys())
        try:
            raw = open(mc, 'rb').read()
        except OSError:
            continue
        touch = sorted(set(m.group(0).decode('ascii', 'ignore')
                           for m in re.finditer(rb'Touch[ -~]{1,20}?(?=[^\x20-\x7e])', raw)))
        reg = set(h.get('Id') for h in (d.get('HitAreas') or []))
        gains = []
        for tid in touch:
            if tid in reg:
                continue
            o, f = cand_old(tid), cand_fixed(tid)
            if o == f:
                continue
            hit_old = (o in gset) or (tid[5:].lower() in gset)
            hit_new = (f in gset) or (tid[5:].lower() in gset)
            if not hit_old and hit_new:
                gains.append((tid, o, f))
        if gains:
            total_gain += len(gains)
            print('\n%s  可补登记 %d 个（下划线形态修正后命中动作组）:' % (name, len(gains)))
            for tid, o, f in gains:
                print('   %-16s 旧候选=%-20s 新候选=%-20s ✓' % (tid, o, f))
    print('\n=== 因下划线形态被丢弃的判定区合计: %d 个' % total_gain)
    return 0


if __name__ == '__main__':
    sys.exit(main())
