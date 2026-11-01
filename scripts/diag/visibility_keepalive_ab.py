"""A/B：证明「headless 页面变 hidden ⇒ rAF 停摆」，并验证三种保活手段哪个真有效。

阴性对照（必须有）：现状 Page（现成的 gallery_ui_shots.Page，不加任何保活）→ 期望 rAF 停。
阳性组（逐项加，看哪一项单独就够）：
  B1 浏览器启动参数：--disable-renderer-backgrounding
                      --disable-backgrounding-occluded-windows
  B2 CDP `Emulation.setFocusEmulationEnabled(true)`
  B3 CDP `Page.setWebLifecycleState('active')`（每次采样前重复调用）

判据：rAF 计数在 8 秒窗口里 Δ≥4 且 visibilityState 恒 visible。
三项分开测，是为了避免"加了一堆参数来了一项有效"而说不出是哪一项——
以后新探针要保活，只需抄那一条最小改动。
"""
import json
import os
import random
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"d:\azur"
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import websocket      # noqa: E402
import chrome_tree    # noqa: E402
import paths as P     # noqa: E402
from cdp_helper import kill_stale  # noqa: E402
from gallery_ui_shots import Page  # noqa: E402

BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'
KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
WIN = (1920, 1200)


class RawPage(Page):
    """在标准 Page 之上只加「可选保活」，其余完全一致（同一 close/kill_tree 兜底）。"""

    def __init__(self, port, profile, url, win, extra_flags=(), focus=False, lifecycle=False):
        import chrome_tree as CT
        flags = [P.CHROME, '--headless=new',
                 f'--remote-debugging-port={port}', '--remote-allow-origins=*',
                 f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
                 '--disable-background-timer-throttling',
                 '--enable-unsafe-swiftshader', '--use-angle=swiftshader']
        flags += list(extra_flags)
        flags += [f'--window-size={win[0]},{win[1]}', url]
        self.proc = CT.launch(flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                m = [t for t in tabs if 'gallery_v2' in t.get('url', '')
                     and t.get('webSocketDebuggerUrl')]
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
        self._lifecycle = lifecycle
        self.cmd('Page.enable')
        self.cmd('Runtime.enable')
        if focus:
            self.cmd('Emulation.setFocusEmulationEnabled', {'enabled': True})
        if lifecycle:
            self.cmd('Page.setWebLifecycleState', {'state': 'active'})


def open_skin(pg):
    pg.cmd('Network.enable')
    pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
    pg.cmd('Page.navigate', {'url': BASE})
    time.sleep(4)
    pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
          " if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
    time.sleep(0.9)
    pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key===%s;});});
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
          % json.dumps(KEY))
    time.sleep(1.6)
    pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
    time.sleep(1.3)
    pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
    for _ in range(70):
        if pg.ev("(function(){return window.__costumeBoxes?1:0;})()") == 1:
            break
        time.sleep(1)
    time.sleep(1.0)
    pg.ev("""(function(){ window.__hb={raf:0,iv:0};
      (function loop(){ window.__hb.raf++; requestAnimationFrame(loop); })();
      setInterval(function(){ window.__hb.iv++; }, 100); return 1;})()""")


READ = """(function(){var hb=window.__hb||{};
  return JSON.stringify({raf:hb.raf, iv:hb.iv, vis:document.visibilityState,
    tk:(window.__l2TickerState&&window.__l2TickerState())||null});})()"""


def measure(pg, tag, n=8, life=False):
    print('\n=== %s ===' % tag)
    rows, prev = [], None
    for i in range(n):
        time.sleep(1.0)
        if life:
            try:
                pg.cmd('Page.setWebLifecycleState', {'state': 'active'})
            except Exception:
                pass
        r = json.loads(pg.ev(READ))
        if prev:
            print('  t=%ds raf=%s(Δ%+d) iv=%s(Δ%+d) vis=%s tk=%.0f(Δ%.0f)'
                  % (i + 1, r['raf'], r['raf'] - prev['raf'], r['iv'], r['iv'] - prev['iv'],
                     r['vis'], (r['tk'] or {}).get('lastTime', 0),
                     (r['tk'] or {}).get('lastTime', 0) - (prev['tk'] or {}).get('lastTime', 0)))
        else:
            print('  t=%ds raf=%s iv=%s vis=%s tk=%.0f'
                  % (i + 1, r['raf'], r['iv'], r['vis'], (r['tk'] or {}).get('lastTime', 0)))
        rows.append(r)
        prev = r
    advanced = rows[-1]['raf'] - rows[0]['raf']
    hidden_ever = any(x['vis'] != 'visible' for x in rows)
    return advanced, hidden_ever


def run(tag, factory):
    port = random.randint(9510, 9899)
    kill_stale(port)
    prof = os.path.join(ROOT, '.diag', 'chrome_ab_%d' % port)
    pg = None
    try:
        pg = factory(port, prof)
        open_skin(pg)
        adv, hid = measure(pg, tag, life=tag.startswith('B3'))
        print('   → rAF 推进 %d 帧/8s，期间出现非 visible: %s' % (adv, hid))
        return adv, hid
    except Exception as e:  # noqa: BLE001
        print('   [ERR] %s: %s' % (tag, str(e)[:160]))
        return -1, None
    finally:
        if pg is not None:
            try:
                pg.close()
            except Exception:
                pass
        kill_stale(port)
        time.sleep(1.0)


def main():
    results = {}
    results['A 现状(无保活)'] = run(
        'A 现状(无保活)', lambda p, pr: Page(p, pr, BASE, WIN))
    results['B1 启动参数(后台化)'] = run(
        'B1 启动参数(后台化)',
        lambda p, pr: RawPage(p, pr, BASE, WIN, extra_flags=[
            '--disable-renderer-backgrounding',
            '--disable-backgrounding-occluded-windows']))
    results['B2 focusEmulation'] = run(
        'B2 focusEmulation', lambda p, pr: RawPage(p, pr, BASE, WIN, focus=True))
    results['B3 lifecycle active'] = run(
        'B3 lifecycle active', lambda p, pr: RawPage(p, pr, BASE, WIN, lifecycle=True))

    print('\n=== 汇总（rAF 8 秒推进帧数；<0 表示报错）===')
    for k, (adv, hid) in results.items():
        verdict = ('停摆' if adv <= 2 else '存活') if adv >= 0 else '异常'
        print('  %-24s %4d 帧  %s  (出现过非visible: %s)' % (k, adv, verdict, hid))
    a = results['A 现状(无保活)'][0]
    if a > 2:
        print('\n⚠️ 阴性对照没有停摆 ⇒ 本轮无法复现，其余各项的"存活"无区分力。')
    else:
        good = [k for k, (adv, _) in results.items() if k.startswith('B') and adv > 2]
        print('\n结论：阴性对照确实停摆；有效保活项 = %s' % (good or '无（三项都无效）'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
