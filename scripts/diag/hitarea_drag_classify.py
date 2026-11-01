r"""逐标记分类：TouchDragN 到底该播动作、该切参数、还是两者都没有。

用户指出的关键点：「点击标记区 touchdrag16 对应的应该是**丝袜参数变化**，而不是动作。
脚本检查不到动作、没有动作组 —— 是不是脚本有问题可以优化？」

旧脚本（`hitarea_drag_fallback_audit.py`）只算了「动作组落点」，把「该接参数的标记」
也算成了「回退播别人动作」。本脚本补上**参数**这一维，分四类：

  A `action`   有真同名动作组 `touch_dragN`           → 播动作，正确
  B `param`    无同名动作组，但有**同名参数** `touch_dragN` → 应接成**参数切换**（游戏就是这样）
  C `both`     两者都有                              → 播动作 + 同时写参数（游戏常见）
  D `orphan`   两者都没有                            → **不该回退播无关动作**，应无事发生

另需检查「参数型互动区」两个来源：
  · `STATE_TOGGLES`（手工接线，现只有 ougen_8/touchdrag17 → ShoseOff 一条）
  · 装扮参数热区（`param_drawables.json` 自动生成，不需要 trigger 名）

判据全部来自文件（model3.json + moc3 字节 + costume_params.json + param_drawables.json），
不需要浏览器。

用法：
  py -3 scripts/diag/hitarea_drag_classify.py               # 汇总
  py -3 scripts/diag/hitarea_drag_classify.py --detail      # 逐条
  py -3 scripts/diag/hitarea_drag_classify.py --model ougen_8
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L2D = os.path.join(ROOT, 'Output', 'Live2D')
GAL = os.path.join(ROOT, 'Output', 'gallery_v2')

DETAIL = '--detail' in sys.argv
ONLY = None
if '--model' in sys.argv:
    ONLY = sys.argv[sys.argv.index('--model') + 1]


def load_json(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return None


def main():
    costume = load_json(os.path.join(GAL, 'costume_params.json')) or {}
    pdraw = load_json(os.path.join(GAL, 'param_drawables.json')) or {}

    models = sorted(d for d in os.listdir(L2D) if os.path.isdir(os.path.join(L2D, d)))
    if ONLY:
        models = [m for m in models if m == ONLY]
    grand = {'action': 0, 'param': 0, 'both': 0, 'orphan': 0}
    grand_fb = 0
    rows_all = []

    for name in models:
        m3 = os.path.join(L2D, name, name + '.model3.json')
        mc = os.path.join(L2D, name, name + '.moc3')
        if not os.path.isfile(m3):
            continue
        d = json.load(open(m3, encoding='utf-8'))
        groups = list((d.get('FileReferences') or {}).get('Motions', {}).keys())
        gset = set(groups)
        ds = [g for g in groups if re.match(r'^touch_drag\d+$', g)]
        # 该模型**参数**名（从 param_drawables 的键拿不到全量，用 costume 表 + 命名推测不够；
        # 真正的全量参数名要从 moc3 读，但这里用「该模型的参数表」——param_drawables 里
        # 只登记了装扮参数。故额外从 moc3 字节里找形如 touch_dragN 的参数名。
        try:
            raw = open(mc, 'rb').read()
        except OSError:
            raw = b''
        touch = sorted(set(m.group(0).decode('ascii', 'ignore')
                           for m in re.finditer(rb'Touch[ -~]{1,20}?(?=[^\x20-\x7e])', raw)))
        # moc3 里同时存参数名与 drawable 名；touch_dragN 若作为参数存在，会以该形态出现
        params_in_moc3 = set(m.group(0).decode('ascii', 'ignore')
                             for m in re.finditer(rb'[A-Za-z_][A-Za-z0-9_]{1,40}', raw))

        rows = []
        for tid in touch:
            low = tid.lower()
            if not re.match(r'^touchdrag\d+$', low):
                continue
            n = int(re.match(r'^touchdrag(\d+)$', low).group(1))
            act = 'touch_drag%d' % n
            has_act = act in gset
            has_param = act in params_in_moc3
            if has_act and has_param:
                kind = 'both'
            elif has_act:
                kind = 'action'
            elif has_param:
                kind = 'param'
            else:
                kind = 'orphan'
            # 前端会不会回退（有任意 touch_drag 组就会）
            fb = None
            if not has_act and ds:
                fb = ds[(n - 1) % len(ds)]
            rows.append((tid, act, kind, has_act, has_param, fb))
            grand[kind] += 1
            if fb:
                grand_fb += 1
        if rows:
            rows_all.append((name, ds, rows))

    print('=== TouchDrag* 逐标记分类（判据：动作组 + moc3 里是否也有同名参数）')
    print('    A action = 有同名动作组（正确播动作）')
    print('    B param  = 无动作组但有同名参数（**应该接成参数切换**）')
    print('    C both   = 两者都有')
    print('    D orphan = 两者都没有（不该回退播无关动作）\n')
    print('  合计 %d 个标记：' % sum(grand.values()))
    for k, label in (('action', 'A 有动作组'), ('both', 'C 动作+参数'),
                     ('param', 'B ★只有参数（旧脚本误判为回退）'),
                     ('orphan', 'D ★两者都无')):
        print('    %-34s %d' % (label, grand[k]))
    print('    会被前端回退到别的动作组的: %d' % grand_fb)

    print('\n=== 逐模型')
    for name, ds, rows in rows_all:
        cnt = {}
        for r in rows:
            cnt[r[2]] = cnt.get(r[2], 0) + 1
        print('\n  %-14s 标记 %-3d A%-3d B%-3d C%-3d D%-3d   可用 drag 组 %s'
              % (name, len(rows), cnt.get('action', 0), cnt.get('param', 0),
                 cnt.get('both', 0), cnt.get('orphan', 0), ds))
        if DETAIL or ONLY:
            for tid, act, kind, ha, hp, fb in rows:
                mark = {'action': '  ', 'both': '  ', 'param': '★B', 'orphan': '★D'}[kind]
                extra = '' if not fb else ('  回退→%s' % fb)
                print('     %s %-16s 动作组=%-5s 参数=%-5s%s'
                      % (mark, tid, ha, hp, extra))
    return 0


if __name__ == '__main__':
    sys.exit(main())
