# -*- coding: utf-8 -*-
"""F2（合成算子 paste -> alpha_composite）换算法前的**门控翻转全库预演**——只读，不落任何产物。

为什么要它：叠脸门控读的是画布 alpha（`>=250` 算不透明）。旧算子把 alpha 平方，
于是源 alpha=250 被压成 245、刚好跌破 250 ⇒ 旧口径**系统性低估不透明度**，
可能把「脸已烤好」误判成洞而多叠一层（gezi_2 就是这么把睁眼换成闭眼发出去的）。
47 个带标签样本只翻 1 条，但那只是 47 个 —— 换算法等于换分类器，必须在**全库候选**上重扫。

每条翻转都配一个「materiality」：同一张图叠脸 vs 不叠脸到底差多少像素。
差 0 像素的翻转是无操作，不算事；差得多才需要人看。

用法: py -3 scripts/diag/face_gate_flip_scan.py [--n K]
输出: .diag/face_gate_flips.tsv + .diag/face_gate_flips.log（末行 FLIPSCAN-DONE 是完成哨兵）
"""
import sys, os, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C
import paths as P

ROOT = P.ROOT
TSV = os.path.join(ROOT, '.diag', 'face_gate_flips.tsv')
CAND_DIR = os.path.join(P.AB, 'paintingface')


def build(bundle):
    """解析 + 逐层光栅化一次，供两种算子复用（省一半纹理解码）。"""
    rects, go_names, fm, cm, parts, deps = C.parse_painting(bundle)
    kept = [p for p in parts if p.get('active', True) or p['name'] in C.FACE_SLOT_EXEMPT] or parts
    boxes, mirrors, roots = C.layout_all(rects, fm, cm)
    order = C.draw_order(rects, fm, cm)
    allb = list(boxes.values())
    cw = int(max(b[0] + b[2] for b in allb))
    ch = int(max(b[1] + b[3] for b in allb))
    by_rect = {}
    for p in kept:
        by_rect.setdefault(p['rect_pid'], []).append(p)
    layers = []
    for pid in order:
        for part in by_rect.get(pid, []):
            try:
                res = C.build_part(dict(part))
            except Exception:
                continue
            if res is None:
                continue
            arr, bbox, frame = res
            if C.is_lighting(arr):
                continue
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
            img = Image.fromarray(arr.astype(np.uint8), 'RGBA').transpose(Image.FLIP_TOP_BOTTOM)
            if mx:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            if my:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            if (img.width, img.height) != (ww, wh):
                img = img.resize((ww, wh), Image.BILINEAR)
            layers.append((img, (int(round(rx + x0 * sx)), int(round(ch - (ry + y1 * sy))), ww, wh)))
    face_pid = next((rp for rp in rects if go_names.get(rp) == 'face'), None)
    rect = fimg = None
    if face_pid is not None and face_pid in boxes:
        rx, ry, rw, rh = boxes[face_pid]
        fpx, fpy = int(round(rx)), int(round(ch - (ry + rh)))
        fww, fwh = max(1, int(round(rw))), max(1, int(round(rh)))
        rect = (fpx, fpy, fww, fwh)
        fx = C.paintingface_face(bundle, os.environ.get('FACE_DEFAULT', '1'))
        if fx is not None and fww > 8 and fwh > 8:
            fimg, _ = fx
            mx, my = mirrors.get(face_pid, (False, False))
            fimg = fimg.transpose(Image.FLIP_TOP_BOTTOM)
            if mx:
                fimg = fimg.transpose(Image.FLIP_LEFT_RIGHT)
            if my:
                fimg = fimg.transpose(Image.FLIP_TOP_BOTTOM)
            if (fimg.width, fimg.height) != (fww, fwh):
                fimg = fimg.resize((fww, fwh), Image.BILINEAR)
    return layers, rect, fimg, cw, ch


def paint(layers, cw, ch, source_over, face=None):
    c = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    items = list(layers) + ([face] if face else [])
    for img, (px, py, ww, wh) in items:
        if source_over:
            x0, y0 = max(0, px), max(0, py)
            x1, y1 = min(cw, px + ww), min(ch, py + wh)
            if x1 <= x0 or y1 <= y0:
                continue
            sub = img.crop((x0 - px, y0 - py, x1 - px, y1 - py))
            c.paste(Image.alpha_composite(c.crop((x0, y0, x1, y1)), sub), (x0, y0))
        else:
            c.paste(img, (px, py), img)
    return c


def gate(canvas, rect, fimg, mad_max):
    if rect is None or fimg is None:
        return None
    fpx, fpy, fww, fwh = rect
    sp = np.asarray(fimg).astype(int)
    foot = sp[..., 3] > 200
    n = int(foot.sum())
    if n < 64:
        return None
    sub = np.asarray(canvas.crop((fpx, fpy, fpx + fww, fpy + fwh))).astype(int)
    opq = (sub[..., 3] >= 250) & foot
    frac = float(opq.sum()) / n
    mad = float(np.abs(sp[..., :3] - sub[..., :3])[opq].mean()) if int(opq.sum()) >= 64 else None
    hole = frac < C.FACE_OPAQUE_MIN or mad is None or mad > mad_max
    return {'frac': frac, 'mad': mad, 'hole': hole}


def main():
    n_lim = None
    if '--n' in sys.argv:
        n_lim = int(sys.argv[sys.argv.index('--n') + 1])
    # 两侧阈值分开：旧侧必须用**当时真正生效**的 30，新侧用重标后的值 ——
    # 要回答的是「相对已发出去的产物，哪些皮肤贴脸决定会变」，不是「两个阈值差多少」。
    mad_old = float(sys.argv[sys.argv.index('--mad-old') + 1]) if '--mad-old' in sys.argv else 30.0
    mad_new = float(sys.argv[sys.argv.index('--mad-new') + 1]) if '--mad-new' in sys.argv else C.FACE_MAD_MAX
    print(f'对比：旧算子+MAD>{mad_old:g}  vs  新算子+MAD>{mad_new:g}', flush=True)
    stems = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(P.PAINT_OUT, '*.png')))
    cands = [s for s in stems if os.path.isfile(os.path.join(CAND_DIR, s))]
    if n_lim:
        cands = cands[:n_lim]
    print(f'候选 {len(cands)} / 产物 {len(stems)}（有同名 paintingface 包）', flush=True)
    rows = []
    n_no_face = n_err = 0
    for i, b in enumerate(cands):
        try:
            C._env_cache.clear(); C._obj_cache.clear(); C._img_cache.clear()
            layers, rect, fimg, cw, ch = build(b)
            if rect is None:
                n_no_face += 1
                continue
            g0 = gate(paint(layers, cw, ch, False), rect, fimg, mad_old)
            g1 = gate(paint(layers, cw, ch, True), rect, fimg, mad_new)
        except Exception as e:
            n_err += 1
            if n_err <= 10:
                print(f'  ! {b}: {type(e).__name__} {e}', flush=True)
            continue
        if (i + 1) % 100 == 0:
            print(f'  …{i+1}/{len(cands)} 翻转 {len(rows)} / 出错 {n_err} / 无 face 槽 {n_no_face}',
                  flush=True)
        if g0 is None or g1 is None:
            continue
        d0, d1 = ('洞' if g0['hole'] else '好脸'), ('洞' if g1['hole'] else '好脸')
        if d0 == d1:
            continue
        # materiality：同算法(新)下 叠脸 vs 不叠脸差多少像素
        cn = paint(layers, cw, ch, True)
        cy = paint(layers, cw, ch, True, face=(fimg, rect))
        A, B = np.asarray(cn).astype(np.int16), np.asarray(cy).astype(np.int16)
        dd = np.abs(A - B)
        vis = int((dd.sum(axis=2) >= 12).sum())
        rows.append({'skin': b, 'old': d0, 'new': d1,
                     'old_op': round(g0['frac'], 4), 'new_op': round(g1['frac'], 4),
                     'old_mad': None if g0['mad'] is None else round(g0['mad'], 1),
                     'new_mad': None if g1['mad'] is None else round(g1['mad'], 1),
                     'vis_px': vis, 'max_d': int(dd.max()), 'size': f'{cw}x{ch}'})
        print(f'  ⚠ {b} {d0}->{d1}  op {g0["frac"]:.3f}->{g1["frac"]:.3f} '
              f'MAD {g0["mad"]}->{g1["mad"]}  叠/不叠可见差 {vis:,} 像素', flush=True)
    rows.sort(key=lambda r: -r['vis_px'])
    with open(TSV, 'w', encoding='utf-8', newline='') as f:
        f.write(json.dumps({'candidates': len(cands), 'no_face_slot': n_no_face,
                            'errors': n_err, 'flips': len(rows)}, ensure_ascii=False) + '\n')
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'\n=== 扫完 {len(cands)} 个候选：无 face 槽 {n_no_face} / 出错 {n_err} / **翻转 {len(rows)}**')
    mat = [r for r in rows if r['vis_px'] > 0]
    print(f'  其中有可见差异的 {len(mat)} 个；方向分布：'
          f'洞->好脸 {sum(1 for r in rows if r["old"]=="洞" and r["new"]=="好脸")}，'
          f'好脸->洞 {sum(1 for r in rows if r["old"]=="好脸" and r["new"]=="洞")}')
    for r in mat[:40]:
        print(f'  {r["skin"]:24s} {r["old"]}->{r["new"]}  可见差 {r["vis_px"]:>9,} 像素 '
              f'最大Δ{r["max_d"]:>3}  op {r["old_op"]}->{r["new_op"]} MAD {r["old_mad"]}->{r["new_mad"]}')
    print(f'\n明细 -> {TSV}')
    print('FLIPSCAN-DONE', flush=True)


if __name__ == '__main__':
    main()
