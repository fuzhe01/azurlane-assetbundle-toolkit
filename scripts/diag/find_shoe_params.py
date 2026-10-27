"""定位「左脚/左腿在 idle 中不可见」的参数根因。

用户关键线索（2026-10-24）：
  旧画廊 ougen_8 idle 里左脚**穿着红底高跟鞋**；新画廊看不到。
  在红底高跟鞋位置点击 → 触发脱鞋局部动画 → 露出**穿黑丝袜的左脚**。
  ⇒ 左腿部件是存在的，只是被「脱鞋状态」隐藏了。

所以问题不是部件丢失，而是**某些状态参数停在了脱鞋后的值**。

本脚本做三件事：
  1. 从 moc3 取全部参数的 (min, max, default)
  2. 读 idle 动作里这些参数的实际值（我们的 motion3.json）
  3. 列出「动作里被写成非默认值」的参数 —— 尤其关注与鞋/脚/腿相关的命名

用法: py -3 scripts/diag/find_shoe_params.py ougen_8
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

import UnityPy  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
BUNDLE = os.path.join(ROOT, 'files', 'AssetBundles', 'live2d', KEY)
MD = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')


def moc3_idents(path):
    raw = open(path, 'rb').read()
    return set(m.group().decode() for m in re.finditer(rb'[A-Za-z_][A-Za-z0-9_]{2,40}', raw)), raw


def clip_const(clip):
    """5 元素定值曲线 {Id: value}"""
    p = os.path.join(MD, clip + '.motion3.json')
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding='utf-8'))
    out = {}
    for c in d.get('Curves', []):
        s = c.get('Segments') or []
        if len(s) == 5 and abs(s[1] - s[-1]) < 1e-9:
            out[c.get('Id')] = (s[1], c.get('Target'))
    return out


def main():
    idents, raw = moc3_idents(os.path.join(ROOT, 'Output', 'Live2D', KEY, KEY + '.moc3'))
    # 与鞋/脚/腿/手相关的标识符
    KW = ('Shoe', 'shoes', 'Heel', 'heel', 'Foot', 'foot', 'Leg', 'leg',
          'Hand', 'hand', 'Sock', 'sock', 'Stocking', 'stocking', 'Xie', 'xie', 'Jiao', 'jiao')
    related = sorted(i for i in idents if any(k in i for k in KW))
    print('moc3 中与鞋/脚/腿/手相关的标识符 (%d 个):' % len(related))
    for i in range(0, min(len(related), 60), 4):
        print('   ' + '  '.join('%-24s' % x for x in related[i:i + 4]))

    print('\n=== idle 里的定值曲线（非默认值的重点看）===')
    ci = clip_const('idle')
    print('idle 定值曲线数:', len(ci))
    # 找出与上面相关的
    hits = {k: v for k, v in ci.items() if any(kw in k for kw in KW)}
    print('其中与鞋/脚/腿/手相关:', len(hits))
    for k, v in sorted(hits.items()):
        print('   %-26s = %-8s target=%s' % (k, round(v[0], 3), v[1]))

    print('\n=== idle9 / mail 里同样的相关定值 ===')
    for clip in ('idle9', 'mail'):
        c = clip_const(clip)
        h = {k: v for k, v in c.items() if any(kw in k for kw in KW)}
        print('%s: 共 %d 定值，相关 %d' % (clip, len(c), len(h)))
        for k, v in sorted(h.items())[:20]:
            print('   %-26s = %-8s' % (k, round(v[0], 3)))


if __name__ == '__main__':
    sys.exit(main())