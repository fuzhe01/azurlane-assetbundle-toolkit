"""探查参数热区在「V 空间 → 屏幕坐标」的实际落点（诊断用，定位 __costumeScreenOf 返回 null 的原因）。

打印每一项：热区 V 空间包围盒、换算后的屏幕包围盒、视口尺寸、mdl.scale/x/y、命中网格统计。

用法: py -3 scripts/diag/probe_costume_hotzone_coords.py [模型key]
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

from cdp_helper import open_page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){var t=0;function p(){if(!(window.PIXI&&window.PIXI.Container)){if(t++<900)setTimeout(p,20);return;}
  var pr=window.PIXI.Container.prototype;if(pr.__hz)return;pr.__hz=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

INFO = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var im=m.internalModel, core=im.coreModel, ppu=im.pixelsPerUnit||1;
  var cux=im.width/ppu, cuy=im.height/ppu, s=m.scale.x;
  var wrap=document.getElementById('l2wrap'); var r=wrap.getBoundingClientRect();
  var bx=window.__costumeBoxes();
  function toS(vx,vy){ return [m.x+(vx+cux/2)*ppu*s, m.y+(cuy/2-vy)*ppu*s]; }
  var rows=bx.map(function(b){
    var g=b.box;
    var p0=toS(g.x0,g.y1), p1=toS(g.x1,g.y0);
    return {id:b.id, n:b.n, area:+b.area.toFixed(2), v:g,
            s:[+p0[0].toFixed(1),+p0[1].toFixed(1),+p1[0].toFixed(1),+p1[1].toFixed(1)]};
  });
  return JSON.stringify({ppu:ppu, cux:+cux.toFixed(2), cuy:+cuy.toFixed(2), scale:+s.toFixed(4),
    mdlx:+m.x.toFixed(1), mdly:+m.y.toFixed(1),
    wrap:{left:+r.left.toFixed(1), top:+r.top.toFixed(1), w:wrap.clientWidth, h:wrap.clientHeight},
    items:rows});
})()
"""


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2
    pg = open_page(BASE, tag='hzc')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Network.enable'); pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': BASE})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
              % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        for _ in range(40):
            time.sleep(1.0)
            if pg.ev("(window.__l2model && window.COSTUME && window.PARAM_DRAWABLES)?1:0") == 1:
                break
        print(pg.ev("""(function(){return (window.__l2model && window.__costumeBoxes)?'probe OK':'NO PROBE';})()"""))
        raw = pg.ev(INFO)
        d = json.loads(raw)
        print('ppu=%s cux=%s cuy=%s scale=%s mdl=(%s,%s) wrap=%s'
              % (d['ppu'], d['cux'], d['cuy'], d['scale'], d['mdlx'], d['mdly'], d['wrap']))
        for it in d['items']:
            s = it['s']
            print('%-16s n=%-3d area=%-7s screen=[%s,%s,%s,%s]  inView=%s'
                  % (it['id'], it['n'], it['area'], s[0], s[1], s[2], s[3],
                     (s[2] > 0 and s[0] < d['wrap']['w'] and s[3] > 0 and s[1] < d['wrap']['h'])))
        # 每个热区：网格扫描有多少点真的命中（走产品函数）
        for it in d['items']:
            n = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(it['id']))
            print('  screenOf %-16s -> %s' % (it['id'], n))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
