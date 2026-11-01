"""严格验证 login 播完是否回落（带强制前置门禁）。

2026-10-23 两次踩坑，本版全部封死：
  ① 不信 #l2Curr 标签：库自动回落时不刷新它，标签会一直是 login（假证据）
  ② 不做无门禁的结论：服务器挂了 / 页面白屏时三张图完全相同，
     会被算成「差 0.00 → 回落生效」的假通过。
     ⇒ 本版先验服务器、再验页面渲染出内容，任一不过直接 exit 1，不输出结论。

设计：A=等 idle 稳定  B=播 login 等 35s  C=手动播 idle
判据：以 C vs A 为「本底差异」（idle 呼吸循环导致同状态也不同），
     若 B ≈ C（在 1.8 倍本底内）→ 已回落；若 B 明显异于 C → 卡在末帧。
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

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402
from PIL import Image, ImageChops, ImageStat, ImageFilter  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'login_return2')
os.makedirs(OUT, exist_ok=True)
MIN_EDGE = 8.0


def server_ok():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def crop_viewer(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    return im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))


def edge_of(img):
    return ImageStat.Stat(img.filter(ImageFilter.FIND_EDGES)).mean[0]


def diff(a, b):
    w = min(a.size[0], b.size[0]); h = min(a.size[1], b.size[1])
    d = ImageChops.difference(a.crop((0, 0, w, h)), b.crop((0, 0, w, h))).convert('L')
    hist = d.histogram(); tot = sum(hist)
    return ImageStat.Stat(d).mean[0], sum(hist[24:]) * 100.0 / tot


def main():
    # ---- 门禁 1：服务器 ----
    if not server_ok():
        print('[INVALID] 服务器 %s 不可用 —— 请先启动，本脚本不做任何结论' % URL)
        return 2
    print('[OK] 服务器在线')

    pg = Page(9255, os.path.join(ROOT, '.diag', 'chrome_loginret2'),
              URL, (1400, 1000))
    try:
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        steps = {}
        steps['card'] = pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD';
          c.click(); return 'OK';})()
        """ % json.dumps(KEY))
        time.sleep(1.5)
        steps['skin'] = pg.ev("""
        (function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
             return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()
        """ % json.dumps(KEY))
        time.sleep(1.2)
        steps['tab'] = pg.ev("""
        (function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
             return e.dataset.k==='live2d';});
          if(!t) return 'NO_TAB';
          if(t.classList.contains('dis')) return 'DIS';
          t.click(); return 'OK';})()
        """)
        print('步骤:', steps)
        time.sleep(10)

        # ---- 门禁 2：渲染出内容 ----
        pa = os.path.join(OUT, 'A_idle.png')
        pg.shot(pa)
        ia = crop_viewer(pa)
        ea = edge_of(ia)
        print('[A] idle edge=%.2f' % ea)
        if ea < MIN_EDGE:
            print('[INVALID] idle 状态渲染不出内容（edge %.2f < %.1f）—— 页面未就绪，不输出结论'
                  % (ea, MIN_EDGE))
            return 2

        # B: 播 login 等 35s
        r = pg.ev("""(function(){ var s=document.getElementById('l2Motion'); if(s) s.value='login';
                   var b=document.getElementById('l2Replay'); if(b){b.click(); return 'REPLAY';}
                   if(window.__l2play) return window.__l2play('login')?'HOOK':'FALSE';
                   return 'NO_PATH'; })()""")
        print('[B] 播 login (%s)，等 35s ...' % r)
        time.sleep(35)
        pb = os.path.join(OUT, 'B_login_35s.png')
        pg.shot(pb)
        ib = crop_viewer(pb)
        print('    edge=%.2f l2Curr=%s' % (edge_of(ib),
              pg.ev("(function(){var e=document.getElementById('l2Curr');return e?e.textContent:null;})()")))

        # C: 手动 idle
        pg.ev("""(function(){ var s=document.getElementById('l2Motion'); if(s) s.value='idle';
                   var b=document.getElementById('l2Replay');
                   if(b) b.click(); else if(window.__l2play) window.__l2play('idle'); return 1; })()""")
        print('[C] 手动播 idle，等 10s ...')
        time.sleep(10)
        pc = os.path.join(OUT, 'C_manual_idle.png')
        pg.shot(pc)
        ic = crop_viewer(pc)
        ec = edge_of(ic)
        print('    edge=%.2f' % ec)
        if ec < MIN_EDGE:
            print('[INVALID] 手动 idle 也渲染不出内容 —— 不输出结论')
            return 2

        m_ab, p_ab = diff(ia, ib)
        m_ac, p_ac = diff(ia, ic)
        m_bc, p_bc = diff(ib, ic)
        print('\n=== 像素对比（查看器区域）===')
        print('  A idle       edge=%.2f' % ea)
        print('  B login+35s  edge=%.2f' % edge_of(ib))
        print('  C 手动 idle  edge=%.2f' % ec)
        print('  B vs A : 平均差 %6.2f  显著差 %5.2f%%' % (m_ab, p_ab))
        print('  C vs A : 平均差 %6.2f  显著差 %5.2f%%  ← 本底（呼吸循环）' % (m_ac, p_ac))
        print('  B vs C : 平均差 %6.2f  显著差 %5.2f%%' % (m_bc, p_bc))

        base = max(m_ac, 0.5)
        print('\n=== 结论 ===')
        if m_bc <= base * 1.8:
            print('  B ≈ C（%.2f vs 本底 %.2f）→ login 播完已回到 idle 画面' % (m_bc, base))
            print('  ⇒ 回落生效；#l2Curr 标签不刷新是 UI 瑕疵')
            return 0
        print('  B 明显异于 C（%.2f vs 本底 %.2f）→ 卡在 login 末帧，需修' % (m_bc, base))
        return 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())