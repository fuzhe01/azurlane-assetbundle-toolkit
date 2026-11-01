"""排查「部件在某动作中消失」：逐 drawable 读不透明度与可见性。

用户目视发现 ougen_8 大量动作里左脚/左腿缺失、右手偶尔消失（mail 中长时间消失、
idle9 中左脚掌消失、idle 中左脚+部分左腿缺失）。

Live2D 里一个部件「看不见」只有几种可能，本脚本逐条量化：
  1. 该 drawable 的 multiplyColor / screenColor 被设为全黑/全白（补丁 shader 的经典症状）
  2. 该 drawable 的 opacity（PartOpacity）被动作曲线写成 0
  3. 该 drawable 的顶点被移到画布外
  4. 该 drawable 根本没被渲染（渲染顺序/遮罩问题）

做法：直接对多个动作截图，再用 **drawable 级**数据核对（HITAREAS 不够，
用户说的是部件本身）。若拿不到 drawable 数据，就先给出「哪些动作复现」的清单。

用法: py -3 .diag/probe_part_vanish.py [key] [clips...]
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
CLIPS = sys.argv[2:] or ['idle', 'idle9', 'mail']
PORT = 9300
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'part_vanish')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookPV) return; proto.__dshHookPV=true;
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

# 逐 drawable 取不透明度 + 顶点包围盒（判断是否移出画布）
DRAWABLE_DUMP = r"""
(function(){
  var m=window.__l2model; if(!m) return JSON.stringify({err:'NO_MODEL'});
  var core=m.internalModel.coreModel;
  var n=0; try{ n=core.getDrawableCount(); }catch(e){ return JSON.stringify({err:String(e)}); }
  var out=[];
  for(var i=0;i<n;i++){
    var rec={i:i};
    try{ rec.op = core.getDrawableOpacity(i); }catch(e){}
    try{ rec.mc = core.getDrawableMultiplyColor(i); }catch(e){}
    try{ rec.sc = core.getDrawableScreenColor(i); }catch(e){}
    try{
      var v=core.getDrawableVertexPositions(i);
      if(v && v.length>=2){
        var xs=[], ys=[];
        for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
        rec.bbox=[Math.min.apply(null,xs), Math.min.apply(null,ys),
                  Math.max.apply(null,xs), Math.max.apply(null,ys)];
      }
    }catch(e){}
    try{ rec.id = core.getDrawableIndex && null; }catch(e){}
    out.push(rec);
  }
  return JSON.stringify({n:n, d:out});
})()
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_pv'), URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
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
        time.sleep(9)

        print('模型:', pg.ev("typeof window.__l2model"))
        base = None
        for clip in CLIPS:
            r = pg.ev("""(function(){var s=document.getElementById('l2Motion');
                       if(!s) return 'NO_SEL';
                       if(![...s.options].some(function(o){return o.value===%s;})) return 'NO_GROUP';
                       s.value=%s;
                       if(window.__l2play) { window.__l2play(%s); return 'HOOK'; }
                       return 'NO_HOOK';})()""" % (json.dumps(clip), json.dumps(clip), json.dumps(clip)))
            time.sleep(5)
            dump = pg.ev(DRAWABLE_DUMP)
            shot = os.path.join(OUT, '%s_%s.png' % (KEY, clip))
            pg.shot(shot)
            try:
                d = json.loads(dump)
                if 'err' in d:
                    print('%-8s %s' % (clip, d)); continue
                ds = d['d']
                zero_op = [x['i'] for x in ds if x.get('op') is not None and x['op'] < 0.02]
                black_mc = [x['i'] for x in ds if isinstance(x.get('mc'), (list, tuple))
                            and len(x['mc']) >= 3 and max(x['mc'][:3]) < 0.02]
                off = []
                for x in ds:
                    b = x.get('bbox')
                    if b and (b[2] < -200 or b[0] > 4000 or b[3] < -200 or b[1] > 4000):
                        off.append(x['i'])
                print('%-8s play=%-8s drawables=%-4d 透明度≈0:%-3d 乘色全黑:%-3d 移出画面:%-3d -> %s'
                      % (clip, r, d['n'], len(zero_op), len(black_mc), len(off), os.path.basename(shot)))
                if zero_op[:8]:
                    print('         透明度0 的 drawable: %s' % zero_op[:12])
                if black_mc[:8]:
                    print('         乘色全黑的 drawable: %s' % black_mc[:12])
                if base is None:
                    base = {x['i']: x.get('op') for x in ds}
            except Exception as e:  # noqa: BLE001
                print('%-8s 解析失败: %s / %s' % (clip, e, str(dump)[:120]))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())