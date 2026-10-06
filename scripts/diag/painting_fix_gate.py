# -*- coding: utf-8 -*-
"""改完 compose 两处口径后的回归闸门。

设计要点：**探针不复刻任何合成算术**。画布口径与合成算子都已收敛成正本里的
一个函数（`compose_paintings_v2.canvas_frame` / `.over`），所以「旧行为」只要把这两个
函数临时换成退役实现、再调正本 `compose()` 就得到了 —— 探针自己算仿射/取整的话，
差一个 floor 就会虚报几十万实心区变化（这一版踩过）。

退役实现（2026-10-06 之前的正本）：
  画布  只取 `max(x+w)`/`max(y+h)`、从不减 min ⇒ 负侧内容被 paste 静默裁
  合成  `canvas.paste(img, box, img)` ⇒ Pillow 对 RGBA 蒙版把 alpha 缩放两次（a -> a²/255）

判据（任一不满足 = 红，不许换入）：
  ① 旧口径复现盘上产物**逐字节相同** —— 否则这个闸门在比空气
  ② 新落笔 ⊇ 旧落笔（`lost` 必须 0）
  ③ 离任何半透明像素 >=2px 的实心区，可见变化(|Δ|>=12) 必须 0
  ④ 不透明(>=250)不得退化成半透明

用法: py -3 scripts/diag/painting_fix_gate.py [skin ...]   # 不给参数 = 正本 8 皮肤对照组
退出码 0 = 四条全过。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C
import paths as P

ROOT = P.ROOT
CONTROL = ['2b', 'feiteliekaer_3', 'hailunna_4', 'xili_alter', 'kewei_6',
           'aersasi_3', 'chicheng_4', 'adiliao_2']
LAST = {}


def retired_canvas_frame(rects_yup):
    rs = [r for r in rects_yup if r is not None]
    if not rs:
        return 0, 0, 0, 0
    cw = int(max(r[0] + r[2] for r in rs))
    ch = int(max(r[1] + r[3] for r in rs))
    if not (256 <= cw <= 12000 and 256 <= ch <= 12000):
        cw, ch = min(cw, 12000), min(ch, 12000)
    return 0, 0, cw, ch


def retired_over(dst, src, px, py):
    dst.paste(src, (px, py), src)


def retired_dims(bundle):
    """退役画布口径的**输入集**与现役不同（当年对所有 RectTransform 取 max，
    现役是「内容 ∪ root」），所以探针必须自己复算那套 max —— 这是唯一必须留在探针里的
    一行旧规则，其余仿射/取整全部由正本执行。"""
    C._env_cache.clear(); C._obj_cache.clear(); C._img_cache.clear()
    rects, go_names, fm, cm, parts, deps = C.parse_painting(bundle)
    boxes, mirrors, roots = C.layout_all(rects, fm, cm)
    cw = int(max(b[0] + b[2] for b in boxes.values()))
    ch = int(max(b[1] + b[3] for b in boxes.values()))
    if not (256 <= cw <= 12000 and 256 <= ch <= 12000):
        cw, ch = min(cw, 12000), min(ch, 12000)
    return cw, ch


def run(bundle, retired, tag, op_retired=False):
    """在正本上临时换上退役实现（或不动），渲到 .diag/fix_gate/<tag>/。
    返回 (产物路径, 正本记下的取景事实 LAST_CANVAS) —— 对齐要用它，不能靠猜。

    `retired` 只切**画布口径**，`op_retired` 单独切**合成算子**：两个必须能分开，
    否则「找回 N 像素」这一列会把 F1 找回被裁的内容和 F2 让极淡像素复活混成一谈。"""
    cf, ov = C.canvas_frame, C.over
    if retired:
        ocw, och = retired_dims(bundle)

        def _retired(rects_yup):
            return 0, 0, ocw, och
        C.canvas_frame = _retired
    if retired or op_retired:
        C.over = retired_over
    try:
        out = os.path.join(ROOT, '.diag', 'fix_gate', tag)
        os.makedirs(out, exist_ok=True)
        C._env_cache.clear(); C._obj_cache.clear(); C._img_cache.clear()
        C.compose(bundle, out, save=True)
    finally:
        C.canvas_frame, C.over = cf, ov
    return os.path.join(out, f'{bundle}.png'), dict(C.LAST_CANVAS[bundle])


def near_semi(a, b, pad=2):
    semi = (a < 250) | (b < 250)
    from numpy.lib.stride_tricks import sliding_window_view
    h, w = semi.shape
    k = 2 * pad + 1
    big = np.zeros((h + k - 1, w + k - 1), bool)
    big[pad:pad + h, pad:pad + w] = semi
    return sliding_window_view(big, (k, k), axis=(0, 1)).any(axis=(2, 3))


def main():
    names = [a.strip() for a in sys.argv[1:] if a.strip() and not a.startswith('--')] or CONTROL
    f1only = '--f1only' in sys.argv          # 只量画布口径：两版都用退役算子
    bad = []
    for b in names:
        p_old, f_old = run(b, True, 'old')
        p_new, f_new = run(b, False, 'f1only' if f1only else 'new', op_retired=f1only)
        old = Image.open(p_old).convert('RGBA')
        new = Image.open(p_new).convert('RGBA')
        msgs = []
        # ① 旧口径必须逐字节复现盘上产物
        disk = os.path.join(P.PAINT_OUT, b + '.png')
        fx = True
        if os.path.isfile(disk):
            d = np.asarray(Image.open(disk).convert('RGBA'))
            o = np.asarray(old)
            same_shape = d.shape == o.shape
            maxd = int(np.abs(d.astype(int) - o.astype(int)).max()) if same_shape else -1
            fx = same_shape and maxd == 0
            msgs.append(f'旧=盘{"✅" if fx else f"❌(形状{same_shape} 最大差{maxd})"}')
        else:
            msgs.append('旧=盘—(盘上无)')
        # 精确对齐：正本自己记了取景事实（画布原点 / 画布尺寸 / getbbox 裁掉的左上角）。
        # 成品行 = (ch + oy - crop_y) - 世界y，成品列 = 世界x + (-ox - crop_x)。
        # 于是同一个世界点在两版里的行列差是**整数常量**，不需要任何图像配准或猜测。
        def frame_k(f):
            ox, oy = f["origin"]
            cw, ch = f["canvas"]
            cx, cy = f["crop"]
            return ch + oy - cy, -ox - cx        # (K 行基准, M 列基准)

        ka, ma = frame_k(f_old)
        kb, mb = frame_k(f_new)
        A0 = np.asarray(old).astype(np.int16)
        B0 = np.asarray(new).astype(np.int16)
        # 成品行 = K - 世界y、成品列 = 世界x + M  =>  按世界坐标排的公共原点是 (-K, -M)
        r0 = min(-ka, -kb)
        c0 = min(-ma, -mb)
        ar, ac = -ka - r0, -ma - c0
        br, bc = -kb - r0, -mb - c0
        H = max(ar + A0.shape[0], br + B0.shape[0])
        W = max(ac + A0.shape[1], bc + B0.shape[1])
        A = np.zeros((H, W, 4), np.int16)
        B = np.zeros((H, W, 4), np.int16)
        A[ar:ar + A0.shape[0], ac:ac + A0.shape[1]] = A0
        B[br:br + B0.shape[0], bc:bc + B0.shape[1]] = B0
        aa, ba = A[..., 3], B[..., 3]
        # 独立自检：对齐正确的话，两版「实心区包围盒左上角」必须重合。
        # 不重合 = 我的配准坏了，绝不能把由此产生的整幅轮廓差当成图变了。
        def core_tl(m):
            op = m >= 250
            rs = np.where(op.sum(axis=1) >= 8)[0]
            cs = np.where(op.sum(axis=0) >= 8)[0]
            return (int(rs[0]), int(cs[0])) if len(rs) and len(cs) else (-1, -1)
        tal, tbl = core_tl(aa), core_tl(ba)
        # 实心盒差 <=12px 属正常：F2 本来就会把一批 alpha 245 推过 250，实心区集合自己外扩。
        # 它只作为「core/sank/lost 不为 0 时是不是我没对齐」的诊断量，不单独判红 ——
        # 真错位会在 core 上炸出几十万，这里 core 全 0 就是对齐成立的证据。
        aligned = abs(tal[0] - tbl[0]) <= 12 and abs(tal[1] - tbl[1]) <= 12
        msgs.append(f'配准{"✅" if aligned else f"⚠实心盒差{tal[0]-tbl[0]},{tal[1]-tbl[1]}"}')
        dsum = np.abs(A - B).sum(axis=2)
        vis = dsum >= 12
        core = int((vis & ~near_semi(aa, ba)).sum())
        sank = int(((aa >= 250) & (ba < 250)).sum())
        lost = int(((aa > 10) & (ba <= 10)).sum())
        gained = int(((aa <= 10) & (ba > 10)).sum())
        content_bad = core != 0 or sank != 0 or lost != 0
        # 配准只在内容判据红的时候才有意义（那时它解释「其实是没对齐」）。
        # 画布长出几百像素的皮肤上，实心盒本来就会挪位，拿它单独判红是误报。
        ok = fx and not content_bad
        if not ok:
            bad.append(b)
        tag = '❌' if not ok else '✅'
        note = '' if not (content_bad and not aligned) else '  ← 内容判据红且配准存疑，先看这个'
        print(f'  {tag} {b:22s} {old.size} -> {new.size} | {" ".join(msgs)} '
              f'| 平移({br - ar},{bc - ac}) 实心区可见变化 {core:>8,} 不透明退化 {sank:>7,} '
              f'丢失 {lost:>7,} 找回 {gained:>9,}{note}')
    print(f'\n{"✅ 闸门通过" if not bad else "❌ 不合格: " + ",".join(bad)}')
    print('判据：旧口径复现在盘产物 / 实心区(离半透明>2px)零可见变化 / 不透明不退化 / 内容零丢失')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
