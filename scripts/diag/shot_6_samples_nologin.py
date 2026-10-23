"""6 个样本的目视截图（login 关闭版）。

为什么关掉 login：2026-10-23 实测发现，`开场 login` 播完后前端没有回落到 idle，
模型卡在 login 末帧。部分模型（benningdun_2 / aersasi_2）的 login 结尾是「逐渐离场」式，
导致角色移出画面、只剩背景。这是 **index.html 的回落逻辑缺陷**，不是导出数据的问题
（关掉 login 后同一模型完整可见，已对照验证）。

本脚本只做「让用户看到正确画面」这一件事，不改任何前端代码。

判据（落在截图像素上，不用 canvas.drawImage —— WebGL 未 preserveDrawingBuffer 时它恒空白）：
  中心区 FIND_EDGES 均值 > 2.0 视为「有角色细节」；同时 tab 必须是目标 tab。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))   # scripts/diag/ -> 仓库根
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402  必须在 join scripts 之后
import gallery_ui_shots as GU  # noqa: E402

_real = getattr(P, 'CHROME', '') or ''
if _real and os.path.exists(_real):
    GU.CHROME = _real
elif not os.path.exists(GU.CHROME):
    raise SystemExit('[FAIL] 找不到可用的 Chromium 浏览器')

from gallery_ui_shots import Page  # noqa: E402
from PIL import Image, ImageStat, ImageFilter  # noqa: E402

PORT = 9230
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'samples_final')
PROFILE = os.path.join(ROOT, '.diag', 'chrome_final6')

TARGETS = [
    ('1_painting_haitian_3', 'haitian_3',    'painting'),
    ('2_spine_aersasi',      'aersasi',      'spine'),
    ('3_l2d_benningdun_2',   'benningdun_2', 'live2d'),
    ('4_l2d_aersasi_2',      'aersasi_2',    'live2d'),
    ('5_l2d_aersasi_3',      'aersasi_3',    'live2d'),
    ('6_l2d_ougen_8',        'ougen_8',      'live2d'),
]


def center_edge(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    crop = im.crop((int(w * .42), int(h * .28), int(w * .88), int(h * .72)))
    return round(ImageStat.Stat(crop.filter(ImageFilter.FIND_EDGES)).mean[0], 2)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(PROFILE, exist_ok=True)
    pg = Page(PORT, PROFILE, URL, (1400, 1000))
    rows = []
    try:
        pg.ev("window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));1")
        time.sleep(1.2)

        # 强制关闭 login（并写回 localStorage，防页面重载后恢复）
        r = pg.ev("""
        (function(){
          var b=document.querySelector('#gOpt button[data-k=login]');
          if(!b) return 'NO_BTN';
          var on=b.classList.contains('on')||b.dataset.on==='1';
          if(on){ b.click(); }
          var now=b.classList.contains('on')||b.dataset.on==='1';
          try{ var o=JSON.parse(localStorage.getItem('gallery.opt.v1')||'{}'); o.login=false;
               localStorage.setItem('gallery.opt.v1', JSON.stringify(o)); }catch(e){}
          return JSON.stringify({before:on, after:now});
        })()
        """)
        print('login 开关:', r)
        time.sleep(0.5)

        for name, skin, tab in TARGETS:
            r1 = pg.ev("""
            (function(){
              var key=%s;
              var ship=(window.GALLERY.ships||[]).find(s=>(s.skins||[]).some(k=>k.key===key));
              if(!ship) return 'NO_SHIP';
              var c=[...document.querySelectorAll('.card')].find(function(el){
                  return (el.textContent||'').indexOf(ship.name)>=0;});
              if(!c) return 'NO_CARD';
              c.click(); return 'OPEN|'+ship.name;
            })()
            """ % json.dumps(skin))
            time.sleep(1.0)

            r2 = pg.ev("""
            (function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(el){
                return el.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'SKIN_OK';})()
            """ % json.dumps(skin))
            time.sleep(0.8)

            r3 = pg.ev("""
            (function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(el){
                return el.dataset.k===%s;}); if(!t) return 'NO_TAB';
                if(t.classList.contains('dis')) return 'DISABLED'; t.click(); return 'TAB_OK';})()
            """ % json.dumps(tab))
            time.sleep(4.0)   # 等模型加载 + 首帧

            shot = os.path.join(OUT, name + '.png')
            pg.shot(shot)
            edge = center_edge(shot)
            tabon = pg.ev("(function(){var o=document.querySelector('#mTabs .tab.on');"
                          "return o?o.dataset.k:null;})()")
            # 硬判据：页面若渲染出「Live2D 加载失败」之类的错误文本，一律算失败。
            # 宽高比/edge 会骗人（斜纹背景自身就有边缘），错误文本不会。
            fail = pg.ev("(function(){var m=document.body.innerText.match("
                         "/Live2D[^\\n]{0,12}(失败|错误)|Spine[^\\n]{0,12}(失败|错误)|加载失败/);"
                         "return m? m[0].slice(0,60):null;})()")
            ok = (tabon == tab) and edge > 2.0 and not fail
            print('%-22s %-9s %-9s tab=%-9s edge=%-6.2f fail=%-6s %s'
                  % (name, r1, r2, tabon, edge, fail or '-', 'PASS' if ok else 'FAIL'))
            rows.append((name, tab, tabon, edge, fail, ok))

            pg.ev("(function(){var b=document.getElementById('close'); if(b) b.click(); return 1})()")
            time.sleep(0.7)

        print('\n页面异常:', pg.ev("JSON.stringify(window.__errs||[])"))
    finally:
        pg.close()

    print('\n===== 判据汇总（edge>2.0 且 tab 正确 且 无失败文本 = 有角色内容）=====')
    ok = sum(1 for *_, good in rows if good)
    for name, tab, tabon, edge, fail, good in rows:
        print('%-22s edge=%-6.2f fail=%-6s %s' % (name, edge, fail or '-', 'PASS' if good else 'FAIL'))
    print('%s %d/%d' % ('[PASS]' if ok == len(rows) else '[FAIL]', ok, len(rows)))
    print('截图:', OUT)
    return 0 if ok == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
