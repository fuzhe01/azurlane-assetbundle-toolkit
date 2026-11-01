"""新旧画廊 ougen_8 并排对比截图。

目的：把「目视发现但说不清」的问题变成可对照的两张图。
同一模型、同一动作、同一时刻各自截图，拼成左右对比图。

关键：两边都用各自页面自己的交互路径（点卡片 → 选皮肤 → 切 Live2D → 播同一动作），
不直接调库函数，保证比的是用户真实看到的画面。

旧画廊: http://127.0.0.1:8777/gallery_v2/index.html
新画廊: http://127.0.0.1:8778/gallery_v2/index.html

用法: py -3 .diag/compare_galleries.py [key]
输出: .diag/gallery_compare/<tag>_old.png / _new.png / _side_by_side.png
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))   # scripts/diag/ -> 仓库根
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
OUT = os.path.join(ROOT, '.diag', 'gallery_compare')
os.makedirs(OUT, exist_ok=True)

SITES = [
    ('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9250),
    ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9251),
]


def prepare(pg, url, key, port):
    """打开页面 → 点卡片 → 选皮肤 → 切 live2d。"""
    steps = {}
    steps['card'] = pg.ev("""
    (function(){
      var G=window.GALLERY; if(!G) return 'NO_GALLERY';
      var ship=(G.ships||[]).find(function(s){
         return (s.skins||[]).some(function(k){return k.key===%s;});});
      if(!ship) return 'NO_SHIP';
      var cards=[...document.querySelectorAll('.card')];
      var c=cards.find(function(el){return (el.textContent||'').indexOf(ship.name)>=0;});
      if(!c) return 'NO_CARD('+cards.length+')';
      c.click(); return 'OK|'+ship.name;
    })()
    """ % json.dumps(key))
    time.sleep(1.5)
    steps['skin'] = pg.ev("""
    (function(){
      var rows=[...document.querySelectorAll('#mSkins .skin')];
      var d=rows.find(function(el){return el.dataset.k===%s;});
      if(!d) return 'NO_ROW('+rows.length+')';
      d.click(); return 'OK';
    })()
    """ % json.dumps(key))
    time.sleep(1.2)
    steps['tab'] = pg.ev("""
    (function(){
      var t=[...document.querySelectorAll('#mTabs .tab')].find(function(el){
         return el.dataset.k==='live2d';});
      if(!t) return 'NO_TAB';
      if(t.classList.contains('dis')) return 'DISABLED';
      t.click(); return 'OK';
    })()
    """)
    time.sleep(5)
    steps['motions'] = pg.ev(
        "(function(){var s=document.getElementById('l2Motion');"
        "return s? [...s.options].map(function(o){return o.value;}).length : -1;})()")
    return steps


def play_group(pg, group):
    return pg.ev("""
    (function(){
      var s=document.getElementById('l2Motion');
      if(!s) return 'NO_SEL';
      if(![...s.options].some(function(o){return o.value===%s;})) return 'NO_GROUP';
      s.value=%s;
      var r=document.getElementById('l2Replay');
      if(r){ r.click(); return 'REPLAY'; }
      if(window.__l2play) return window.__l2play(%s)? 'HOOK':'FALSE';
      return 'NO_PATH';
    })()
    """ % (json.dumps(group), json.dumps(group), json.dumps(group)))


def stat_edge(path):
    """中心区边缘密度：判断该侧是否真的渲染出内容（近白 = 没渲染）。"""
    from PIL import ImageFilter, ImageStat as _IS
    im = Image.open(path).convert('RGB')
    w, h = im.size
    crop = im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))
    return round(_IS.Stat(crop.filter(ImageFilter.FIND_EDGES)).mean[0], 2)


def shoot_with_retry(pg, path, min_edge=8.0, tries=4):
    """截图直到该侧确实有内容。近白帧（采集时序问题）会自动重截。

    2026-10-23 教训：对比脚本单次截图偶发抓到空白帧（edge 5.81 vs 旧侧 19.11），
    若不校验就会把"采集失败"当成"数据差异"，得出完全错误的结论。
    edge 门限取 8.0：实测正常渲染 18~28，空白帧 5.8~9.2。
    返回 (best_edge, ok)。
    """
    best = None
    for i in range(tries):
        pg.shot(path)
        e = stat_edge(path)
        if best is None or e > best:
            best = e
        if e >= min_edge:
            return e, True
        time.sleep(3.0)
    return best, False


def main():
    results = {}
    validity = {}
    for tag, url, port in SITES:
        print('\n===== %s : %s =====' % (tag, url))
        # 门禁：先确认该站点可达，否则整侧无效
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                if r.status != 200:
                    print('  [INVALID] HTTP %s' % r.status)
                    continue
        except Exception as e:  # noqa: BLE001
            print('  [INVALID] 站点不可达: %s' % e)
            continue

        pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_cmp_' + tag), url, (1400, 1000))
        try:
            pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
               if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
            time.sleep(0.6)
            st = prepare(pg, url, KEY, port)
            print('  步骤:', st)

            for group in ('idle', 'login'):
                r = play_group(pg, group)
                time.sleep(7)
                p = os.path.join(OUT, '%s_%s.png' % (group, tag))
                e, ok = shoot_with_retry(pg, p)
                print('  播 %-6s %-10s edge=%-6.2f -> %s%s'
                      % (group, r, e, os.path.basename(p), '' if ok else '  [空白帧-无效]'))
                results.setdefault(group, {})[tag] = p
                validity[(group, tag)] = ok
        finally:
            pg.close()

    # 拼接对比图（仅当两侧都有效）
    print('\n===== 拼接左右对比 =====')
    for group, paths in results.items():
        if 'old' not in paths or 'new' not in paths:
            continue
        if not (validity.get((group, 'old')) and validity.get((group, 'new'))):
            print('  跳过 %s：有一侧是空白帧，拼出来的差异无意义' % group)
            continue
        a = Image.open(paths['old']).convert('RGB')
        b = Image.open(paths['new']).convert('RGB')
        h = min(a.size[1], b.size[1])
        a = a.crop((0, 0, a.size[0], h))
        b = b.crop((0, 0, b.size[0], h))
        canvas = Image.new('RGB', (a.size[0] + b.size[0] + 8, h), (30, 30, 30))
        canvas.paste(a, (0, 0))
        canvas.paste(b, (a.size[0] + 8, 0))
        d = ImageDraw.Draw(canvas)
        d.text((10, 8), 'OLD (D:\\Azur Lane Assets)', fill=(255, 80, 80))
        d.text((a.size[0] + 18, 8), 'NEW (D:\\azur)', fill=(80, 200, 80))
        outp = os.path.join(OUT, '%s_side_by_side.png' % group)
        canvas.save(outp)
        print('  %s  (%dx%d)' % (outp, *canvas.size))
    print('\n输出目录:', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())