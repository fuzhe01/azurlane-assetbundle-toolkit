r"""查清「未登记的 Touch* 到底为什么被丢弃」（判定区遗漏的根因）。

`fix_model3.py` 的补登记规则是：`Touch<X>` → 候选名 `touch_<x>`（或 `<x>`），
**命中动作组才登记，命中不到直接丢弃**。所以「未登记」只有两种可能：
  a) 该模型根本没有对应动作组（数据里就没有）→ 丢弃是**对的**
  b) 有动作组但**名字拼不出来**（命名规则没覆盖）→ 丢弃是**错的**（真遗漏）

本脚本把每个未登记的 Touch* 分成这两类，并对 b 类给出「最接近的动作组」，
用来判断是命名规则漏了哪种形态。

用法：py -3 scripts/diag/hitarea_missing_cause.py [模型]
"""
import json
import os
import re
import sys
from difflib import get_close_matches

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L2D = os.path.join(ROOT, 'Output', 'Live2D')
ONLY = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else None


def camel_to_snake(tid):
    """与 fix_model3.py 完全一致的候选名生成。"""
    cand = 'touch_' + re.sub(r'(?<!^)(?=[A-Z])', '_', tid[5:]).lower()
    return cand.replace('__', '_')


def main():
    models = sorted(d for d in os.listdir(L2D) if os.path.isdir(os.path.join(L2D, d)))
    if ONLY:
        models = [m for m in models if m == ONLY]
    grand = {'a': 0, 'b': 0}
    for name in models:
        m3 = os.path.join(L2D, name, name + '.model3.json')
        mc = os.path.join(L2D, name, name + '.moc3')
        if not os.path.isfile(m3):
            continue
        d = json.load(open(m3, encoding='utf-8'))
        groups = list((d.get('FileReferences') or {}).get('Motions', {}).keys())
        gset = set(groups)
        try:
            raw = open(mc, 'rb').read()
        except OSError:
            continue
        touch = set(m.group(0).decode('ascii', 'ignore')
                    for m in re.finditer(rb'Touch[ -~]{1,20}?(?=[^\x20-\x7e])', raw))
        reg = set(h.get('Id') for h in (d.get('HitAreas') or []))
        missing = sorted(touch - reg)
        if not missing:
            continue
        ca, cb = [], []
        for tid in missing:
            cand = camel_to_snake(tid)
            alt = tid[5:].lower()
            if cand in gset or alt in gset:
                ca.append((tid, cand if cand in gset else alt))   # 明明有动作组却没登记 = 真 bug
            else:
                near = get_close_matches(cand, groups, n=2, cutoff=0.6)
                near2 = get_close_matches(alt, groups, n=2, cutoff=0.6)
                cb.append((tid, cand, near or near2))
        grand['a'] += len(ca); grand['b'] += len(cb)
        print('\n%s  未登记 %d 个（有动作组却漏=%d，无对应动作组=%d）' % (name, len(missing), len(ca), len(cb)))
        if ca:
            print('  ★ 真遗漏（动作组存在，规则没登记）:')
            for tid, g in ca:
                print('      %-16s → %s' % (tid, g))
        if cb:
            print('  无对应动作组（丢弃是对的），最接近的候选:')
            for tid, cand, near in cb[:14]:
                print('      %-16s 候选=%-20s 近似=%s' % (tid, cand, near))
            if len(cb) > 14:
                print('      ...另有 %d 个' % (len(cb) - 14))
    print('\n=== 合计：真遗漏 %d 个 / 无对应动作组 %d 个' % (grand['a'], grand['b']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
