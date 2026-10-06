# -*- coding: utf-8 -*-
"""门控翻转样本的「叠脸 / 不叠脸」对照图：给人裁定用，不改任何产物。

对每个皮肤在**正确合成（alpha_composite）**下渲两版——一版按 face 槽叠 paintingface 脸谱、
一版不叠——并排 + 脸槽区域放大，标出门控两侧读数。
用法: py -3 scripts/diag/face_overlay_cmp.py <skin> [skin ...]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image, ImageDraw
import compose_paintings_v2 as C
import painting_fix_ab as AB
import paths as P

OUT = os.path.join(P.ROOT, '.diag', 'fix_ab')
os.makedirs(OUT, exist_ok=True)


def render(layers, cw, ch, face):
    c = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    for name, img, (px, py, ww, wh) in layers:
        x0, y0 = max(0, px), max(0, py)
        x1, y1 = min(cw, px + ww), min(ch, py + wh)
        if x1 <= x0 or y1 <= y0:
            continue
        sub = img.crop((x0 - px, y0 - py, x1 - px, y1 - py))
        c.paste(Image.alpha_composite(c.crop((x0, y0, x1, y1)), sub), (x0, y0))
    if face:
        fimg, (fpx, fpy, fww, fwh) = face
        x0, y0 = max(0, fpx), max(0, fpy)
        x1, y1 = min(cw, fpx + fww), min(ch, fpy + fwh)
        if x1 > x0 and y1 > y0:
            sub = fimg.crop((x0 - fpx, y0 - fpy, x1 - fpx, y1 - fpy))
            c.paste(Image.alpha_composite(c.crop((x0, y0, x1, y1)), sub), (x0, y0))
    return c


def main():
    for b in sys.argv[1:] or ['gezi_2']:
        layers, _fi, (cw, ch) = AB.layer_images(b)
        rect, fimg = AB.face_layer(b)
        face = (fimg, rect) if (fimg is not None and rect) else None
        if face is None:
            print(f'{b}: 无 face 槽/脸谱，跳过')
            continue
        fpx, fpy, fww, fwh = rect
        no = render(layers, cw, ch, None)
        ye = render(layers, cw, ch, face)
        no.save(os.path.join(OUT, f'{b}__noface.png'))
        ye.save(os.path.join(OUT, f'{b}__withface.png'))
        A = np.asarray(no).astype(np.int16)
        B = np.asarray(ye).astype(np.int16)
        d = np.abs(A - B).sum(axis=2)
        print(f'[{b}] 脸槽 ({fpx},{fpy},{fww}x{fwh})  叠/不叠差异像素 '
              f'{int((d>0).sum()):,}（{float((d>0).mean())*100:.2f}%），最大单通道差 {int(np.abs(A-B).max())}')
        # 全图并排 + 脸槽放大并排
        S = 620

        def fit(im):
            r = S / max(im.size)
            return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)

        def onwhite(im):
            g = Image.new('RGB', im.size, (250, 250, 250))
            g.paste(im, mask=im.split()[3])
            return g
        o, n = fit(no), fit(ye)
        zoom = 900
        bx0, by0 = max(0, fpx - 40), max(0, fpy - 40)
        bx1, by1 = min(cw, fpx + fww + 40), min(ch, fpy + fwh + 40)
        zo = no.crop((bx0, by0, bx1, by1))
        zn = ye.crop((bx0, by0, bx1, by1))
        zr = zoom / max(zo.size)
        zo = zo.resize((int(zo.width * zr), int(zo.height * zr)), Image.LANCZOS)
        zn = zn.resize((int(zn.width * zr), int(zn.height * zr)), Image.LANCZOS)
        W = max(o.width + n.width, zo.width + zn.width) + 30
        H = 30 + max(o.height, n.height) + 30 + max(zo.height, zn.height)
        sheet = Image.new('RGB', (W, H), (18, 18, 26))
        dd = ImageDraw.Draw(sheet)
        dd.text((8, 4), f'{b} — 正确合成下：不叠脸（左） vs 叠脸（右）', fill=(200, 220, 255))
        sheet.paste(onwhite(o), (8, 26))
        sheet.paste(onwhite(n), (14 + o.width, 26))
        y1_ = 26 + max(o.height, n.height) + 14
        dd.text((8, y1_ - 4), '脸槽放大', fill=(255, 220, 140))
        y2_ = y1_ + 18
        sheet.paste(onwhite(zo), (8, y2_))
        sheet.paste(onwhite(zn), (14 + zo.width, y2_))
        p = os.path.join(OUT, f'{b}__FACECMP.png')
        sheet.save(p)
        print(f'  -> {p}')


if __name__ == '__main__':
    main()
