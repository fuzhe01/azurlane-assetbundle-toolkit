# -*- coding: utf-8 -*-
"""2x2 对照取证：页面（原项目 / fork）× 数据（原项目 / EMIT_CONST / fork）。

四个站点：
  8791  原页面 + 原数据(EMIT_CONST=0)
  8792  原页面 + EMIT_CONST=1 数据
  8793  fork页面 + 原数据
  8778  fork页面 + fork数据

判据：手部参数值 + vis 可见件数 + 截图。数值只做锚点，最终以用户目视为准。

用法: py -3 scripts/diag/quad_frame_probe.py [model] [group]
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

OUT = os.path.join(ROOT, '.diag', 'quad')
os.makedirs(OUT, exist_ok=True)

SITES = [
    ('A 原页面+原数据  ', 8791, False),
    ('B 原页面+EMITCONST', 8792, False),
    ('C fork页面+原数据 ', 8793, True),
    ('D fork页面+fork数据', 8778, True),
]

HOOK = r"""
(function(){
  var t=0;
  function pat(){
    if(!(window.PIXI && window.PIXI.Container)){ if(t++<800) setTimeout(pat,20); return; }
    var pr=window.PIXI.Container.prototype;
    if(pr.__qh) return; pr.__qh=true; var o=pr.addChild;
    pr.addChild=function(){
      for(var i=0;i<arguments.length;i++){ var c=arguments[i];
        try{ if(c&&c.internalModel&&c.internalModel.coreModel) window.__m=c; }catch(e){} }
      return o.apply(this,arguments); };
  }
  pat();
})()
"""

DUMP = r"""
(function(){
  var m=window.__m; if(!m) return JSON.stringify({err:'NO_MODEL'});
  var core=m.internalModel.coreModel;
  var H=["Beimian_Hand_A","Beimian_Hand_A2","Beimian_Hand_B","Beimian_Hand_B2",
         "Zhengmian_Hand_A","Zhengmian_Hand_A2","Zhengmian_Hand_B","Zhengmian_Hand_B2"];
  var pv={};
  for(var i=0;i<H.length;i++){
    try{ var ix=core.getParameterIndex(H[i]); pv[H[i]]= ix>=0 ? +core.getParameterValueByIndex(ix).toFixed(1) : 'NP'; }
    catch(e){ pv[H[i]]='E'; }
  }
  var n=core.getDrawableCount(), v=0;
  for(var j=0;j<n;j++){ try{ if(core.getDrawableDynamicFlagIsVisible(j)) v++; }catch(e){} }
  var g=''; try{ g=m.internalModel.motionManager.state.currentGroup||''; }catch(e){}
  return JSON.stringify({g:g, pv:pv, n:n, vis:v});
})()
"""


def open_site(port, use_shortcut, model, prof):
    url = 'http://127.0.0.1:%d/gallery_v2/index.html' % port
    if use_shortcut:
        url += '?ship=' + model
    pg = Page(port + 900, os.path.join(ROOT, '.diag', prof), url, (1400, 1000))
    pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
    pg.cmd('Network.enable')
    pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
    pg.cmd('Page.navigate', {'url': url})
    if not use_shortcut:
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')){b.click();return 1;} return 0;})()""")
        time.sleep(0.8)
        pg.ev("(function(){var c=document.querySelector('.card'); if(c) c.click(); return 1;})()")
        time.sleep(2)
        pg.ev("(function(){var d=document.querySelector('#mSkins .skin'); if(d) d.click(); return 1;})()")
        time.sleep(1.5)
        pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab'))
           .find(function(e){return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
    for _ in range(40):
        time.sleep(1)
        if pg.ev('window.__m?1:0') == 1:
            return pg, True
    return pg, False


def play(pg, group):
    return pg.ev("""(function(){
      if(window.__l2play){ window.__l2play(__G__); return 'PLAYED'; }
      var s=document.getElementById('l2Motion');
      if(!s) return 'NO_SEL';
      if(![].slice.call(s.options).some(function(o){return o.value===__G__;})) return 'NO_GROUP';
      s.value=__G__; s.dispatchEvent(new Event('change')); return 'CHANGED';})()"""
                  .replace('__G__', json.dumps(group)))


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
    groups = sys.argv[2:] or ['idle']
    for tag, port, shortcut in SITES:
        prof = 'chrome_q%d' % port
        try:
            pg, ok = open_site(port, shortcut, model, prof)
        except Exception as e:  # noqa: BLE001
            print('%s [%d] 打开失败: %s' % (tag, port, e))
            continue
        try:
            if not ok:
                print('%s [%d] 模型未就绪' % (tag, port))
                continue
            for g in groups:
                st = play(pg, g)
                time.sleep(2.4)
                d = pg.ev(DUMP)
                try:
                    j = json.loads(d)
                except Exception:  # noqa: BLE001
                    j = {'err': str(d)[:80]}
                if 'err' in j:
                    print('%s [%d] %-14s play=%s %s' % (tag, port, g, st, j['err']))
                else:
                    pv = ' '.join('%s=%s' % (k.replace('Hand', 'H'), v) for k, v in sorted(j['pv'].items()))
                    print('%s [%d] %-14s g=%-13s vis=%3d  %s' % (tag, port, g, j['g'], j['vis'], pv))
                pg.shot(os.path.join(OUT, '%s_%s_%d.png' % (model, g, port)))
        finally:
            pg.close()
    print('\n截图: %s' % OUT)


if __name__ == '__main__':
    main()
