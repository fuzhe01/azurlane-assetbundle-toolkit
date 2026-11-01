"""验证标签同步 ticker 实际读到的值。

打印 window.__currTick（ticker 每帧写入）与 #l2Curr 标签，确认：
  - ticker 在跑（n 递增）
  - 回落发生后 ticker 读到 idle 且标签被更新

用法: py -3 .diag/verify_label_ticker.py [key] [port]
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
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9280
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'


def kill_stale(port):
    """杀掉占用该调试端口的残留 Edge，避免 no CDP tab。"""
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command',
                              "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*remote-debugging-port=%d*' } | Select-Object -ExpandProperty ProcessId" % port],
                             capture_output=True, text=True, timeout=30).stdout
        for pid in [x.strip() for x in out.splitlines() if x.strip().isdigit()]:
            subprocess.run(['taskkill', '/F', '/PID', pid],
                           capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001
        pass


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    kill_stale(PORT)
    time.sleep(2)

    label_js = "(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()"
    tick_js = "JSON.stringify(window.__currTick||null)"

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_vlt%d' % PORT), URL, (1400, 1000))
    try:
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(9)

        print('idle 时:  label=%s  tick=%s' % (pg.ev(label_js), pg.ev(tick_js)))

        pg.ev("""(function(){var s=document.getElementById('l2Motion'); if(s) s.value='login';
                   var b=document.getElementById('l2Replay'); if(b) b.click(); return 1;})()""")
        print('\n播放 login:')
        for t in range(0, 22, 2):
            time.sleep(2)
            print(' t=%2ds  label=%-8s tick=%s' % (t + 2, pg.ev(label_js), pg.ev(tick_js)))

        print('\n回落日志:', pg.ev("JSON.stringify(window.__fbLog||'EMPTY')"))

        final = pg.ev(label_js)
        print('\n=== 结论 ===')
        print('  最终标签: %s' % final)
        ok = final and final.lower().startswith('idle')
        print('  %s' % ('PASS：标签已跟随实际回落' if ok else 'FAIL：标签仍停在动作名'))
        return 0 if ok else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())