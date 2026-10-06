# -*- coding: utf-8 -*-
"""把 BGM 的 wav 转成 opus/ogg（与现有 CV2 语音同一格式、同一播放路径），逐份校验时长。

为什么是 opus/ogg 而不是别的：`Output/Audio/CV2/*.ogg` 实测 codec_name=opus，
前端 `gallery_src/index.html:1216` 就是 `new Audio(path)` —— 跟着走就不引入第二条播放路径。
wav 侧实测 536 首 / 19.1 小时 / 44.1kHz 立体声，opus 128k ≈ 1.0 GB（回收 91%）。

⚠️ **本工具不删源文件**。删除是另一件事，要拿这份 manifest 逐条对过之后单独放行。
校验口径（三条，任一不过该文件判失败）：
  ① 产物存在且 > 1 KB；② ffprobe 能读出时长且与源差 < 0.25 s；③ 源 md5 记进台账（删了还能对账）。
可续跑：已在 manifest 里且源 md5 未变、产物还在 ⇒ 跳过（536 首约 15~25 分钟，中断不必重来）。

用法:
    py -3 scripts/transcode_bgm.py --out .diag/bgm_ogg --limit 3     # 样本
    py -3 scripts/transcode_bgm.py --out Output/Audio/BGM_ogg        # 全量（不删源）
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P

SRC_DIR = os.path.join(P.OUT, 'Audio', 'BGM')
MANIFEST = os.path.join(P.ROOT, 'ledger', 'bgm_transcode.json')
# ↑ 台账入库：删掉 wav 之后，这是唯一能逐份证明「这个 ogg 当时由那个 md5 的 wav 转出来」的东西，
#    所以不放 .diag（临时区，无 git 兜底）。
FFMPEG = P.tool('AL_FFMPEG', 'ffmpeg')
FFPROBE = FFMPEG.replace('ffmpeg', 'ffprobe') if FFMPEG else ''


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def dur(p):
    r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'default=nw=1:nk=1', p],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        return float(r.stdout.strip())
    except ValueError:
        return -1.0


def load():
    try:
        with open(MANIFEST, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'codec': 'libopus', 'bitrate': '', 'done': {}}


def main():
    ap = argparse.ArgumentParser(description='BGM wav → opus/ogg（带逐份时长校验，不删源）')
    ap.add_argument('--out', required=True, help='产物目录（样本建议放 .diag/）')
    ap.add_argument('--limit', type=int, default=0, help='只处理前 N 个（0=全部）')
    ap.add_argument('--bitrate', default='128k')
    ap.add_argument('--redo', action='store_true', help='忽略台账重转')
    a = ap.parse_args()
    if not FFMPEG:
        print('[FAIL] 找不到 ffmpeg（设 AL_FFMPEG 或装到 PATH）')
        return 2
    os.makedirs(a.out, exist_ok=True)
    rec = load()
    rec['bitrate'] = a.bitrate
    wavs = sorted(f for f in os.listdir(SRC_DIR) if f.lower().endswith('.wav'))
    if a.limit:
        wavs = wavs[:a.limit]
    tot_src = sum(os.path.getsize(os.path.join(SRC_DIR, w)) for w in wavs)
    print(f'源 {len(wavs)} 个 wav / {tot_src / 2**30:.2f} GB → {a.out}（opus {a.bitrate}）')
    ok = skip = bad = 0
    out_bytes = 0
    t0 = time.time()
    for i, w in enumerate(wavs, 1):
        src = os.path.join(SRC_DIR, w)
        dst = os.path.join(a.out, os.path.splitext(w)[0] + '.ogg')
        h = md5(src)
        old = rec['done'].get(w)
        if not a.redo and old and old['src_md5'] == h and os.path.isfile(dst):
            skip += 1
            out_bytes += old['dst_size']
            continue
        r = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y',
                            '-i', src, '-c:a', 'libopus', '-b:a', a.bitrate,
                            '-application', 'audio', dst],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        ds, dd = (os.path.getsize(dst) if os.path.isfile(dst) else 0), dur(dst)
        sd = old['src_dur'] if old and old.get('src_dur') else dur(src)
        if not os.path.isfile(dst) or ds < 1024:
            bad += 1
            print(f'  ✗ {w}: 产物缺失/过小 rc={r.returncode} {r.stderr.strip()[:120]}')
            continue
        if dd < 0 or abs(dd - sd) > 0.25:
            bad += 1
            print(f'  ✗ {w}: 时长对不上 源 {sd:.2f}s vs 产物 {dd:.2f}s')
            continue
        rec['done'][w] = {'src_md5': h, 'src_size': os.path.getsize(src), 'src_dur': sd,
                          'dst': os.path.relpath(dst, P.ROOT).replace(os.sep, '/'),
                          'dst_size': ds, 'dst_dur': round(dd, 3),
                          'dst_md5': md5(dst), 'at': time.strftime('%Y-%m-%d %H:%M:%S')}
        ok += 1
        out_bytes += ds
        if i <= 3 or i % 50 == 0 or i == len(wavs):
            print(f'  [{i}/{len(wavs)}] {os.path.splitext(w)[0][:34]:36s} '
                  f'{os.path.getsize(src) / 2**20:7.1f}→{ds / 2**20:6.2f} MB  {sd / 60:5.2f} 分钟')
        if i % 25 == 0:
            with open(MANIFEST, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print(f'\n成功 {ok} / 已存在跳过 {skip} / 失败 {bad}，用时 {(time.time() - t0) / 60:.1f} 分钟')
    print(f'台账共 {len(rec["done"])} 条 → {MANIFEST}')
    if out_bytes:
        print(f'产物合计 {out_bytes / 2**30:.2f} GB')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
