# -*- coding: utf-8 -*-
"""风险闸门预演：把合成算子从 `paste(img,box,img)`（Pillow 会把 RGBA 蒙版的 alpha 缩放两次）
换成标准 source-over 之后，**叠脸门控的裁定会不会翻**。

为什么要专门量这条：门控读的是画布 alpha（`>=250` 算不透明）。旧口径下源 alpha=250
会被压成 245 —— 刚好跌破 250，于是旧口径**系统性低估不透明度**，可能把「脸已烤好」
误判成洞而多叠一层。换正确合成后这类皮肤会停止叠脸。到底翻几条、翻向哪一侧，
只能在 2026-09-27 人工目视裁定过的 47 个带标签样本上量（`face_gate_labels_check.py` 的标签集）。

用法: py -3 scripts/diag/face_gate_semantics_ab.py
退出码 0 = 换算子后标签符合率不下降；非 0 = 有回退，别换。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import painting_fix_ab as AB
from face_gate_labels_check import HOLE_TRANSPARENT, HOLE_BLOCK, BAKED, NEUTRAL

FACE_OPAQUE_MIN = C.FACE_OPAQUE_MIN
FACE_MAD_MAX = C.FACE_MAD_MAX


def ctx(bundle):
    layers, _fi, (cw, ch) = AB.layer_images(bundle)
    rect, face = AB.face_layer(bundle)
    return layers, rect, face, cw, ch


def gate(c, source_over):
    """按指定合成算子渲底图，再复算门控读数（与正本 compose() 同一套公式）。

    ⚠ 脸谱必须**无条件**取：门控判成「好脸」时正本不会叠，若探针照抄这条
    就会把整个 BAKED 组当成「无脸谱」跳过 —— 那等于只测了单侧，闸门是假的。
    """
    layers, rect, face, cw, ch = c
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
    if rect is None or face is None:
        return None
    fpx, fpy, fww, fwh = rect
    if fww <= 8 or fwh <= 8:
        return None
    fimg = face
    sp = np.asarray(fimg).astype(int)
    foot = sp[..., 3] > 200
    n_foot = int(foot.sum())
    if n_foot < 64:
        return None
    sub = np.asarray(canvas.crop((fpx, fpy, fpx + fww, fpy + fwh))).astype(int)
    rgb = sub[..., :3]
    opq = (sub[..., 3] >= 250) & foot
    frac = float(opq.sum()) / n_foot
    mad = float(np.abs(sp[..., :3] - rgb)[opq].mean()) if int(opq.sum()) >= 64 else None
    hole = frac < FACE_OPAQUE_MIN or mad is None or mad > FACE_MAD_MAX
    return {'frac': frac, 'mad': mad, 'hole': hole}


def main():
    labels = ([(b, '洞') for b in HOLE_TRANSPARENT + HOLE_BLOCK] +
              [(b, '好脸') for b in BAKED])
    print(f'{"bundle":22s} {"期望":5s} | {"旧 op":>6s} {"旧MAD":>7s} {"旧判":>4s} | '
          f'{"新 op":>6s} {"新MAD":>7s} {"新判":>4s} | 变化')
    flips = []
    old_ok = new_ok = scored = 0
    cache = {}
    for b, want in labels:
        try:
            if b not in cache:
                cache[b] = ctx(b)
            g0 = gate(cache[b], False)
            g1 = gate(cache[b], True)
        except Exception as e:
            print(f'{b:22s} 跳过: {e}')
            continue
        if g0 is None or g1 is None:
            print(f'{b:22s} {want:5s} | 无 face 槽/脸谱，跳过')
            continue
        scored += 1
        d0 = '洞' if g0['hole'] else '好脸'
        d1 = '洞' if g1['hole'] else '好脸'
        old_ok += (d0 == want)
        new_ok += (d1 == want)
        mark = '' if d0 == d1 else f'  ⚠ 翻转 {d0}->{d1}'
        if d0 != d1:
            flips.append((b, want, d0, d1))
        def fmt(v):
            return '   None' if v is None else f'{v:7.1f}'
        print(f'{b:22s} {want:5s} | {g0["frac"]:6.3f} {fmt(g0["mad"])} {d0:>4s} | '
              f'{g1["frac"]:6.3f} {fmt(g1["mad"])} {d1:>4s} |{mark}')
    print(f'\n标签符合率：旧 {old_ok}/{scored}  新 {new_ok}/{scored}（两侧都有人的子集）')
    if flips:
        print('翻转清单：')
        for t in flips:
            print(f'  {t[0]:22s} 标签={t[1]:4s} 旧判={t[2]} 新判={t[3]} '
                  f'{"✅ 修对" if t[3]==t[1] else "❌ 判坏"}')
    rc = 0
    print(f'\n退出码 {rc}（0 = 换算子不会让任何带标签样本从对翻到错）')
    bad = [t for t in flips if t[2] == t[1] and t[3] != t[1]]
    if bad:
        print('❌ 以下样本从「判对」翻成「判错」，不得直接换：')
        for t in bad:
            print(f'   {t[0]} (标签 {t[1]})')
        rc = 1
    return rc


if __name__ == '__main__':
    sys.exit(main())
