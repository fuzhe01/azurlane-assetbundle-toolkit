r"""逐动作参数去向审计：切动作时哪些参数会被写、写成什么（只读）。

用途：回答「切到这个动作，某个参数会不会被拉回默认？」——**不靠猜、不靠运行时观察**，
逐个 motion3.json 解析曲线首末值 + 定值判定，把被监视参数（装扮类 + 动作状态类）在每个动作里的
取值列成表，最后汇总「每个参数出现在多少个动作、出现过哪些非零值」。

用法：py -3 scripts/diag/l2d_action_state_audit.py [模型]
输出建议重定向到文件再 grep（55 动作 × 15 参数的行会超过终端缓冲）。

判读要点（2026-10-28 ougen_8 实测结论）
  · 装扮类（Cloth1/2/3、Stock1/2、ShoseOff、Paramring、NeckMoney、BondEyes/HeartEyes/
    ParamEyeSmile）在 45~49 个动作里**全是定值 0** ⇒「切动作时鞋/丝袜被拉回默认」在数据层
    就是这么写的，不是前端 bug；要改只能靠 STATE_TOGGLES / costume pins 在运行时接管。
  · 动作状态类只有 KissShow / BoobHeart / ButtHeart1 / ButtHeart2 出现非零，与
    `build_motion_chain_map.ACTION_STATE_PARAMS` 的白名单**完全一致，无漏项**。
  · `login` 的 Stock1 是 1→0 的动画曲线（开场穿着→脱掉），别当成状态参数。
"""
import json, os, sys, glob
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
GAL = os.path.join(ROOT, 'Output', 'gallery_v2')
L2D = os.path.join(ROOT, 'Output', 'Live2D')
model = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
mdir = os.path.join(L2D, model)

cp = json.load(open(os.path.join(GAL, 'costume_params.json'), encoding='utf-8')).get(model) or []
costume = [r['id'] for r in cp]
pd = json.load(open(os.path.join(GAL, 'param_drawables.json'), encoding='utf-8')).get(model) or {}
mc = json.load(open(os.path.join(GAL, 'motion_chain.json'), encoding='utf-8'))['models'][model]
state = sorted((mc.get('state_params') or {}).keys())
print('costume_params :', costume)
print('param_drawables:', {k: len(v) for k, v in pd.items()})
print('state_params   :', state)
print('action_state   :', sorted(k for k, v in (mc.get('state_params') or {}).items()
                                if v.get('kind') == 'action_state'))


def parse(seg):
    """返回 [(type_or_None, t, v)] 的端点值列表 + const 判定。"""
    if not seg or len(seg) < 2:
        return None, None
    pts = [(None, float(seg[0]), float(seg[1]))]
    i = 2
    const = True
    while i < len(seg):
        t = seg[i]
        if t == 0 or t == 2:
            if i + 2 >= len(seg):
                break
            pts.append((t, float(seg[i + 1]), float(seg[i + 2])))
            i += 3
        elif t == 1:
            if i + 6 >= len(seg):
                break
            pts.append((t, float(seg[i + 5]), float(seg[i + 6])))
            i += 7
        elif t == 3:
            # InverseStepped 在某些导出版本里是 3 个数
            if i + 2 >= len(seg):
                break
            pts.append((t, float(seg[i + 1]), float(seg[i + 2])))
            i += 3
        else:
            break
    if len(pts) > 1:
        vals = {round(p[2], 4) for p in pts}
        const = len(vals) == 1
    return pts, const


def scan_group(g):
    defs = (mc.get('durations') or {})
    # 从 model3.json 拿 File
    m3 = None
    for p in glob.glob(os.path.join(mdir, '*.model3.json')):
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        if (d.get('FileReferences') or {}).get('Motions'):
            m3 = d
            break
    return m3


m3p = None
for p in glob.glob(os.path.join(mdir, '*.model3.json')):
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:
        continue
    if (d.get('FileReferences') or {}).get('Motions'):
        m3p = (p, d)
        break
motions = m3p[1]['FileReferences']['Motions']
print('\n动作组数:', len(motions))

COST = set(costume)
watch = COST | set(state)
rows = []
for g, entries in sorted(motions.items()):
    f = os.path.join(mdir, entries[0]['File'])
    if not os.path.isfile(f):
        continue
    j = json.load(open(f, encoding='utf-8'))
    hits = {}
    ndrv = 0
    for c in j.get('Curves') or []:
        if c.get('Target') != 'Parameter':
            continue
        pid = c.get('Id')
        ndrv += 1
        if pid in watch:
            pts, const = parse(c.get('Segments') or [])
            hits[pid] = {'start': pts[0][2] if pts else None,
                         'end': pts[-1][2] if pts else None,
                         'const': const}
    dur = (j.get('Meta') or {}).get('Duration')
    rows.append((g, dur, j.get('Meta', {}).get('Loop'), ndrv, hits))

print('\n%-24s %7s %-6s %5s  %s' % ('group', 'dur', 'loop', 'nCur', 'watched params (start→end const?)'))
for g, dur, loop, ndrv, hits in rows:
    if not hits:
        desc = '—'
    else:
        desc = '  '.join('%s:%.3f→%.3f%s' % (k, v['start'], v['end'], '*' if v['const'] else '')
                         for k, v in sorted(hits.items()))
    print('%-24s %7s %-6s %5d  %s' % (g, dur, loop, ndrv, desc))

print('\n*  = 整条曲线只有一个值（定值）')

# 汇总：每个 watch 参数出现在多少个动作里、有没有非零
print('\n=== 汇总：每个被监视参数在各动作里的取值分布 ===')
for p in sorted(watch):
    vals = []
    ng = 0
    for g, dur, loop, ndrv, hits in rows:
        if p in hits:
            ng += 1
            vals.append((g, hits[p]['start'], hits[p]['end'], hits[p]['const']))
    nz = [v for v in vals if abs(v[1]) > 0.5 or abs(v[2]) > 0.5]
    print('%-16s 出现 %2d/%d 个动作  非零取值 %d 个 %s'
          % (p, ng, len(rows), len(nz),
             ('→ ' + ', '.join('%s:%.2f→%.2f' % (a, b, c) for a, b, c, _ in nz[:6])) if nz else ''))
