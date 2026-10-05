# -*- coding: utf-8 -*-
"""闸门判据的反向对照测试：`row_backed()` 与 `dup_row_fix()`（正本在 ship_meta_authority_diff）。

为什么单独一个文件：这两条判据是受保护档(painting/suffix)允许被改动的**仅有的出口**。
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
_n = len(CASES) + len(CASES2) + len(CASES3)
print('\n%s 判据反向对照 %d/%d' % ('[PASS]' if not fails else '[FAIL]', _n - fails, _n))
sys.exit(1 if fails else 0)
