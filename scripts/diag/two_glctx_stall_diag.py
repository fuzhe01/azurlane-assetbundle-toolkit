"""第十一层取证：**同页两个 WebGL 上下文**是否就是「1fps + 主线程空闲」的成因。

上一节 `new_canvas_stall_audit` 的关键读数（同一次会话、连续 A/B）：
  A0 初载（1 块 canvas 986x627）        60.0 fps
  A2 点舰船卡（新增 2098x1492 canvas）  59.5 fps → 随后仍在几秒内归位到 1fps（渐进式）
  A/B 结果：
    · 隐藏第 2 块 canvas（display:none） → **仍 1fps**（WebGL 在 display:none 下照样跑 GL 命令）
    · 清掉祖先 backdrop-filter/will-change → 仍 1fps
    · CSS 尺寸对齐 backing store → 仍 1fps
    · backing store 缩到 CSS 尺寸 → 仍 1fps（且实测未生效，说明有 resize 逻辑反复改回）

⇒ 「一块画布太大 / 有模糊」都不是病灶。产物页从 1 块 WebGL 变成 **2 块同时逐帧重绘**，
   而这一点从未被单独验证过。本节就用不含任何产品代码的最小页把变量扣死：

  D1 单上下文（1 块 986x627）        → 必须 60fps（阳性对照）
  D2 双上下文（986x627 + 2098x1492） → 若 1fps，就是这个组合本身
  D3 双上下文但第二块 800x600（小）  → 若也 1fps，与尺寸无关、与"两个上下文"有关
                                          若稳 60，则是"第二个上下文 + 大尺寸"的组合

判据：D1 稳、D2 不稳 ⇒ 该现象**与产品代码无关，是 headless 合成器在双 WebGL 上下文下的行为**，
      本轮所有「刷新率相关」的探针判据都必须以此为前置条件重新校核。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

BASE = 'file:///D:/azur/scripts/diag/gl_two_ctx.html'

READ = r"""
(function(){
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0};
  return JSON.stringify({n:p.n, ms:+(performance.now()-p.t0).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    nCtx:window.__nCtx||0,
    cv:[].map.call(document.querySelectorAll('canvas'),function(c){return c.width+'x'+c.height;})});
})()
"""


def fps_between(a, b):
    dm = b['ms'] - a['ms']
    return (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0


def case(label, query, rounds=10):
    print('\n===== %s (%s) =====' % (label, query))
    pg = open_page(BASE + query + '#gallery_v2', win=(1400, 1000), tag=label[:2])
    try:
        time.sleep(2.0)
        first = json.loads(pg.ev(READ))
        print('  上下文数=%d 画布=%s' % (first['nCtx'], first['cv']))
        print('  %-7s %-6s %-9s %-7s %s' % ('ms', 'n', 'gapMax', 'stalls', 'fps'))
        prev = first
        for _ in range(rounds):
            s = json.loads(pg.ev(READ))
            print('  %-7d %-6d %-9d %-7d %.1f' % (s['ms'], s['n'], s['gapMax'],
                                                  s['stalls'], fps_between(prev, s)))
            prev = s
            time.sleep(1.0)
    finally:
        pg.close()


def case_lose_context():
    """在产品页上验证 loseContext：若帧率恢复到 60 ⇒ 病灶确实是"第二个 WebGL 上下文在跑"。"""
    print('\n===== D4 产品页 + 对第 2 块画布 loseContext =====')
    URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
    pg = open_page(URL, win=(1400, 1000), tag='d4')
    try:
        time.sleep(3.5)
        print('装计数:', pg.ev(COUNTER))
        print('  %-7s %-6s %-9s %-7s %s' % ('ms', 'n', 'gapMax', 'stalls', 'fps'))
        prev = None
        for _ in range(4):
            s = json.loads(pg.ev(READ))
            print('  %-7d %-6d %-9d %-7d %s' % (s['ms'], s['n'], s['gapMax'], s['stalls'],
                                                 ('%.1f' % fps_between(prev, s)) if prev else ''))
            prev = s
            time.sleep(1.0)
        print('  点舰船卡:', pg.ev(TO_CARD))
        time.sleep(3.0)
        print('  对第 2 块画布 loseContext:', pg.ev("""(function(){
            var cv=document.querySelectorAll('canvas'); var d=cv[cv.length-1];
            if(!d||d.__lost) return 'NO_TARGET';
            var gl=d.getContext('webgl2')||d.getContext('webgl');
            var ext=gl&&gl.getExtension('WEBGL_lose_context');
            if(!ext) return 'NO_EXT';
            d.__lost=true; ext.loseContext(); return 'LOST';
        })()"""))
        time.sleep(2.0)
        prev = None
        for _ in range(6):
            s = json.loads(pg.ev(READ))
            print('  %-7d %-6d %-9d %-7d %s' % (s['ms'], s['n'], s['gapMax'], s['stalls'],
                                                 ('%.1f' % fps_between(prev, s)) if prev else ''))
            prev = s
            time.sleep(1.0)
        print('  判据：loseContext 后回 60 ⇒ 病灶就是它；仍 1fps ⇒ 另有其因')
    finally:
        pg.close()


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

TO_CARD = """var b=document.querySelector('#gOpt button[data-k=login]');
  if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();
  var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();"""


def main():
    case('D1 单上下文', '?c=1')
    case('D2 双上下文(986+2098)', '?c=2')
    case_lose_context()
    return 0


if __name__ == '__main__':
    sys.exit(main())
