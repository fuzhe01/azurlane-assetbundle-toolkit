"""第十三层取证（产品缺陷定根因）：`backdrop-filter`（毛玻璃）在每帧变化的 WebGL 背景上重算。

已确认（这一条把问题性质改写了）：
  · `headful_vs_headless_fps`：**有窗口的真实浏览器**点舰船卡后同样从 60fps 掉到 **4.2fps**
    （随后回 18.8fps，抖动）。⇒ 这**不是 headless 仪器问题，是真实产品性能缺陷**。
  · 衰减是**渐进**的（点完先 59.3fps，几秒后才归位），且 `visibility=visible`、`focus=true`、
    `UNMASKED_RENDERER` 始终 NVIDIA、无 context lost、堆平稳、主线程 idle 72.6%。
    ⇒ 时间花在**主线程之外**（GPU/合成器），而主线程闲 ⇒ 是被合成器反压拖住。

页面上唯一会「每帧重算」的昂贵合成操作是 `backdrop-filter`：
  · `index.html:204` `.mask{position:fixed;inset:0;backdrop-filter:blur(3px)}` —— **全屏**
  · `index.html:125` `.card.g{backdrop-filter:blur(var(--glass-blur))}` —— 卡片毛玻璃
  · `index.html:26/36/135` nav / nav-rim / card::before
  初载 60fps 是因为这层底下**没有每帧变化的画面**；点舰船卡后底下出现
  **每帧重绘的 WebGL canvas**（2098x1492，CSS 尺寸的 2 倍）⇒ 每帧都要把全屏背景重新采样+模糊。

上一节 A/B 没验出结论的原因（已修）：当时只对 canvas 祖先链设 `style.filter/backdropFilter='none'`
内联，既没带 `-webkit-` 前缀、也没带 `!important`，还被类规则和层叠顺序压掉。
本节改用**注入样式表 + !important**，并逐类拆开，避免"一次改一堆所以说不清是哪一项"。

判据：
  E1 全局 `backdrop-filter:none !important` → 若 fps 回到 >30 ⇒ 定责成立；
  E2 只禁 `.mask` 的全屏模糊       → 分清是全屏那层还是卡片那几层；
  E3 只禁 `.card*` 的模糊          → 同上，另一侧；
  E4 恢复全部后必须重新衰减       → 证明是 E1~E3 的改动在起作用，而不是时间/次数巧合。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

COUNTER = r"""
(function(){
  if(window.__rafc) return 'ALREADY';
  window.__rafc={n:0,t0:performance.now(),gapMax:0,prev:0,stalls:0};
  function loop(){
    var now=performance.now();
    if(window.__rafc.prev){ var g=now-window.__rafc.prev;
      if(g>window.__rafc.gapMax) window.__rafc.gapMax=g; if(g>200) window.__rafc.stalls++; }
    window.__rafc.prev=now; window.__rafc.n++; requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return 'OK';
})()
"""

READ = r"""
(function(){
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0};
  return JSON.stringify({n:p.n, ms:+(performance.now()-p.t0).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    cv:[].map.call(document.querySelectorAll('canvas'),function(c){return c.width+'x'+c.height;})});
})()
"""

TO_CARD = """var b=document.querySelector('#gOpt button[data-k=login]');
  if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();
  var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();"""

STYLE_ID = '__abStyle'


def inject(css):
    return """(function(){
      var s=document.getElementById('%s');
      if(!s){ s=document.createElement('style'); s.id='%s';
              document.documentElement.appendChild(s); }
      s.textContent=%s;
      return 'INJECTED';
    })()""" % (STYLE_ID, STYLE_ID, json.dumps(css))


def measure(pg, label, sec=5.0):
    time.sleep(0.6)
    a = json.loads(pg.ev(READ))
    time.sleep(sec)
    b = json.loads(pg.ev(READ))
    dm = b['ms'] - a['ms']
    f = (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0
    print('  %-38s %6.1f fps  gapMax=%-5d 停顿=%d' % (label, f, b['gapMax'], b['stalls']))
    return f


MASKS = [
    ('E1 全局禁 backdrop-filter', """
      *,*::before,*::after{
        backdrop-filter:none !important;
        -webkit-backdrop-filter:none !important; }"""),
    ('E2 只禁 .mask 全屏模糊', """
      .mask, .mask::before, .mask::after{
        backdrop-filter:none !important;
        -webkit-backdrop-filter:none !important; }"""),
    ('E3 只禁 .card/.card::before 模糊', """
      .card, .card::before, .card::after,
      .card.g, .card.g::before, .card.g::after{
        backdrop-filter:none !important;
        -webkit-backdrop-filter:none !important; }"""),
]


def main():
    pg = open_page(URL, win=(1400, 1000), tag='bf')
    try:
        time.sleep(3.5)
        print('装计数:', pg.ev(COUNTER))
        measure(pg, 'E0 初载（阳性对照，应 60）', sec=4.0)
        pg.ev(TO_CARD)
        measure(pg, 'E0b 点舰船卡（基线，应衰减）', sec=6.0)
        for label, css in MASKS:
            print('    -> %s => %s' % (label, pg.ev(inject(css))))
            measure(pg, label)
        print('    -> 恢复全部（清空覆盖样式） => %s' % pg.ev(inject('')))
        measure(pg, 'E4 恢复原始 CSS（应重新衰减）')
        print('\n  判据：E1 回 >30fps 且 E4 重新衰减 ⇒ backdrop-filter 是病灶（因果闭环）')
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
