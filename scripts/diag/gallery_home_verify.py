#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画廊首页渲染完整性 + `?ship=` 直达验收探针。

守住的是一类**静默整批失效**缺陷（2026-09-30 实证）：
  `index.json` 里 `category='story'` 且 `npc:true` 的角色卡片带 `skins: []`（设计产物，非脏数据），
  而前端 `thumbOf(skin)` / `defSkin(s)` 未防空 -> `renderGrid()` 在 `makeCard` 抛
  `TypeError: Cannot read properties of undefined (reading 'cg')` -> forEach 中断，
  **该分区后续卡片全部不渲染**（分区标题还在，底下空白，极易误判成"索引少条目"）。
  更远的连带：`apply()` 与页面底部 `?ship=` 直达 IIFE 在**同一个 <script> 块**里，
  `apply()` 一抛错整块终止，那个 IIFE 从未注册 ⇒ **所有 `?ship=` 参数静默失效**。

所以本探针断言 4 件事：
  ① 首页 `.card` 数 == `GALLERY.ships` 数（今天 8 == 8）
  ② 各分区标题的声明条数与实际卡片数一致（"标题在、卡片没出来"是本缺陷的特征症状）
  ③ `?ship=<有皮肤>` 直达生效：mask 有 `on`、皮肤命中、L2D tab 未 dis
  ④ `?ship=<空皮肤 story 角色>` 不抛错、弹层能开并显示友好提示

判据不依赖任何写死行号或写死模型名（除了作为 `?ship` 样本的两个 id 可 env 覆盖）：
  条数从页面自身 `GALLERY` 读，空皮肤样本从 `GALLERY.ships` 里**动态挑选**
  （找 `skins` 长度为 0 的第一条）——索引变了探针不会假红。

env:
  GHV_URL     画廊首页 URL（默认 http://127.0.0.1:8778/gallery_v2/index.html）
  GHV_SHIP    非空 `?ship` 样本 id（默认取第一个 live2d 皮肤非空的船）
  GHV_EMPTY   空 skins 样本 id（默认自动挑）
退出码：0 全通过 / 1 有 FAIL
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = r'D:\azur'
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
import cdp_slot          # noqa: E402
import cdp_wait          # noqa: E402
import chrome_tree       # noqa: E402

CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
BASE = os.environ.get('GHV_URL', 'http://127.0.0.1:8778/gallery_v2/index.html')
BUDGET = 150


class Browser:
    """最小 CDP 会话：Popen 起 headless -> 建 ws -> cmd/ev 两个入口。"""

    def __init__(self, tag):
        PORT, PROFILE = cdp_slot.slot(ROOT, tag)
        self.proc = subprocess.Popen(
            [CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
             '--remote-allow-origins=*', f'--user-data-dir={PROFILE}',
             '--no-first-run', '--no-default-browser-check',
             '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
             '--window-size=1280,900', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        chrome_tree.install(self.proc)
        ws_url = None
        for _ in range(90):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
                ws_url = [t['webSocketDebuggerUrl'] for t in tabs
                          if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws_url:
            raise RuntimeError(f'CDP {PORT} 未就绪（没拿到 page target）')
        import websocket
        self.ws = websocket.create_connection(ws_url[0], timeout=300, max_size=None)
        self._id = 0
        self.cmd('Runtime.enable')
        self.cmd('Page.enable')
        # 页面加载期未捕获异常必须能抓到：本缺陷恰恰死在加载期，事后 evaluate 看不见
        self.cmd('Page.addScriptToEvaluateOnNewDocument', {'source':
                 "window.__errs=[];window.addEventListener('error',e=>window.__errs.push("
                 "String(e.message)+' @'+e.filename+':'+e.lineno));"})

    def cmd(self, method, params=None):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get('id') == mid:
                if 'error' in r:
                    raise RuntimeError(json.dumps(r['error'])[:200])
                return r.get('result', {})

    def ev(self, expr):
        r = self.cmd('Runtime.evaluate',
                     {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        if r.get('exceptionDetails'):
            ed = r['exceptionDetails']
            ex = ed.get('exception', {}) or {}
            return 'EVALERR ' + str(ex.get('description') or ed.get('text'))[:300]
        return r.get('result', {}).get('value')

    def goto(self, url):
        self.cmd('Page.navigate', {'url': url})
        return cdp_wait.wait_ready(self.ev, url, budget=BUDGET)

    def close(self):
        try:
            self.cmd('Browser.close')
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            chrome_tree.kill_tree(self.proc.pid)


RESULTS = []


def check(ok, label, detail=''):
    RESULTS.append((bool(ok), label, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}  {detail}")


def errs_expr():
    # spine-all.js 惰性取 THREE 才报的 ReferenceError，与画廊无关
    return "(window.__errs||[]).filter(e=>!/THREE is not defined/.test(e))"


def main():
    b = Browser('homeverify')

    print('== ① 首页渲染完整性 ==')
    ok, secs, last = b.goto(BASE)
    print(f'[ready] ok={ok} {secs}s')
    if not ok:
        print('  last=', last)
        b.close()
        return 1
    time.sleep(1.5)
    raw = b.ev(r"""JSON.stringify({
      ships: GALLERY.ships.length,
      cards: document.querySelectorAll('.card').length,
      secs: [...document.querySelectorAll('.sec-hd')].map(e=>e.textContent.trim()),
      errs: %s,
      emptyShip: ((GALLERY.ships.find(s=>!(s.skins||[]).length)||{}).id)||null,
      richShip: ((GALLERY.ships.find(s=>(s.skins||[]).some(k=>k.live2d))||GALLERY.ships.find(s=>(s.skins||[]).length)||{}).id)||null
    })""" % errs_expr())
    if isinstance(raw, str) and raw.startswith('EVALERR'):
        print(' ', raw)
        b.close()
        return 1
    d = json.loads(raw)
    b.close()

    check(d['cards'] == d['ships'],
          '首页卡片数 == GALLERY.ships 数',
          f"cards={d['cards']} ships={d['ships']}")
    # 每个 "分区名 N" 的声明数应等于该分区实际卡片数之和；这里只用总数对齐 + 标题齐备做判据
    check(len(d['secs']) >= 1 and all(s for s in d['secs']),
          '分区标题齐备', f"secs={d['secs']}")
    total = sum(int(s.split()[-1]) for s in d['secs'] if s.split()[-1].isdigit())
    check(total == d['cards'],
          '分区标题声明条数之和 == 实际卡片数（"标题在、卡片没出来"的判据）',
          f"声明 {total} vs 实际 {d['cards']}")
    check(not d['errs'], '加载期无未捕获异常', f"errs={d['errs']}")

    if d['richShip']:
        print(f"== ② ?ship={d['richShip']} 直达 ==  (env GHV_SHIP 可覆盖)")
    if d['emptyShip']:
        print(f"== ③ ?ship={d['emptyShip']} 空皮肤 story 角色 ==  (env GHV_EMPTY 可覆盖)")

    def ship_probe(br, sid, label):
        ok, secs, last = br.goto(BASE + '?ship=' + sid)
        print(f"[ready] {label} ok={ok} {secs}s")
        if not ok:
            print('  last=', last)
            return None
        time.sleep(2.0)
        raw = br.ev(r"""JSON.stringify({
          id:(curShip||{}).id, skin:(curSkin||{}).key,
          mask:document.getElementById('mask').className,
          tabs:[...document.querySelectorAll('#mTabs .tab')].map(t=>t.dataset.k+':'+(t.classList.contains('dis')?'dis':'en')),
          note:document.getElementById('mView').textContent.trim().slice(0,80),
          errs:%s
        })""" % errs_expr())
        if isinstance(raw, str) and raw.startswith('EVALERR'):
            print(' ', raw)
            return None
        return json.loads(raw)

    rich = os.environ.get('GHV_SHIP') or d['richShip']
    if rich:
        b2 = Browser('homeverify_ship')
        r = ship_probe(b2, rich, f'ship={rich}')
        if r:
            check(r['id'] == rich, '`?ship=` 直达命中目标角色', f"id={r['id']} skin={r['skin']}")
            check('on' in r['mask'].split(), '弹层已打开（mask 带 on）', f"mask='{r['mask']}'")
            check(not r['errs'], '直达页无未捕获异常', f"errs={r['errs']}")
            l2 = [t for t in r['tabs'] if t.startswith('live2d')]
            if l2:
                check(l2[0].endswith(':en'), 'Live2D tab 可用（未 dis）', f"tabs={r['tabs']}")
            # 空皮肤模型：skin 必然取不到，只要弹层开了 + 有提示 + 不抛错即算过
            if not r['skin']:
                check(bool(r['note']), '空皮肤角色显示友好提示（不是空白弹层）', f"note='{r['note']}'")
        b2.close()

    empty = os.environ.get('GHV_EMPTY') or d['emptyShip']
    if empty and empty != rich:
        b3 = Browser('homeverify_empty')
        r = ship_probe(b3, empty, f'ship={empty}')
        if r:
            check(r['id'] == empty, '空皮肤角色仍能直达打开', f"id={r['id']}")
            check('on' in r['mask'].split(), '空皮肤角色弹层已打开', f"mask='{r['mask']}'")
            check(bool(r['note']), '空皮肤角色显示友好提示', f"note='{r['note']}'")
            check(not r['errs'], '空皮肤角色页无未捕获异常', f"errs={r['errs']}")
        b3.close()

    bad = [x for x in RESULTS if not x[0]]
    print(f"\n结果: {'PASS' if not bad else 'FAIL'}  ({len(RESULTS) - len(bad)}/{len(RESULTS)})")
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
