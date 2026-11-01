"""决定性实验：把 idle 模式下被 restTick 复位掉的参数，逐一设为「非默认值」看鞋是否出现。

背景（2026-10-24 查明的机制）：
  index.html 的 restTick 会把「被动作驱动过、当前待机不驱动」的参数
  **拉回 moc3 的 getParameterDefaultValue**。默认值 = 模型的「静止姿势」。
  如果该模型的默认值对应「脱鞋态」，那么任何一次点击后都会永久停成脱鞋态。

本脚本不猜参数，而是**穷举**：把每个「idle 里是默认值、而某个动作里被改成别的值」的参数
逐个试（批量），观察脚部区域是否出现鞋。

判据：截图里脚部区域的红色像素变化 + 与已知「穿鞋态」参照图的相关性。
为了快，先按「参数在 touc_drag*/mail 里变化、且 idle 里等于默认值」筛出候选。

用法: py -3 scripts/diag/find_shoe_switch_param.py ougen_8
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
from PIL import Image  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PORT = 9430
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'shoe_param')
os.makedirs(OUT, exist_ok=True)
MD = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSP) return; proto.__dshHookSP=true;
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


def curve_ends(clip):
    p = os.path.join(MD, clip + '.motion3.json')
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding='utf-8'))
    out = {}
    for c in d.get('Curves', []):
        s = c.get('Segments') or []
        if len(s) >= 2:
            out[c.get('Id')] = s[-1]
    return out


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


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    idle = curve_ends('idle')
    # 候选：在 touch_drag*/mail 里与 idle 不同的参数
    cand = set()
    for clip in ('mail', 'touch_drag1', 'touch_drag2', 'touch_drag3',
                 'touch_head', 'touch_body', 'touch_special'):
        for k, v in curve_ends(clip).items():
            if k in idle and abs(v - idle[k]) > 1.0:
                cand.add(k)
    cand = sorted(cand)
    print('候选参数（动作里与 idle 不同）: %d 个' % len(cand))
    print('  ', cand[:20])

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_sp%d' % PORT), URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key==='%s';});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % KEY)
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k==='%s';}); if(d) d.click(); return 1;})()""" % KEY)
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(11)

        base = os.path.join(OUT, 'base.png')
        pg.shot(base)
        print('\n基线红像素:', red_px(base))

        # 逐参数设置到动作里的值，看红像素是否明显变化
        print('\n=== 逐参数试验（只试前 24 个候选）===')
        results = []
        for pid in cand[:24]:
            val = None
            for clip in ('touch_drag3', 'mail', 'touch_drag1'):
                v = curve_ends(clip).get(pid)
                if v is not None:
                    val = v
                    break
            if val is None:
                continue
            ok = pg.ev("""
            (function(){
              var m=window.__l2model; if(!m) return 'NO_MODEL';
              var core=m.internalModel.coreModel;
              var i=core.getParameterIndex('%s');
              if(i<0) return 'NO_IDX';
              core.setParameterValueByIndex(i, %s);
              return 'SET:'+core.getParameterValueByIndex(i).toFixed(2);
            })()
            """ % (pid, val))
            time.sleep(1.2)
            p = os.path.join(OUT, '%s.png' % pid)
            pg.shot(p)
            rp = red_px(p)
            results.append((pid, val, rp))
            mark = ' <<<' if abs(rp - red_px(base)) > 300 else ''
            print('  %-16s -> %8.2f   红像素 %-6d%s' % (pid, val, rp, mark))

        print('\n=== 红像素变化最大的参数 ===')
        b = red_px(base)
        for pid, val, rp in sorted(results, key=lambda x: -abs(x[2] - b))[:8]:
            print('  %-16s 值 %8.2f  红像素 %-6d (基线 %d, 差 %+d)' % (pid, val, rp, b, rp - b))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())