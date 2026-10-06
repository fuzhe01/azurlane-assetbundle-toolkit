# -*- coding: utf-8 -*-
"""F2（合成算子 paste -> alpha_composite）的**爆炸半径**实测：只换算子、不动画布口径。

要回答的问题是「会不会毁掉那些看着没问题的立绘」。数学上两个算子只在
`0 < src_alpha < 255` 的像素上不同（纯 0 / 纯 255 逐位相同），所以改动面天生
被限制在抗锯齿边缘带。但「数学上」不算数，本脚本按皮肤量三件事：

  changed        两版有差异的像素数
  edge           其中「在 3x3 邻域内存在 alpha<250 的像素」的 —— 这是应该变的
  **far**        离任何半透明像素 >=2px 却变了的 —— **这才是会毁图的东西，必须 ~0**
  rgb_far_max    far 集合上的最大 RGB 通道差（far 为空时给 0）

并落 N 张改前/改后并排拼图供目视。
用法: py -3 scripts/diag/painting_alpha_blast_radius.py [--n 200] [--extra a b c]
"""
import sys, os, glob, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image, ImageDraw
import compose_paintings_v2 as C
import painting_fix_ab as AB
import paths as P

ROOT = P.ROOT
OUT = os.path.join(ROOT, '.diag', 'alpha_blast')
os.makedirs(OUT, exist_ok=True)


def render(bundle, source_over, with_overlay):
    layers, face_img, (cw, ch) = AB.layer_images(bundle)
    canvas = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    for name, img, (px, py, ww, wh) in layers:
        if source_over:
            x0, y0 = max(0, px), max(0, py)
            x1, y1 = min(cw, px + ww), min(ch, py + wh)
            if x1 <= x0 or y1 <= y0:
                continue
            sub = img.crop((x0 - px, y0 - py, x1 - px, y1 - py))
            canvas.paste(Image.alpha_composite(canvas.crop((x0, y0, x1, y1)), sub), (x0, y0))
        else:
            canvas.paste(img, (px, py), img)
    if with_overlay and face_img is not None:
        fimg, (fpx, fpy, fww, fwh), _g = face_img
        x0, y0 = max(0, fpx), max(0, fpy)
        x1, y1 = min(cw, fpx + fww), min(ch, fpy + fwh)
        if x1 > x0 and y1 > y0:
            sub = fimg.crop((x0 - fpx, y0 - fpy, x1 - fpx, y1 - fpy))
            canvas.paste(Image.alpha_composite(canvas.crop((x0, y0, x1, y1)), sub), (x0, y0))
    return canvas


def classify(A, B):
    """A=旧 B=新，同尺寸同原点。

    changed        两版有差异的像素
    edge           其中 3x3 邻域内存在 alpha<250 的（抗锯齿带，本来就该变）
    far            离任何半透明像素 >=2px 却变了的
    far_visible    far 里 |Δ| 合计 >=12 的 —— **这才是能看见的毁图**
    far_delta_max  far 上的最大单通道差
    """
    aa, ba = A[..., 3], B[..., 3]
    delta = np.abs(A.astype(np.int16) - B.astype(np.int16))
    dsum = delta.sum(axis=2)
    diff = dsum > 0
    changed = int(diff.sum())
    if changed == 0:
        return 0, 0, 0, 0, 0, 0.0
    semi = (ba < 250) | (aa < 250)
    from numpy.lib.stride_tricks import sliding_window_view
    sw = sliding_window_view(np.pad(semi, 1), (3, 3), axis=(0, 1))
    near = sw.any(axis=(2, 3))
    edge = int((diff & near).sum())
    far = diff & ~near
    n_far = int(far.sum())
    far_vis = int((far & (dsum >= 12)).sum())
    far_max = int(delta.max(initial=0)) if n_far else 0
    tot = A.shape[0] * A.shape[1]
    return changed, edge, n_far, far_vis, far_max, changed / tot


def main():
    n = 200
    if '--n' in sys.argv:
        n = int(sys.argv[sys.argv.index('--n') + 1])
    allstems = sorted(os.path.basename(p)[:-4] for p in
                      glob.glob(os.path.join(P.PAINT_OUT, '*.png')))
    hard = ['2b', 'feiteliekaer_3', 'hailunna_4', 'xili_alter', 'kewei_6',
            'aersasi_3', 'chicheng_4', 'adiliao_2', 'i168', 'i168_2', 'moermansike_2',
            'gezi_2', 'baixue_2', 'beier', 'banerwei_2', 'i404']
    pool = [h for h in hard if h in allstems]
    rng = random.Random(20261006)
    stride = max(1, len(allstems) // max(1, n))
    pool += allstems[::stride]
    seen, todo = set(), []
    for s in pool:
        if s not in seen:
            seen.add(s)
            todo.append(s)
    print(f'抽样 {len(todo)} 个皮肤（含 16 个历史疑难/回归样本 + 等距抽样）')
    rows = []
    worst_far = []
    for i, b in enumerate(todo):
        try:
            old = render(b, False, True)
            new = render(b, True, True)
        except Exception as e:
            print(f'  ! {b}: {e}')
            continue
        if old.size != new.size:
            print(f'  ! {b}: 尺寸不同 {old.size} vs {new.size}')
            continue
        A, B = np.asarray(old), np.asarray(new)
        ch, edge, far, far_vis, far_max, frac = classify(A, B)
        rows.append((b, ch, edge, far, far_vis, far_max, frac, old.size))
        if far_vis > 0:
            worst_far.append((b, far_vis, far_max))
        if (i + 1) % 20 == 0:
            print(f'  {i+1}/{len(todo)}  累计「离边缘且肉眼可见」非零 {len(worst_far)} 个', flush=True)
    rows.sort(key=lambda t: -t[6])
    print(f'\n=== 换算法后：{len(rows)} 个皮肤')
    nzero = sum(1 for r in rows if r[1] == 0)
    print(f'  零变化 {nzero}   「离边缘 >=2px 且 |Δ|>=12」非零 {len(worst_far)} 个')
    if worst_far:
        worst_far.sort(key=lambda t: -t[1])
        for b, f, fm in worst_far[:20]:
            print(f'    {b:22s} far_visible={f:,}  far 上最大单通道差={fm}')
    print('\n  变化占比最高的 15 个：')
    print(f'    {"skin":22s} {"changed":>10s} {"edge":>10s} {"far":>9s} {"far可见":>8s} '
          f'{"far最大Δ":>7s} {"占比":>7s}  尺寸')
    for r in rows[:15]:
        print(f'    {r[0]:22s} {r[1]:>10,} {r[2]:>10,} {r[3]:>9,} {r[4]:>8,} '
              f'{r[5]:>7d} {r[6]*100:>6.2f}%  {r[7][0]}x{r[7][1]}')
    med = rows[len(rows) // 2]
    print(f'  中位：变化占比 {med[6]*100:.3f}%（{med[0]}）')

    # 改前/改后并排总览（取变化占比最高的 8 个 + 3 个用户报的）
    pick = [r[0] for r in rows[:8]]
    pick += [x for x in ('baixue_2', 'beier', 'gezi_2') if x not in pick and x in seen]
    tiles = []
    for b in pick:
        old = render(b, False, True).convert('RGBA')
        new = render(b, True, True).convert('RGBA')
        S = 460

        def fit(im):
            r = S / max(im.size)
            return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
        o, n2 = fit(old), fit(new)
        t = Image.new('RGB', (S + 10 + S, S + 22), (22, 22, 32))
        for im, x, lab in ((o, 0, 'OLD'), (n2, S + 10, 'NEW')):
            bg = Image.new('RGB', im.size, (250, 250, 250))
            bg.paste(im, mask=im.split()[3])
            t.paste(bg, (x, 20))
        ImageDraw.Draw(t).text((4, 4), f'{b}  OLD | NEW', fill=(200, 220, 255))
        tiles.append(t)
    W = tiles[0].width
    sheet = Image.new('RGB', (W * 2 + 30, max(t.height for t in tiles) * ((len(tiles) + 1) // 2)
                              + 20 * ((len(tiles) + 1) // 2)), (12, 12, 18))
    for i, t in enumerate(tiles):
        col, row = i % 2, i // 2
        sheet.paste(t, (col * (W + 20), row * (t.height + 20)))
    p = os.path.join(OUT, 'alpha_cmp_sheet.png')
    sheet.save(p)
    print(f'\n并排总览 -> {p}  尺寸 {sheet.size}')


if __name__ == '__main__':
    main()
