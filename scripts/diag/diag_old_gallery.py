"""诊断旧画廊（8777）为什么只显示背景。

用户反馈：http://127.0.0.1:8777/gallery_v2/index.html 只有背景，其余空白。
文件看起来齐全（index.js/index.json/vendor 都在），所以要看浏览器里的真实错误。

关键：必须确认探针连的是**正确的端口**（8777 = 旧画廊 D:\Azur Lane Assets，
8778 = 本项目 D:\azur）——之前反复踩过"探错了端口"。

用法: py -3 scripts/diag/diag_old_gallery.py
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import cdp_helper  # noqa: E402
from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8777/gallery_v2/index.html'

HOOK = r"""
(function(){
  window.__errs=[];
  window.addEventListener('error', function(e){
    window.__errs.push({msg:String(e.message||''), src:(e.filename||'').split('/').pop(), line:e.lineno||0});
  }, true);
  window.addEventListener('unhandledrejection', function(e){
    window.__errs.push({msg:'rej: '+String(e.reason)});
  });
})();
"""


def main():
    # 先确认端口内容正确
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            b = r.read()
            print('8777 index.html: HTTP %d, %d 字节' % (r.status, len(b)))
            if b'window.GALLERY' in b or b'GALLERY=' in b:
                print('  含 index.js 外链（预期）')
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 8777 不可达:', e); return 2

    pg = open_page(URL, tag='old')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(6)

        print('\nJS 错误:')
        raw = pg.ev("JSON.stringify(window.__errs||[])")
        try:
            for e in json.loads(raw):
                print('   ', e)
        except Exception:  # noqa: BLE001
            print('   ', raw)

        print('\n关键对象:')
        print(pg.ev("""JSON.stringify({
            url: location.href,
            GALLERY: typeof window.GALLERY,
            ships: (window.GALLERY&&window.GALLERY.ships)? window.GALLERY.ships.length : null,
            cards: document.querySelectorAll('.card').length,
            bodyChildren: document.body.children.length,
            bodyText: document.body.innerText.slice(0, 100)
        })"""))

        # 抓已加载的资源
        print('\n资源加载 (performance):')
        print(pg.ev("""
        (function(){
          var rs=performance.getEntriesByType('resource');
          return JSON.stringify(rs.map(function(r){
            return {f: r.name.split('/').pop(), dur: Math.round(r.duration),
                    size: r.transferSize, status: r.responseStatus};
          }).slice(0, 20), null, 1);
        })()
        """))

        pg.shot(os.path.join(ROOT, '.diag', 'old_gallery_shot.png'))
        print('\n截图: .diag/old_gallery_shot.png')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())