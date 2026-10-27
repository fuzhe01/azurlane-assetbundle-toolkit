# -*- coding: utf-8 -*-
"""vanish_matrix.py — 批量驱动 vanish_can.py 跑「多模型 × 多动作组」的可见件扫描矩阵，
并把两组结果（如实验组 vs 官方参考组）逐组做绝对差对照。

为什么需要它：`vanish_can.py` 一次只能扫一个 --base + 一个 --ship，做 A/B 时必须
手工跑 N×M 次再人眼比对，极易漏组、也留不下可复核的原始数字。本脚本把
「跑 → 落盘 → 逐组求差 → 打表」固化成一条命令。

⚠️ 依赖一个活着的 8778 静态服务器（docroot = D:\\azur\\Output）。
   本机实测 `run_detached.py` 起的 8778 会静默死亡，必须用**附着的**后台 shell 保活。

用法:
  # 跑一组并落盘
  py -3 scripts/diag/vanish_matrix.py --base=../_ab/E --tag=E

  # 跑完后与另一组对照（逐组绝对差）
  py -3 scripts/diag/vanish_matrix.py --tag=E --vs=official

输出：
  .diag/vc2/<tag>_<model>.txt   原始 stdout（含完整 JSON）
  .diag/vc2/<tag>_<model>.json  解析后的指标
"""
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
VC = os.path.join(ROOT, '.diag', 'vc2')
VANISH = os.path.join(HERE, 'vanish_can.py')

MODELS = ['ougen_8', 'aersasi_2', 'aersasi_3', 'antu_2', 'benningdun_2']
GRPS = 'mail,mission,home,touch_head,touch_body,idle'
METRICS = ['neverSeen', 'alwaysSeen', 'partial', 'tailOff', 'flicker']


def arg(name, default=None):
    for a in sys.argv[1:]:
        if a == '--' + name:
            return True
        if a.startswith('--' + name + '='):
            return a.split('=', 1)[1]
    return default


def parse_stdout(text):
    i = text.find('\n{')
    if i < 0:
        i = text.find('{')
        if i < 0:
            return None
    try:
        return json.loads(text[i:])
    except Exception:
        return None


def _call(base, model, grps, fps, wait):
    url_args = ['--base=' + base, '--ship=' + model, '--grp=' + grps,
                '--fps=' + str(fps), '--gpu', '--wait=' + str(wait)]
    p = subprocess.run([sys.executable, VANISH] + url_args,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return (p.stdout or '') + (p.stderr or ''), p.returncode


def run_one(base, tag, model, grps, fps, wait, iso=False):
    t0 = time.time()
    # 隔离模式：每个动作组一个独立页面进程。
    # 为什么必须隔离——physics 是有状态积分器、部件 opacity 也不随 startMotion 复位，
    # 同一页面连续跑多组时，后一组会继承前一组留下的参数/物理状态，凭空翻出可见位差异。
    # 实测（aersasi_3）：连续 6 组跑 official 得 touch_body `#104~#109 全 A`，
    # 每组独立页面跑同一份数据得 `全 N`；而逐组独立页面对照下 E vs official 只剩 1 件换类。
    if iso:
        merged, rc_all = {}, 0
        for g in [x for x in grps.split(',') if x]:
            txt, rc = _call(base, model, g, fps, wait)
            d = parse_stdout(txt)
            if rc != 0 or not d:
                rc_all = rc or 1
            elif g in d:
                merged[g] = d[g]
        out = json.dumps(merged, ensure_ascii=False, indent=1)
        rc = rc_all
    else:
        out, rc = _call(base, model, grps, fps, wait)
    with open(os.path.join(VC, '%s_%s.txt' % (tag, model)), 'w', encoding='utf-8') as fh:
        fh.write(out)
    data = parse_stdout(out)
    if data:
        with open(os.path.join(VC, '%s_%s.json' % (tag, model)), 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
    return data, time.time() - t0, rc


def load_json(tag, model):
    p = os.path.join(VC, '%s_%s.json' % (tag, model))
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def fmt_row(name, vals):
    return '| %-13s | %s |' % (name, ' | '.join('%6s' % (v if v is not None else '-') for v in vals))


def main():
    os.makedirs(VC, exist_ok=True)
    tag = arg('tag')
    vs = arg('vs')
    base = arg('base')
    grps = arg('grp', None) or arg('grps', GRPS)
    fps = arg('fps', '30')
    wait = arg('wait', '900')
    models = arg('models', ','.join(MODELS)).split(',')
    iso = bool(arg('iso', False))

    if base and tag:
        print('== 采集 tag=%s base=%s grp=%s fps=%s%s =='
              % (tag, base, grps, fps, '  隔离(每组独立页面)' if iso else ''))
        for m in models:
            data, el, rc = run_one(base, tag, m, grps, fps, wait, iso=iso)
            if not data:
                print('%-13s FAIL rc=%s %.1fs' % (m, rc, el))
                continue
            tot = sum(data[g].get('frames', 0) for g in data if 'frames' in data[g])
            print('%-13s ok  %.1fs  组数=%d 帧合计=%d' % (m, el, len(data), tot))
        if not vs:
            return 0

    if not vs:
        print('需要 --vs=<另一 tag> 做对照，或 --base + --tag 采集')
        return 2

    print('\n== 逐组指标对照  %s vs %s ==' % (tag, vs))
    print('| 指标 | mail | mission | home | touch_head | touch_body | idle | 组数 |')
    print('|---|---|---|---|---|---|---|---|')
    order = [g for g in grps.split(',') if g]
    grand = {}
    for m in models:
        a = load_json(tag, m)
        b = load_json(vs, m)
        if not a or not b:
            print('%-13s (缺数据)' % m)
            continue
        dev = {}
        for g in order:
            if g not in a or g not in b:
                continue
            s = 0
            for k in METRICS:
                s += abs(int(a[g].get(k, 0)) - int(b[g].get(k, 0)))
            dev[g] = s
            grand[g] = grand.get(g, 0) + s
            # dur 一致性自检：两侧必须同 clip 同时长
            if abs(a[g].get('dur', 0) - b[g].get('dur', 0)) > 1e-3:
                print('  !! %s/%s dur 不一致: %s vs %s' % (m, g, a[g].get('dur'), b[g].get('dur')))
            if a[g].get('durSrc') not in (None, 'motion', 'json'):
                print('  !! %s/%s durSrc=%s（时长回退，结果不可信）'
                      % (m, g, a[g].get('durSrc')))
        print('| %-13s | %s | %4d |' % (m, ' | '.join('%6d' % dev.get(g, -1) for g in order),
                                        sum(dev.values())))
        # 明细：五指标分开看，便于判形态变化（neverSeen↑ 是修复的预期形态）
        for g in order:
            if dev.get(g, 0) == 0:
                continue
            print('   %-12s ' % g + '  '.join(
                '%s=%s/%s' % (k, a[g].get(k), b[g].get(k)) for k in METRICS))
            # 逐件分类串对照：定位到「哪一件换了类」以及换成了什么
            ca, cb = a[g].get('cls'), b[g].get('cls')
            if ca and cb and len(ca) == len(cb):
                ch = [(i, ca[i], cb[i]) for i in range(len(ca)) if ca[i] != cb[i]]
                if ch:
                    print('      逐件换类 %d 处: %s' % (len(ch), ', '.join(
                        '#%d %s->%s' % (i, x, y) for i, x, y in ch[:12])))
                else:
                    print('      逐件分类完全相同（差异只在帧级 flicker 计数，无件换类）')
    print('| %-13s | %s | %4d |' % ('合计', ' | '.join('%6d' % grand.get(g, 0) for g in order),
                                    sum(grand.values())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
