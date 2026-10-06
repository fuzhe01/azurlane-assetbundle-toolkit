# -*- coding: utf-8 -*-
"""BGM 页验收：数据能载入、配色 token 真的生效、**点了真的在播**（判据落在播放那一刻）。

为什么必须有这个探针（而不是"打开看一眼"）：`bgm.html` 的播放条、进度、时长全部是 DOM 文本，
所以判据不碰页面内部变量、只看产品可见状态 —— 与 WF-16 硬规则 4「验证不能自洽闭环」同形。
⚠️ 无头 Chrome 的自动播放策略会把 `A.play()` 静默拒掉（`element.click()` 不算用户手势），
   所以启动参数必须带 `--autoplay-policy=no-user-gesture-required`，否则"没在播"是假红灯。
   端口 / profile 走 `cdp_slot`，写死会让两个会话灌进同一个浏览器（数据整齐偏移一位而不是报错）。

用法: py -3 scripts/diag/bgm_page_probe.py            # 需要画廊服务器在 8777 上
"""
import json
import os
import subprocess
import threading
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
import cdp_slot                      # noqa: E402
import chrome_tree                   # noqa: E402
import paths as P                    # noqa: E402
sys.path.insert(0, os.path.join(ROOT, 'gallery_src'))
import _gallery_server as GS         # noqa: E402  自己起一份，测当前代码而非 8777 上那台旧进程

CHROME = P.tool('AL_CHROME', 'chrome',
                r'C:/Program Files/Google/Chrome/Application/chrome.exe',
                r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
PORT, PROFILE = cdp_slot.slot(ROOT, 'bgmp')
FAIL = []
_srv = None
_httpd = None


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def base_url():
    return f'http://127.0.0.1:{_port}/gallery_v2/'


def say(cond, msg):
    print(('  PASS  ' if cond else '  FAIL  ') + msg)
    if not cond:
        FAIL.append(msg)


def serve_up():
    """原地起一份服务器（含 Range），返回 (是否可用, 拿到的字节数)。"""
    global _srv, _httpd, _port
    _port = _free_port()
    _httpd = GS.make_server(port=_port, root=P.OUT)
    _srv = threading.Thread(target=_httpd.serve_forever, daemon=True)
    _srv.start()
    try:
        b = urllib.request.urlopen(base_url() + 'bgm.json', timeout=8).read()
        return len(b) >= 20000, len(b)
    except Exception as e:
        print(f'  ! bgm.json 取不到: {e}')
        return False, 0


def main():
    if not CHROME:
        print('[FAIL] 找不到 Chrome/Edge（设 AL_CHROME）')
        return 2
    ok, n = serve_up()
    if not ok:
        print(f'[FAIL] 自起的服务器取不到 bgm.json（{n} 字节）⇒ 先跑 build_bgm_index.py / deploy_gallery.py')
        return 2
    proc = subprocess.Popen([CHROME, '--headless=new', f'--remote-debugging-port={PORT}',
                             '--remote-allow-origins=*', f'--user-data-dir={PROFILE}',
                             '--no-first-run', '--no-default-browser-check',
                             '--autoplay-policy=no-user-gesture-required',
                             '--disable-background-timer-throttling', '--window-size=1280,900',
                             base_url() + 'bgm.html'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    chrome_tree.install(proc)
    ws = None
    try:
        for _ in range(90):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
                u = [t['webSocketDebuggerUrl'] for t in tabs
                     if 'bgm.html' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
                if u:
                    import websocket
                    ws = websocket.create_connection(u[0], timeout=120, max_size=None)
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if ws is None:
            print('[FAIL] 128 秒内没连上浏览器')
            return 2
        _id = 0

        def cmd(m, p=None):
            nonlocal _id
            _id += 1
            ws.send(json.dumps({'id': _id, 'method': m, 'params': p or {}}))
            ws.settimeout(120)
            while True:
                r = json.loads(ws.recv())
                if r.get('id') == _id:
                    if 'error' in r:
                        raise RuntimeError(json.dumps(r['error'])[:160])
                    return r.get('result', {})

        def ev(e):
            r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True,
                                         'awaitPromise': True})
            if r.get('exceptionDetails'):
                return {'__err': str(r['exceptionDetails'].get('text'))[:200]}
            return r.get('result', {}).get('value')

        JS_WAIT = r"""(async()=>{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          for(let i=0;i<80 && !document.querySelector('.row');i++) await t(250);
          return {rows:document.querySelectorAll('.row').length,
                  sub:(document.getElementById('sub')||{}).textContent||'',
                  brand:getComputedStyle(document.documentElement).getPropertyValue('--brand').trim(),
                  ease:getComputedStyle(document.documentElement).getPropertyValue('--ease-ios').trim(),
                  bodyBg:getComputedStyle(document.body).backgroundImage,
                  err:(document.getElementById('list')||{}).textContent||''};
        })()"""
        d = ev(JS_WAIT)
        print('== 数据与样式 ==')
        if isinstance(d, dict) and '__err' in d:
            say(False, f"页面 JS 异常: {d['__err']}")
        else:
            say(d['rows'] >= 500, f"列表渲染 {d['rows']} 行（期望 ≥500）")
            say('首' in d['sub'] and '小时' in d['sub'], f"计数条文案: {d['sub'][:60]}")
            say(bool(d['brand']) and bool(d['ease']),
                f"theme.css 生效：--brand={d['brand']!r} --ease-ios={d['ease'][:22]!r}")
            # 量的是 background-image：body 用的是 linear-gradient(var(--bg)→var(--bg2))，
        # 拿 backgroundColor 判必然恒为透明 —— 上一版这条就是假红灯（自己写错的判据）
        say('gradient' in d['bodyBg'] and 'rgb' in d['bodyBg'],
            f"body 渐变背景由 token 渲染: {d['bodyBg'][:70]}")

        print('== 播放（点了真的在响）==')
        d2 = ev(r"""(async()=>{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          document.querySelector('.play').click();
          const barOn=document.getElementById('bar').classList.contains('on');
          const t0a=document.getElementById('t0').textContent;
          const cur=document.getElementById('cur').textContent;
          const title=document.title;
          const playing=document.querySelector('.row.playing')!==null;
          // 进度只能从 DOM 读：A 在闭包里，故意不去够它（避免"探针替产品造钩子"）
          await t(2200);
          const t0b=document.getElementById('t0').textContent;
          const sk=document.getElementById('sk').value;
          return {barOn, t0a, t0b, cur, title, playing, sk, dur:document.getElementById('t1').textContent};
        })()""")
        if isinstance(d2, dict) and '__err' in d2:
            say(False, f"播放 JS 异常: {d2['__err']}")
        else:
            say(d2['barOn'] and d2['playing'], f"播放条出现且当前行高亮（曲名 {d2['cur'][:26]}）")
            say(d2['t0a'] != d2['t0b'], f"进度在走：{d2['t0a']} → {d2['t0b']}（总长 {d2['dur']}）")
            say(float(d2['sk']) > 0, f"进度条 value={d2['sk']}（>0 说明 currentTime 已推进）")
            say(d2['title'] != '音乐库 · 碧蓝航线资产浏览器', f"标题跟随当前曲目: {d2['title'][:34]}")

        print('== 搜索与专辑筛选 ==')
        d3 = ev(r"""(async()=>{
          const t=ms=>new Promise(r=>setTimeout(r,ms)); const q=document.getElementById('q');
          const n0=document.querySelectorAll('.row').length;
          q.value='灾厄'; q.dispatchEvent(new Event('input')); await t(300);
          const n1=document.querySelectorAll('.row').length;
          const hit=document.querySelector('.row .nm')?document.querySelector('.row .nm').textContent:'';
          q.value=''; q.dispatchEvent(new Event('input')); await t(300);
          const chip=[...document.querySelectorAll('.chip')].find(c=>c.dataset.a==='弧光');
          chip.click(); await t(300);
          const n2=document.querySelectorAll('.row').length;
          const back=[...document.querySelectorAll('.chip')].find(c=>c.dataset.a==='');
          back.click(); await t(300);
          const n3=document.querySelectorAll('.row').length;
          return {n0,n1,hit,n2,n3};
        })()""")
        if isinstance(d3, dict) and '__err' in d3:
            say(False, f"筛选 JS 异常: {d3['__err']}")
        else:
            say(d3['n1'] > 0 and '灾厄' in d3['hit'], f"搜「灾厄」得 {d3['n1']} 行，首行 {d3['hit'][:20]}")
            say(0 < d3['n2'] < d3['n0'], f"专辑「弧光」筛出 {d3['n2']} / {d3['n0']} 行")
            say(d3['n3'] == d3['n0'], f"切回「全部」恢复 {d3['n3']} 行")

        print('== 拖动进度（这条只有 Range 服务器才可能过）==')
        d5 = ev(r'''(async()=>{
          const t=ms=>new Promise(r=>setTimeout(r,ms));
          const dur=document.getElementById('t1').textContent;
          const sk=document.getElementById('sk');
          sk.dataset.drag=1; sk.value=500; sk.dispatchEvent(new Event('input'));
          sk.dispatchEvent(new Event('pointerup'));
          await t(1800);
          return {dur, t0:document.getElementById('t0').textContent, sk:sk.value};
        })()''')
        say(isinstance(d5, dict) and 'Infinity' not in str(d5.get('dur', '')),
            f"总时长显示正常（不是 Infinity:NaN）: {d5}")

        print('== 主页入口 ==')
        d4 = ev("""(async()=>{ const r=await fetch('index.html'); const b=await r.text();
                    return {status:r.status, has:b.includes(\"location.href='bgm.html'\")}; })()""")
        say(isinstance(d4, dict) and d4.get('status') == 200 and d4.get('has'),
            f"index.html 可取且含「音乐库」入口按钮（{d4}）")
        print()
        if FAIL:
            print(f'[FAIL] {len(FAIL)} 条判据未过')
            return 1
        print('[PASS] BGM 页全部判据通过')
        return 0
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        chrome_tree.kill_tree(proc.pid)
        if _httpd:
            _httpd.shutdown()
            _httpd.server_close()


if __name__ == '__main__':
    sys.exit(main())
