# -*- coding: utf-8 -*-
"""shot_budget.py — 把截图压进「看得清又炸不掉上下文」的预算，并给出可替代看图的文本摘要。

为什么需要（2026-10-28 事故）：
  置顶会话因上下文超限中断，总量 213 万 token，其中**一张 1.7 MB 的 PNG 就占 76%**。
  图片一旦进入上下文，之后**每一轮对话都会重发一遍**（不是只算一次），所以一张大图的代价
  是「体积 × 剩余轮数」。无头浏览器截一张 2560×1600 的 PNG 轻松 1.5-4 MB，
  而判定「有没有黑边 / 这块区域是不是空的 / 两版差异在哪」根本不需要那个分辨率。

三条用法（按推荐顺序）：

  1) 只要结论，不要图 —— 让像素变成数字：
       py -3 scripts/diag/shot_budget.py .diag/uishots/3_painting_haitian_3.png --text-only
     输出：尺寸/体积 + 3×3 分块的平均色与不透明覆盖率 + 非空包围盒。
     「四周是不是黑底」「右下角那块有没有内容」这类问题看这几行就够，不必把图塞进上下文。

  2) 必须看图 —— 先压到预算内再看：
       py -3 scripts/diag/shot_budget.py shot.png --max-kb 200 --max-edge 1024
     默认就压（200 KB / 最长边 1024），输出写 `shot.small.png`。
     压完体积仍超预算会继续降边长，直到达标或到底线（320px）为止。

  3) 两版对比 —— 用差异指标替代并排看图：
       py -3 scripts/diag/shot_budget.py after.png --diff before.png
     输出变化像素占比、变化包围盒、平均色差。占比 0.00% 就是"没变"，
     比肉眼比对两张缩略图可靠得多。

体检（收尾时确认没留下超预算的大图）：
    py -3 scripts/diag/shot_budget.py --audit .diag --max-kb 200
  退出码：0 = 全部达标；1 = 有超预算文件（会列出建议）。

被其它探针复用时只需 `from shot_budget import fit, summarize`：
  `fit(src, dst=None, max_kb=200, max_edge=1024)` 返回压缩后的路径；
  `summarize(path)` 返回可直接 print 的文本行列表。
"""
import argparse
import glob
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from PIL import Image  # noqa: E402

IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
MIN_EDGE = 320          # 底线：再压就判不出「哪块有内容」了
TEXT_MAX_EDGE = 512     # --text-only 只统计分块均值，不需要原分辨率，先缩到这里省内存


def _kb(path):
    return os.path.getsize(path) / 1024.0


def _open(path, max_edge=None):
    im = Image.open(path)
    im.load()
    if max_edge and max(im.size) > max_edge:
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return im


def fit(src, dst=None, max_kb=200, max_edge=1024, min_edge=MIN_EDGE):
    """把 src 压到 max_kb 以内、最长边不超过 max_edge，返回输出路径。

    策略：先缩到 max_edge；仍超预算就按 0.8 的比率继续缩（PNG 体积大致随边长平方走），
    缩到 min_edge 还超就接受并给出警告——宁可留一张小图，也不要留一张 3 MB 的原图。
    """
    im = _open(src, max_edge)
    if dst is None:
        stem, _ = os.path.splitext(src)
        dst = stem + '.small.png'
    if os.path.abspath(dst) == os.path.abspath(src):
        raise ValueError('fit(): 输出路径不能与输入相同（会覆盖原图）')
    edge = max(im.size)
    while True:
        im.save(dst, 'PNG', optimize=True)
        if _kb(dst) <= max_kb or edge <= min_edge:
            break
        edge = int(edge * 0.8)
        im = im.resize((max(1, int(im.width * 0.8)), max(1, int(im.height * 0.8))), Image.LANCZOS)
    if _kb(dst) > max_kb:
        print('[shot_budget] ⚠️ %s 压到 %d px 仍有 %.0f KB（预算 %d KB）—— 建议改用 --text-only'
              % (os.path.basename(dst), edge, _kb(dst), max_kb), file=sys.stderr)
    return dst


def _grid_stats(im, n=3):
    """n×n 分块的平均色与不透明覆盖率——「哪块有内容」的文本替身。"""
    im = im.convert('RGBA')
    w, h = im.size
    px = im.load()
    out = []
    for gy in range(n):
        row = []
        for gx in range(n):
            x0, x1 = w * gx // n, w * (gx + 1) // n
            y0, y1 = h * gy // n, h * (gy + 1) // n
            sr = sg = sb = sa = 0
            cnt = 0
            step = max(1, min((x1 - x0) // 32, (y1 - y0) // 32))
            for y in range(y0, y1, step):
                for x in range(x0, x1, step):
                    r, g, b, a = px[x, y]
                    sr += r * a; sg += g * a; sb += b * a; sa += a
                    cnt += 1
            if sa:
                row.append('#%02x%02x%02x/a=%.2f' % (sr // sa, sg // sa, sb // sa, sa / (255.0 * cnt)))
            else:
                row.append('#------/a=0.00')
        out.append(row)
    return out


def _bbox(im):
    """非透明内容的包围盒，返回 (box, 说明)。三态要分清，否则会把「满幅不透明」读成「全透明」。"""
    alpha = im.convert('RGBA').getchannel('A')
    lo, hi = alpha.getextrema()
    if lo == 255:
        return None, '满幅（整张不透明）'
    box = alpha.getbbox()
    if box is None:
        return None, '无（全透明）'
    return box, str(box)


def summarize(path, n=3):
    """返回可打印的文本行列表。--text-only 与 fit 之后都调用它。"""
    im = _open(path, TEXT_MAX_EDGE)
    src = Image.open(path)
    lines = ['%s  %dx%d  %.0f KB'
             % (os.path.basename(path), src.size[0], src.size[1], _kb(path))]
    box, desc = _bbox(im)
    lines.append('  非透明包围盒: %s' % desc)
    grid = _grid_stats(im, n)
    lines.append('  分块（%dx%d，行=上中下，列=左中右）: 平均色/alpha覆盖率' % (n, n))
    for gy, row in enumerate(grid):
        lines.append('    %s  %s' % ('上中下'[gy], '  '.join(row)))
    return lines


def diff(a, b, max_edge=1024):
    """两图差异指标（numpy 向量化，百万像素级秒出）。尺寸不同先按 b 的尺寸对齐再比。"""
    import numpy as np
    ia, ib = _open(a, max_edge).convert('RGBA'), _open(b, max_edge).convert('RGBA')
    if ia.size != ib.size:
        ia = ia.resize(ib.size, Image.LANCZOS)
    A = np.asarray(ia, dtype=np.int16)
    B = np.asarray(ib, dtype=np.int16)
    d = np.abs(A - B).sum(axis=2)          # 每像素四通道绝对差之和
    mask = d > 24
    changed = int(mask.sum())
    npx = float(d.size)
    bbox = None
    if changed:
        ys, xs = np.nonzero(mask)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    return {
        'size': '%dx%d' % (ia.size[0], ia.size[1]),
        'changed_px': changed,
        'changed_ratio': changed / npx,
        'bbox': bbox,
        'mean_delta': float(d.mean()) / 4.0,
    }


def crop(src, box, dst=None):
    """裁出关键区域再压缩——「只截关键区域」这一条的可执行形式。

    box 用**相对比例**（0~1）而不是像素：同一处 UI 在 2560 宽和 1400 宽的窗口里像素坐标不同，
    比例才是跨分辨率可复用的。例：`--crop 0.35,0.05,0.75,0.45` 取中上部那块（通常是脸）。
    """
    im = Image.open(src)
    im.load()
    w, h = im.size
    x0, y0, x1, y1 = [float(v) for v in box]
    px = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
    out = im.crop(px)
    if dst is None:
        stem, _ = os.path.splitext(src)
        dst = stem + '.crop.png'
    if os.path.abspath(dst) == os.path.abspath(src):
        raise ValueError('crop(): 输出路径不能与输入相同')
    out.save(dst, 'PNG', optimize=True)
    print('[shot_budget] 裁剪 %s → %s  像素框 %s  新尺寸 %dx%d'
          % (os.path.basename(src), os.path.basename(dst), px, out.width, out.height))
    return dst


def audit(root, max_kb=200, limit=30):
    files = []
    for ext in IMG_EXT:
        files += glob.glob(os.path.join(root, '**', '*' + ext), recursive=True)
    over = [(p, _kb(p)) for p in files if _kb(p) > max_kb]
    over.sort(key=lambda t: -t[1])
    print('[shot_budget] 扫描 %d 张图，超预算（>%d KB）%d 张' % (len(files), max_kb, len(over)))
    for p, kb in over[:limit]:
        print('  %8.0f KB  %s' % (kb, os.path.relpath(p, root)))
    if len(over) > limit:
        print('  ...另有 %d 张' % (len(over) - limit))
    if over:
        print('  处置：这些图**不要**直接送进上下文；要么 --text-only 取结论，'
              '要么 fit() 压到预算内再截关键区域。')
    return 1 if over else 0


def main(argv):
    ap = argparse.ArgumentParser(description='截图预算：压缩 / 文本摘要 / 差异指标 / 体检')
    ap.add_argument('files', nargs='*', help='输入图片')
    ap.add_argument('--out', help='压缩输出路径（仅单文件时有效）')
    ap.add_argument('--max-kb', type=int, default=200)
    ap.add_argument('--max-edge', type=int, default=1024)
    ap.add_argument('--text-only', action='store_true', help='只输出文本摘要，不写任何图片')
    ap.add_argument('--diff', help='与这张基线图做差异比对')
    ap.add_argument('--crop', help='按相对比例裁关键区域：x0,y0,x1,y1（0~1）')
    ap.add_argument('--audit', help='体检目录：列出所有超预算图片')
    ap.add_argument('--no-compress', action='store_true', help='只打印摘要，不压（等价于 --text-only + 体积检查）')
    a = ap.parse_args(argv)

    if a.audit:
        return audit(a.audit, a.max_kb)
    if not a.files:
        ap.print_help()
        return 2

    rc = 0
    for src in a.files:
        if not os.path.isfile(src):
            print('[shot_budget] 找不到 %s' % src, file=sys.stderr)
            rc = 2
            continue
        work = src
        if a.crop:
            box = [v for v in a.crop.split(',')]
            if len(box) != 4:
                print('[shot_budget] --crop 需要 4 个相对比例 x0,y0,x1,y1', file=sys.stderr)
                return 2
            work = crop(src, box)
        for line in summarize(work):
            print(line)
        if a.diff:
            d = diff(work, a.diff)
            print('  vs %s: 变化 %.2f%%（%d px）  包围盒 %s  平均色差 %.1f/255'
                  % (os.path.basename(a.diff), d['changed_ratio'] * 100,
                     d['changed_px'], d['bbox'], d['mean_delta']))
        if a.text_only or a.no_compress:
            continue
        dst = a.out if (a.out and len(a.files) == 1) else None
        out = fit(work, dst, a.max_kb, a.max_edge)
        print('  → 已压缩: %s  %.0f KB → %.0f KB（最长边 ≤%d）'
              % (out, _kb(work), _kb(out), a.max_edge))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
