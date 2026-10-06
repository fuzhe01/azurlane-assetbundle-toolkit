# -*- coding: utf-8 -*-
"""白雪皮肤2「脖子上一条细空线」定位：底图单层 / 叠脸之后 / 源纹理 三处对拍。

成品里有一行 ~420px 宽的透明带。要回答它来自哪：
  A 底图纹理自己就有（源数据如此）
  B mesh 光栅化漏采（三角形边界像素中心）
  C face 槽叠脸时脸谱自身底边留了一行透明
全部在**画布坐标**下量（成品被 getbbox 裁过，坐标不同源会读错行）。
用法: py -3 scripts/diag/baixue2_seam_probe.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image
import compose_paintings_v2 as C

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts', '..'))
OUT = os.path.join(ROOT, '.diag', 'probe_20261006')
os.makedirs(OUT, exist_ok=True)
BUN = sys.argv[1] if len(sys.argv) > 1 else 'baixue_2'

prod = Image.open(os.path.join(ROOT, 'Output', 'Paintings_v2', BUN + '.png')).convert('RGBA')

rects, go_names, father_map, children_map, parts, deps = C.parse_painting(BUN)
boxes, mirrors, roots = C.layout_all(rects, father_map, children_map)
order = C.draw_order(rects, father_map, children_map)
allb = list(boxes.values())
cw = int(max(b[0] + b[2] for b in allb))
ch = int(max(b[1] + b[3] for b in allb))
face_pid = next((rp for rp in rects if go_names.get(rp) == 'face'), None)
rx, ry, rw, rh = boxes[face_pid]
fpx, fpy = int(round(rx)), int(round(ch - (ry + rh)))
fww, fwh = max(1, int(round(rw))), max(1, int(round(rh)))
print(f'{BUN}: 画布 {cw}x{ch}  部件 {len(parts)}  face 槽画布框 ({fpx},{fpy},{fww}x{fwh})')

by_rect = {}
for p in parts:
    by_rect.setdefault(p['rect_pid'], []).append(p)


def layer_img(part, pid):
    res = C.build_part(dict(part))
    if res is None:
        return None
    arr, bbox, frame = res
    rx2, ry2, rw2, rh2 = boxes.get(pid, (0, 0, frame[0], frame[1]))
    sx = rw2 / frame[0] if frame[0] else 1
    sy = rh2 / frame[1] if frame[1] else 1
    x0, y0, x1, y1 = bbox
    mx, my = mirrors.get(pid, (False, False))
    if mx:
        x0, x1 = frame[0] - x1, frame[0] - x0
    if my:
        y0, y1 = frame[1] - y1, frame[1] - y0
    ww = max(1, int(round((x1 - x0) * sx)))
    wh = max(1, int(round((y1 - y0) * sy)))
    img = Image.fromarray(arr.astype(np.uint8), 'RGBA').transpose(Image.FLIP_TOP_BOTTOM)
    if mx:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if my:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    if (img.width, img.height) != (ww, wh):
        img = img.resize((ww, wh), Image.BILINEAR)
    px, py = int(round(rx2 + x0 * sx)), int(round(ch - (ry2 + y1 * sy)))
    solo = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    solo.paste(img, (px, py), img)
    return solo, (px, py, ww, wh), arr, bbox, frame


# ---- 1) 底图单层 ----
base = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
for pid in order:
    for part in by_rect.get(pid, []):
        got = layer_img(part, pid)
        if got is None:
            continue
        solo, box, arr, bbox, frame = got
        base = Image.alpha_composite(base, solo)
        print(f'  层 {part["name"]!r} 像素框 {box}')
A = np.asarray(base)


def bands(mat, tag, xlo, xhi, ylo, yhi):
    op = mat > 200
    for y in range(max(1, ylo), min(mat.shape[0] - 1, yhi)):
        bad = (~op[y, xlo:xhi]) & op[y - 1, xlo:xhi] & op[y + 1, xlo:xhi]
        n = int(bad.sum())
        if n > 150:
            xs = np.where(bad)[0] + xlo
            print(f'  [{tag}] y={y} 透明带 x∈[{xs.min()},{xs.max()}] 宽 {n}')


x0f, x1f = fpx, fpx + fww
print(f'\n在 face 槽横向范围 x∈[{x0f},{x1f}] 内找透明带：')
bands(A[..., 3], '底图', x0f, x1f, fpy, fpy + fwh)
C.compose(BUN, OUT, save=True)
g = C.FACE_GATE.get(BUN)
print(f'  FACE_GATE = {g}')

# ---- 2) 脸谱自身 ----
fx = C.paintingface_face(BUN, os.environ.get('FACE_DEFAULT', '1'))
if fx:
    fimg, (fw, fh) = fx
    print(f'\n  脸谱原图 {fw}x{fh}，resize 到 {fww}x{fwh}')
    fi = fimg.transpose(Image.FLIP_TOP_BOTTOM)
    if (fi.width, fi.height) != (fww, fwh):
        fi = fi.resize((fww, fwh), Image.BILINEAR)
    FA = np.asarray(fi)
    print(f'  脸谱 alpha：每 20 行的不透明数（自顶）')
    for y in range(0, fwh, max(1, fwh // 25)):
        print(f'    行{y:4d} 不透明 {int((FA[..., 3][y] > 200).sum()):4d} / {fww}')
    print(f'  脸谱最底 6 行不透明数: {[int((FA[..., 3][y] > 200).sum()) for y in range(fwh-6, fwh)]}')
    fi.save(os.path.join(OUT, f'{BUN}_face_overlay.png'))

# ---- 3) 源纹理里对应行 ----
part = parts[0]
so = C.find_obj(part['spr_bundle'], part['spr_pid'])
sd = so.read()
rd = getattr(sd, 'm_RD', None)
tex_pid = getattr(getattr(rd, 'texture', None), 'm_PathID', 0) or \
    getattr(getattr(rd, 'm_Texture', None), 'm_PathID', 0) or 0
tex = C.decoded_texture(part['spr_bundle'], tex_pid)
T = np.asarray(tex.convert('RGBA'))
print(f'\n  源纹理 {part["spr_bundle"]} tex_pid={tex_pid} {tex.size} m_Rect={tuple(sd.m_Rect)} frame={part["frame"]}')
mo = C.find_obj(part.get('mesh_bundle', part['spr_bundle']), part['mesh_pid'])
if mo is not None:
    from UnityPy.helpers.MeshHelper import MeshHandler
    h = MeshHandler(mo.read()); h.process()
    verts = np.asarray(h.m_Vertices, np.float64)[:, :2]
    uvs = np.asarray(h.m_UV0, np.float64)[:, :2]
    tris = np.asarray(h.get_triangles(), np.int64).reshape(-1, 3)
    print(f'  mesh 顶点 {len(verts)} 三角 {len(tris)}  '
          f'X[{verts[:,0].min():.1f},{verts[:,0].max():.1f}] Y[{verts[:,1].min():.1f},{verts[:,1].max():.1f}]')
    print(f'  UV  X[{uvs[:,0].min():.4f},{uvs[:,0].max():.4f}] Y[{uvs[:,1].min():.4f},{uvs[:,1].max():.4f}]')
    np.savez(os.path.join(OUT, f'{BUN}_mesh.npz'), verts=verts, uvs=uvs, tris=tris)

# ---- 4) 放大成品这一带 ----
P = np.asarray(prod)
op = P[..., 3] > 200
found = None
for y in range(1, op.shape[0] - 1):
    bad = (~op[y]) & op[y - 1] & op[y + 1]
    if int(bad.sum()) > 200:
        xs = np.where(bad)[0]
        print(f'\n  成品 y={y} 透明带 x∈[{xs.min()},{xs.max()}] 宽 {int(bad.sum())}')
        found = y
if found:
    for dy in range(-3, 4):
        row = P[found + dy, :, 3]
        nz = np.where(row <= 200)[0]
        print(f'   成品 y={found+dy}: 非不透明像素 {int((row<=200).sum())}  '
              f'alpha 分布 {sorted(set(row[found and 600:1100].tolist()))[:6]}')
    y0 = max(0, found - 110)
    crop = prod.crop((max(0, int(P.shape[1]*0.25)), y0, int(P.shape[1]*0.72), found + 110))
    bg = Image.new('RGB', crop.size, (255, 255, 255))
    bg.paste(crop, mask=crop.split()[3])
    bg = bg.resize((bg.width * 2, bg.height * 2), Image.NEAREST)
    p = os.path.join(OUT, f'{BUN}_seam_zoom.png')
    bg.save(p)
    print(f'  -> {p}')
