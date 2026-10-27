"""在浏览器里逐个验证：哪个参数真的能让「红底高跟鞋」出现/消失。

用户目视证据：touchdrag17 位置有三态（无脚 / 黑丝左脚 / 红底高跟鞋）。
但 ShoseOff=0 与 =1 的画面**肉眼无差异**（已截图确认），说明它不是那个开关。

本脚本对每个候选参数，把它在 lo/hi 之间切换并**各截一张图**，
再用「脚部区域的红色像素数」量化（红底高跟鞋的鞋底是纯红，很好认）。
最后把差异最大的几张图单独存出来供目视。

用法: py -3 scripts/diag/find_real_shoe_switch.py ougen_8
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

import cdp_helper  # noqa: E402
from cdp_helper import open_page  # noqa: E402
from PIL import Image  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'real_shoe')
os.makedirs(OUT, exist_ok=True)

# 全部候选：来自 costume_params.json + 几何映射里动过脚的参数
CANDS = ['ShoseOff', 'Stock1', 'Stock2', 'Cloth1', 'Cloth2', 'Cloth3',
         'Paramring', 'NeckMoney']

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookRS) return; proto.__dshHookRS=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

SET = r"""
(function(){
  var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
  if(!pm[%s]) pm[%s]=Object.create(null);
  pm[%s][%s]=%s;
  var m=window.__l2model;
  return JSON.stringify({id:%s, val:%s,
    now:+m.internalModel.coreModel.getParameterValueById(%s).toFixed(3)});
})()
"""


def red_in_box(path):
    """统计「脚部区域」的红色像素数。
    脚在画面左下偏中：按整图比例裁一块，避免把背景的红色也算进来。"""
    im = Image.open(path).convert('RGB')
    w, h = im.size
    # 查看器区域 -> 左下 35%~75% 宽、55%~90% 高
    x0 = int(w * (0.42 + (0.99 - 0.42) * 0.10))
    x1 = int(w * (0.42 + (0.99 - 0.42) * 0.60))
    y0 = int(h * (0.10 + (0.92 - 0.10) * 0.45))
    y1 = int(h * (0.10 + (0.92 - 0.10) * 0.95))
    im = im.crop((x0, y0, x1, y1))
    px = im.load()
    W, H = im.size
    n = 0
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            r, g, b = px[x, y]
            if r > 100 and r - g > 55 and r - b > 55:
                n += 1
    return n


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = open_page(URL, tag='rs')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(13)

        print('模型:', pg.ev("typeof window.__l2model"))
        if pg.ev("typeof window.__l2model") != 'object':
            print('[INVALID] 未就绪'); return 2

        k = json.dumps(KEY)
        rows = []
        for pid in CANDS:
            for val, tag in ((0, 'lo'), (1, 'hi')):
                r = pg.ev(SET % (k, k, k, json.dumps(pid), val, json.dumps(pid), val, json.dumps(pid)))
                time.sleep(2.2)
                p = os.path.join(OUT, '%s_%s.png' % (pid, tag))
                pg.shot(p)
                rp = red_in_box(p)
                rows.append((pid, tag, val, rp))
                print('  %-12s %-3s val=%-3s 脚部红像素 %-5d' % (pid, tag, val, rp))

        print('\n=== 按参数汇总（hi - lo 的红像素差）===')
        by = {}
        for pid, tag, val, rp in rows:
            by.setdefault(pid, {})[tag] = rp
        diffs = []
        for pid, d in by.items():
            if 'lo' in d and 'hi' in d:
                diffs.append((pid, d['lo'], d['hi'], d['hi'] - d['lo']))
        for pid, lo, hi, df in sorted(diffs, key=lambda x: -abs(x[3])):
            mark = ' <<<' if abs(df) > 200 else ''
            print('  %-12s lo=%-5d hi=%-5d 差=%+d%s' % (pid, lo, hi, df, mark))
        print('\n判读：差值大的参数才是真正影响脚部外观的；<200 视为噪声')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())