"""截图区域统计（可复用）——把「某块区域有没有内容 / 有没有红底」变成可复现的数字。

为什么需要单独一个模块（2026-10-29，TROUBLESHOOTING §163）：
`Page.shot()` 是 **整页截图**，左侧还有画廊侧栏；而 Live2D 侧的一切坐标换算
（`toS()`、`__costumeScreenOf()`、`getDrawableVertexPositions()`）给的都是
**相对 canvas 左上角**的 stage / V 坐标。两者直接相减会差一个侧栏宽度（实测 292 px），
把「已经画出来的左脚」量成「0 内容」—— 本项目已经把这条假阴性当过一次结论。

所以像素判定的唯一正确入口是：**先问页面要 canvas 的 getBoundingClientRect()**，
拿到左上角偏移，再加到 stage 坐标上，才允许裁图。

第二件事：红像素的阈值必须**多档并列**。
  · loose (R>60,  R-G>25, R-B>25) —— 会把暖棕/肤色也算进来
  · mid   (R>90,  R-G>40, R-B>40)
  · strict(R>110, R-G>50, R-B>50) —— 只留真正的饱和红（红底）
单用 loose 会得出「左右差不多」，单用 strict 会漏掉暗部的红。报结论必须写清用的哪一档。

用法：
    from shot_regions import region_stats, auto_canvas_left
    st = region_stats('D:/azur/.diag/foot_shot.png', left=292, top=0,
                      box=(333, 379, 464, 520))
    print(st['strict_pct'], st['content_pct'], st['median'])

**第三种用法（2026-10-29 追加，优先级最高）：两帧差分**
    diff_stats(a, b, left=..., top=...)  —— 只报「哪些像素变了」，不依赖调用方指定区域。
为什么它比区域统计更可信：区域统计要求调用方先猜「目标物在哪」，猜错就把「量错部位」
当成「东西没渲染」（本项目已栽两次：V y −1.5..1.15 其实是小腿，不是鞋）。差分由**被测系统
自己**决定变化范围：改一个参数、截两帧，变化包围盒就是该参数的真实作用域。
前置条件：必须冻结姿态（idle/呼吸/物理），否则全身都在动，差分淹没目标。
"""
import numpy as np
from PIL import Image

RED_TIERS = {
    'loose':  ((60, 25, 25)),
    'mid':    ((90, 40, 40)),
    'strict': ((110, 50, 50)),
}


def _load(path):
    im = Image.open(path).convert('RGB')
    return np.asarray(im).astype(np.int16)


def red_masks(a):
    rr, gg, bb = a[..., 0], a[..., 1], a[..., 2]
    out = {}
    for name, (mn, dg, db) in RED_TIERS.items():
        out[name] = (rr > mn) & (rr - gg > dg) & (rr - bb > db)
    return out


def auto_canvas_left(path, search=(0.10, 0.45)):
    """从整页截图里**粗定位** canvas 左边界（侧栏结束处），只用作交叉核对。

    判据：列众数占比 abrupt drop。
      · 侧栏右半是一整块纯色底（列众数占比 0.89~0.96）；
      · 画布区是模型 + 上/下半背景，列内像素杂得多（实测 0.82 左右）。
    实测 ougen_8 整页 1370×871，最大跌幅就落在 292（0.96 → 0.83）。
    ⚠️ 侧栏**左半**（x<~40）反而只有 0.14，因为它有自己的按钮/文字/渐变 ——
    所以「从左往右找第一处不纯」这种写法会直接返回 0（已经踩过）。
    正解是找**跌幅最大**的那一列。
    ⚠️ 这个函数永远只做交叉核对。产品侧能问就必须问页面（VIEWRECT 片段）；
    两者不一致时以页面为准，并把不一致本身当异常报出来，不许静默取平均。
    """
    a = _load(path)
    H, W = a.shape[:2]
    med = np.median(a, axis=0)
    same = (np.abs(a - med[None, :, :]).max(axis=2) <= 4)
    frac = same.mean(axis=0)
    lo = max(1, int(W * search[0]))
    hi = min(W - 1, int(W * search[1]))
    best, best_i = 0.0, lo
    for i in range(lo, hi):
        drop = frac[i - 1] - frac[i]
        if drop > best:
            best, best_i = float(drop), i
    return best_i


def region_stats(path, left=0, top=0, box=None, dpr=1.0):
    """统计一块 canvas 坐标区域。

    box = (x0, y0, x1, y1)，**canvas 坐标**（左闭右开，不含 x1/y1）。
    left/top 是 canvas 在整页截图里的偏移（VIEWRECT 的 left/top，dpr=1 时单位即像素）。
    """
    a = _load(path)
    H, W = a.shape[:2]
    ox = int(round(left * dpr))
    oy = int(round(top * dpr))
    if box is None:
        px0, py0, px1, py1 = 0, 0, W, H
    else:
        px0 = max(0, int(round(box[0] * dpr)) + ox)
        py0 = max(0, int(round(box[1] * dpr)) + oy)
        px1 = min(W, int(round(box[2] * dpr)) + ox)
        py1 = min(H, int(round(box[3] * dpr)) + oy)
    if px1 <= px0 or py1 <= py0:
        return {'err': 'EMPTY_BOX', 'page_box': [px0, py0, px1, py1], 'n': 0}
    sub = a[py0:py1, px0:px1]
    n = sub.shape[0] * sub.shape[1]
    med = np.median(sub.reshape(-1, 3), axis=0)
    # 内容判据：与本区中位色明显不同，且不是接近纯白（侧栏/按钮底色）
    d = np.abs(sub - med[None, None, :]).max(axis=2)
    content = d > 24
    masks = red_masks(sub)
    out = {
        'n': int(n), 'page_box': [int(px0), int(py0), int(px1), int(py1)],
        'median': [int(v) for v in med],
        'content_pct': round(float(content.mean()) * 100, 2),
        'nearblack_pct': round(float((sub.max(axis=2) < 70).mean()) * 100, 2),
        'lum_p50': int(np.percentile(sub.mean(axis=2), 50)),
    }
    for k, m in masks.items():
        out[k] = int(m.sum())
        out[k + '_pct'] = round(float(m.mean()) * 100, 3)
    return out


def red_components(path, left=0, top=0, box=None, tier='strict', dpr=1.0,
                   max_report=15):
    """红像素连通域（4-邻域 BFS 手写，本机没有 scipy）。坐标一律回报成 canvas 坐标。

    用途：判「两只鞋的红底各有多大」——单个区域盒的百分比会被鞋外的腿部皮肤稀释，
    连通域能直接给出「每个红底块的像素数 + 包围盒」。
    """
    from collections import deque
    a = _load(path)
    H, W = a.shape[:2]
    ox = int(round(left * dpr)); oy = int(round(top * dpr))
    if box is None:
        px0, py0, px1, py1 = ox, oy, W, H
    else:
        px0 = max(ox, int(round(box[0] * dpr)) + ox)
        py0 = max(oy, int(round(box[1] * dpr)) + oy)
        px1 = min(W, int(round(box[2] * dpr)) + ox)
        py1 = min(H, int(round(box[3] * dpr)) + oy)
    m = red_masks(a)[tier][py0:py1, px0:px1]
    h, w = m.shape
    seen = np.zeros_like(m, dtype=bool)
    comps = []
    for y0 in range(h):
        row = m[y0]
        for x0 in np.nonzero(row & ~seen[y0])[0]:
            if seen[y0, x0]:
                continue
            q = deque([(y0, int(x0))]); seen[y0, x0] = True
            n = 0; ax0 = ax1 = int(x0); ay0 = ay1 = y0
            while q:
                cy, cx = q.popleft(); n += 1
                if cx < ax0: ax0 = cx
                if cx > ax1: ax1 = cx
                if cy < ay0: ay0 = cy
                if cy > ay1: ay1 = cy
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            comps.append({'n': n,
                          'canvas_bbox': [ax0 + px0 - ox, ay0 + py0 - oy,
                                          ax1 + px0 - ox, ay1 + py0 - oy]})
    comps.sort(key=lambda c: -c['n'])
    return {'tier': tier, 'total': int(m.sum()), 'count': len(comps),
            'top': comps[:max_report]}


def diff_stats(path_a, path_b, left=0, top=0, box=None, dpr=1.0,
               thresh=12, max_report=12):
    """两帧差分：**不依赖调用方指定区域**，由被测系统自己决定变化范围。

    参数：
      thresh —— 每通道差值 > thresh 才算变化。默认 12 足够滤掉 PNG/合成抖动
                （实测同帧重截的变化像素为 0）。
      box    —— 可选裁剪（canvas 坐标）；不传就整块 canvas。

    返回（坐标一律回报成 canvas 坐标，`page_bbox` 另给整页坐标便于裁图）：
      changed       变化像素数
      changed_pct   占所测区域百分比
      bbox          变化的 canvas 包围盒 [x0,y0,x1,y1]（无变化时 None）
      page_bbox     同上，已加 left/top 偏移（直接喂给 make_sheet.py 的 --crop）
      split         变化像素按「画布左半 / 右半」的分布 —— 判「单侧变化」用
      red_delta     变化像素里红色（strict 档）在两帧各自的数量差，判「红底换装」用
    """
    a = _load(path_a)
    b = _load(path_b)
    if a.shape != b.shape:
        return {'err': 'SHAPE_MISMATCH', 'a': list(a.shape), 'b': list(b.shape)}
    H, W = a.shape[:2]
    ox = int(round(left * dpr)); oy = int(round(top * dpr))
    if box is None:
        px0, py0, px1, py1 = ox, oy, W, H
    else:
        px0 = max(ox, int(round(box[0] * dpr)) + ox)
        py0 = max(oy, int(round(box[1] * dpr)) + oy)
        px1 = min(W, int(round(box[2] * dpr)) + ox)
        py1 = min(H, int(round(box[3] * dpr)) + oy)
    if px1 <= px0 or py1 <= py0:
        return {'err': 'EMPTY_BOX'}
    da = a[py0:py1, px0:px1].astype(np.int16)
    db = b[py0:py1, px0:px1].astype(np.int16)
    d = np.abs(da - db).max(axis=2)
    m = d > thresh
    n_total = m.shape[0] * m.shape[1]
    out = {'thresh': thresh, 'n': int(n_total),
           'changed': int(m.sum()),
           'changed_pct': round(float(m.sum()) / max(1, n_total) * 100, 3)}
    if not m.any():
        out['bbox'] = None
        out['page_bbox'] = None
        return out
    ys, xs = np.nonzero(m)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    out['bbox'] = [x0, y0, x1, y1]                       # 区域内坐标
    out['page_bbox'] = [x0 + px0, y0 + py0, x1 + px0, y1 + py0]
    out['bbox_canvas'] = [x0 + px0 - ox, y0 + py0 - oy, x1 + px0 - ox, y1 + py0 - oy]
    # 变化像素落在画布中线哪一侧 —— 「只有一侧在换」= 单只鞋/单侧缺件
    midx = (W // 2) - ox
    gx = xs + px0 - ox
    left_n = int((gx < midx).sum())
    out['split'] = {'left': left_n, 'right': int(m.sum()) - left_n,
                    'canvas_mid_x': int(midx)}
    # 红底换装：变化区里的红像素两帧计数（穿鞋态通常显著更多）
    ra = red_masks(da)['strict']; rb = red_masks(db)['strict']
    out['red_delta'] = {'a': int(ra.sum()), 'b': int(rb.sum()),
                        'diff': int(rb.sum()) - int(ra.sum())}
    # 变化区的连通簇：两只鞋会给出两个分离的簇
    sub_m = m.astype(np.uint8)
    from collections import deque
    seen = np.zeros_like(sub_m, dtype=bool)
    comps = []
    h, w = sub_m.shape
    for y0i in range(h):
        for x0i in np.nonzero(sub_m[y0i] & ~seen[y0i])[0]:
            if seen[y0i, x0i]:
                continue
            q = deque([(y0i, int(x0i))]); seen[y0i, x0i] = True
            cnt = 0; ax0 = ax1 = int(x0i); ay0 = ay1 = y0i
            while q:
                cy, cx = q.popleft(); cnt += 1
                if cx < ax0: ax0 = cx
                if cx > ax1: ax1 = cx
                if cy < ay0: ay0 = cy
                if cy > ay1: ay1 = cy
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and sub_m[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            comps.append({'n': cnt,
                          'canvas_bbox': [ax0 + px0 - ox, ay0 + py0 - oy,
                                          ax1 + px0 - ox, ay1 + py0 - oy]})
    comps.sort(key=lambda c: -c['n'])
    out['count'] = len(comps)
    out['top'] = comps[:max_report]
    return out
