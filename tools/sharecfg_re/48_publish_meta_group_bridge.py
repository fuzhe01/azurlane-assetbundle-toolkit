#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布「META 组 ↔ 自机立绘」补桥表：游戏配置里**有船行、没有皮肤行**的 META 实体（含台账）。

为什么需要这一步（2026-10-05，§108）：`build_ship_meta.py` 的桥是
`磁盘 stem → 皮肤表 painting → ship_group → stats → 舰级字段`，语音侧的桥是
`皮肤行 → ship_group → cv-<ship_group>.b`。**两条桥的起点都是皮肤行** ⇒
只要游戏还没给这个实体写皮肤行，就会出现"船行有、包也有，但整条管线当她不存在的"状态：
实测 `ship_data_group` 有 `group_type=970113 / nationality=97`、`fleet_tech_ship_class` 写着
`灵敏·META`、`files/AssetBundles/cue/cv-970113.b`（2.3MB，含 `-battle`/`-gift`）早在盘上，
而皮肤表 2865 行里**没有 970113 这一组**（同系列 9701100 杜威 / 9701110 龙骑兵 / 9701120 布里斯托尔 都在，
`9701130` 那一格是空的）⇒ 她的立绘被剥后缀折进本体灵敏，语音借本体的 `cv-70109`。

**立绘这一半不靠命名规则猜**，用游戏自己写的字段：她的剧情皮肤行（id 900549，
`painting=npclingmin_alter`，`name=灵敏·META`）里 **`prefab = 'lingmin_alter'`** ——
`prefab` 就是该实体的自机立绘资源名。加入方式：`fleet_tech_ship_class` 的实体名 ↔ 皮肤行 `name`
**精确相等**（清洗「（后排）」那类方位尾缀后），且**候选必须唯一**（0 条或多条一律判红，不许挑一条）。

产物：`inputs/gamecfg/meta_group_bridge.json`，键=**自机立绘资源名（小写）**，值含
`group/cn/nationality_code/faction/type_code/type/painting/bank/row_id/story_painting/prefab/via`。
⚠️ **rarity 一律留空**：配置侧这几张表里没有她的稀有度字段，而按中文名去维基兜底会命中
**本体灵敏（北方联合/精锐）** —— 那是错的兜底方向，宁可留空（卡片少一个标签，比挂错阵营好）。

不入库（`.gitignore: inputs/*/*.json`），台账 `inputs/gamecfg/MANIFEST.json` 入库。

用法:
  py -3 tools/sharecfg_re/48_publish_meta_group_bridge.py           # 写盘
  py -3 tools/sharecfg_re/48_publish_meta_group_bridge.py --check    # 只跑断言，不写文件
退出码：任一断言不过即 1（红时**不写文件**）。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LUAJ = os.path.join(ROOT, '.diag', 'sharecfg_re', 'lua_json')
DST = os.path.join(ROOT, 'inputs', 'gamecfg')
OUT_FN = 'meta_group_bridge.json'
PAINT_DIR = os.path.join(ROOT, 'Output', 'Paintings_v2')
CUE_DIR = os.path.join(ROOT, 'files', 'AssetBundles', 'cue')

sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import skin_table                                          # noqa: E402
from build_ship_meta import NATIONALITY, TYPE, RARITY, clean_ship_name   # noqa: E402

PLACE = re.compile(r'\{namecode:\d+\}')
# 配置侧查不到的字段，只能**显式声明**并带出处，不许从"同名本体船"偷偷兜底（那正是 §108 去掉的错贴值）。
# 用户 2026-10-05 游戏内核实后拍板：稀有度 SR、CV 沿用花井美春。
# ⚠️ `SR` 按项目码表是 **4 = 精锐**（`5` 才是 SSR/超稀有），所以这里写 `rarity_code=4`。
CONFIRMED = {
    970113: {'rarity_code': 4, 'voice_actor': 304,
             'via': '用户 2026-10-05 游戏内裁定：稀有度 SR(码表 4=精锐)、CV 同本体(花井美春, 码 304)'},
}
ROLE = ('META 实体的「有船行、无皮肤行」补桥：自机立绘资源名（小写）→ 语音包组号/阵营/舰种/实体名/'
        '剧情行 id + prefab 出处（游戏本体 ship_data_group + fleet_tech_ship_class + ship_skin_template.prefab）')
CONSUMERS = ['scripts/build_ship_meta.py', 'scripts/extract_cv_voice.py']


def _rows(doc, key):
    """摊平设备侧表：容器可能是 {id: {...}} 或带一层嵌套，统一产出 dict 行。"""
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    out = []
    for v in (doc or {}).values():
        if isinstance(v, dict) and key in v:
            out.append(v)
        elif isinstance(v, dict):
            out.extend(_rows(v, key))
    return out


def build(verbose=False):
    grp = json.load(open(os.path.join(LUAJ, 'ship_data_group.json'), encoding='utf-8'))
    tech = json.load(open(os.path.join(LUAJ, 'fleet_tech_ship_class.json'), encoding='utf-8'))
    skin = skin_table.load()
    sk_rows = [r for r in skin.values() if isinstance(r, dict) and r.get('id') is not None]
    sk_groups = {str(r.get('ship_group')) for r in sk_rows}
    sk_paints = {str(r.get('painting') or '').lower() for r in sk_rows}
    tech_name = {str(r.get('id')): r for r in _rows(tech, 'id')}
    paintings = {os.path.splitext(f)[0].lower() for f in os.listdir(PAINT_DIR)} if os.path.isdir(PAINT_DIR) else set()
    banks = {m.group(1) for f in os.listdir(CUE_DIR)
             for m in [re.match(r'cv-(\d+)\.b$', f)] if m} if os.path.isdir(CUE_DIR) else set()

    out, notes = {}, []
    for g in _rows(grp, 'group_type'):
        if g.get('nationality') != 97:
            continue
        gid = str(g['group_type'])
        if gid in sk_groups:                       # 皮肤行齐备，桥本来就走得通
            continue
        trow = tech_name.get(gid) or {}
        nm = clean_ship_name(trow.get('name') or '')
        if not nm or PLACE.search(nm) or '？' in nm:
            notes.append('组 %s：实体名不可用（%r），跳过' % (gid, trow.get('name')))
            continue
        cands = [r for r in sk_rows if clean_ship_name(str(r.get('name') or '')) == nm]
        if len(cands) != 1:
            # 唯一性是这个加入方式的全部强度所在：0 条=没有出处，≥2 条=同名不同实体，两种都不许猜一条。
            notes.append('组 %s（%s）：同名皮肤行 %d 条，不唯一 ⇒ 不接管'
                         % (gid, nm, len(cands)))
            continue
        row = cands[0]
        pf = str(row.get('prefab') or '').strip()
        key = pf.lower()
        if not pf:
            notes.append('组 %s（%s）：剧情行 %s 没有 prefab ⇒ 猜不出立绘，跳过' % (gid, nm, row['id']))
            continue
        if key in sk_paints:
            notes.append('组 %s（%s）：prefab %s 已是别的皮肤行的 painting，跳过' % (gid, nm, pf))
            continue
        if key not in paintings:
            notes.append('组 %s（%s）：盘上没有 %s.png，跳过' % (gid, nm, pf))
            continue
        if gid not in banks:
            notes.append('组 %s（%s）：cue 里没有 cv-%s.b（音频侧还没拉到），跳过' % (gid, nm, gid))
            continue
        rec = {
            'group': int(gid), 'cn': nm,
            'nationality_code': g.get('nationality'),
            'faction': NATIONALITY.get(g.get('nationality'), ''),
            'type_code': g.get('type'), 'type': TYPE.get(g.get('type'), ''),
            'rarity': '', 'rarity_via': '配置侧无稀有度字段，留空（按中文名兜底会命中本体同名，见脚本头）',
            'painting': pf, 'bank': 'cv-%s' % gid,
            'row_id': row['id'], 'story_painting': row.get('painting'),
            'via': 'ship_data_group(nat=97,group_type=%s) + fleet_tech_ship_class(%s)'
                   ' + ship_skin_template[%s].prefab' % (gid, nm, row['id']),
        }
        cf = CONFIRMED.get(int(gid))
        if cf:
            rec['rarity'] = RARITY.get(cf['rarity_code'], '')
            rec['rarity_code'] = cf['rarity_code']
            rec['voice_actor'] = cf['voice_actor']
            rec['confirmed_via'] = cf['via']
            # `rarity_via` 必须跟着改口：留着「留空」那句会和已填的值自相矛盾（产物里写反话比空着更坏）
            rec['rarity_via'] = cf['via']
        out[key] = rec
        if verbose:
            print('  补桥 %s ← group %s（%s），剧情行 %s / 立绘 %s，语音包 cv-%s'
                  % (key, gid, nm, row['id'], pf, gid))
    return out, notes


def selfcheck(out, sk_groups, sk_paints):
    """正向 + **反向**对照。反向那条是关键：它保证这脚本不会把已有皮肤行的 META 也接管一遍。"""
    checks = [
        ('补表条目都确实"组内无皮肤行"', all(str(v['group']) not in sk_groups for v in out.values())),
        ('补表指向的 painting 不是任何皮肤行的 painting',
         all(v['painting'].lower() not in sk_paints for v in out.values())),
        ('反向对照：970110(杜威·META) 这类皮肤行齐备的组**没有**被写进补表',
         'duwei_alter' not in out and '970110' in sk_groups),
        ('每条都有阵营与舰种（META + 舰种码可查）',
         all(v['faction'] == 'META' and v['type'] for v in out.values())),
        ('稀有度/CV 若被填上，必须带 `confirmed_via`（声明出处），且码值能在码表里查到',
         all((not v.get('rarity') and 'voice_actor' not in v)
             or (v.get('confirmed_via') and RARITY.get(v.get('rarity_code')) == v.get('rarity'))
             for v in out.values())),
    ]
    return checks


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
    for s in ('tools/sharecfg_re/41_export_lua_tables.py', 'tools/sharecfg_re/48_publish_meta_group_bridge.py'):
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

    skin = skin_table.load()
    rows = [r for r in skin.values() if isinstance(r, dict)]
    sk_groups = {str(r.get('ship_group')) for r in rows}
    sk_paints = {str(r.get('painting') or '').lower() for r in rows}

    out, notes = build(verbose=True)
    print('补桥条目 %d / 皮肤表 %d 行 / META 组里已有皮肤行的 %d 个'
          % (len(out), len(rows), len(sk_groups)))
    for n in notes:
        print('  ! %s' % n)
    ok = True
    for desc, passed in selfcheck(out, sk_groups, sk_paints):
        print('%s %s' % ('✓' if passed else '✗', desc))
        ok &= passed
    if not ok:
        print('\n闸门：红 —— 断言未全过，不写文件')
        return 1
    if a.check:
        print('\n闸门：绿（--check 未写文件）')
        return 0

    os.makedirs(DST, exist_ok=True)
    body = json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True)
    blob = body.encode('utf-8')
    # 二进制写：文本模式在 Windows 上把 \n 变 \r\n，台账的 bytes/sha256 就对不上（§103 撞过两次）
    with open(os.path.join(DST, OUT_FN), 'wb') as f:
        f.write(blob)
    entry = {'path': OUT_FN, 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(),
             'rows': len(out), 'role': ROLE, 'consumers': CONSUMERS,
             'source': '.diag/sharecfg_re/lua_json/{ship_data_group,fleet_tech_ship_class}.json'
                       ' + inputs/gamecfg/ship_skin_template.json'}
    # ⚠️ 必须**先读完旧台账再开写句柄**：`open(...,'w')` 一执行就把文件截成 0 字节，
    # 那时 `merge_ledger()` 再去读就只能读到空文件（本轮真把 MANIFEST.json 写坏过一次，
    # 靠 `git checkout HEAD --` 才恢复 —— 台账是入库的，产物不入库，所以必须这样保序）。
    led = merge_ledger(entry)
    with open(os.path.join(DST, 'MANIFEST.json'), 'w', encoding='utf-8') as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    print('\n[WRITE] inputs/gamecfg/%s（%d 条）+ 台账已更新' % (OUT_FN, len(out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
