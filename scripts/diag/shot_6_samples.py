"""6 个样本的目视验证：走前端真实 DOM 点击路径逐个打开并截图。

为什么要走 DOM 点击而不是直接调库：项目 DoD 禁止绕过被测入口
（验前端却直接调 startMotion 会得到假阴性）。这里点的是卡片、皮肤行、tab，
跟用户手动操作一致。

DOM 约定（2026-10-23 从 gallery_src/index.html 实读，不是猜的）：
  - 舰船卡片   .card              （click -> openShip(s, card)）
  - 皮肤列表   #mSkins .skin[data-k]（click -> setSkin）
  - 标签条     #mTabs .tab[data-k]  （painting / spine / live2d / voice；disabled 项带 .dis）
  - 查看器画布 canvas（Live2D/Spine 都有）

判据：
  1. 页面无未捕获异常
  2. 目标 tab 真的选中（.tab.on 的 data-k 等于目标）
  3. 画布非空白（取样像素方差 > 阈值）—— 只看 canvas 尺寸会被"空白画布"骗过
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import gallery_ui_shots as GU  # noqa: E402
import paths as P  # noqa: E402

# gallery_ui_shots 把 CHROME 写死为 Google Chrome，本机只有 Edge。
# 只覆盖模块级常量，不复制它的 Page（它负责 chrome_tree 生命周期清理）。
_real = getattr(P, 'CHROME', '') or ''
if _real and os.path.exists(_real):
    GU.CHROME = _real
elif not os.path.exists(GU.CHROME):
    raise SystemExit('[FAIL] 找不到可用的 Chromium 浏览器')

from gallery_ui_shots import Page  # noqa: E402

PORT = 9226
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'samples_shots')
PROFILE = os.path.join(ROOT, '.diag', 'chrome_6samples')

TARGETS = [
    ('1_painting_haitian_3', 'haitian_3',  'painting'),
    ('2_spine_aersasi',      'aersasi',    'spine'),
    ('3_l2d_benningdun_2',   'benningdun_2', 'live2d'),
    ('4_l2d_aersasi_2',      'aersasi_2',  'live2d'),
    ('5_l2d_aersasi_3',      'aersasi_3',  'live2d'),
    ('6_l2d_ougen_8',        'ougen_8',    'live2d'),
]

# 画布非空白的判据：把 WebGL canvas 抹到 2D 画布上取样，统计非背景像素比例
JS_CANVAS_NONBLANK = r"""
(function(){
  var c = document.querySelector('canvas');
  if(!c) return JSON.stringify({err:'NO_CANVAS'});
  try{
    var t = document.createElement('canvas');
    t.width = 160; t.height = 160;
    var g = t.getContext('2d');
    g.drawImage(c, 0, 0, 160, 160);
    var d = g.getImageData(0,0,160,160).data;
    var n=0, sum=0, sum2=0;
    for(var i=0;i<d.length;i+=4){
      var v = (d[i]+d[i+1]+d[i+2])/3;
      if(d[i+3] > 8){ n++; sum+=v; sum2+=v*v; }
    }
    var mean = n? sum/n : 0;
    var varr = n? (sum2/n - mean*mean) : 0;
    return JSON.stringify({w:c.width,h:c.height,opaqueRatio:n/(160*160),mean:mean,var:varr});
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(PROFILE, exist_ok=True)
    pg = Page(PORT, PROFILE, URL, (1400, 1000))
    results = []
    try:
        pg.ev("window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
              "window.addEventListener('unhandledrejection',e=>window.__errs.push('rej:'+String(e.reason)));1")
        time.sleep(1.2)

        for name, skin, tab in TARGETS:
            # 1) 打开舰船卡（用皮肤反查所属舰）
            r1 = pg.ev("""
            (function(){
              var key=%s;
              var ship=(window.GALLERY.ships||[]).find(s=>(s.skins||[]).some(k=>k.key===key));
              if(!ship) return 'NO_SHIP_FOR_KEY';
              var cards=[...document.querySelectorAll('.card')];
              var c=cards.find(function(el){
                 return (el.textContent||'').indexOf(ship.name)>=0 || el.dataset.id===ship.id;});
              if(!c) return 'NO_CARD|'+ship.name;
              c.click();
              return 'OPEN|'+ship.name;
            })()
            """ % json.dumps(skin))
            time.sleep(1.2)

            # 2) 选皮肤
            r2 = pg.ev("""
            (function(){
              var d=[...document.querySelectorAll('#mSkins .skin')].find(function(el){
                 return el.dataset.k===%s;});
              if(!d) return 'NO_SKIN_ROW';
              d.click(); return 'SKIN_OK';
            })()
            """ % json.dumps(skin))
            time.sleep(1.0)

            # 3) 切 tab（.dis 表示该皮肤无此类内容）
            r3 = pg.ev("""
            (function(){
              var t=[...document.querySelectorAll('#mTabs .tab')].find(function(el){
                 return el.dataset.k===%s;});
              if(!t) return 'NO_TAB';
              if(t.classList.contains('dis')) return 'TAB_DISABLED';
              t.click(); return 'TAB_CLICKED';
            })()
            """ % json.dumps(tab))
            time.sleep(3.0)   # 等模型加载/首帧

            info = pg.ev("""
            (function(){
              var on=document.querySelector('#mTabs .tab.on');
              var im=document.querySelector('.viewEl img, #view img, .vbox img');
              return JSON.stringify({
                tabOn: on? on.dataset.k : null,
                img: im? [im.naturalWidth, im.naturalHeight, (im.src||'').slice(-45)] : null,
                errs:(window.__errs||[]).slice(0,4)
              });
            })()
            """)
            cv = pg.ev(JS_CANVAS_NONBLANK)

            shot = os.path.join(OUT, name + '.png')
            pg.shot(shot)
            meta = {'open': r1, 'skin': r2, 'tab': r3,
                    'ui': json.loads(info) if info and info.startswith('{') else info,
                    'canvas': json.loads(cv) if cv and cv.startswith('{') else cv}
            print('%-22s %s | %s | %s' % (name, r1, r2, r3))
            print('                       tabOn=%s img=%s' % (meta['ui'].get('tabOn') if isinstance(meta['ui'], dict) else '?',
                                                              meta['ui'].get('img') if isinstance(meta['ui'], dict) else '?'))
            print('                       canvas=%s' % (meta['canvas'],))
            results.append((name, meta))

            pg.ev("(function(){var b=document.getElementById('close'); if(b) b.click(); return 1})()")
            time.sleep(0.8)

        print('\n页面累计异常:', pg.ev("JSON.stringify(window.__errs||[])"))
    finally:
        pg.close()

    # 汇总判据
    print('\n===== 判据汇总 =====')
    ok = 0
    for name, m in results:
        c = m['canvas'] if isinstance(m['canvas'], dict) else {}
        tabon = m['ui'].get('tabOn') if isinstance(m['ui'], dict) else None
        want = dict((n, t) for n, s, t in TARGETS)[name]
        good_tab = (tabon == want)
        good_cv = c.get('opaqueRatio', 0) > 0.02 and c.get('var', 0) > 30
        good = good_tab and good_cv and not m['ui'].get('errs')
        ok += bool(good)
        print('%-22s tab %-4s(%s) 画布占用 %.3f 方差 %.0f -> %s'
              % (name, tabon, 'OK' if good_tab else 'FAIL',
                 c.get('opaqueRatio', 0), c.get('var', 0), 'PASS' if good else 'FAIL'))
    print('%s %d/%d 通过' % ('[PASS]' if ok == len(results) else '[FAIL]', ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
