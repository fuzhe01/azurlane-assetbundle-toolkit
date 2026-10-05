#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画廊三档制的「其他」档判据——**唯一一份**，索引器与闸门都必须从这里取。

2026-10-05 用户定档：类别只留 舰船 / 剧情角色 / 其他，不再为剪影与形态族各开一档。
「其他」收的是**不是实体卡**的东西：

| 判据 | 实测张数 | 例子 |
|---|---|---|
| `npc` 前缀（剧情里的复制体 / NPC 换装） | 58 | `npcaimudeng`、`npclingmin_alter` |
| 键里含 `unknown`（塞壬 BOSS，假 stats 不可信） | 12 | `unknown5`、`unknown_undefined` |
| `_hei` / `_heihei` / `_shadow` / `_undefined` 结尾 | 3 | `unknown3_shadow` |
| `left` / `mid` / `right` 前缀（剧情里的左中右分身） | 3 | `leftchicheng_alter` |
| 用户点名的组件立绘 | 4 | `fulami`、`error13`、`lanmao`、`sairenboss14_jz` |

⚠️ **`_alter`（META / 异格）不在这里**：它是独立实体，按"能不能查到自机舰级信息"落舰船或剧情角色。
唯一例外是被上面两条抓走的 `npc*_alter` 与 `left/mid/right*_alter`（用户 2026-10-05 明确点名）。

⚠️ 这条判据同时被 `build_gallery_index.py`（产生 category）和
`diag/gallery_index_diff_check.py`（放行 `story→other`）使用。写两份必然漂移——
本项目已经为同类漂移付过一次 12 条语音错派的代价（§85）。
"""
import re

OTHER_PREFIX = re.compile(r'^(npc|left|mid|right)')
OTHER_SUF = re.compile(r'(_hei|_heihei|_shadow|_undefined)$')
# 用户点名单条，不是正则能概括的（组件立绘：一只猫、一个联动角色、一个 BOSS 碎片）
OTHER_NAMED = {'fulami', 'error13', 'lanmao', 'sairenboss14_jz'}


def is_other(key):
    """这张卡是不是「其他」档（非实体卡）。"""
    k = str(key or '').strip().lower()
    return bool(OTHER_PREFIX.match(k) or 'unknown' in k
                or OTHER_SUF.search(k) or k in OTHER_NAMED)
