"""用**有头 Edge（真实 GPU）**打开页面并截图，复现用户在真实浏览器看到的现象。

为什么必须这么做（2026-10-24）：
  headless 用 `--use-angle=swiftshader` 软件渲染，与真实 GPU 行为不同。
  历史 §136 已记录过这种偏差（真实 GPU 上出问题、headless 全绿）。
  用户报告 8777 旧画廊「只有背景，其余空白」，而我的 headless 截图完全正常
  —— 必须在真实 GPU 下复现，否则改错方向。

做法：启动有头 Edge（不加 --headless），CDP 连上去截图。
      窗口会短暂出现（用户要求"和我目视一样的环境"，这是必要的）。

用法: py -3 scripts/diag/shot_real_gpu.py <port> [clip]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))

import paths as P  # noqa: E402
import chrome_tree        # 整树清理：atexit + profile 回读（见该模块 docstring）

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
CLIP = sys.argv[2] if len(sys.argv) > 2 else 'idle'
TAG = 'old' if PORT == 8777 else 'new'
URL = 'http://127.0.0.1:%d/gallery_v2/index.html' % PORT
DBG = 9570
PROFILE = os.path.join(ROOT, '.diag', 'chrome_realgpu_%s' % TAG)
OUT = os.path.join(ROOT, '.diag', 'realgpu')
os.makedirs(OUT, exist_ok=True)
os.makedirs(PROFILE, exist_ok=True)

CHROME = P.CHROME


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP %d' % r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] %d 不可达: %s' % (PORT, e)); return 2

    # 有头模式：不加 --headless，不加 swiftshader → 走真实 GPU
    args = [CHROME,
            '--remote-debugging-port=%d' % DBG,
            '--remote-allow-origins=*',
            '--user-data-dir=%s' % PROFILE,
            '--no-first-run', '--no-default-browser-check',
            '--window-size=1400,1000',
            URL]
    proc = chrome_tree.launch(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('已启动有头 Edge（真实 GPU），PID', proc.pid)

    ws_url = None
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/json' % DBG, timeout=2) as rr:
                tabs = json.load(rr)
            m = [t for t in tabs if 'gallery_v2' in t.get('url', '') and t.get('webSocketDebuggerUrl')]
            if m:
                ws_url = m[0]['webSocketDebuggerUrl']
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)

    if not ws_url:
        print('[FAIL] 连不上 CDP')
        proc.terminate()
        return 2

    import websocket
    ws = websocket.create_connection(ws_url, timeout=120, max_size=None)
    mid = [0]

    def cmd(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(ws.recv())
            if r.get('id') == mid[0]:
                return r.get('result', {})

    def ev(expr):
        r = cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        if r.get('exceptionDetails'):
            return 'EXC ' + str(r['exceptionDetails'].get('text'))
        return r.get('result', {}).get('value')

    def shot(path):
        d = cmd('Page.captureScreenshot', {'format': 'png'})
        open(path, 'wb').write(__import__('base64').b64decode(d['data']))

    try:
        cmd('Page.enable')
        cmd('Runtime.enable')
        time.sleep(6)

        print('GPU 信息:', ev("""
        (function(){
          try{
            var c=document.createElement('canvas');
            var gl=c.getContext('webgl')||c.getContext('experimental-webgl');
            if(!gl) return 'NO_WEBGL';
            var d=gl.getExtension('WEBGL_debug_renderer_info');
            return d? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'unknown';
          }catch(e){ return 'ERR:'+e; }
        })()
        """))

        print('页面状态:', ev("""JSON.stringify({
            GALLERY: typeof window.GALLERY,
            ships: (window.GALLERY&&window.GALLERY.ships)? window.GALLERY.ships.length: null,
            cards: document.querySelectorAll('.card').length,
            bodyText: document.body.innerText.slice(0,80)
        })"""))

        shot(os.path.join(OUT, '%s_1_list.png' % TAG))

        # 打开 ougen_8 Live2D
        ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        print('开卡:', ev("""
        (function(){
          var cards=[...document.querySelectorAll('.card')];
          var c=cards.find(function(e){ var t=e.textContent||''; return t.indexOf('欧根亲王')>=0; });
          if(!c) return 'NO_CARD';
          c.click(); return 'OK';
        })()
        """))
        time.sleep(2.5)
        print('选肤:', ev("""
        (function(){var rows=[...document.querySelectorAll('#mSkins .skin')];
          var d=rows.find(function(e){return e.dataset.k==='ougen_8';});
          if(!d) return 'NO_ROW'; d.click(); return 'OK';})()
        """))
        time.sleep(1.5)
        print('切L2D:', ev("""
        (function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';});
          if(!t) return 'NO_TAB'; if(t.classList.contains('dis')) return 'DIS';
          t.click(); return 'OK';})()
        """))
        time.sleep(16)

        print('模型:', ev("typeof window.__l2model"))
        print('查看器文本:', ev("(document.getElementById('l2wrap')||{}).innerText || ''"))
        shot(os.path.join(OUT, '%s_2_l2d.png' % TAG))

        # 播指定动作
        print('播 %s:' % CLIP, ev("""
        (function(){var s=document.getElementById('l2Motion');
          if(!s) return 'NO_SEL';
          if(![...s.options].some(function(o){return o.value===%s;})) return 'NO_GROUP';
          s.value=%s;
          if(window.__l2play){ window.__l2play(%s); return 'PLAYED'; }
          return 'NO_HOOK';})()
        """ % (json.dumps(CLIP), json.dumps(CLIP), json.dumps(CLIP))))
        time.sleep(4)
        shot(os.path.join(OUT, '%s_3_%s.png' % (TAG, CLIP)))

        print('\n截图: .diag/realgpu/')
        return 0
    finally:
        try:
            cmd('Browser.close')
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.terminate()


if __name__ == '__main__':
    sys.exit(main())