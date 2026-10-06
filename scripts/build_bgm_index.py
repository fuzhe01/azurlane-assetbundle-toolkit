# -*- coding: utf-8 -*-
"""生成画廊 BGM 页的数据 `Output/gallery_v2/bgm.json`（自包含，前端不再回头读 .diag）。

三个来源，缺后两个也能跑（只是没有中文名）：
  1. `Output/Audio/BGM*/*.ogg` —— 曲目本体（时长优先取 `transcode_bgm.py` 的台账，缺则 ffprobe）
  2. `.diag/sharecfg_re/lua_json/music_collect_config.json` —— 官方中文曲名（实测 54 首）
  3. `.diag/sharecfg_re/lua_json/music_album.json` —— 11 张专辑的中文名
⚠️ 2/3 在 `.diag/`（gitignore、可再生的解表产物），所以**名字一律烘进 bgm.json**，
   前端只读 bgm.json；这两张表读不到时打警告并降级成 slug，不静默出半截数据。

用法: py -3 scripts/build_bgm_index.py [--dir Output/Audio/BGM_ogg] [--out Output/gallery_v2/bgm.json]
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P

LUA = os.path.join(P.ROOT, '.diag', 'sharecfg_re', 'lua_json')
TRANSCODE_MANIFEST = os.path.join(P.ROOT, 'ledger', 'bgm_transcode.json')


def _lua(name):
    """读一张解好的 lua 表。**表头行按内容剔**（它带 `__name`），不按键的 `#` 前缀——
    实测两种约定并存：`music_collect_config` 的数据行键是 `1/10/11…`、表头是 `#54`；
    而 `music_album` 的**数据行键本身就是 `#0..#9`**，按前缀滤会把整张表滤空。"""
    try:
        with open(os.path.join(LUA, name), encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return [v for v in d.values() if isinstance(v, dict) and '__name' not in v]


def humanize(slug):
    """`bgm-battle-nep` → `Battle · Nep`；`-inst`/`-short`/`-full` 这类版本尾巴单独标。"""
    s = re.sub(r'^bgm[-_]', '', slug)
    parts = [x for x in re.split(r'[-_]', s) if x]
    tail = ''
    if parts and parts[-1].lower() in ('inst', 'short', 'full', 'loop', 'ver2', 'edit'):
        tail = parts.pop()
    name = ' · '.join(x.upper() if len(x) <= 3 and x.isascii() else x.capitalize() for x in parts)
    return (name + (f'（{tail}）' if tail else '')) or slug


def main():
    ap = argparse.ArgumentParser(description='生成 bgm.json')
    ap.add_argument('--dir', default=os.path.join(P.OUT, 'Audio', 'BGM_ogg'))
    ap.add_argument('--out', default=os.path.join(P.OUT, 'gallery_v2', 'bgm.json'))
    a = ap.parse_args()
    if not os.path.isdir(a.dir):
        print(f'[FAIL] 目录不存在: {a.dir}')
        return 2

    durs = {}
    try:
        with open(TRANSCODE_MANIFEST, encoding='utf-8') as f:
            for w, r in (json.load(f).get('done') or {}).items():
                durs[w] = r.get('src_dur') or r.get('dst_dur')
    except (OSError, ValueError):
        print('! 转码台账读不到，时长改用 ffprobe（慢一些）')

    cn = {}
    rows = _lua('music_collect_config.json')
    if rows:
        # 专辑表**没有 id 字段**（键是 `#0..#9` 的行号），能对上 `album_id` 的只有 `order`：
        # 1..10 连续无重复，且 id=10 的曲目全是鸢尾主题、正对 order=10「奏响鸢尾之歌」⇒ 按 order 连。
        albums = {str(x.get('order')): x.get('album_name') for x in (_lua('music_album.json') or [])}
        for r in rows:
            m = r.get('music')
            if m:
                cn[m] = {'title_cn': r.get('name') or '', 'album': albums.get(str(r.get('album_id')), '')}
    else:
        print('! music_collect_config.json 读不到 ⇒ 中文曲名/专辑留空（bgm.json 仍自包含）')

    oggs = sorted(f for f in os.listdir(a.dir) if f.lower().endswith('.ogg'))
    if not oggs:
        print(f'[FAIL] {a.dir} 里没有 .ogg')
        return 2
    tracks = []
    for f in oggs:
        stem = os.path.splitext(f)[0]
        p = os.path.join(a.dir, f)
        # 转码台账的键是**源 wav 名**，不是 ogg 名
        dur = durs.get(stem + '.wav')
        if dur is None:
            ff = P.tool('AL_FFMPEG', 'ffmpeg')
            r = subprocess.run([ff.replace('ffmpeg', 'ffprobe'), '-v', 'error', '-show_entries',
                                'format=duration', '-of', 'default=nw=1:nk=1', p],
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
            try:
                dur = round(float(r.stdout.strip()), 2)
            except ValueError:
                dur = 0.0
        info = cn.get(stem, {})
        # 前端在 Output/gallery_v2/ 里，所以 URL 相对 Output 再加一层 ../（与语音条同一写法）
        tracks.append({'file': f, 'url': '../' + os.path.relpath(p, P.OUT).replace(os.sep, '/'),
                       'slug': stem, 'title': humanize(stem), 'title_cn': info.get('title_cn', ''),
                       'album': info.get('album', ''), 'dur': round(dur or 0, 2),
                       'size': os.path.getsize(p)})
    tracks.sort(key=lambda t: (t['album'] == '', t['album'], t['slug']))
    out = {'generated': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
           'source_dir': os.path.relpath(a.dir, P.ROOT).replace(os.sep, '/'),
           'counts': {'tracks': len(tracks), 'named_cn': sum(1 for t in tracks if t['title_cn']),
                      'albums': len({t['album'] for t in tracks if t['album']}),
                      'hours': round(sum(t['dur'] for t in tracks) / 3600, 2),
                      'mb': round(sum(t['size'] for t in tracks) / 2 ** 20, 1)},
           'tracks': tracks}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    c = out['counts']
    print(f'[OK] {a.out}：{c["tracks"]} 首 / {c["hours"]} 小时 / {c["mb"]} MB，'
          f'其中官方中文名 {c["named_cn"]} 首、专辑 {c["albums"]} 张')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
