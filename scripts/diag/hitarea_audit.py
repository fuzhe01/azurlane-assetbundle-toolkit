r"""审计全库 HitAreas（判定区）生成结果：有没有遗漏、有没有不对应。

`fix_model3.py` 的生成规则（已读源码）：
  A. **占位替换**（仅当 Id 全部 ∈ {HitArea, HitArea2} 或为空）：
     只补 Head / Body / Special 三条，Id = `Touch<Area>`，Name 取候选里第一个存在的动作组。
  B. **补登记**（对所有模型）：扫 moc3 字节里的 `Touch*` 名字，
     拼出 `touch_<x>` 候选名，命中动作组才登记；命中不到就**丢弃**。

本脚本逐模型核对四类问题：
  ① **moc3 里有 Touch* drawable 但 model3 没登记**（遗漏）
  ② **登记了但 Id 不是 moc3 里真实存在的 drawable**（前端 getDrawableIndex 解析不到 → 点不到）
  ③ **登记了但 Name 不是该模型真实动作组**（点了播不出来）
  ④ **同一个 Name 被多条登记**（点哪儿都播同一个，属规则缺陷）

判据全部来自文件本身（model3.json + moc3 字节 + motion/ 目录），不需要浏览器。

用法：py -3 scripts/diag/hitarea_audit.py [--verbose]
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L2D = os.path.join(ROOT, 'Output', 'Live2D')
VERBOSE = '--verbose' in sys.argv


def moc3_touch_names(moc3_path):
    """从 moc3 字节里抠出所有 `Touch*` 名字（与 fix_model3.py 用同一正则）。"""
    try:
        raw = open(moc3_path, 'rb').read()
    except OSError:
        return set()
    out = set()
    for m in re.finditer(rb'Touch[ -~]{1,20}?(?=[^\x20-\x7e])', raw):
        out.add(m.group(0).decode('ascii', 'ignore'))
    return out


def main():
    if not os.path.isdir(L2D):
        print('找不到 %s' % L2D)
        return 2
    models = sorted(d for d in os.listdir(L2D) if os.path.isdir(os.path.join(L2D, d)))
    tot = {'models': 0, 'areas': 0, 'miss': 0, 'badid': 0, 'badname': 0, 'dup': 0}
    rows = []
    for name in models:
        m3 = os.path.join(L2D, name, name + '.model3.json')
        mc = os.path.join(L2D, name, name + '.moc3')
        if not os.path.isfile(m3):
            continue
        tot['models'] += 1
        try:
            d = json.load(open(m3, encoding='utf-8'))
        except Exception as e:
            print('  [读不了] %s: %s' % (name, e))
            continue
        hits = d.get('HitAreas') or []
        groups = list((d.get('FileReferences') or {}).get('Motions', {}).keys())
        gset = set(groups)
        touch = moc3_touch_names(mc)

        ids = [h.get('Id') for h in hits]
        nms = [h.get('Name') for h in hits]
        # ① 遗漏：moc3 有 Touch*，但既没登记 Id，也没有对应的动作组可用
        reg = set(i for i in ids if i)
        missing = sorted(t for t in touch if t not in reg)
        # ② Id 不在 moc3 的 Touch* 集合里（占位 Id 也算）
        badid = [i for i in ids if i and i not in touch]
        # ③ Name 不是真实动作组
        badname = [n for n in nms if n and n not in gset]
        # ④ 同一 Name 多条
        seen = {}
        for h in hits:
            seen.setdefault(h.get('Name'), []).append(h.get('Id'))
        dup = {k: v for k, v in seen.items() if len(v) > 1}

        tot['areas'] += len(hits)
        tot['miss'] += len(missing)
        tot['badid'] += len(badid)
        tot['badname'] += len(badname)
        tot['dup'] += len(dup)
        if missing or badid or badname or dup:
            rows.append((name, len(hits), len(touch), missing, badid, badname, dup))

    print('=== HitAreas 审计（%d 个模型 / %d 条判定区）' % (tot['models'], tot['areas']))
    print('   ① moc3 有 Touch* 但未登记 : %d 条（跨模型合计）' % tot['miss'])
    print('   ② 登记的 Id 不是真实 drawable: %d 条' % tot['badid'])
    print('   ③ 登记的 Name 不是动作组    : %d 条' % tot['badname'])
    print('   ④ 同一 Name 被多条登记      : %d 组' % tot['dup'])
    print('\n=== 有问题的模型：%d 个' % len(rows))
    for name, nh, nt, missing, badid, badname, dup in rows[:40]:
        print('\n  %-16s 登记 %-3d 条 / moc3 Touch* %-3d 个' % (name, nh, nt))
        if missing:
            print('     ① 未登记 %d 个: %s' % (len(missing), ', '.join(missing[:12]) + (' ...' if len(missing) > 12 else '')))
        if badid:
            print('     ② Id 不在 moc3: %s' % badid[:8])
        if badname:
            print('     ③ Name 不是动作组: %s' % badname[:8])
        if dup:
            print('     ④ 重名: %s' % dict(list(dup.items())[:5]))
    if len(rows) > 40:
        print('\n  ...另有 %d 个模型（省略）' % (len(rows) - 40))
    return 0


if __name__ == '__main__':
    sys.exit(main())
