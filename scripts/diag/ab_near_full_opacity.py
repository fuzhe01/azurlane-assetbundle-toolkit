"""追查可见 drawable 差 1 个（旧 313 / 新 312）与 #62 opacity 0.968→1.000。

已排除：资产逐字节相同、idle 参数 0 差异、缩放/位置/ppu 相同、多帧差异≈呼吸本底。
剩一个真实差异：可见 drawable 数差 1，且 #62 的 opacity 在新版是 1.000、旧版 0.968。

本脚本在同一动作下，把「可见性判定阈值」放宽到 0.9，列出所有 opacity ∈ (0.9,1.0]
的 drawable，看差异究竟在哪几个，并读它们的顶点位置（判断在身体哪个部位）。

用法: py -3 scripts/diag/ab_near_full_opacity.py ougen_8 idle
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

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
CLIP = sys.argv[2] if len(sys.argv) > 2 else 'idle'

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9400),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9401)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookNFO) return; proto.__dshHookNFO=true;
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

# 统计阈值分布：多少 drawable 落在各 opacity 区间
BUCKET = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, n=core.getDrawableCount();
  var buckets={zero:0,low:0,mid:0,high:0,full:0};
  var nearFull=[], lowOnes=[];
  for(var i=0;i<n;i++){
    var op=null; try{ op=core.getDrawableOpacity(i); }catch(e){ continue; }
    if(op<0.001) buckets.zero++;
    else if(op<0.5) { buckets.low++; lowOnes.push([i,+op.toFixed(3)]); }
    else if(op<0.95) buckets.mid++;
    else if(op<0.9999) { buckets.high++; nearFull.push([i,+op.toFixed(3)]); }
    else buckets.full++;
  }
  return JSON.stringify({n:n, buckets:buckets, nearFull:nearFull, lowOnes:lowOnes.slice(0,20)});
})()
"""


def run(tag, url, port):
    pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_nfo%d' % port), url, (1400, 1000))
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
        return json.loads(pg.ev(BUCKET))
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
    if 'err' in o or 'err' in n:
        print('[INVALID]', o.get('err'), n.get('err')); return 2

    print('%-6s %-10s %-10s' % ('区间', '旧', '新'))
    for k in ('zero', 'low', 'mid', 'high', 'full'):
        print('%-6s %-10d %-10d' % (k, o['buckets'][k], n['buckets'][k]))

    om = dict((x[0], x[1]) for x in o.get('nearFull', []))
    nm = dict((x[0], x[1]) for x in n.get('nearFull', []))
    print('\n=== 接近全不透明（0.95~1.0）的 drawable ===')
    print('  旧 %d 个 / 新 %d 个' % (len(om), len(nm)))
    diff = [(i, om.get(i), nm.get(i)) for i in sorted(set(om) | set(nm))
            if abs((om.get(i) or 0) - (nm.get(i) or 0)) > 0.005]
    print('  其中数值不同: %d' % len(diff))
    for x in diff[:20]:
        print('    #%-5d 旧 %-8s 新 %-8s' % (x[0], x[1], x[2]))
    return 0


if __name__ == '__main__':
    sys.exit(main())