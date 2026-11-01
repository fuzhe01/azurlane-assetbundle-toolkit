"""对照两站「刚打开、不主动播任何动作」时的默认画面。

前面的对比都是我主动播 idle 之后拍的。用户说的「旧画廊 idle 里能看到红底高跟鞋」
很可能是**刚打开页面时**的默认状态 —— 那是前端自己选的待机组（idleGroup 或就近组），
不一定是 idle。

本脚本：只打开页面、不播任何动作、等它自己稳定，然后拍照比对。
判据除了像素差，还统计「红色像素数」与「可见 drawable 数」。

用法: py -3 scripts/diag/ab_default_state.py ougen_8
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
OUT = os.path.join(ROOT, '.diag', 'default_state')
os.makedirs(OUT, exist_ok=True)

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9390),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9391)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookDS) return; proto.__dshHookDS=true;
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

CUR = r"""
(function(){var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var st=m.internalModel.motionManager.state||{};
  var e=document.getElementById('l2Curr');
  var core=m.internalModel.coreModel, vis=0;
  for(var i=0;i<core.getDrawableCount();i++){ try{ if(core.getDrawableOpacity(i)>0.02) vis++; }catch(e){} }
  return JSON.stringify({group: st.currentGroup===undefined?'<undef>':st.currentGroup,
                         label: e?e.textContent:null, visible: vis});})()
"""


def red_px(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    im = im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))
    px = im.load(); W, H = im.size; n = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]
            if r > 110 and r - g > 60 and r - b > 60:
                n += 1
    return n


def run(tag, url, port):
    pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_ds%d' % port), url, (1400, 1000))
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
        # 不播任何动作，等它自己稳定
        time.sleep(12)
        p = os.path.join(OUT, 'default_%s.png' % tag)
        pg.shot(p)
        info = pg.ev(CUR)
        return p, info
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

    res = {}
    for tag, url, port in SITES:
        p, info = run(tag, url, port)
        res[tag] = (p, json.loads(info) if info and info.startswith('{') else {'raw': info})
        print('%-4s %s  红像素 %d' % (tag, res[tag][1], red_px(p)))

    o = Image.open(res['old'][0]).convert('RGB')
    n = Image.open(res['new'][0]).convert('RGB')
    w = min(o.size[0], n.size[0]); h = min(o.size[1], n.size[1])
    box = (int(w * .42), int(h * .10), int(w * .99), int(h * .92))
    o = o.crop(box); n = n.crop(box)
    if o.size != n.size:
        n = n.resize(o.size)
    d = ImageChops.difference(o, n).convert('L')
    print('\n默认画面像素差异: 均值 %.2f' % ImageStat.Stat(d).mean[0])
    print('判读：若两边 group 相同且红像素接近，说明默认状态一致')
    return 0


if __name__ == '__main__':
    sys.exit(main())