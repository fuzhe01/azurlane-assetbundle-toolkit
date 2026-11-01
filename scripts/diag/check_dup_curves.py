"""验证假说：idle 里同一参数既有动画曲线又有定值曲线 → 定值覆盖动画。

背景（2026-10-24）：
  上一轮我用 L2D_MOTION_EMIT_CONST=1 补入了 ConstantClip 曲线，
  曲线数从 4487 涨到 23326。技能里说定值曲线是「复位指令」，
  但如果**同一参数既有 streamed 动画曲线、又有 constant 定值曲线**，
  两者在 Curves 数组里并存时，后写的那条会覆盖前一条 —— 动画被钉成定值。

  这正好解释用户看到的差异：旧画廊（无 constant 曲线）的 idle 脚是抬起的姿态，
  新画廊（有 constant）的脚姿势不对。

本脚本逐 clip 检查「同一 Id 出现多次」的情况，
并区分它是动画曲线（段长 > 5，有中段关键帧）还是定值曲线（5 元素且首末相同）。

用法: py -3 scripts/diag/check_dup_curves.py ougen_8
"""
import json
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
NEW = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')
OLD = os.path.join(r'D:\Azur Lane Assets\Output\Live2D', KEY, 'motion')


def is_const(segs):
    return len(segs) == 5 and abs(segs[1] - segs[-1]) < 1e-9


def analyze(path):
    d = json.load(open(path, encoding='utf-8'))
    seen = defaultdict(list)
    for c in d.get('Curves', []):
        s = c.get('Segments') or []
        seen[c.get('Id')].append(('const' if is_const(s) else 'anim', len(s),
                                 s[1] if len(s) > 1 else None,
                                 s[-1] if s else None))
    return seen, len(d.get('Curves', []))


def main():
    print('%-16s %8s %8s %10s' % ('clip', '旧曲线', '新曲线', '重复Id'))
    dup_total = 0
    bad_examples = []
    clips = sorted(f[:-len('.motion3.json')] for f in os.listdir(NEW)
                   if f.endswith('.motion3.json'))
    for clip in clips:
        pn = os.path.join(NEW, clip + '.motion3.json')
        po = os.path.join(OLD, clip + '.motion3.json')
        if not os.path.exists(pn) or not os.path.exists(po):
            continue
        seen_n, tot_n = analyze(pn)
        seen_o, tot_o = analyze(po)
        dups = {k: v for k, v in seen_n.items() if len(v) > 1}
        if dups:
            dup_total += len(dups)
        if len(dups) <= 12:
            print('%-16s %8d %8d %10d' % (clip, tot_o, tot_n, len(dups)))
        else:
            print('%-16s %8d %8d %10d  <<<' % (clip, tot_o, tot_n, len(dups)))
        # 记录「既动画又定值」的典型
        for pid, lst in dups.items():
            kinds = set(x[0] for x in lst)
            if 'anim' in kinds and 'const' in kinds:
                bad_examples.append((clip, pid, lst))

    print('\n合计重复 Id: %d' % dup_total)
    print('\n=== 「同一参数既动画又定值」的样例（定值会覆盖动画）===')
    print('共 %d 处' % len(bad_examples))
    for clip, pid, lst in bad_examples[:15]:
        print('  %-14s %-18s %s' % (clip, pid, lst))

    # 重点看 idle / mail
    print('\n=== idle / mail 的全部重复 Id ===')
    for clip in ('idle', 'mail'):
        pn = os.path.join(NEW, clip + '.motion3.json')
        if not os.path.exists(pn):
            continue
        seen_n, tot = analyze(pn)
        dups = {k: v for k, v in seen_n.items() if len(v) > 1}
        print('%s: 总曲线 %d，重复 Id %d 个' % (clip, tot, len(dups)))
        for pid, lst in list(dups.items())[:20]:
            print('   %-20s %s' % (pid, lst))
    return 0


if __name__ == '__main__':
    sys.exit(main())