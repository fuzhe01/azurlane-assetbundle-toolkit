#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量「背景层」与「角色层」的像素覆盖关系，判断取景该以谁为准。

**为什么需要**（2026-10-04 天津风皮肤2 实测推导）：
逐层导出后真相大白 ——
  · 主层 `tianjinfeng_2`  = 角色本体（吊着的姿态，斜 45°，画得完全正常）
  · `2B2` = **整个房间背景**，美术把它做成了 45° 菱形（用户确认「就是吊着的」）
  · `2M`  = **同一角色的另一套 outfit**（白腿红裙），游戏里应当**与本体二选一**
  · `2T`  = 零星红点（粒子特效）
所以取景若以「整幅画的外接框」为准，会被 45° 菱形背景撑到 2 倍对角线，
角色就缩成中间一小块（用户看到的「背后有另一个身体」= 2M 的身体从本体旁边露出来）。

**判据**：以角色层（最大附件层 / 骨骼最集中那层）为取景基准时，
菱形背景的四个角会落在画面外 —— 这正是想要的效果（游戏里也是这么构图的）。

**只读**：读逐层导出的 PNG。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths as P  # noqa: E402

try:
    from PIL import Image
except ImportError:
    print("[缺] 需要 Pillow", file=sys.stderr)
    sys.exit(2)

KEY = sys.argv[1] if len(sys.argv) > 1 else "tianjinfeng_2"
CG = os.path.join(P.CG_OUT if hasattr(P, "CG_OUT") else
                  os.path.join(P.ROOT, "Output", "CG_v2"))


def box_of(path, thr=10):
    """返回 (宽, 高, 覆盖率, 四角是否触边)。"""
    im = Image.open(path).convert("RGBA")
    a = im.getchannel("A")
    w, h = im.size
    px = a.load()
    x0, y0, x1, y1 = w, h, -1, -1
    n = 0
    for y in range(h):
        for x in range(w):
            if px[x, y] > thr:
                n += 1
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    if x1 < x0:
        return w, h, 0.0, False
    return x1 - x0 + 1, y1 - y0 + 1, n / float(w * h), (
        x0 <= 1 and y0 <= 1 and x1 >= w - 2 and y1 >= h - 2)


def main():
    print("=== %s 逐层产物（各层单独 fit 后的落笔）===" % KEY)
    files = {}
    d = CG
    for f in sorted(os.listdir(d)):
        if f.startswith(KEY + "_L_") and f.endswith(".png"):
            layer = f[len(KEY) + 3:-4]
            files[layer] = os.path.join(d, f)
    if not files:
        print("[缺] 没找到逐层产物：%s/%s_L_*.png" % (d, KEY), file=sys.stderr)
        return 2
    for layer, p in files.items():
        w, h, cov, touch = box_of(p)
        print("  %-22s %5dx%-5d 覆盖 %6.2f%%  铺满=%s  %s"
              % (layer, w, h, cov * 100, "是" if touch else "否",
                 "(%.1f MB)" % (os.path.getsize(p) / 1048576.0)))
    print()
    print("判读：单独 fit 后仍『铺满』的层 = 它是背景（外接框被它撑满）；")
    print("      角色层不会铺满（它有留白）。取景应以角色层为准。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
