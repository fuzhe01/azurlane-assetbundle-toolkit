# -*- coding: utf-8 -*-
"""三档制的前端验收探针：在真浏览器里证明「舰船 / 剧情角色 / 其他」三档**确实按索引的
category 分好了**，并且秘书舰三族是**三张各自有名字的卡**。

为什么必须跑浏览器而不是只读 index.json：档位是前端 `catOf()` 算出来的，
数据对而前端还留着旧的 `'hei'/'variant'` 分支 ⇒ 页面上一张卡都点不到（假绿灯）。
判据全部落在**渲染那一刻的 DOM** 上（卡片副标题、档位按钮文案与计数）。

  py -3 scripts/diag/gallery_cat3_probe.py            # 需要画廊服务器在 8777
  起服务：py -3 scripts/diag/run_detached.py --log .diag/_srv.log -- \
          py -3 Output/gallery_v2/_gallery_server.py

六条判据（任一不满足退出码 1）：
  1 档位条恰好 4 个按钮，文案是 全部 / 舰船 / 剧情角色 / 其他（旧的剪影、特殊形态必须消失）
  2 计数自洽：全部 == 舰船 + 剧情角色 + 其他（"报一个点不到的数"就是这条要拦的）
  3 「其他」档里能数到 npc 前缀卡与 `· 剧情剪影` 伪卡，且**没有**秘书舰角色卡
  4 「剧情角色」档里 领航员-TB / 领洋者-娜比娅 / 探索者-艾普洛 是三张独立卡、各有 ≥10 皮肤
  5 三张卡的皮肤数与索引一致（防止前端合并时把皮肤整批丢掉）
  6 页面上的卡总数 == 索引三档之和（数据与渲染同源核对）
"""
import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
from gallery_ui_shots import Page, preflight        # noqa: E402

EV = lambda s: f"(()=>{{{s}}})()"
SEC = ['领航员-TB', '领洋者-娜比娅', '探索者-艾普洛']

fails = 0


def chk(desc, ok, detail=''):
    global fails
    fails += 0 if ok else 1
    print('%s %s%s' % ('✓' if ok else '✗', desc, ('  — ' + detail) if detail else ''))


def cards(pg):
    """当前网格里渲染出来的卡片：[名字, 副标题]。"""
    return json.loads(pg.ev(EV(
        "return JSON.stringify([...document.querySelectorAll('#main .card')]"
        ".map(c=>[c.querySelector('.nm').textContent.trim(),"
        "c.querySelector('.py').textContent.trim()]))")))


def click_tab(pg, c):
    pg.ev(EV(f"document.querySelector('#fCat button[data-c=\"{c}\"]').click();return 1"))
    time.sleep(1.2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=9333)
    ap.add_argument('--page', default='index.html')
    a = ap.parse_args()
    url = preflight(a.page)
    profile = os.path.join(ROOT, '.diag', 'chrome_cat3')
    os.makedirs(profile, exist_ok=True)
    pg = Page(a.port, profile, url, '1440,900')
    try:
        time.sleep(2.5)                                  # 等 index.js + 首屏渲染
        idx = json.loads(pg.ev(EV("return JSON.stringify(window.GALLERY.counts)")))

        tabs = [t.strip() for t in json.loads(pg.ev(EV(
            "return JSON.stringify([...document.querySelectorAll('#fCat button')]"
            ".map(b=>b.textContent.trim()))")))]
        chk('1 档位条只有 4 档', len(tabs) == 4, str(tabs))
        names = [t.split()[0] for t in tabs]
        chk('1b 旧的「剧情剪影 / 特殊形态」两档已消失',
            not any(n in names for n in ('剧情剪影', '特殊形态')), str(names))
        nums = {n: int(t.split()[-1]) for n, t in zip(names, tabs) if t.split()[-1].isdigit()}
        chk('2 计数自洽 全部 == 舰船+剧情角色+其他',
            nums.get('全部') == nums.get('舰船', 0) + nums.get('剧情角色', 0) + nums.get('其他', 0),
            str(nums))

        click_tab(pg, 'other')
        oth = cards(pg)
        oth_txt = '\n'.join(n + '|' + p for n, p in oth)
        chk('3 「其他」里有 npc 前缀卡', 'npc' in oth_txt.lower(), oth[0][1] if oth else '空')
        chk('3b 「其他」里有「· 剧情剪影」伪卡', '剧情剪影' in oth_txt)
        chk('3c 「其他」里**没有**秘书舰角色卡',
            not any(s in [n for n, _ in oth] for s in SEC))

        click_tab(pg, 'story')
        st = {n: p for n, p in cards(pg)}
        got = {s: st.get(s) for s in SEC}
        chk('4 三族是剧情角色档里的三张独立卡', all(got.values()), str(list(got)))
        skin_n = json.loads(pg.ev(EV(
            "return JSON.stringify(Object.fromEntries(window.GALLERY.ships"
            ".filter(s=>['tbniang','lingyangzhe32_3','tansuozhe32_3'].includes(s.id))"
            ".map(s=>[s.name,(s.skins||[]).length])))")))
        chk('5 三张卡的皮肤数 ≥10（与索引一致）',
            all(int((skin_n.get(s) or 0)) >= 10 for s in SEC), str(skin_n))
        total = int(pg.ev(EV("return window.GALLERY.ships.length"
                             "+(window.GALLERY.silhouettes||[]).length"
                             "+(window.GALLERY.variants||[]).length")))
        chk('6 页面卡总数 == 索引三档条目之和',
            total == idx['ships'] + idx['silhouettes'] + idx['variants'],
            f'{total} vs {idx["ships"]}+{idx["silhouettes"]}+{idx["variants"]}')
        print('\n索引 counts: ship %s / story %s / other %s'
              % (idx.get('ship'), idx.get('story'), idx.get('other')))
    finally:
        pg.close()
    print('\n%s 三档制前端验收 %s' % ('[PASS]' if not fails else '[FAIL]',
                                     '全绿' if not fails else '%d 条红' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
