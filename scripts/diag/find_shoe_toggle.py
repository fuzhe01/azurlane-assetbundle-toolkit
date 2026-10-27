"""查「脱鞋」互动驱动哪些参数：用它反推「穿鞋状态」应该是哪组值。

用户线索（2026-10-24）：新画廊 ougen_8 idle 里看不到红底高跟鞋；
在红底高跟鞋位置点击 → 触发脱鞋局部动画 → 露出穿黑丝袜的左脚。
⇒ 存在一个「鞋子可见性」参数（多半是某 PartOpacity 或形态开关），idle 里它的值不对。

做法：
  1. 列出所有 clip 里 PartOpacity 类曲线（真正控制部件显隐的）
  2. 找出哪些 clip 动了这些部件 —— 特别是 touch_drag* / touch_* 系列
  3. 对比 idle 与「脱鞋动作」里同一部件的值

用法: py -3 scripts/diag/find_shoe_toggle.py ougen_8
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
MD = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')


def curves(clip):
    p = os.path.join(MD, clip + '.motion3.json')
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding='utf-8')).get('Curves', [])


def part_opacity_map(clip):
    """{PartId: 末帧值}"""
    cs = curves(clip)
    if cs is None:
        return {}
    out = {}
    for c in cs:
        if c.get('Target') == 'PartOpacity':
            s = c.get('Segments') or []
            if s:
                out[c.get('Id')] = s[-1]
    return out


def main():
    clips = sorted(f[:-len('.motion3.json')] for f in os.listdir(MD)
                   if f.endswith('.motion3.json'))
    print('clip 总数:', len(clips))

    # 统计每个 PartOpacity 部件被哪些 clip 改动、末帧值分布
    parts = {}
    for clip in clips:
        for pid, v in part_opacity_map(clip).items():
            parts.setdefault(pid, {})[clip] = v

    print('\n=== 有 PartOpacity 曲线的部件（真正控制显隐）===')
    for pid in sorted(parts):
        d = parts[pid]
        vals = sorted(set(round(v, 3) for v in d.values()))
        print('%-16s 出现于 %-3d 个 clip  末帧值集合 %s' % (pid, len(d), vals[:8]))

    if not parts:
        print('  （没有任何 PartOpacity 曲线）')
        # 退回：看 Parameter Target 里有没有疑似显隐/开关的参数
        print('\n=== 替代线索：所有 clip 中「值只在 0 和 1 之间切换」的参数 ===')
        cand = {}
        for clip in clips:
            cs = curves(clip) or []
            for c in cs:
                if c.get('Target') != 'Parameter':
                    continue
                s = c.get('Segments') or []
                if len(s) < 5:
                    continue
                vals = [s[i] for i in range(1, len(s)) if isinstance(s[i], (int, float))]
                if not vals:
                    continue
                if set(round(v, 3) for v in vals) <= {0.0, 1.0} and 0.0 in vals and 1.0 in vals:
                    cand.setdefault(c.get('Id'), set()).add(clip)
        for pid in sorted(cand, key=lambda x: -len(cand[x]))[:25]:
            print('%-22s 在 %-3d 个 clip 里 0↔1 切换' % (pid, len(cand[pid])))
    return 0


if __name__ == '__main__':
    sys.exit(main())