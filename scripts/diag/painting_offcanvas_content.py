# -*- coding: utf-8 -*-
"""内容级测量：负坐标节点到底让多少**不透明像素**落在画布外被静默裁掉。

`painting_canvas_extent_scan.py` 只量 RectTransform 框，框越界不等于内容越界
（美术常把透明留白伸到框外）。本脚本走 compose 的真实路径逐层 build_part，
把每层的 alpha 按同一套仿射投到画布坐标，数「落在 [0,cw)x[0,ch) 之外」的不透明像素。

判据：`lost / opaque >= 1%` 且 `lost >= 2000 px` 才算真丢内容。
用法: py -3 scripts/diag/painting_offcanvas_content.py [skin ...]
      不给参数时读 .diag/negcoord_scan.tsv 的命中清单
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C
import paths as P

ROOT = P.ROOT
TSV = os.path.join(ROOT, '.diag', 'negcoord_scan.tsv')
OUT = os.path.join(ROOT, '.diag', 'offcanvas_content.tsv')


def measure(bundle_name):
    rects, go_names, fm, cm, parts, deps = C.parse_painting(bundle_name)
    kept = [p for p in parts if p.get('active', True) or p['name'] in C.FACE_SLOT_EXEMPT]
    if not kept:
        kept = parts
    boxes, mirrors, roots = C.layout_all(rects, fm, cm)
    order = C.draw_order(rects, fm, cm)
    allb = list(boxes.values())
    cw = int(max(b[0] + b[2] for b in allb))
    ch = int(max(b[1] + b[3] for b in allb))
    by_rect = {}
    for p in kept:
        by_rect.setdefault(p['rect_pid'], []).append(p)
    tot_opq = tot_lost = 0
    detail = []
    for pid in order:
        for part in by_rect.get(pid, []):
            try:
                res = C.build_part(dict(part))
            except Exception as e:
                detail.append(f'{part["name"]}:ERR')
                continue
            if res is None:
                continue
            arr, bbox, frame = res
            if C.is_lighting(arr):
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
            # 把 alpha 按同一步长重采样到像素框，再数画布外
            img = np.asarray(
                Image.fromarray(a.astype(np.uint8), 'L').resize((ww, wh)))
            opq = int((img > 10).sum())
            vx0, vy0 = max(0, -px), max(0, -py)
            vx1, vy1 = min(ww, cw - px), min(wh, ch - py)
            vis = int((img[vy0:vy1, vx0:vx1] > 10).sum()) if vx1 > vx0 and vy1 > vy0 else 0
            lost = max(0, opq - vis)
            tot_opq += opq
            tot_lost += lost
            if lost > 2000:
                detail.append(f'{part["name"]}:{lost}')
    return cw, ch, tot_opq, tot_lost, detail


def main():
    from PIL import Image  # noqa
    names = [n.strip() for n in sys.argv[1:] if n.strip()]
    if not names:
        with open(TSV, encoding='utf-8') as f:
            next(f)
            names = [l.split('\t')[0] for l in f if l.strip()]
    print(f'待量 {len(names)} 个皮肤')
    rows = []
    for i, n in enumerate(names):
        try:
            cw, ch, opq, lost, det = measure(n)
        except Exception as e:
            print(f'  ! {n}: {e}')
            continue
        if opq and lost / opq >= 0.01 and lost >= 2000:
            rows.append((n, cw, ch, opq, lost, lost / opq, ';'.join(det)))
        if (i + 1) % 20 == 0:
            print(f'  {i+1}/{len(names)} 真丢内容 {len(rows)}', flush=True)
    rows.sort(key=lambda t: -t[4])
    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        f.write('skin\tcw\tch\topaque_px\toffcanvas_opaque_px\tratio\tlayers\n')
        for t in rows:
            f.write(f'{t[0]}\t{t[1]}\t{t[2]}\t{t[3]}\t{t[4]}\t{t[5]:.4f}\t{t[6]}\n')
    print(f'\n=== {len(rows)} / {len(names)} 个皮肤确有内容被画布裁掉 -> {OUT}')
    for t in rows:
        print(f'  {t[0]:26s} 画布{t[1]}x{t[2]:<6} 不透明{t[3]:>9,} 裁掉{t[4]:>9,} ({t[5]*100:5.1f}%)  {t[6][:70]}')


if __name__ == '__main__':
    main()
