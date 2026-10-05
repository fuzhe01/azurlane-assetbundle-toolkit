#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布「秘书舰 NPC 语音与台词表」：立绘资源名（小写）→ 语音包号 + 逐条台词（含台账）。

为什么单独一步（不塞进 45 号）：45 号回答的是"这张立绘属于哪个角色"，本脚本回答的是
"这张立绘**说话吗、说的是什么**"。两件事的消费方不同（45 → build_ship_meta；本表 →
`extract_secretary_voice.py` + 画廊语音层），写进一份文件会让台账与消费方都对不上。

权威源：游戏本体 `secretary_special_ship`（41 行 / 3 个角色）。每行自带
`voice: cv-<包号>` 与一组台词字段（login / mail / touch / mission / mission_complete /
expedition / home / huodong / qingrenjie / shengdan / wansheng / xinnian / zhongqiu /
genghuan / chuxi + `chime_0..23` 报时词）。

**cue 名 == 台词字段名**（实测 `cv-1000.b` 解出 44 条：chime_0..23 / login / mail /
main_1..5 / touch / …），所以映射是直读，不需要任何语义推断。唯一要处理的是 `main`：
表里是一整串用 `|` 分隔的 5 段，包里是 `main_1..main_5` 五条 cue ⇒ 按 `|` 切开对齐。

台词正文里的 `{namecode:NN}` 占位符就地换成真名（用 `inputs/gamecfg/name_code.json`），
否则字幕会显示 `{namecode:98}` 这种东西（§36 的教训）。

产物不入库（`.gitignore: inputs/*/*.json`），台账 `inputs/gamecfg/MANIFEST.json` 入库。

用法: py -3 tools/sharecfg_re/47_publish_npc_voice.py [--check]
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LUAJ = os.path.join(ROOT, '.diag', 'sharecfg_re', 'lua_json')
DST = os.path.join(ROOT, 'inputs', 'gamecfg')
OUT_FN = 'npc_voice.json'
SRC_TABLE = 'secretary_special_ship'
NAME_CODE = os.path.join(DST, 'name_code.json')

ROLE = ('秘书舰 NPC 立绘（小写）→ 语音包号 cv-<id> + 逐条台词正文（占位符已展开）+ group/type/'
        'unlock_desc，41 行 3 个实体（游戏本体 9.7.385 的 secretary_special_ship 表）')
CONSUMERS = ['scripts/extract_secretary_voice.py', 'scripts/build_gallery_index.py']
# 表里的台词字段：cue 名与字段名一一对应（`main` 特殊，按 `|` 切成 main_1..N）
LINE_FIELDS = ['login', 'mail', 'touch', 'mission', 'mission_complete', 'expedition',
               'home', 'huodong', 'qingrenjie', 'shengdan', 'wansheng', 'xinnian',
               'zhongqiu', 'genghuan', 'chuxi']
CHIME = re.compile(r'^chime_\d+$')
PLACE = re.compile(r'\{namecode:(\d+)\}')
PACK = re.compile(r'^cv-\d+$')


def expand(text, ncode):
    """`{namecode:NN}` → 真名。查不到就**原样留着**并在自检里点名，不许悄悄留占位符。"""
    miss = []

    def rep(m):
        rec = ncode.get(m.group(1))
        if not rec:
            miss.append(m.group(1))
            return m.group(0)
        return str(rec.get('name') or '').strip() or m.group(0)
    return PLACE.sub(rep, str(text or '').strip()), miss


def build():
    raw = json.load(open(os.path.join(LUAJ, SRC_TABLE + '.json'), encoding='utf-8'))
    ncode = json.load(open(NAME_CODE, encoding='utf-8')) if os.path.exists(NAME_CODE) else {}
    out, missing = {}, []
    for v in raw.values():
        if not isinstance(v, dict) or not v.get('painting'):
            continue
        stem = str(v['painting']).strip().lower()
        lines = {}
        for f in LINE_FIELDS:
            txt, miss = expand(v.get(f), ncode)
            missing += miss
            if txt:
                lines[f] = txt
        if v.get('main'):                                    # 一整串 `|` 分段 ↔ 包内 main_1..N
            for i, seg in enumerate([s.strip() for s in str(v['main']).split('|') if s.strip()], 1):
                txt, miss = expand(seg, ncode)
                missing += miss
                lines['main_%d' % i] = txt
        for k in sorted([k for k in v if CHIME.match(str(k))], key=lambda x: int(x.split('_')[1])):
            txt, miss = expand(v[k], ncode)
            missing += miss
            if txt:
                lines[k] = txt
        rec = {'cn': str(v.get('name') or '').strip(),
               'character_id': v.get('character_id'),
               'row_id': v.get('id'), 'group': v.get('group'), 'type': v.get('type'),
               'voice_pack': str(v.get('voice') or '').strip(),
               'unlock_type': v.get('unlock_type'),
               'unlock_desc': str(v.get('unlock_desc') or '').strip(),
               'lines': lines}
        if stem in out and out[stem]['row_id'] != rec['row_id']:
            raise SystemExit('歧义：立绘 %s 同时属于行 %s 与 %s' % (stem, out[stem]['row_id'], rec['row_id']))
        out[stem] = rec
    return out, sorted(set(missing))


def selfcheck(data):
    """五条真值断言：任一条红即不得写文件、不得记台账。"""
    packs = {r['voice_pack'] for r in data.values()}
    return [
        ('41 行全部收进来（3 角色 × 各自换装集）', len(data) == 41),
        ('实体只有 3 个', {r['cn'] for r in data.values()} ==
         {'领航员-TB', '领洋者-娜比娅', '探索者-艾普洛'}),
        ('语音包号全部形如 cv-<数字>，去重后 13 个',
         all(PACK.match(p) for p in packs) and len(packs) == 13),
        ('每行台词 ≥10 条（少于这个数说明字段名对不上）',
         all(len(r['lines']) >= 10 for r in data.values())),
        ('台词正文里没有未展开的 {namecode} 占位符',
         not any('{namecode' in t for r in data.values() for t in r['lines'].values())),
    ]


def merge_ledger(entry):
    path = os.path.join(DST, 'MANIFEST.json')
    led = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else \
        {'schema_version': 1, 'purpose': '从游戏本体 sharecfg 容器直接解出的权威映射',
         'provenance': {'regenerate_via': []}, 'files': []}
    prov = led.setdefault('provenance', {})
    prov.setdefault('game_version_local_assets', '9.7.385')
    prov.setdefault('container_grammar', 'docs/TROUBLESHOOTING.md §33/§34')
    prov['landed_at'] = datetime.date.today().isoformat()
    rg = prov.setdefault('regenerate_via', [])
    for s in ('tools/sharecfg_re/41_export_lua_tables.py', 'tools/sharecfg_re/47_publish_npc_voice.py'):
        if s not in rg:
            rg.append(s)
    files = [f for f in led.get('files', []) if f.get('path') != OUT_FN]
    files.append(entry)
    files.sort(key=lambda f: f['path'])
    led['files'] = files
    return led


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只跑断言与统计，不写文件')
    a = ap.parse_args()
    data, missing = build()
    print('立绘 %d 行 / 语音包 %d 个 / 台词条目 %d 条'
          % (len(data), len({r['voice_pack'] for r in data.values()}),
             sum(len(r['lines']) for r in data.values())))
    if missing:
        print('!! 有 %d 个 {namecode} 编号在 name_code 表里查不到（样例 %s）'
              % (len(missing), missing[:6]))
    ok = True
    for desc, passed in selfcheck(data):
        print('%s %s' % ('✓' if passed else '✗', desc))
        ok &= passed
    if not ok:
        print('\n闸门：红 —— 断言未全过，不写文件')
        return 1
    if a.check:
        print('\n闸门：绿（--check 未写文件）')
        return 0
    os.makedirs(DST, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    blob = body.encode('utf-8')
    # 二进制写：文本模式在 Windows 上会把 \n 变成 \r\n，台账里的 bytes/sha256 就对不上
    # （45 号脚本注释里点过同一条坑，本轮自己又撞一次：期望 202178B / 实际 203904B）
    with open(os.path.join(DST, OUT_FN), 'wb') as f:
        f.write(blob)
    entry = {'path': OUT_FN, 'bytes': len(blob),
             'sha256': __import__('hashlib').sha256(blob).hexdigest(),
             'rows': len(data), 'role': ROLE, 'consumers': CONSUMERS,
             'source': '.diag/sharecfg_re/lua_json/%s.json' % SRC_TABLE}
    led = merge_ledger(entry)
    with open(os.path.join(DST, 'MANIFEST.json'), 'w', encoding='utf-8') as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    print('\n[WRITE] inputs/gamecfg/%s（%d 行）+ 台账已更新' % (OUT_FN, len(data)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
