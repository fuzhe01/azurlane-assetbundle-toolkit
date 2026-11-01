# -*- coding: utf-8 -*-
"""hand_skin_map.py — 对画廊截图做肤色分布热图，定位「手」在画布上的位置。

用途：手掌消失排查时，判断①隔离渲染出的手部 mesh 到底落在画面哪里；②正常渲染下
那个位置有没有肤色（有=手在，无=手没画/被盖）。

用法: py -3.14 .diag/hand_skin_map.py <png> [--grid 24x16] [--crop x0,y0,x1,y1]
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image


def is_skin(r, g, b):
    return r > 110 and g > 60 and b > 40 and r > g and g >= b and (r - b) > 18 and (r - g) > 6


def main():
    path = sys.argv[1]
    grid = "24x16"
    crop = None
    for i, a in enumerate(sys.argv):
        if a == "--grid":
            grid = sys.argv[i + 1]
        if a == "--crop":
            crop = tuple(int(x) for x in sys.argv[i + 1].split(","))
    im = Image.open(path).convert("RGB")
    W, H = im.size
    if crop:
        im = im.crop(crop)
        W, H = im.size
    print(f"{os.path.basename(path)}  {W}x{H}  crop={crop}")
    gw, gh = (int(x) for x in grid.split("x"))
    px = im.load()
    cell_w, cell_h = W / gw, H / gh
    counts = [[0] * gw for _ in range(gh)]
    tot = 0
    for gy in range(gh):
        y0, y1 = int(gy * cell_h), int((gy + 1) * cell_h)
        for gx in range(gw):
            x0, x1 = int(gx * cell_w), int((gx + 1) * cell_w)
            n = 0
            for y in range(y0, min(y1, H), 2):
                for x in range(x0, min(x1, W), 2):
                    r, g, b = px[x, y]
                    if is_skin(r, g, b):
                        n += 1
            counts[gy][gx] = n
            tot += n
    mx = max(max(row) for row in counts) or 1
    shades = " .:-=+*#%@"
    print(f"肤色像素总数(采样1/4)={tot}")
    print("热图（列=x，行=y，越亮肤色越多）：")
    hdr = "    " + "".join(f"{int(gx*cell_w)//100%10}" for gx in range(gw))
    print(hdr)
    for gy in range(gh):
        row = "".join(shades[min(len(shades) - 1, int(v / mx * (len(shades) - 1)))] for v in counts[gy])
        print(f"{int(gy*cell_h):4d} {row}")
    # 找最密集的若干格
    cells = sorted(((counts[gy][gx], gx, gy) for gy in range(gh) for gx in range(gw)), reverse=True)
    print("\nTop 肤色格（x,y 为像素坐标中心，count=采样点数）:")
    for v, gx, gy in cells[:10]:
        if v <= 0:
            break
        print(f"  ({int(gx*cell_w)},{int(gy*cell_h)}) count={v}  ~{v*4}px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
