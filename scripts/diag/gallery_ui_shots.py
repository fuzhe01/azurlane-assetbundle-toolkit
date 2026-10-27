# -*- coding: utf-8 -*-
"""画廊 UI 截图：依次打开若干界面状态各截一张（跨「列表 + 三种查看器 + 语音页」）。

用途：改视觉语言时先看样板再铺开——判据是"人眼看图"，所以工具只负责
把每个状态拍成**同一视角、同一尺寸、同一等待时长**的图片。

  py -3 scripts/diag/gallery_ui_shots.py                              # 截 index.html 一套（5 张）
  py -3 scripts/diag/gallery_ui_shots.py --pages a.html,b.html --tags before,after
  py -3 scripts/diag/gallery_ui_shots.py --out .diag/uishots

⚠️ 三个坑（都踩过）：
  1. 无头窗口尺寸必须对齐用户实机（默认 2560,1600）——弹窗上限按 vw/vh 算，小窗口看不出真实观感。
  2. 打开皮肤后**不要**给 .view 刷背景色（取景量具 gallery_framing_ab.py 会刷，那是为了量落笔像素）；
     这里要看的就是用户实际看到的底。
  3. **默认只截 `index.html`**。旧默认还写了一张 `index_b.html`（"改前页"），但那份校对页
     从来没入库、D 盘上也不存在（`git log --all` 无记录）⇒ 默认跑必然在 `preflight` 阶段
     报 404 退出 1（2026-10-27 实测）。要对比两份就显式 `--pages a.html,b.html`。
     皮肤 key 同理：**必须是本项目 index.json 里实有的**（haitian_3 / benningdun_2 /
     aersasi / aersasi_2 / aersasi_3 / antu_2 / ougen_8），旧默认的 ninghai_4 / tansuozhe_2
     来自另一份全库画廊，在本项目上恒 NO_SHIP。
"""
import sys, os, json, time, base64, argparse, subprocess, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import websocket, chrome_tree, cdp_wait

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
CHROME = r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
# ⚠️ BASE 不许再写死 8777：本项目当前服务在 8778（8777 上是另一份画廊，如旧机拷贝的全库）。
# 在错误的服务上截出的"改前/改后"样板看起来正常，实际两个页面都不是本项目产物。
BASE = os.environ.get('SHOTS_BASE', 'http://127.0.0.1:8778/gallery_v2')
WAIT = {'painting': 4.0, 'live2d': 11.0, 'spine': 11.0, 'voice': 4.0}

# 界面状态清单：(文件名, tab, 皮肤 key)。覆盖「列表 + 三种查看器 + 语音页」
# ⚠️ 皮肤 key 必须存在于**当前项目**的 index.json（实测现有 7 个皮肤：
#    haitian_3 / benningdun_2 / aersasi / aersasi_2 / aersasi_3 / antu_2 / ougen_8）。
#    以前写的是 ninghai_4 / tansuozhe_2，那是旧机全库才有的模型 → 本项目上必 NO_SHIP。
STATES = [('1_grid', None, None), ('2_live2d', 'live2d', 'aersasi_2'),
          ('3_painting', 'painting', 'haitian_3'), ('4_spine', 'spine', 'aersasi'),
          ('5_voice', 'voice', 'aersasi_2')]


class Page:
    def __init__(self, port, profile, url, win, gpu=False):
        """gpu=True 时不传 SwiftShader，走机器真实 GPU（D3D11）。

        为什么需要（2026-10-25，TROUBLESHOOTING §137 已被实证）：SwiftShader 与真 GPU
        对 Live2D 的 `isVisible` 判定不一致（实测 ArtMesh255~258 在软件渲染 vis=1、
        真 GPU vis=0），而用户环境是硬件光栅化。**凡对账「可见性/像素」的裸页判据，
        默认的 SwiftShader 路径会给出系统性偏差的假绿灯**，必须用 gpu=True 复测。
        """
        flags = [CHROME, '--headless=new',
                 f'--remote-debugging-port={port}', '--remote-allow-origins=*',
                 f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
                 '--disable-background-timer-throttling']
        if not gpu:
            flags += ['--enable-unsafe-swiftshader', '--use-angle=swiftshader']
        flags += [f'--window-size={win[0]},{win[1]}', url]
        self.proc = chrome_tree.install(subprocess.Popen(
            flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        ws = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                m = [t for t in tabs if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
                if m:
                    ws = m[0]['webSocketDebuggerUrl']
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws:
            raise RuntimeError('no CDP tab')
        self.ws = websocket.create_connection(ws, timeout=180, max_size=None)
        self._id = 0
        self.cmd('Page.enable'); self.cmd('Runtime.enable')

    def cmd(self, m, p=None):
        self._id += 1; mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
        self.ws.settimeout(180)
        while True:
            r = json.loads(self.ws.recv())
            if r.get('id') == mid:
                return r.get('result', {})

    def ev(self, expr):
        r = self.cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        if r.get('exceptionDetails'):
            ed = r['exceptionDetails']
            ex = ed.get('exception', {}) or {}
            # SyntaxError 的信息在 text / description 里，**不在 message 里**——
            # 只取 message 会输出一句没用的 "EXC None"（2026-09-28 白转两轮）。
            msg = ex.get('description') or ex.get('value') or ed.get('text') or 'no detail'
            return 'EXC ' + str(msg)[:300]
        return r.get('result', {}).get('value')

    def shot(self, path):
        d = base64.b64decode(self.cmd('Page.captureScreenshot', {'format': 'png'})['data'])
        open(path, 'wb').write(d)

    def close(self):
        try: self.cmd('Browser.close')
        except Exception: pass
        try: self.proc.wait(timeout=10)
        except Exception: chrome_tree.kill_tree(self.proc.pid)


def open_state(pg, tab, key):
    if tab is None:
        return pg.ev("document.querySelectorAll('.card').length")
    return pg.ev("""(()=>{const k=%r,t=%r;
      const hit=G.ships.find(s=>(s.live2dSkins||[]).includes(k)||(s.spineSkins||[]).includes(k)
                    ||s.skins.some(x=>x.key===k));
      if(!hit) return 'NO_SHIP';
      const sk=hit.skins.find(x=>x.key===k)||hit.skins[0];
      openShip(hit); setSkin(sk); buildSkinList(hit); tab=t; renderView();
      [...document.getElementById('mTabs').children].forEach(c=>c.classList.toggle('on', c.dataset.k===t));
      return 'ok';})()""" % (key, tab))


def preflight(page):
    """先探一次服务再启动 Chrome。真实翻车：8777 上的服务器静默死掉后，本工具照样
    截出 5 张"空白页"并逐条打印文件名、退出码 0 —— 判据必须能红。"""
    url = f'{BASE}/{page}'
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status != 200:
                raise RuntimeError(f'{url} -> HTTP {r.status}')
    except Exception as e:
        raise SystemExit(f'! 先起服务器再跑（{url} 不可达：{e}）\n'
                         f'  双击 Output\\gallery_v2\\启动资产浏览器.bat，'
                         f'或不弹浏览器地起：py -3 scripts/diag/run_detached.py --log .diag/_srv.log -- py -3 Output/gallery_v2/_gallery_server.py')
    return url


def assert_rendered(pg, page, name, tab):
    """每拍一张都要证明"画面真的渲染了"，而不是只证明脚本没抛异常。"""
    n = pg.ev("""(()=>{const v=document.getElementById('mView');
      return JSON.stringify([document.querySelectorAll('.card').length,
        !!window.GALLERY, v?v.childElementCount:0,
        (document.querySelector('.note')||{}).textContent||'']);})()""")
    cards, has_g, vchildren, note = json.loads(n)
    if not has_g:
        raise SystemExit(f'! {page} / {name}: window.GALLERY 不存在（index.js 没加载？）')
    if cards == 0:
        raise SystemExit(f'! {page} / {name}: 网格一张卡都没渲染（页面脚本崩了或 index.js 坏了）')
    if tab and vchildren == 0:
        raise SystemExit(f'! {page} / {name}: #mView 是空的，note={note[:80]!r}')
    return cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', default=os.environ.get('SHOTS_PAGES', 'index.html'),
                    help='逗号分隔：要截的页面（默认只 index.html；对比两份写 a.html,b.html）')
    ap.add_argument('--tags', default=os.environ.get('SHOTS_TAGS', 'cur'))
    ap.add_argument('--win', default='2560,1600')
    ap.add_argument('--out', default=os.path.join(ROOT, '.diag', 'uishots'))
    ap.add_argument('--port', type=int, default=9431)
    a = ap.parse_args()
    pages = a.pages.split(',')
    tags = a.tags.split(',')
    win = tuple(int(v) for v in a.win.split(','))
    os.makedirs(a.out, exist_ok=True)
    profile = os.path.join(ROOT, '.diag', 'chrome_uishots')
    os.makedirs(profile, exist_ok=True)
    for tag, page in zip(tags, pages):
        preflight(page)
        print(f'== {tag}  {page} ==')
        pg = Page(a.port, profile, f'{BASE}/{page}', win)
        time.sleep(7)
        pg.ev("localStorage.clear()")
        pg.cmd('Page.navigate', {'url': f'{BASE}/{page}'})
        # 就绪门槛（scripts/diag/cdp_wait.py）：不能拿 document.readyState 当判据 ——
        # CDP 会话初连时执行上下文还在 about:blank，其 readyState 天生 'complete'，
        # 门槛第一次判就放行，后面全打在空白页上（本工具的症状是 5 张全空白 PNG）。
        # 同时替代原来那句裸 time.sleep(6) 的赌博。
        _ok, _secs, _last = cdp_wait.wait_ready(pg.ev, f'{BASE}/{page}', budget=150)
        print(f'  [ready] ok={_ok} {_secs}s' + ('' if _ok else f' last={_last}'))
        if not _ok:
            pg.close()
            raise SystemExit(f'! {page}: 页面在预算内未就绪（探针故障，非产品故障）')
        for name, tab, key in STATES:
            r = open_state(pg, tab, key)
            if tab:
                time.sleep(WAIT[tab])
            cards = assert_rendered(pg, page, name, tab)
            out = os.path.join(a.out, f'{tag}_{name}.png')
            pg.shot(out)
            print(f'  {name:<12} 卡片{cards:>5}  {str(r):<8} -> {os.path.basename(out)}')
        pg.close()
        time.sleep(1.5)


if __name__ == '__main__':
    main()
