# -*- coding: utf-8 -*-
"""全库只读扫描：静态立绘的两类系统性影响面，一次跑完、不落任何产物。

① 负坐标裁切：compose() 现在按 `max(x+w)` / `max(y+h)` 开画布，**不减 min**，
   于是世界框落在负侧的部件被 PIL paste 静默裁掉（beier 的 `_rw` 丢了 33% 的落笔）。
   本脚本只加载 prefab 本体、不解析依赖包也不解码纹理，所以能全库跑。
② 半透明像素占比：canvas.paste(img, box, img) 对 RGBA 蒙版会把 alpha 平方
   （Pillow 文档 "scaling the alpha channel twice"）。这里只统计「画布上有多少
   个像素不是纯 0/纯 255」的**代理量**——真正的判据要渲出来才准，见 diag/alpha_squaring_diff.py。

用法:
  py -3 scripts/diag/painting_canvas_extent_scan.py            # 全库
  py -3 scripts/diag/painting_canvas_extent_scan.py beier ...  # 只扫指定皮肤
输出: .diag/negcoord_scan.tsv （名字 / 越界不透明像素估计 / 节点名）
"""
import sys, os, json, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import UnityPy
from UnityPy import config
import paths as P

config.FALLBACK_UNITY_VERSION = "2022.3.62f3"
ROOT = P.ROOT
OUT_TSV = os.path.join(ROOT, '.diag', 'negcoord_scan.tsv')


def scan_one(bundle_name):
    """只读 prefab 本体：算出「带 sprite 的节点」的世界框，返回负侧越界面积估计。"""
    import compose_paintings_v2 as C
    path = os.path.join(P.AB, "painting", bundle_name)
    if not os.path.isfile(path):
        return None
    env = UnityPy.load(path)
    objs = {o.path_id: o for o in env.objects}
    rects, go_names, father_map, children_map, rect_go, go_active = {}, {}, {}, {}, {}, {}
    spr_go = set()
    for o in env.objects:
        t = o.type.name
        if t == "RectTransform":
            r = o.read()
            rects[o.path_id] = r
            gp = getattr(getattr(r, "m_GameObject", None), "m_PathID", 0)
            g = objs.get(gp)
            go_names[o.path_id] = g.read().m_Name if g else ""
            rect_go[o.path_id] = gp
            if g is not None:
                go_active[gp] = bool(g.read().m_IsActive)
            father_map[o.path_id] = getattr(getattr(r, "m_Father", None), "m_PathID", 0) or 0
            children_map[o.path_id] = [getattr(c, "m_PathID", 0)
                                       for c in (getattr(r, "m_Children", None) or [])]
        elif t == "MonoBehaviour":
            d = o.read()
            sp = getattr(d, "m_Sprite", None)
            if sp is not None and getattr(sp, "m_PathID", 0):
                gp = getattr(getattr(d, "m_GameObject", None), "m_PathID", 0)
                if gp:
                    spr_go.add(gp)
    if not rects:
        return None
    boxes, mirrors, roots = C.layout_all(rects, father_map, children_map)

    def eff_active(rect_pid):
        seen, cur = set(), rect_pid
        while cur and cur not in seen:
            seen.add(cur)
            if not go_active.get(rect_go.get(cur), True):
                return False
            cur = father_map.get(cur) or 0
        return True

    neg = []
    for pid, b in boxes.items():
        if rect_go.get(pid) not in spr_go:
            continue
        if not eff_active(pid):
            continue
        x, y, w, h = b
        if x < -1 or y < -1:
            ax = max(0.0, -x) * max(0.0, min(w, -x + w))
            ay = max(0.0, -y) * max(0.0, min(h, -y + h))
            # 越界面积（px²）：左侧 + 下侧的 L 形，别重复计角落
            area = max(0.0, -x) * h + max(0.0, -(y)) * max(0.0, w - (-x))
            neg.append((go_names.get(pid, '?'), x, y, w, h, area))
    cw = int(max(b[0] + b[2] for b in boxes.values()))
    ch = int(max(b[1] + b[3] for b in boxes.values()))
    if not neg:
        return {'cw': cw, 'ch': ch, 'neg': []}
    return {'cw': cw, 'ch': ch, 'neg': neg}


def main():
    names = [os.path.basename(p)[:-4] for p in
             sorted(glob.glob(os.path.join(P.PAINT_OUT, '*.png')))]
    if len(sys.argv) > 1:
        names = [n.strip() for n in sys.argv[1:] if n.strip()]
    print(f'待扫 {len(names)} 个皮肤（只读 prefab 本体，不解码纹理）')
    rows = []
    for i, n in enumerate(names):
        try:
            r = scan_one(n)
        except Exception as e:
            print(f'  ! {n}: {e}')
            continue
        if r and r['neg']:
            tot = sum(x[5] for x in r['neg'])
            rows.append((n, r['cw'], r['ch'], tot,
                         ';'.join(f'{x[0]}@({x[1]:.0f},{x[2]:.0f},{x[3]:.0f}x{x[4]:.0f})'
                                  for x in r['neg'])))
        if (i + 1) % 400 == 0:
            print(f'  {i+1}/{len(names)} 命中 {len(rows)}')
    rows.sort(key=lambda t: -t[3])
    with open(OUT_TSV, 'w', encoding='utf-8', newline='') as f:
        f.write('skin\tcw\tch\tneg_area_px2\tnodes\n')
        for t in rows:
            f.write('\t'.join(str(x) for x in t) + '\n')
    print(f'\n=== 负坐标越界：{len(rows)} / {len(names)} 个皮肤命中 -> {OUT_TSV}')
    for t in rows[:40]:
        print(f'  {t[0]:26s} 画布{t[1]}x{t[2]}  越界面积≈{t[3]:,.0f} px²  {t[4][:80]}')


if __name__ == '__main__':
    main()
