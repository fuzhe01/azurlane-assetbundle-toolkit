"""第十层取证：A2「点舰船卡」新增的 `2098x1492` 画布为什么让帧率永久掉到 1fps。

上一节决定性读数（同一次会话内连续测，每步静置 5 秒）：
  A0 初载 login 界面      60.0 fps  gapMax=21    停顿=0   canvas=[986x651]
  A1 关 login 浮层        60.0 fps  gapMax=26    停顿=0   canvas=[986x627]
  A2 点舰船卡（静态立绘）  **1.9 fps  gapMax=3492  停顿=3**  canvas=[986x627, **2098x1492**]
  A3 选皮肤               0.8 fps
  A4 切 Live2D            1.0 fps
  ⇒ 触发器是 A2 这一步，且同一步里**新增了一块 2098x1492 的画布**（第一块只有 986x627）。
    衰减此后不再恢复（停顿计数单调 +3 → +7 → +13）。

注意：上一节 `canvas_size_stall_ab` 里我自建的 2740x1810 画布是**稳定 60fps**的，
所以「尺寸大」本身不足以解释。产物页那块画布与自建画布的差别只可能在
  ① CSS 显示尺寸 ≠ backing store（缩放合成）②祖先链上的 transform/filter/backdrop-filter
  ③alpha/混合。本节直接把这些**读出来**并逐个 A/B 关掉。

判据：任一 A/B（隐藏该 canvas / 去掉祖先 filter / 去掉 transform / CSS 尺寸对齐像素）
把 fps 拉回 >30 ⇒ 该项就是病灶；全部无效 ⇒ 转向 GPU 侧的 surface 分配。
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

READ = ("JSON.stringify({n:window.__rafc.n, ms:+(performance.now()-window.__rafc.t0).toFixed(0),"
        " gapMax:+window.__rafc.gapMax.toFixed(0), stalls:window.__rafc.stalls})")

TO_CARD = """var b=document.querySelector('#gOpt button[data-k=login]');
  if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();
  var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();"""

# 两块 canvas 的完整状况：backing store、CSS 尺寸、祖先链上的合成相关属性
AUDIT = r"""
(function(){
  var out=[];
  [].forEach.call(document.querySelectorAll('canvas'), function(cv,i){
    var r=cv.getBoundingClientRect(); var cs=getComputedStyle(cv);
    var chain=[]; var n=cv.parentElement; var depth=0;
    while(n && depth<6){
      var s=getComputedStyle(n);
      var bits=[];
      if(s.transform && s.transform!=='none') bits.push('transform='+s.transform);
      if(s.filter && s.filter!=='none') bits.push('filter='+s.filter);
      if(s.backdropFilter && s.backdropFilter!=='none') bits.push('backdrop='+s.backdropFilter);
      if(s.willChange && s.willChange!=='auto') bits.push('will-change='+s.willChange);
      if(s.mixBlendMode && s.mixBlendMode!=='normal') bits.push('blend='+s.mixBlendMode);
      if(s.opacity!=='1') bits.push('opacity='+s.opacity);
      if(s.contain && s.contain!=='none') bits.push('contain='+s.contain);
      if(bits.length) chain.push((n.tagName+'.'+(n.className||'')).slice(0,34)+' :: '+bits.join(' | '));
      n=n.parentElement; depth++;
    }
    out.push({idx:i, px:cv.width+'x'+cv.height,
      css:Math.round(r.width)+'x'+Math.round(r.height),
      ratio:+(cv.width/Math.max(1,r.width)).toFixed(2),
      alpha:cs.opacity, chain:chain});
  });
  return JSON.stringify(out);
})()
"""


def fps_over(pg, sec=4.0):
    time.sleep(0.5)
    a = json.loads(pg.ev(READ))
    time.sleep(sec)
    b = json.loads(pg.ev(READ))
    dm = b['ms'] - a['ms']
    return ((b['n'] - a['n']) * 1000.0 / dm if dm else 0.0), b


def report(pg, label):
    f, b = fps_over(pg)
    print('  %-34s %6.1f fps  gapMax=%d 停顿=%d' % (label, f, b['gapMax'], b['stalls']))
    return f


AB_TESTS = [
    ('隐藏第 2 块 canvas（display:none）',
     """(function(){var c=document.querySelectorAll('canvas');var d=c[c.length-1];
         if(!d) return 'NONE'; d.style.display='none'; return 'HID';})()"""),
    ('恢复显示 + 去掉祖先链 filter/backdrop',
     """(function(){var c=document.querySelectorAll('canvas');var d=c[c.length-1];
         if(!d) return 'NONE'; d.style.display='';
         var n=d.parentElement, k=0;
         while(n&&k<6){ n.style.filter='none'; n.style.backdropFilter='none';
           n.style.willChange='auto'; n=n.parentElement; k++; }
         return 'CLEARED';})()"""),
    ('CSS 尺寸对齐 backing store（去掉缩放合成）',
     """(function(){var c=document.querySelectorAll('canvas');var d=c[c.length-1];
         if(!d) return 'NONE';
         d.style.width=d.width+'px'; d.style.height=d.height+'px';
         return 'SIZE '+d.width+'x'+d.height;})()"""),
    ('把 backing store 缩小到 CSS 尺寸（986x627 量级）',
     """(function(){var c=document.querySelectorAll('canvas');var d=c[c.length-1];
         if(!d) return 'NONE';
         var r=d.getBoundingClientRect();
         d.style.width=d.style.height='';
         d.width=Math.max(64,Math.round(r.width)); d.height=Math.max(64,Math.round(r.height));
         return 'RESIZED '+d.width+'x'+d.height;})()"""),
]


def main():
    pg = open_page(URL, win=(1400, 1000), tag='audit')
    try:
        time.sleep(3.5)
        print('装计数:', pg.ev(COUNTER))
        report(pg, 'A0 初载')
        pg.ev(TO_CARD)
        report(pg, 'A2 点舰船卡（已触发衰减）')
        print('\n--- 两块 canvas 的合成状况 ---')
        for item in json.loads(pg.ev(AUDIT)):
            print('  canvas[%d] 像素 %s  CSS %s  比例 %s  opacity %s'
                  % (item['idx'], item['px'], item['css'], item['ratio'], item['alpha']))
            for line in item['chain']:
                print('      祖先 %s' % line)
        print('\n--- 逐个 A/B ---')
        for label, js in AB_TESTS:
            r = pg.ev(js)
            print('    -> %s => %s' % (label, str(r)[:44]))
            report(pg, label)
        print('\n  判据：任一 A/B 把 fps 拉回 >30 ⇒ 该项是病灶')
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
