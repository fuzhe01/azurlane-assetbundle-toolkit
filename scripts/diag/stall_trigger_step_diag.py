"""第九层取证：定位「60fps → 1fps」的**触发动作**。

上一节关键读数（同仪器、真 GPU、静置）：
  · G0 画廊**初载 login 界面**：10 秒 59.9fps 恒定、`stalls=0`、`gapMax=18~19ms` ⇒ **完全健康**；
  · 各种进舰船/Live2D/静态立绘用例：一律衰减到 1fps。
  ⇒ 衰减发生在「离开首页」这段 UI 动作上，而不是页面一打开就有。

本节把这段动作切成 4 步，每步后静置 5 秒量帧率，找出是哪一步翻的：
  A0 初载                      （已知 60fps，作为自身阳性对照）
  A1 关掉 login 浮层
  A2 点舰船卡（进入舰船视图，此时是静态立绘）
  A3 选皮肤 ougen_8
  A4 切 Live2D

判据：某一步之后 fps 从 ≈60 掉到 <10 且此后不再恢复 ⇒ 该步就是触发器。
     必须在**同一次会话里连续测**（换页面重开会丢掉"哪一步"的信息，只能看到结果）。
      每步读数同时记 `canvas` 列表与尺寸：若触发步正好新增/放大了 canvas，
      则"新画布接管呈现"是候选机制。
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
  var cv=[].map.call(document.querySelectorAll('canvas'),
    function(c){return c.width+'x'+c.height;});
  return JSON.stringify({n:p.n, ms:+(performance.now()-p.t0).toFixed(0),
    gapMax:+p.gapMax.toFixed(0), stalls:p.stalls||0, cv:cv});
})()
"""

STEPS = [
    ('A1 关 login 浮层',
     """var b=document.querySelector('#gOpt button[data-k=login]');
        if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();"""),
    ('A2 点舰船卡（静态立绘）',
     """var s=(window.GALLERY.ships||[]).find(function(x){
          return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
        var c=[...document.querySelectorAll('.card')].find(function(e){
          return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();"""),
    ('A3 选皮肤 ougen_8',
     """var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
          return e.dataset.k=='ougen_8';}); if(d) d.click();"""),
    ('A4 切 Live2D',
     """var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
          return e.dataset.k=='live2d';}); if(t&&!t.classList.contains('dis')) t.click();"""),
]


def measure(pg, label, sec=5.0):
    """静置 sec 秒后报该段的平均 fps、gapMax、停顿次数。"""
    time.sleep(0.6)
    a = json.loads(pg.ev(READ))
    time.sleep(sec)
    b = json.loads(pg.ev(READ))
    dm = b['ms'] - a['ms']
    f = (b['n'] - a['n']) * 1000.0 / dm if dm else 0.0
    print('  %-26s %6.1f fps  gapMax=%-5d 停顿=%-2d canvas=%s'
          % (label, f, b['gapMax'], b['stalls'], b['cv']))
    return f


def main():
    pg = open_page(URL, win=(1400, 1000), tag='trig')
    try:
        time.sleep(3.5)
        print('装计数:', pg.ev(COUNTER))
        print('  %-26s %s' % ('阶段', '读数'))
        measure(pg, 'A0 初载（自身阳性对照）')
        for label, js in STEPS:
            r = pg.ev(js)
            print('    -> %s 执行=%s' % (label, str(r)[:40]))
            measure(pg, label)
        print('\n  判据：某步后 fps<10 且不再恢复 ⇒ 该步是触发器')
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
