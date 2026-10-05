# -*- coding: utf-8 -*-
"""闸门判据的反向对照测试：`row_backed()` / `dup_row_fix()` / `majority_fix()` /
`pair_tiebreak()` / `pair_rescue()`（正本都在 `ship_meta_authority_diff`）。

为什么单独一个文件：这些判据是受保护档(painting/suffix)允许被改动的**仅有的出口**。
它们写错的方向是**放行回退**（换成更远/不存在的行、或把有 CV 的行换回剧情行也认），而正向跑一遍永远看不出来——
只有把反向样本喂进去才知道它拦不拦。⇒ 每条都配一个"必须为 False"的对照。

用法: py -3 scripts/diag/test_meta_gate_proofs.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding='utf-8')

import ship_meta_authority_diff as G      # noqa: E402

TAB = {'aierdeliqi', 'aierdeliqi_9', 'mile', 'mile_3', 'lingmin', 'npclingmin_alter'}
CASES = [
    # (说明, (key, field, old, new), 期望)
    ('变体名退回远亲 → 停在表里真实存在的近行（本轮真实改动）',
     (('aierdeliqi_9_n', 'base_painting', 'aierdeliqi', 'aierdeliqi_9'), TAB), True),
    ('本名行自己补上（旧值是别的行）',
     (('mile_3', 'base_painting', 'mile', 'mile_3'), TAB), True),
    ('反向：从近行退回远亲 = 回退，必须拦',
     (('aierdeliqi_9_n', 'base_painting', 'aierdeliqi_9', 'aierdeliqi'), TAB), False),
    ('新 base 在权威表里根本没有这一行 = 凭空造名，必须拦',
     (('aierdeliqi_9_n', 'base_painting', 'aierdeliqi', 'aierdeliqi_12'), TAB), False),
    ('新 base 不是本名的前缀（换成不相干的皮肤）',
     (('aierdeliqi_9_n', 'base_painting', 'aierdeliqi', 'mile_3'), TAB), False),
    ('改的不是 base_painting 字段（skin_name 之类不走这条）',
     (('aierdeliqi_9_n', 'skin_name', '埃尔德里奇', '金月桂香'), TAB), False),
    ('旧值为空（从无到有不算"升级"，该走新增条目那条判据）',
     (('mile_3', 'base_painting', '', 'mile_3'), TAB), False),
    ('新旧相同（没改动却混进这条计数）',
     (('mile_3', 'base_painting', 'mile_3', 'mile_3'), TAB), False),
]

fails = 0


def check(label, cases, call):
    global fails
    bad = 0
    for desc, args, want in cases:
        got = call(args)
        ok = got == want
        bad += 0 if ok else 1
        print('%s %-52s 期望 %-5s 实得 %s' % ('✓' if ok else '✗', desc, want, got))
    fails += bad
    print('   —— %s %d/%d' % (label, len(cases) - bad, len(cases)))


# ---------- dup_row_fix：「同一 painting 多行」时的换行放行 ----------
# 行数据取自真实两行（海伦娜·META：剧情行 900315 cv=-1 / 自机行 9702010 cv=34）
_HL = [{'id': 900315, 'voice_actor': -1, 'ship_group': 900315},
       {'id': 9702010, 'voice_actor': 34, 'ship_group': 970201}]
_ROWS = {'hailunna_alter': _HL, 'single_alter': [_HL[1]]}
_PICK = {'hailunna_alter': _HL[1]}          # 新规则选中的行
_PICK_BACK = {'hailunna_alter': _HL[0]}     # 反向：选回剧情行
_GS = {970201}                              # 只有自机组在 ship_data_statistics 里查得到


def call_dup(args):
    t, picked, rows, gs = args
    return G.dup_row_fix(t, t[0], rows, picked, gs)


CASES2 = [
    ('正向：剧情行→自机行，阵营从无到有',
     (('hailunna_alter', 'faction', '', 'META'), _PICK, _ROWS, _GS), True),
    ('正向：同一次换行带来的 cn 改动',
     (('hailunna_alter', 'cn', '海伦娜·META', '海伦娜·META'), _PICK, _ROWS, _GS), True),
    ('category 只认 story→ship 这个方向',
     (('hailunna_alter', 'category', 'story', 'ship'), _PICK, _ROWS, _GS), True),
    ('反向：把有 CV 的行换成没 CV 的行 = 回退，必须拦',
     (('hailunna_alter', 'faction', 'META', ''), _PICK_BACK, _ROWS, _GS), False),
    ('反向：category 从 ship 掉回 story，必须拦',
     (('hailunna_alter', 'category', 'ship', 'story'), _PICK, _ROWS, _GS), False),
    ('该 painting 只有一行（根本没换行）',
     (('single_alter', 'faction', '', 'META'), _PICK, _ROWS, _GS), False),
    ('新旧选中同一行（剧情行自己选自己）',
     (('hailunna_alter', 'faction', '', 'META'), _PICK_BACK, _ROWS, _GS), False),
    ('新行有 CV 但它的组在 stats 表里查不到 → 不算自机',
     (('hailunna_alter', 'faction', '', 'META'), _PICK, _ROWS, set()), False),
    ('白名单外的字段（skin_name）不走这条',
     (('hailunna_alter', 'skin_name', 'A', 'B'), _PICK, _ROWS, _GS), False),
]

check('row_backed', CASES, lambda a: G.row_backed(*a))
check('dup_row_fix', CASES2, call_dup)

# ---------- majority_fix：组内候选行自相矛盾时的「少数派 → 多数派」放行 ----------
import collections  # noqa: E402

_K = lambda r: (r.get('nationality'), r.get('type'), r.get('rarity'))
_OUT = {'id': 900399, 'nationality': 2, 'type': 5, 'rarity': 5, 'english_name': 'MNF Gascogne'}
_MAJR = {'id': 900912, 'nationality': 9, 'type': 5, 'rarity': 5, 'english_name': 'MNF Gascogne'}
_SIM = {'id': 900464, 'nationality': 96, 'type': 23, 'rarity': 5, 'english_name': 'simulation'}
_REAL = {'id': 900467, 'nationality': 96, 'type': 23, 'rarity': 5, 'english_name': 'HNLMS Gouden Leeuw'}
_TIE_A = {'id': 1, 'nationality': 1, 'type': 1, 'rarity': 1, 'english_name': 'A'}
_TIE_B = {'id': 2, 'nationality': 2, 'type': 2, 'rarity': 2, 'english_name': 'B'}


def sup(pairs):
    c = collections.Counter()
    for r, n in pairs:
        c[_K(r)] = n
    return c


def call_maj(args):
    t, g, support, prev, cur = args
    return G.majority_fix(t, g, support, prev, cur, _K)


CASES3 = [
    ('正向：单条 outlier(nat=2 皇家) → 4 数派(nat=9 维希教廷)',
     (('jiasikenie', 'faction', '皇家', '维希教廷'), 99901,
      {99901: sup([(_MAJR, 4), (_OUT, 1)])}, {99901: _OUT}, {99901: _MAJR}), True),
    ('正向：同族内占位英文名 → 真英文名（只认 en 这一列）',
     (('jinshi', 'en', 'simulation', 'HNLMS Gouden Leeuw'), 960003,
      {960003: sup([(_SIM, 1), (_REAL, 5)])}, {960003: _SIM}, {960003: _REAL}), True),
    ('反向：多数派 → 少数派，必须拦',
     (('jiasikenie', 'faction', '维希教廷', '皇家'), 99901,
      {99901: sup([(_MAJR, 4), (_OUT, 1)])}, {99901: _MAJR}, {99901: _OUT}), False),
    ('反向：真英文名 → 占位 simulation，必须拦',
     (('jinshi', 'en', 'HNLMS Gouden Leeuw', 'simulation'), 960003,
      {960003: sup([(_SIM, 1), (_REAL, 5)])}, {960003: _REAL}, {960003: _SIM}), False),
    ('众数并列（2:2）拿不出多数派 → 不许自动放行',
     (('x', 'faction', 'A', 'B'), 7, {7: sup([(_TIE_A, 2), (_TIE_B, 2)])},
      {7: _TIE_A}, {7: _TIE_B}), False),
    ('新旧同一行（根本没换行）',
     (('x', 'faction', 'A', 'B'), 7, {7: sup([(_TIE_A, 2), (_TIE_B, 1)])},
      {7: _TIE_A}, {7: _TIE_A}), False),
    ('同族内改的不是 en 而是 cn（不许混在这里盖章）',
     (('jinshi', 'cn', '金鹿号（后排）', '金鹿号'), 960003,
      {960003: sup([(_SIM, 1), (_REAL, 5)])}, {960003: _SIM}, {960003: _REAL}), False),
    ('字段不在行派生清单里（category 走别的判据）',
     (('x', 'category', 'story', 'ship'), 99901,
      {99901: sup([(_MAJR, 4), (_OUT, 1)])}, {99901: _OUT}, {99901: _MAJR}), False),
    ('这艘卡所属组查不到候选行（g=None）',
     (('x', 'faction', '', 'META'), None, {}, {}, {}), False),
]

check('majority_fix', CASES3, call_maj)

# ---------- pair_tiebreak：众数并列时「min(id) 行 → id==基皮肤 配对行」的放行 ----------
_ESSEX = {'id': 900406, 'name': '埃塞克斯·META', 'nationality': 97, 'type': 7, 'rarity': 5}
_SARA = {'id': 900550, 'name': '萨拉托加·META', 'nationality': 97, 'type': 7, 'rarity': 5}
_OTHER_T = {'id': 900551, 'name': '别船', 'nationality': 1, 'type': 7, 'rarity': 5}


def call_tie(args):
    t, g, base_id, prev, cur = args
    return G.pair_tiebreak(t, g, base_id, prev, cur, _K)


CASES4 = [
    ('正向：组 900550 并列族内 min(id)=900406 → 配对行 id=900550（本轮真实改动）',
     (('npcsalatuojia_alter', 'cn', '埃塞克斯·META', '萨拉托加·META'), 900550, 900550,
      {900550: _ESSEX}, {900550: _SARA}), True),
    ('反向：从配对行换回 min(id) 行，必须拦',
     (('npcsalatuojia_alter', 'cn', '萨拉托加·META', '埃塞克斯·META'), 900550, 900550,
      {900550: _SARA}, {900550: _ESSEX}), False),
    ('新行不是配对行（id != 基皮肤 id）→ 这条不盖章',
     (('x', 'cn', 'A', 'B'), 900550, 900550, {900550: _ESSEX}, {900550: _OTHER_T}), False),
    ('两行三列不同 → 属于 majority_fix 的范围，这里不许重复盖章',
     (('x', 'faction', '白鹰', 'META'), 900550, 900550,
      {900550: _OTHER_T}, {900550: _SARA}), False),
    ('根本没换行', (('x', 'cn', 'A', 'B'), 900550, 900550,
                   {900550: _SARA}, {900550: _SARA}), False),
    ('字段是 category（不走换行判据）',
     (('x', 'category', 'story', 'ship'), 900550, 900550,
      {900550: _ESSEX}, {900550: _SARA}), False),
    ('这艘卡所属组查不到候选行（g=None）', (('x', 'cn', 'A', 'B'), None, None, {}, {}), False),
]

check('pair_tiebreak', CASES4, call_tie)

# ---------- pair_rescue：组内查不到 stats 时「无舰级 → 同名 id 配对行」的放行 ----------
_SKIN = {'id': 900406, 'painting': 'aisaikesi_alter', 'name': '埃塞克斯·META', 'ship_group': 900406}
_STAT = {'id': 900406, 'name': '埃塞克斯·META', 'nationality': 97, 'type': 7, 'rarity': 5}
_SKINID = {900406: _SKIN}
_STATID = {900406: _STAT}
_NEW = {'cn': '埃塞克斯·META', 'base_painting': 'aisaikesi_alter',
         'stats_via': 'id_pair:900406', 'faction': 'META'}


def call_pair(args):
    t, new_e, old_e = args
    return G.pair_rescue(t, new_e, old_e, _STATID, _SKINID, str)


CASES5 = [
    ('正向：阵营从无到有（本轮真实改动 aisaikesi_alter）',
     (('aisaikesi_alter', 'faction', '', 'META'), _NEW, {'faction': ''}), True),
    ('正向：category 随舰级行从 story 变 ship',
     (('aisaikesi_alter', 'category', 'story', 'ship'), _NEW, {'faction': ''}), True),
    ('反向：旧条目本来就有阵营却被换掉，必须拦',
     (('aisaikesi_alter', 'faction', '白鹰', 'META'), _NEW, {'faction': '白鹰'}), False),
    ('新条目没写 stats_via（不是走救援来的）',
     (('aisaikesi_alter', 'faction', '', 'META'),
      {**_NEW, 'stats_via': ''}, {'faction': ''}), False),
    ('stats_via 指向盘上不存在的行',
     (('aisaikesi_alter', 'faction', '', 'META'),
      {**_NEW, 'stats_via': 'id_pair:999999'}, {'faction': ''}), False),
    ('配对皮肤行的 painting 与本条 base_painting 不同（张冠李戴）',
     (('aisaikesi_alter', 'faction', '', 'META'),
      {**_NEW, 'base_painting': 'salatuojia_alter'}, {'faction': ''}), False),
    ('两侧 name 不相同（只剩 id 同号这一条，等于用号段大小当判据）',
     (('aisaikesi_alter', 'faction', '', 'META'),
      {**_NEW, 'cn': '别的东西'}, {'faction': ''}), False),
    ('字段是 base_painting（换 base 走 row_backed）',
     (('aisaikesi_alter', 'base_painting', 'aisaikesi', 'aisaikesi_alter'),
      _NEW, {'faction': ''}), False),
]

check('pair_rescue', CASES5, call_pair)

# ---------- bridge_fix：META 实体从「剥后缀折进本体」改成「补桥表自己那一行」 ----------
_BR_NEW = {'source': 'bridge', 'base_painting': 'lingmin_alter', 'meta_group': 970113,
           'meta_via': 'ship_data_group+fleet_tech_ship_class+prefab', 'faction': 'META',
           'cn': '灵敏·META', 'rarity': '', 'voice_actor': -1}
_OLD = {'source': 'suffix', 'base_painting': 'lingmin', 'faction': '北方联合',
        'cn': '灵敏', 'rarity': '精锐', 'voice_actor': 304}


def call_bridge(args):
    t, new_e, old_e = args
    return G.bridge_fix(t, new_e, old_e)


CASES6 = [
    ('正向：阵营从本体船换成 META（本轮真实改动 lingmin_alter）',
     (('lingmin_alter', 'faction', '北方联合', 'META'), _BR_NEW, _OLD), True),
    ('正向：稀有度从错贴的「精锐」变空（去错值不算回退）',
     (('lingmin_alter', 'rarity', '精锐', ''), _BR_NEW, _OLD), True),
    ('正向：CV 字段从本体的换成 -1（她那行表里没有 voice_actor，不许拿本体的顶）',
     (('lingmin_alter', 'voice_actor', 304, -1), _BR_NEW, _OLD), True),
    ('反向：从 META 换回本体船（新条目不走桥）必须拦',
     (('lingmin_alter', 'faction', 'META', '北方联合'),
      {**_BR_NEW, 'source': 'suffix', 'faction': '北方联合'},
      {**_OLD, 'faction': 'META', 'base_painting': 'lingmin_alter'}), False),
    ('反向：旧口径本来就有她自己那一行（base_painting == 本键）⇒ 不该被桥接管',
     (('lingmin_alter', 'faction', '北方联合', 'META'),
      _BR_NEW, {**_OLD, 'base_painting': 'lingmin_alter'}), False),
    ('新条目没有 meta_via（没出处）必须拦',
     (('lingmin_alter', 'faction', '北方联合', 'META'),
      {**_BR_NEW, 'meta_via': ''}, _OLD), False),
    ('旧条目来源不是配置桥（npc_table 那类）不走这条',
     (('lingmin_alter', 'faction', '北方联合', 'META'),
      _BR_NEW, {**_OLD, 'source': 'npc_table'}), False),
    ('字段是别的列（voice_bank 之外的未知列仍要落别条判据）',
     (('lingmin_alter', 'l2d_se', 'a', 'b'), _BR_NEW, _OLD), False),
    # 第二轮（§108）：同一张补桥条目内，把**显式声明过**的稀有度从空填上
    ('正向：补桥条目内 rarity 从空 → 声明值（带 confirmed_via，本轮真实改动）',
     (('lingmin_alter', 'rarity', '', '精锐'),
      {**_BR_NEW, 'rarity': '精锐', 'confirmed_via': '用户 2026-10-05 裁定：SR=码 4'},
      {**_OLD, 'source': 'bridge', 'base_painting': 'lingmin_alter', 'rarity': ''}), True),
    ('反向：声明值被抹成空，必须拦',
     (('lingmin_alter', 'rarity', '精锐', ''),
      {**_BR_NEW, 'rarity': ''},
      {**_OLD, 'source': 'bridge', 'base_painting': 'lingmin_alter', 'rarity': '精锐'}), False),
    ('反向：同一格从一个声明值换成另一个（精锐→超稀有）不走这条',
     (('lingmin_alter', 'rarity', '精锐', '超稀有'),
      {**_BR_NEW, 'rarity': '超稀有', 'confirmed_via': '改了说法'},
      {**_OLD, 'source': 'bridge', 'base_painting': 'lingmin_alter', 'rarity': '精锐'}), False),
    ('填了稀有度却没有 confirmed_via（没出处）必须拦',
     (('lingmin_alter', 'rarity', '', '精锐'),
      {**_BR_NEW, 'rarity': '精锐'},
      {**_OLD, 'source': 'bridge', 'base_painting': 'lingmin_alter', 'rarity': ''}), False),
    ('声明值不许顺手改阵营（bridge→bridge 只放行稀有度那一格）',
     (('lingmin_alter', 'faction', '北方联合', 'META'),
      {**_BR_NEW, 'confirmed_via': '有'},
      {**_OLD, 'source': 'bridge', 'base_painting': 'lingmin_alter'}), False),
]

check('bridge_fix', CASES6, call_bridge)
_n = len(CASES) + len(CASES2) + len(CASES3) + len(CASES4) + len(CASES5) + len(CASES6)
print('\n%s 判据反向对照 %d/%d' % ('[PASS]' if not fails else '[FAIL]', _n - fails, _n))
sys.exit(1 if fails else 0)
