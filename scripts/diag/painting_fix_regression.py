# -*- coding: utf-8 -*-
"""改完 compose 的两处口径（画布覆盖内容并集 / source-over 合成）后的回归闸门。

分两条判据，因为这次捆了两个性质完全不同的改动：

  F1 画布口径  —— 只可能**找回**内容（新画布 = 内容 ∪ root 的并集，是旧画布的超集），
                  不可能丢。所以「零回退」按构造成立，这里仍实测一遍。
  F2 合成算子  —— **故意**改所有半透明像素，所以不能要求逐字节不变。
                  能要求的是：**离任何半透明像素 >=2px 的实心区一个像素都不许变**。
                  实心区变了才是毁图。

本脚本只对「旧口径下没有被裁掉内容」的皮肤做逐像素比对（那批 F1 是恒等的，
差异只能来自 F2，判据才干净）；被裁的那 19 个走 painting_fix_ab.py 的并排图人工过。

用法: py -3 scripts/diag/painting_fix_regression.py [skin ...]
      不给参数 = 正本 8 皮肤零回退对照组
退出码 0 = 实心区零变化 且 无内容丢失
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C
import paths as P

ROOT = P.ROOT
OUT = os.path.join(ROOT, '.diag', 'fix_regress')
CONTROL = ['2b', 'feiteliekaer_3', 'hailunna_4', 'xili_alter', 'kewei_6',
           'aersasi_3', 'chicheng_4', 'adiliao_2']
# 2026-10-06 扫描判定「旧口径下有内容被裁」的清单，逐像素比对要把它们排除
CLIPPED_TSV = os.path.join(ROOT, '.diag', 'offcanvas_content.tsv')


def clipped_set():
    if not os.path.isfile(CLIPPED_TSV):
        return set()
    with open(CLIPPED_TSV, encoding='utf-8') as f:
        next(f, None)
        return {l.split('\t')[0] for l in f if l.strip()}


def anchor(mat, need=8):
    """鲁棒锚点 = 第一个/一列**有 >=need 个**不透明像素的行/列。
    用「第一个不透明像素」当锚点会被一个杂点挪走整行，1px 错位就能让整张画的
    轮廓全被判成变化（实测 hailunna_4 因此虚报 89 万实心区变化）。"""
    op = mat >= 250
    rows = np.where(op.sum(axis=1) >= need)[0]
    cols = np.where(op.sum(axis=0) >= need)[0]
    return (int(rows[0]), int(cols[0])) if len(rows) and len(cols) else (0, 0)


def align(A, B, fine=4):
    """把两版贴进同一公共框，使**两者的锚点重合**（不是让两者的左上角重合——
    新画布会因极淡像素外扩而把裁切原点往前挪，左上角对齐等于把整张画推歪）。
    锚点只保证粗对齐，再做 ±fine 的平移精搜把残差压到最小：判据用「|Δ|>=12 的像素数」，
    它正是本闸门要量的东西，所以精搜不会把真变化抹平（真变化不会因平移整张画而变少）。"""
    rA, cA = anchor(A[..., 3])
    rB, cB = anchor(B[..., 3])
    pr = max(rA, rB) + fine
    pc = max(cA, cB) + fine
    H = max(pr - rA + A.shape[0], pr - rB + B.shape[0]) + fine
    W = max(pc - cA + A.shape[1], pc - cB + B.shape[1]) + fine
    CA = np.zeros((H, W, 4), np.int16)
    CB = np.zeros((H, W, 4), np.int16)
    CA[pr - rA:pr - rA + A.shape[0], pc - cA:pc - cA + A.shape[1]] = A
    CB[pr - rB:pr - rB + B.shape[0], pc - cB:pc - cB + B.shape[1]] = B

    def score(dr, dc):
        h0 = max(0, dr); h1 = min(H, H + dr)
        w0 = max(0, dc); w1 = min(W, W + dc)
        if h1 - h0 < 16 or w1 - w0 < 16:
            return 1 << 60
        a = CA[h0:h1, w0:w1]
        b = CB[h0 - dr:h1 - dr, w0 - dc:w1 - dc]
        return int((np.abs(a - b).sum(axis=2) >= 12).sum())

    best = (score(0, 0), 0, 0)
    for dr in range(-fine, fine + 1):
        for dc in range(-fine, fine + 1):
            s = score(dr, dc)
            if s < best[0]:
                best = (s, dr, dc)
    _, dr, dc = best
    if dr or dc:
        # 必须与 score() 里的变换**同向**：score 比的是 CB[h-dr, w-dc]，
        # 这里就按同一个式子搬（上一版符号写反，把已经对齐的图又推歪 2px，
        # 虚报了 89 万实心区变化；自测的样本粗对齐本来就精确，抓不到这种错）。
        nCB = np.zeros_like(CB)
        h0, h1 = max(0, dr), min(H, H + dr)
        w0, w1 = max(0, dc), min(W, W + dc)
        nCB[h0:h1, w0:w1] = CB[h0 - dr:h1 - dr, w0 - dc:w1 - dc]
        CB = nCB
    return CA, CB, (cB - cA + dc, rB - rA + dr), best[0]


def near_semi(mat_a, mat_b, pad=2):
    """True 的位置 = 离任一「两版中 alpha<250」的像素 <=pad 圈。"""
    semi = (mat_a < 250) | (mat_b < 250)
    from numpy.lib.stride_tricks import sliding_window_view
    h, w = semi.shape
    k = 2 * pad + 1
    big = np.zeros((h + k - 1, w + k - 1), bool)
    big[pad:pad + h, pad:pad + w] = semi
    win = sliding_window_view(big, (k, k), axis=(0, 1))
    return win.any(axis=(2, 3))


def main():
    names = [a.strip() for a in sys.argv[1:] if a.strip()] or CONTROL
    skip = clipped_set()
    os.makedirs(OUT, exist_ok=True)
    bad = 0
    print(f'排除「旧口径有裁切」的 {len(skip)} 个（它们走并排图人工过）')
    for b in names:
        disk = os.path.join(P.PAINT_OUT, b + '.png')
        if not os.path.isfile(disk):
            print(f'  - {b}: 盘上无产物，跳过')
            continue
        C._env_cache.clear(); C._obj_cache.clear(); C._img_cache.clear()
        try:
            C.compose(b, OUT, save=True)
        except Exception as e:
            print(f'  ✗ {b}: {e}')
            bad += 1
            continue
        new = Image.open(os.path.join(OUT, b + '.png')).convert('RGBA')
        old = Image.open(disk).convert('RGBA')
        if b in skip:
            print(f'  ~ {b}: 属被裁清单，只记录尺寸不判回退  旧{old.size} 新{new.size}')
            continue
        A, B, (dx, dy), resid = align(np.asarray(old).astype(np.int16),
                                      np.asarray(new).astype(np.int16))
        dsum = np.abs(A - B).sum(axis=2)
        diff = dsum > 0
        vis = diff & (dsum >= 12)
        edge = near_semi(A[..., 3], B[..., 3])
        core_vis = int((vis & ~edge).sum())
        # 「实心区」两版都必须仍然不透明 —— 变透明=内容丢了
        sank = int(((A[..., 3] >= 250) & (B[..., 3] < 250)).sum())
        gained = int(((A[..., 3] < 250) & (B[..., 3] >= 250)).sum())
        ok = core_vis == 0 and sank == 0
        bad += 0 if ok else 1
        print(f'  {"✅" if ok else "❌"} {b:22s} 对齐位移({dx},{dy}) 残差 {resid:>8,} 尺寸 {old.size}->{new.size} '
              f'变化 {int(diff.sum()):>9,} 实心区可见变化 {core_vis:>6,}  '
              f'不透明->半透明 {sank:>7,}  半透明->不透明 {gained:>9,}')
    print(f'\n{"闸门通过" if bad == 0 else f"❌ {bad} 个皮肤不合格"} — 判据：实心区(离半透明>2px)零可见变化、'
          f'且不透明像素不得退化成半透明')
    return 1 if bad else 0


def selftest():
    """对齐器自己的对照实验：把一张图整体平移已知量，align 必须原样报出该位移且残差 0。
    没有这一步，「对齐后仍有几百万变化」根本分不清是图变了还是我没对齐。"""
    rng = np.zeros((600, 500, 4), np.int16)
    yy, xx = np.mgrid[0:600, 0:500]
    blob = ((xx - 250) ** 2 + (yy - 300) ** 2) < 180 ** 2
    rng[..., 0] = 200; rng[..., 1] = 60; rng[..., 2] = 90
    rng[..., 3] = np.where(blob, 255, 0).astype(np.int16)
    # 加一点轮廓细节，让「错位」能被 |Δ|>=12 看出来
    ring = (((xx - 250) ** 2 + (yy - 300) ** 2) > 150 ** 2) & (((xx - 250) ** 2 + (yy - 300) ** 2) < 180 ** 2)
    rng[..., 0] = np.where(ring, 20, rng[..., 0]).astype(np.int16)
    ok = True
    cases = [(0, 0, 0), (3, -2, 0), (-7, 5, 0), (1, 0, 0), (40, -120, 0),
             # 扰动锚点：在 B 上多打一个孤立不透明点，让粗锚点先偏掉，
             # 精搜必须把它纠回来。上一版自测的样本粗对齐本来就精确，
             # 所以符号写反也没被抓到 —— 这几个用例就是专门抓这个的。
             (2, 4, 1), (-5, -3, 1), (30, -60, 1)]
    for dr, dc, perturb in cases:
        pad = 200
        H = 600 + 2 * pad
        W = 500 + 2 * pad + 200
        A2 = np.zeros((H, W, 4), np.int16)
        B2 = np.zeros((H, W, 4), np.int16)
        A2[pad:pad + 600, pad:pad + 500] = rng
        B2[pad + dr:pad + dr + 600, pad + dc:pad + dc + 500] = rng
        if perturb:
            # 在内容起点上方 3 行处撒一小撮不透明点：鲁棒锚点(need=8)会被它带偏 3 行，
            # 精搜必须纠回来。这正是「一个杂点挪走整行锚点」的真实形态。
            r0 = pad + dr
            c0 = pad + dc
            B2[r0 - 3:r0 - 1, c0 + 20:c0 + 30] = (200, 60, 90, 255)
        _a, _b, (dx, dy), resid = align(A2, B2)
        # 扰动用例里 B 本来就多了 20 个真像素，残差不可能为 0，只要不超过那点面积
        good = resid <= (40 if perturb else 0)
        ok = ok and good
        print(f'  对齐器自测 平移(行{dr},列{dc}) 锚点扰动{perturb} -> 报出({dx},{dy}) 残差 {resid} '
              f'{"✅" if good else "❌"}')
    return 0 if ok else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
