# -*- coding: utf-8 -*-
"""把 BGM 的 wav 转成 opus/ogg（与现有 CV2 语音同一格式、同一播放路径），逐份校验时长。

为什么是 opus/ogg 而不是别的：`Output/Audio/CV2/*.ogg` 实测 codec_name=opus，
前端 `gallery_src/index.html:1216` 就是 `new Audio(path)` —— 跟着走就不引入第二条播放路径。
wav 侧实测 536 首 / 19.1 小时 / 44.1kHz 立体声，opus 128k ≈ 1.0 GB（回收 91%）。

⚠️ **本工具不删源文件**。删除是另一件事，要拿这份台账逐条对过之后单独放行。
两种档：`--codec opus`（有损，跟 CV2 语音同格式）/ `--codec flac`（无损，`--roundtrip N` 会
真把产物解码回 wav 与源比 md5 —— 无损不能靠格式名字断言）。台账按 codec 分文件。
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
def manifest_path(codec):
    """台账**按 codec 分文件**：共用一份的话，跑 FLAC 会把 opus 那 536 条溯源记录逐条覆盖掉。"""
    f = 'bgm_transcode.json' if codec == 'opus' else f'bgm_transcode_{codec}.json'
    return os.path.join(P.ROOT, 'ledger', f)
# ↑ 台账入库：删掉 wav 之后，这是唯一能逐份证明「这个 ogg 当时由那个 md5 的 wav 转出来」的东西，
#    所以不放 .diag（临时区，无 git 兜底）。
FFMPEG = P.FFMPEG   # 走 paths.py 的候选列表（PATH 里没有 ffmpeg 时也能命中本机安装位）
FFPROBE = os.path.join(os.path.dirname(FFMPEG), 'ffprobe.exe') if FFMPEG else ''


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


def load(man):
    try:
        with open(man, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'codec': 'libopus', 'bitrate': '', 'done': {}}


def encode_args(codec, bitrate):
    """两种档：opus 有损（跟 CV2 语音同格式）/ FLAC 无损（省得少但一个字节都不差）。"""
    if codec == 'flac':
        return ['-c:a', 'flac', '-compression_level', '8'], 'flac'
    return ['-c:a', 'libopus', '-b:a', bitrate, '-application', 'audio'], 'ogg'


def verify_only(codec, ext):
    """删源之前的总闸：不复编码，只把台账里每一条**重算**一遍。
    查三件事 —— 产物还在不在、md5 与台账是否一致、能不能整条解到底
    （FLAC 每帧带 CRC、STREAMINFO 里存整条原始 MD5，解码到 null 就会暴露坏帧）。
    这一步全绿才允许动 `Output/Audio/BGM/` 里的 wav。"""
    rec = load(manifest_path(codec))
    done = {w: r for w, r in rec['done'].items() if r.get('codec') == codec}
    if not done:
        print(f'[FAIL] 台账里没有 codec={codec} 的记录')
        return 2
    miss = changed = err = 0
    src_dir = SRC_DIR
    names = sorted(done)
    for i, w in enumerate(names, 1):
        r = done[w]
        d = os.path.join(P.ROOT, r['dst'])
        if not os.path.isfile(d):
            miss += 1
            print(f'  ✗ 产物不见了: {r["dst"]}')
            continue
        if md5(d) != r['dst_md5']:
            changed += 1
            print(f'  ✗ 产物 md5 与台账不符: {r["dst"]}')
            continue
        s = os.path.join(src_dir, w)
        if os.path.isfile(s) and md5(s) != r['src_md5']:
            err += 1
            print(f'  ✗ 源被改过（台账记的源 md5 对不上）: {w}')
            continue
        p = subprocess.run([FFMPEG, '-v', 'error', '-i', d, '-f', 'null', '-'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if p.returncode or p.stderr.strip():
            err += 1
            print(f'  ✗ 整条解码有问题: {r["dst"]} :: {p.stderr.strip()[:120]}')
        if i % 100 == 0 or i == len(names):
            print(f'  [{i}/{len(names)}] 缺 {miss} / 台账不符 {changed} / 解码或源异常 {err}', flush=True)
    print(f'\n台账 {len(names)} 条：产物缺失 {miss}、md5 不符 {changed}、解码/源异常 {err}')
    if miss or changed or err:
        print('[FAIL] 不许删源')
        return 1
    print('[PASS] 每条都在、每条 md5 与台账一致、每条能整条解到底 —— 可以进入换目录与删源')
    return 0


def main():
    ap = argparse.ArgumentParser(description='BGM wav → opus/ogg 或 FLAC（带逐份校验，不删源）')
    ap.add_argument('--out', required=True, help='产物目录（样本建议放 .diag/）')
    ap.add_argument('--limit', type=int, default=0, help='只处理前 N 个（0=全部）')
    ap.add_argument('--codec', choices=('opus', 'flac'), default='opus')
    ap.add_argument('--bitrate', default='128k')
    ap.add_argument('--roundtrip', type=int, default=0,
                    help='转完后抽 N 份解码回 wav 与源比 md5 —— 这才是"无损"的证据')
    ap.add_argument('--src', default=SRC_DIR, help='源 wav 目录（默认 Output/Audio/BGM）')
    ap.add_argument('--verify-only', action='store_true', dest='verify_only',
                    help='不编码，只复核台账里每一条（产物在/md5 一致/能整条解到底）—— 删源前的闸')
    ap.add_argument('--redo', action='store_true', help='忽略台账重转')
    a = ap.parse_args()
    if not FFMPEG:
        print('[FAIL] 找不到 ffmpeg（设 AL_FFMPEG 或装到 PATH）')
        return 2
    if a.verify_only:
        return verify_only(a.codec, encode_args(a.codec, a.bitrate)[1])
    if not os.path.isdir(a.src):
        print(f'[FAIL] 源目录不存在: {a.src}')
        return 2
    os.makedirs(a.out, exist_ok=True)
    man = manifest_path(a.codec)
    rec = load(man)
    rec['bitrate'] = a.bitrate if a.codec == 'opus' else 'lossless'
    ext = encode_args(a.codec, a.bitrate)[1]
    eargs = encode_args(a.codec, a.bitrate)[0]
    wavs = sorted(f for f in os.listdir(a.src) if f.lower().endswith('.wav'))
    if a.limit:
        wavs = wavs[:a.limit]
    if not wavs:
        # 换过目录之后再跑，源区里已经是 .flac 而不是 .wav —— 扫到 0 个还报"成功 0 失败 0"
        # 就是假绿灯，必须非零退出并说清原因。
        print(f'[FAIL] {a.src} 下没有 wav（找到 {len(os.listdir(a.src))} 个文件）。'
              f'若已换成 FLAC 档，本工具无事可做；要重导请先从源包解码回 wav。')
        return 2
    tot_src = sum(os.path.getsize(os.path.join(a.src, w)) for w in wavs)
    print(f'源 {len(wavs)} 个 wav / {tot_src / 2**30:.2f} GB → {a.out}（{a.codec}，.{ext}）')
    ok = skip = bad = 0
    out_bytes = 0
    t0 = time.time()
    for i, w in enumerate(wavs, 1):
        src = os.path.join(a.src, w)
        dst = os.path.join(a.out, os.path.splitext(w)[0] + '.' + ext)
        h = md5(src)
        old = rec['done'].get(w)
        # 续跑判据必须**含 codec**：否则跑 FLAC 时会因为 opus 的记录还在而整批跳过
        if (not a.redo and old and old.get('src_md5') == h and old.get('codec') == a.codec
                and os.path.isfile(dst)):
            skip += 1
            out_bytes += old['dst_size']
            continue
        r = subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y',
                            '-i', src] + eargs + [dst],
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
                          'codec': a.codec,
                          'dst': os.path.relpath(dst, P.ROOT).replace(os.sep, '/'),
                          'dst_size': ds, 'dst_dur': round(dd, 3),
                          'dst_md5': md5(dst), 'at': time.strftime('%Y-%m-%d %H:%M:%S')}
        ok += 1
        out_bytes += ds
        if i <= 3 or i % 50 == 0 or i == len(wavs):
            print(f'  [{i}/{len(wavs)}] {os.path.splitext(w)[0][:34]:36s} '
                  f'{os.path.getsize(src) / 2**20:7.1f}→{ds / 2**20:6.2f} MB  {sd / 60:5.2f} 分钟')
        if i % 25 == 0:
            with open(man, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
    with open(man, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    print(f'\n成功 {ok} / 已存在跳过 {skip} / 失败 {bad}，用时 {(time.time() - t0) / 60:.1f} 分钟')
    print(f'台账共 {len(rec["done"])} 条 → {man}')
    if out_bytes:
        print(f'产物合计 {out_bytes / 2**30:.2f} GB')

    if a.roundtrip:
        # "无损"不能靠"格式叫 FLAC"来断言 —— 要真的解码回来跟源逐字节比。
        # 取最大/最小/中间各若干，覆盖不同长度与内容。
        import random
        cands = [w for w in wavs if rec['done'].get(w, {}).get('codec') == a.codec]
        cands.sort(key=lambda w: os.path.getsize(os.path.join(a.src, w)))
        pick = list(dict.fromkeys(cands[:2]
                                  + cands[len(cands) // 2:len(cands) // 2 + 2] + cands[-3:]))
        rb = os.path.join(P.ROOT, '.diag', 'roundtrip.raw')

        def pcm(p):
            """比**裸 PCM 样本**，不比 .wav 文件字节 —— 重新封装的 wav 头（chunk 顺序与长度）
            和源不一样，拿整文件 md5 比会把真无损判成"不同"（2026-10-06 实测踩过）。"""
            subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-i', p,
                            '-f', 's16le', rb], check=True)
            return md5(rb)

        same = diff = 0
        print(f'\n== 无损回环验证（两边都解成裸 PCM 比 md5），抽 {len(pick)} 份 ==')
        for w in pick:
            d = os.path.join(a.out, os.path.splitext(w)[0] + '.' + ext)
            eq = pcm(os.path.join(a.src, w)) == pcm(d)
            same += eq
            diff += not eq
            print(f'  {"同" if eq else "异"}  {os.path.splitext(w)[0][:38]:40s} '
                  f'{os.path.getsize(os.path.join(a.src, w)) / 2**20:7.1f} MB')
        os.path.exists(rb) and os.remove(rb)
        print(f'回环：逐字节相同 {same} / 不同 {diff}')
        if diff:
            return 1
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
