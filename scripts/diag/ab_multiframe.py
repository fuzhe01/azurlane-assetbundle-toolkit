"""多帧稳定性对比：排除「恰好两帧不同」的时序干扰，锁定稳定差异。

之前 ab_drawable_diff 显示两画廊 drawable 状态几乎完全一致（仅 #62 从 0.968→1.000），
但截图像素差异 11%（集中在左侧下半身区域）。两种解释：
  ① 时序：两张截图落在 idle 呼吸循环的不同相位
  ② 稳定差异：某个渲染环节不同（physics / 遮罩）

做法：同一动作下，两站点各连拍 5 帧，两两比较：
  - 站内 5 帧互相差多少（= 呼吸抖动本底）
  - 站间对应帧差多少
若站间差 ≈ 站内本底 → 只是时序；若站间差 >> 本底 → 稳定差异。

用法: py -3 scripts/diag/ab_multiframe.py ougen_8 idle
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
from PIL import Image, ImageChops, ImageStat  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
CLIP = sys.argv[2] if len(sys.argv) > 2 else 'idle'
OUT = os.path.join(ROOT, '.diag', 'multiframe')
os.makedirs(OUT, exist_ok=True)

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9370),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9371)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookMF) return; proto.__dshHookMF=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel) window.__l2model=c; }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""


def crop(p):
    im = Image.open(p).convert('RGB')
    w, h = im.size
    return im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))


def dmean(a, b):
    w = min(a.size[0], b.size[0]); h = min(a.size[1], b.size[1])
    d = ImageChops.difference(a.crop((0, 0, w, h)), b.crop((0, 0, w, h))).convert('L')
    return ImageStat.Stat(d).mean[0]


def run(tag, url, port):
    pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_mf%d' % port), url, (1400, 1000))
    shots = []
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': url})
        time.sleep(4)
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
        time.sleep(10)
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value=%s; if(window.__l2play) window.__l2play(%s); return 1;})()"""
             % (json.dumps(CLIP), json.dumps(CLIP)))
        time.sleep(6)
        for i in range(5):
            p = os.path.join(OUT, '%s_%s_f%d.png' % (CLIP, tag, i))
            pg.shot(p)
            shots.append(p)
            time.sleep(1.5)
        return shots
    finally:
        pg.close()


def main():
    for tag, url, _ in SITES:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                if r.status != 200:
                    print('[INVALID] %s' % tag); return 2
        except Exception as e:  # noqa: BLE001
            print('[INVALID] %s: %s' % (tag, e)); return 2

    o = run(*SITES[0])
    n = run(*SITES[1])
    io_ = [crop(p) for p in o]
    inn = [crop(p) for p in n]

    intra_o = [dmean(io_[0], x) for x in io_[1:]]
    intra_n = [dmean(inn[0], x) for x in inn[1:]]
    inter = [dmean(io_[i], inn[i]) for i in range(5)]

    print('\n=== 站内 5 帧互相差异（= 呼吸抖动本底）===')
    print('  旧站内 : %s  均值 %.2f' % ([round(x, 2) for x in intra_o], sum(intra_o) / len(intra_o)))
    print('  新站内 : %s  均值 %.2f' % ([round(x, 2) for x in intra_n], sum(intra_n) / len(intra_n)))
    print('\n=== 站间对应帧差异 ===')
    print('  %s  均值 %.2f' % ([round(x, 2) for x in inter], sum(inter) / len(inter)))

    base = max(sum(intra_o) / len(intra_o), sum(intra_n) / len(intra_n), 0.5)
    mid = sum(inter) / len(inter)
    print('\n=== 判读 ===')
    print('  站内本底 %.2f ；站间 %.2f ；倍数 %.1fx' % (base, mid, mid / base))
    if mid <= base * 2.0:
        print('  → 站间差与呼吸本底同量级：差异来自时序，不是稳定渲染差异')
    else:
        print('  → 站间差显著大于本底：存在稳定差异')
    return 0


if __name__ == '__main__':
    sys.exit(main())