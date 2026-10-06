# -*- coding: utf-8 -*-
"""一次性取证：三个用户报缺的皮肤（beier / baixue_2 / banerwei_2）。

回答三件事：
1. 节点树里每个 RectTransform 的名字 / 激活位 / 有没有 sprite / 世界框（含负坐标）
   —— 用于判「负坐标是否被画布裁掉」「有没有游戏里开着却被我们丢掉的层」。
2. 合成后画布之外被丢弃的像素量（paste 到负偏移 = 静默裁切）。
3. 成品里的「细空线」：一行/一列中被透明像素夹住的窄带。

用法: py -3 scripts/diag/painting_three_probe.py [bundle ...]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', '..'))


def tree(bundle):
    print('=' * 78)
    print(f'[{bundle}] 节点树')
    rects, go_names, father_map, children_map, parts, deps = C.parse_painting(bundle)
    boxes, mirrors, roots = C.layout_all(rects, father_map, children_map)
    order = C.draw_order(rects, father_map, children_map)
    depth = {}

    def d_of(pid):
        d, cur, seen = 0, pid, set()
        while cur and cur not in seen:
            seen.add(cur)
            cur = father_map.get(cur) or 0
            d += 1
        return d - 1

    by_rect = {}
    for p in parts:
        by_rect.setdefault(p['rect_pid'], []).append(p)
    print(f'  RectTransform {len(rects)} / 有 sprite 的部件 {len(parts)} / deps {len(deps)}')
    print(f'  {"序":>3} {"深":>2}  名                        激活  sprite部件                     世界框(x,y,wxh)')
    for i, pid in enumerate(order):
        r = rects[pid]
        b = boxes.get(pid)
        ps = by_rect.get(pid, [])
        nm = go_names.get(pid, '')
        act = all(x['active'] for x in ps) if ps else ''
        desc = ' , '.join(f"{x['name']}({x['spr_bundle'].split('/')[-1]})" for x in ps) or '-'
        bs = f'({b[0]:.0f},{b[1]:.0f},{b[2]:.0f}x{b[3]:.0f})' if b else '-'
        print(f'  {i:>3} {d_of(pid):>2}  {nm[:24]:24s}  {str(act):5s} {desc[:30]:30s} {bs}')
    xs = [b[0] for b in boxes.values()] + [b[0] + b[2] for b in boxes.values()]
    ys = [b[1] for b in boxes.values()] + [b[1] + b[3] for b in boxes.values()]
    print(f'  框并集 X [{min(xs):.0f} .. {max(xs):.0f}]  Y [{min(ys):.0f} .. {max(ys):.0f}]'
          f'   ← 负值部分会被当前画布 (0..max) 裁掉')
    neg = [(go_names.get(p, '?'), boxes[p]) for p in boxes if boxes[p][0] < -1 or boxes[p][1] < -1]
    for nm, b in sorted(neg, key=lambda t: t[1][0] + t[1][1]):
        print(f'    负坐标节点 {nm!r}: ({b[0]:.0f},{b[1]:.0f},{b[2]:.0f}x{b[3]:.0f})')


def clipped(bundle):
    """走真实渲染路径，量「paste 到画布外被丢掉多少不透明像素」。"""
    rects, go_names, father_map, children_map, parts, deps = C.parse_painting(bundle)
    kept = [p for p in parts if p.get('active', True) or p['name'] in C.FACE_SLOT_EXEMPT]
    boxes, mirrors, roots = C.layout_all(rects, father_map, children_map)
    order = C.draw_order(rects, father_map, children_map)
    allb = list(boxes.values())
    cw = int(max(b[0] + b[2] for b in allb))
    ch = int(max(b[1] + b[3] for b in allb))
    by_rect = {}
    for p in kept:
        by_rect.setdefault(p['rect_pid'], []).append(p)
    print(f'\n  [{bundle}] 画布 {cw}x{ch} 逐层越界量（走 build_part 真实路径）')
    tot_lost = 0
    for pid in order:
        for part in by_rect.get(pid, []):
            res = C.build_part(dict(part))
            if res is None:
                print(f'    {part["name"]!r}: build_part=None')
                continue
            arr, bbox, frame = res
            if C.is_lighting(arr):
                print(f'    {part["name"]!r}: lighting-skip（近纯白加算层，被启发式跳过）')
                continue
            a = arr[..., 3]
            rx, ry, rw, rh = boxes.get(pid, (0, 0, frame[0], frame[1]))
            sx = rw / frame[0] if frame[0] else 1
            sy = rh / frame[1] if frame[1] else 1
            x0, y0, x1, y1 = bbox
            mx, my = mirrors.get(pid, (False, False))
            if mx:
                x0, x1 = frame[0] - x1, frame[0] - x0
            if my:
                y0, y1 = frame[1] - y1, frame[1] - y0
            ww = max(1, int(round((x1 - x0) * sx)))
            wh = max(1, int(round((y1 - y0) * sy)))
            px = int(round(rx + x0 * sx))
            py = int(round(ch - (ry + y1 * sy)))
            # 逐像素：把 alpha 按同样仿射投到画布坐标，数落在外面多少
            opq = int((a > 10).sum())
            vx0, vy0 = max(0, -px), max(0, -py)
            vx1 = min(ww, cw - px)
            vy1 = min(wh, ch - py)
            if vx1 > vx0 and vy1 > vy0:
                sub = a[vy0:vy1, vx0:vx1]
                vis = int((sub > 10).sum())
            else:
                vis = 0
            lostpx = opq - vis
            tot_lost += max(0, lostpx)
            flag = '  ⚠ 被裁' if lostpx > opq * 0.02 and lostpx > 2000 else ''
            print(f'    {part["name"]!r:22s} 像素框({px},{py},{ww}x{wh}) 不透明{opq} '
                  f'画布外{max(0,lostpx)}{flag}')
    print(f'  合计画布外不透明像素 ≈ {tot_lost}')


def seams(path, name):
    """成品里的细空线：横向窄透明带（两侧不透明）。"""
    im = Image.open(path)
    a = np.asarray(im)
    al = a[..., 3]
    opq = al > 200
    h, w = al.shape
    print(f'\n  [{name}] 成品 {path} {w}x{h} 细缝扫描')
    hits = []
    for y in range(1, h - 1):
        row = opq[y]
        up, dn = opq[y - 1], opq[y + 1]
        # 这一行透明、上下两行同一列不透明 => 1px 横向裂缝
        bad = (~row) & up & dn
        n = int(bad.sum())
        if n > 30:
            xs = np.where(bad)[0]
            # 连续段
            runs = []
            s = xs[0]
            p = xs[0]
            for x in xs[1:]:
                if x > p + 1:
                    runs.append((s, p))
                    s = x
                p = x
            runs.append((s, p))
            longest = max(runs, key=lambda t: t[1] - t[0])
            hits.append((y, n, longest))
    hits.sort(key=lambda t: -t[2][1] - t[2][0])
    for y, n, (s, e) in hits[:12]:
        print(f'    y={y} 透明像素{n}，最长连续段 x∈[{s},{e}] 宽 {e - s + 1}')
    if not hits:
        print('    未发现 1px 横向裂缝（可能 ≥2px 宽，见下）')
    # 放宽到 2~4px 的窄带
    for band in (2, 3, 4):
        cnt = 0
        best = None
        for y in range(1, h - band - 1):
            mid = ~opq[y:y + band].all(axis=0)
            edge = opq[y - 1] & opq[y + band]
            bad = mid & edge
            n = int(bad.sum())
            if n > 30:
                cnt += 1
                if best is None or n > best[1]:
                    best = (y, n)
        print(f'    {band}px 宽带候选行数 {cnt}' + (f' 最强 y={best[0]} n={best[1]}' if best else ''))


if __name__ == '__main__':
    names = sys.argv[1:] or ['beier', 'baixue_2', 'banerwei_2']
    for b in names:
        tree(b)
        clipped(b)
        p = os.path.join(ROOT, 'Output', 'Paintings_v2', b + '.png')
        if os.path.isfile(p):
            seams(p, b)
