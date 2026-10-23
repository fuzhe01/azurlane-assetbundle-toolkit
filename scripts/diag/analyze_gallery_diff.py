"""量化新旧画廊截图的差异（当前模型不能读图，所以把"看图"变成数字）。

对比项：
  1. 查看器画面的整体差异率
  2. 分块差异热力图（定位差异在角色区域还是背景/边框）
  3. 模型包围盒（位置与尺寸是否一致 —— 判断是不是取景差异）

用法: py -3 .diag/analyze_gallery_diff.py [idle|login]
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
from PIL import Image, ImageChops, ImageStat  # noqa: E402

D = os.path.join(ROOT, '.diag', 'gallery_compare')
TAG = sys.argv[1] if len(sys.argv) > 1 else 'idle'


def viewer_crop(im):
    """两侧都只保留右侧查看器区域，去掉左边列表栏（文字/排版会干扰比较）。"""
    w, h = im.size
    return im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))


def grid(a, b, n=8):
    W, H = a.size
    d = ImageChops.difference(a, b)
    out = []
    for gy in range(n):
        row = []
        for gx in range(n):
            c = d.crop((gx * W // n, gy * H // n, (gx + 1) * W // n, (gy + 1) * H // n))
            row.append(ImageStat.Stat(c.convert('L')).mean[0])
        out.append(row)
    return out


def bbox_of(im):
    """找非背景像素的包围盒：以四角中位色为背景基准。"""
    g = im.convert('L')
    W, H = g.size
    px = g.load()
    s = 8
    corners = []
    for cx, cy in ((0, 0), (W - s, 0), (0, H - s), (W - s, H - s)):
        corners.append(ImageStat.Stat(g.crop((cx, cy, cx + s, cy + s))).median[0])
    bg = sum(corners) / len(corners)
    xs, ys = [], []
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            if abs(px[x, y] - bg) > 22:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def main():
    pa = os.path.join(D, '%s_old.png' % TAG)
    pb = os.path.join(D, '%s_new.png' % TAG)
    for p in (pa, pb):
        if not os.path.exists(p):
            print('缺', p); return 1

    ia = viewer_crop(Image.open(pa).convert('RGB'))
    ib = viewer_crop(Image.open(pb).convert('RGB'))
    w = min(ia.size[0], ib.size[0]); h = min(ia.size[1], ib.size[1])
    ia = ia.crop((0, 0, w, h)); ib = ib.crop((0, 0, w, h))

    print('== %s：查看器区域 %dx%d ==' % (TAG, w, h))

    # 整体差异
    d = ImageChops.difference(ia, ib).convert('L')
    hist = d.histogram()
    total = sum(hist)
    big = sum(hist[24:])
    mean = ImageStat.Stat(d).mean[0]
    print('  整体：平均差 %.2f，显著差异像素 %.2f%%' % (mean, big * 100.0 / total))

    # 分块
    g = grid(ia, ib)
    print('\n  分块平均差（8x8，数值越大差异越集中在那一块）')
    print('        ' + ''.join('%7d' % (i + 1) for i in range(8)))
    for i, row in enumerate(g):
        print('   r%-2d ' % (i + 1) + ''.join('%7.1f' % v for v in row))
    flat = [v for r in g for v in r]
    print('  均值 %.2f  最大 %.2f  超 10 的块 %d/64' % (sum(flat) / 64, max(flat),
                                                     sum(1 for v in flat if v > 10)))

    # 包围盒
    ba, bb = bbox_of(ia), bbox_of(ib)
    print('\n  模型包围盒：旧 %s  新 %s' % (ba, bb))
    if ba and bb:
        dx = max(abs(ba[0] - bb[0]), abs(ba[2] - bb[2]))
        dy = max(abs(ba[1] - bb[1]), abs(ba[3] - bb[3]))
        wa, wb = ba[2] - ba[0], bb[2] - bb[0]
        ha, hb = ba[3] - ba[1], bb[3] - bb[1]
        print('  位置偏差: x %d px, y %d px' % (dx, dy))
        print('  尺寸: 旧 %dx%d  新 %dx%d （差 %+d x %+d）'
              % (wa, ha, wb, hb, wb - wa, hb - ha))
        if abs(wb - wa) > wa * 0.05 or abs(hb - ha) > ha * 0.05:
            print('  → 模型尺寸差异 > 5%：取景/缩放不一致')
        else:
            print('  → 尺寸接近一致')
        if dx > 30 or dy > 30:
            print('  → 位置偏移明显：可能是构图/相机差异')
        else:
            print('  → 位置基本一致')
    print('\n  判读：分块差异若集中在中心列（r3~r7），是角色本体差异；'
          '\n        若均匀分布在四周，则更可能来自背景图/取景。')
    return 0


if __name__ == '__main__':
    sys.exit(main())