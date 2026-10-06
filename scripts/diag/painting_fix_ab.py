# -*- coding: utf-8 -*-
"""立绘合成两处系统性偏差的 A/B 验证（**只写临时目录，不碰正式产物**）。

候选修法两条，分别可开关，用来回答「改了会变成什么样」：
  F1 画布口径：现在按 `max(x+w)`/`max(y+h)` 开画布、**不减 min** ⇒ 世界框/内容落在
     负侧的部件被 PIL paste 静默裁掉（beier 的 `_rw` 丢 15%）。F1 = 按内容并集 min→max。
  F2 合成算子：现在每层用 `canvas.paste(img, box, img)`。Pillow 对 RGBA 蒙版会
     **「把 alpha 通道缩放两次」**（官方文档原话），即 dst_a' = dst_a·(1-m) + src_a·m，
     m = src_a/255 ⇒ 铺在空画布上时 src_a=128 变成 64。实测在盘产物 99.8% 的
     半透明像素满足 a' = a²/255。F2 = 改用 Image.alpha_composite（标准 source-over）。

用法: py -3 scripts/diag/painting_fix_ab.py <skin> [skin ...] [--f1] [--f2]
输出: .diag/fix_ab/<skin>__old.png / __new.png / __CMP.png
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C
import paths as P

ROOT = P.ROOT
OUT = os.path.join(ROOT, '.diag', 'fix_ab')
os.makedirs(OUT, exist_ok=True)


def layer_images(bundle):
    """走 compose 的真实解析/布局/光栅化路径，返回 [(name, PIL RGBA, 画布像素框)] + 元信息。"""
    rects, go_names, fm, cm, parts, deps = C.parse_painting(bundle)
    kept = [p for p in parts if p.get('active', True) or p['name'] in C.FACE_SLOT_EXEMPT] or parts
    boxes, mirrors, roots = C.layout_all(rects, fm, cm)
    order = C.draw_order(rects, fm, cm)
    by_rect = {}
    for p in kept:
        by_rect.setdefault(p['rect_pid'], []).append(p)
    # 画布原点先按「rect 并集的 max」定（与正本一致），F1 再按内容并集整体平移
    cw = int(max(b[0] + b[2] for b in boxes.values()))
    ch = int(max(b[1] + b[3] for b in boxes.values()))
    face_pid = next((rp for rp in rects if go_names.get(rp) == 'face'), None)
    out = []
    for pid in order:
        for part in by_rect.get(pid, []):
            res = C.build_part(dict(part))
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
            px = int(round(rx + x0 * sx))
            py = int(round(ch - (ry + y1 * sy)))
            out.append((part['name'] or str(pid), img, (px, py, ww, wh)))
    # face 叠层（用正本的同一判据：渲一次拿 FACE_GATE）
    face_img = None
    if face_pid is not None:
        rx, ry, rw, rh = boxes[face_pid]
        fpx, fpy = int(round(rx)), int(round(ch - (ry + rh)))
        fww, fwh = max(1, int(round(rw))), max(1, int(round(rh)))
        C.compose(bundle, OUT, save=False)
        g = C.FACE_GATE.get(bundle)
        if g and g.get('hole'):
            fx = C.paintingface_face(bundle, os.environ.get('FACE_DEFAULT', '1'))
            if fx:
                fimg, _ = fx
                mx, my = mirrors.get(face_pid, (False, False))
                fimg = fimg.transpose(Image.FLIP_TOP_BOTTOM)
                if mx:
                    fimg = fimg.transpose(Image.FLIP_LEFT_RIGHT)
                if my:
                    fimg = fimg.transpose(Image.FLIP_TOP_BOTTOM)
                if (fimg.width, fimg.height) != (fww, fwh):
                    fimg = fimg.resize((fww, fwh), Image.BILINEAR)
                face_img = (fimg, (fpx, fpy, fww, fwh), g)
    return out, face_img, (cw, ch)


def face_layer(bundle):
    """**无条件**取 face 槽框 + 脸谱（门控判成「好脸」时正本不会叠，探针必须照样能读）。
    返回 ((fpx,fpy,fww,fwh), PIL RGBA 或 None)；无 face 槽返回 (None, None)。"""
    rects, go_names, fm, cm, parts, deps = C.parse_painting(bundle)
    boxes, mirrors, roots = C.layout_all(rects, fm, cm)
    allb = list(boxes.values())
    cw = int(max(b[0] + b[2] for b in allb))
    ch = int(max(b[1] + b[3] for b in allb))
    face_pid = next((rp for rp in rects if go_names.get(rp) == 'face'), None)
    if face_pid is None or face_pid not in boxes:
        return None, None
    rx, ry, rw, rh = boxes[face_pid]
    fpx, fpy = int(round(rx)), int(round(ch - (ry + rh)))
    fww, fwh = max(1, int(round(rw))), max(1, int(round(rh)))
    fx = C.paintingface_face(bundle, os.environ.get('FACE_DEFAULT', '1'))
    if fx is None:
        return (fpx, fpy, fww, fwh), None
    fimg, _ = fx
    mx, my = mirrors.get(face_pid, (False, False))
    fimg = fimg.transpose(Image.FLIP_TOP_BOTTOM)
    if mx:
        fimg = fimg.transpose(Image.FLIP_LEFT_RIGHT)
    if my:
        fimg = fimg.transpose(Image.FLIP_TOP_BOTTOM)
    if (fimg.width, fimg.height) != (fww, fwh):
        fimg = fimg.resize((fww, fwh), Image.BILINEAR)
    return (fpx, fpy, fww, fwh), fimg


def render(layers, face_img, cw, ch, f1, f2, frame=None):
    """frame=(ox,oy,W,H) 时两种口径都画进**同一个**画布框，比对才对齐；
    否则各自按自己的口径开画布（旧口径 = 只取 max，负侧内容被裁掉）。"""
    if frame is None:
        ox = oy = 0
        boxes = [b for _, _, b in layers] + ([face_img[1]] if face_img else [])
        if f1:
            ox = min(0, min(b[0] for b in boxes))
            oy = min(0, min(b[1] for b in boxes))
            ex = max(0, max(b[0] + b[2] for b in boxes))
            ey = max(0, max(b[1] + b[3] for b in boxes))
            W, H = ex - ox, ey - oy
        else:
            W, H = cw, ch
    else:
        ox, oy, W, H = frame
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    items = [(n, im, b) for n, im, b in layers]
    if face_img:
        items.append(('face-overlay', face_img[0], face_img[1]))
    for name, img, (px, py, ww, wh) in items:
        q = (px - ox, py - oy, ww, wh)
        if f2:
            x0 = max(0, q[0]); y0 = max(0, q[1])
            x1 = min(W, q[0] + q[2]); y1 = min(H, q[1] + q[3])
            if x1 <= x0 or y1 <= y0:
                continue
            sub = img.crop((x0 - q[0], y0 - q[1], x1 - q[0], y1 - q[1]))
            reg = canvas.crop((x0, y0, x1, y1))
            canvas.paste(Image.alpha_composite(reg, sub), (x0, y0))
        else:
            canvas.paste(img, (q[0], q[1]), img)
    if frame is not None and not f1:
        # 旧口径的画布窗口 = [0,cw)x[0,ch)，窗口外一律按「没画」处理
        M = np.asarray(canvas).copy()
        x0, y0 = -ox, -oy
        M[:max(0, y0), :, :] = 0
        M[min(H, y0 + ch):, :, :] = 0
        M[:, :max(0, x0), :] = 0
        M[:, min(W, x0 + cw):, :] = 0
        canvas = Image.fromarray(M, 'RGBA')
    return canvas


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    f1 = '--f1' in sys.argv
    f2 = '--f2' in sys.argv
    print(f'开关: F1(画布按内容并集)={f1}  F2(source-over)={f2}')
    for bundle in args:
        layers, face_img, (cw, ch) = layer_images(bundle)
        # 两种口径都画进「内容并集」这个公共框，比对才逐像素对齐
        boxes = [b for _, _, b in layers] + ([face_img[1]] if face_img else [])
        ox = min(0, min(b[0] for b in boxes))
        oy = min(0, min(b[1] for b in boxes))
        ex = max(0, max(b[0] + b[2] for b in boxes))
        ey = max(0, max(b[1] + b[3] for b in boxes))
        frame = (ox, oy, ex - ox, ey - oy)
        old = render(layers, face_img, cw, ch, False, False, frame)
        new = render(layers, face_img, cw, ch, f1, f2, frame)
        oldc = old.crop(old.getbbox() or (0, 0, old.width, old.height))
        newc = new.crop(new.getbbox() or (0, 0, new.width, new.height))
        oldc.save(os.path.join(OUT, f'{bundle}__old.png'))
        newc.save(os.path.join(OUT, f'{bundle}__new.png'))
        A = np.asarray(old).astype(np.int32)
        B = np.asarray(new).astype(np.int32)
        aa, ba = A[..., 3], B[..., 3]
        gained = int(((aa <= 10) & (ba > 10)).sum())
        lostpx = int(((aa > 10) & (ba <= 10)).sum())
        semi_new = int(((ba > 0) & (ba < 255)).sum())
        semi_old = int(((aa > 0) & (aa < 255)).sum())
        m = (aa > 0) & (ba > 0)
        da = (ba - aa)[m]
        print(f'\n[{bundle}] 层 {len(layers)} +face={"有" if face_img else "无"}  公共框 {frame[2]}x{frame[3]}')
        print(f'  旧成品 {oldc.size}  新成品 {newc.size}   （旧口径画布 {cw}x{ch}，'
              f'负侧被裁 {-ox}x{-oy}）')
        print(f'  找回落笔像素 {gained:,}   丢掉落笔像素 {lostpx:,}')
        print(f'  半透明像素 旧 {semi_old:,} -> 新 {semi_new:,}；两版都落笔处 '
              f'alpha 平均变化 {float(da.mean()) if da.size else 0:+.1f}'
              f'（|Δ|>=30 的 {int((np.abs(da) >= 30).sum()):,} 像素）')
        S = 900
        def fit(im):
            r = S / max(im.size)
            return im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        o, n = fit(oldc.convert('RGBA')), fit(newc.convert('RGBA'))
        H2 = max(o.height, n.height) + 30
        cmp_ = Image.new('RGB', (o.width + n.width + 30, H2), (24, 24, 34))
        for im, x in ((o, 10), (n, o.width + 20)):
            bg = Image.new('RGB', im.size, (250, 250, 250))
            bg.paste(im, mask=im.split()[3])
            cmp_.paste(bg, (x, 25))
        from PIL import ImageDraw
        d = ImageDraw.Draw(cmp_)
        tag = '+'.join([t for t, on in (('F1 画布并集', f1), ('F2 source-over', f2)) if on]) or '（无开关）'
        d.text((12, 6), 'OLD (在盘口径)', fill=(255, 220, 120))
        d.text((o.width + 22, 6), f'NEW ({tag})', fill=(120, 255, 160))
        cmp_.save(os.path.join(OUT, f'{bundle}__CMP.png'))
        print(f'  -> {OUT}/{bundle}__CMP.png')


if __name__ == '__main__':
    main()
