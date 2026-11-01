# -*- coding: utf-8 -*-
"""对单个 Live2D 样本，结构对比「reconstruct_live2d 版」与「AssetStudioModCLI -m live2d 版」的
moc3/physics3/model3，定位抖动根因（目前结论：moc3 逐字节一致，差异集中在 physics3 / model3）。

用法:
  py -3 scripts/diag/l2d_rec_vs_assetstudio_diff.py aersasi_2    # 样本名

汇总对比目标:
  Output/Live2D/<name>/<name>.moc3|.physics3.json|.model3.json      （reconstruct 版）
  .diag/l2d_as_<name>/Live2DOutput/Assets/ArtResource/Live2d/<name>/<name>/  （AS 版）
"""
import hashlib
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def md5(p):
    if not os.path.isfile(p):
        return None
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def main(name):
    rec = os.path.join(ROOT, 'Output', 'Live2D', name)
    asd = os.path.join(ROOT, '.diag', f'l2d_as_{name}', 'Live2DOutput',
                       'Assets', 'ArtResource', 'Live2d', name, name)
    if not (os.path.isdir(rec) and os.path.isdir(asd)):
        print(f'!! 目录不齐: rec={rec} as={asd}')
        sys.exit(2)

    for ext in ('.moc3', '.model3.json', '.physics3.json'):
        r = os.path.join(rec, name + ext)
        a = os.path.join(asd, name + ext)
        mr, ma = md5(r), md5(a)
        same = (mr == ma and mr is not None)
        print(f'[{("SAME" if same else "DIFF"):4}] {ext:<16} rec={mr} as={ma}')

    print('\n--- physics3 结构 ---')
    try:
        rp = json.load(open(os.path.join(rec, name + '.physics3.json'), encoding='utf-8'))
        ap = json.load(open(os.path.join(asd, name + '.physics3.json'), encoding='utf-8'))
    except Exception as e:
        print('!! physics3 解析失败:', e)
        return
    for tag, d in (('rec', rp), ('AS', ap)):
        ps = d.get('PhysicsSettings', [])
        tot = sum(len(p.get('Input', [])) + len(p.get('Output', [])) for p in ps)
        print(f'  {tag:<3} PhysicsGroups={len(ps):<4} 输入+输出条目={tot:<4} '
              f'各组输出曲线数={[len(p.get("Output", [])) for p in ps]}')
    # 组名对齐（Motion/Opacity 双输入常见）
    rk = [g.get('Name') for g in rp.get('PhysicsSettings', [])]
    ak = [g.get('Name') for g in ap.get('PhysicsSettings', [])]
    print(f'  rec 组名: {rk}')
    print(f'  AS  组名: {ak}')

    print('\n--- physics3 逐字段差异（rec 有 / AS 有 / 只在一侧）---')
    for gi, (rg, ag) in enumerate(zip(rp.get('PhysicsSettings', []), ap.get('PhysicsSettings', []))):
        for side, key in (('Input', 'Source'), ('Output', 'Destination')):
            for ri, (ri_e, ai_e) in enumerate(zip(rg.get(side, []), ag.get(side, []))):
                rk, ak = set(ri_e.keys()), set(ai_e.keys())
                missing = sorted(rk - ak)
                extra = sorted(ak - rk)
                if missing or extra:
                    print(f'  G{gi} {side}[{ri}] 只rec有字段={missing} 只AS有字段={extra}')
                    if missing:
                        print(f'    rec={ri_e}')
                        print(f'    as ={ai_e}')
        # 数值权重对比（同 key 都存在的条目，找数值不等的）
        for side in ('Input', 'Output'):
            for ri, (ri_e, ai_e) in enumerate(zip(rg.get(side, []), ag.get(side, []))):
                for k in sorted(set(ri_e) & set(ai_e)):
                    if ri_e[k] != ai_e[k]:
                        print(f'  G{gi} {side}[{ri}] {k}: rec={ri_e[k]!r} as={ai_e[k]!r}')

        # 组级字段差异（Normalization/Stiffness 等）
        rks, aks = set(rg.keys()), set(ag.keys())
        if rks != aks:
            print(f'  G{gi} 组级字段: 只rec有={sorted(rks-aks)} 只AS有={sorted(aks-rks)}')
        for k in sorted(rks & aks):
            if rg[k] != ag[k]:
                print(f'  G{gi} 组级 {k}: rec={rg[k]!r} as={ag[k]!r}')

    rm = json.load(open(os.path.join(rec, name + '.model3.json'), encoding='utf-8'))
    am = json.load(open(os.path.join(asd, name + '.model3.json'), encoding='utf-8'))
    for tag, d in (('rec', rm), ('AS', am)):
        print(f'  {tag:<3} keys={sorted(d.keys())}')
    for k in sorted(set(rm) | set(am)):
        if rm.get(k) != am.get(k):
            print(f'  差异键 {k}: rec={rm.get(k)} as={am.get(k)}')


def _motion_meta(p):
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:
        return None
    return d.get('Meta', {}), d.get('Curves', [])


def compare_motion(name, clip, rec, asd, max_show=3):
    """对比一个 motion3.json：曲线数 / 参数ID表 / 段结构。"""
    rp = os.path.join(rec, 'motion', clip + '.motion3.json')
    ap = os.path.join(asd, 'motions', clip + '.motion3.json')
    if not (os.path.isfile(rp) and os.path.isfile(ap)):
        print(f'  motion[{clip}] 缺: rec={os.path.isfile(rp)} as={os.path.isfile(ap)}')
        return
    rm, rc = _motion_meta(rp)
    am, ac = _motion_meta(ap)
    rid = [c.get('Id') for c in rc]
    aid = [c.get('Id') for c in ac]
    print(f'  motion[{clip}] rec {os.path.getsize(rp)}B/{len(rc)}曲线 '
          f'vs AS {os.path.getsize(ap)}B/{len(ac)}曲线')
    print(f'    参数ID: 仅rec={sorted(set(rid)-set(aid))[:5]} '
          f'仅AS={sorted(set(aid)-set(rid))[:5]} 共有={len(set(rid)&set(aid))}')
    for i, (rc_, ac_) in enumerate(zip(rc[:max_show], ac[:max_show])):
        rs, as_ = rc_.get('Segments', []), ac_.get('Segments', [])

        def seg_shape(segs):
            return [f'{s.get("SegmentCount", "?")}段/{len(s.get("Points", []))}点'
                    for s in segs[:2] if isinstance(s, dict)]
        print(f'    C{i} {rc_.get("Id")}: rec段={len(rs)} {seg_shape(rs)} '
              f'AS段={len(as_)} {seg_shape(as_)}')


def motion_diffs(name, rec, asd):
    print('\n--- 动作曲线对比（samples）---')
    for c in ('idle', 'home', 'main_1', 'touch_body', 'login'):
        compare_motion(name, c, rec, asd)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    name = sys.argv[1]
    main(name)
    rec_dir = os.path.join(ROOT, 'Output', 'Live2D', name)
    as_dir = os.path.join(ROOT, '.diag', f'l2d_as_{name}', 'Live2DOutput',
                          'Assets', 'ArtResource', 'Live2d', name, name)
    motion_diffs(name, rec_dir, as_dir)