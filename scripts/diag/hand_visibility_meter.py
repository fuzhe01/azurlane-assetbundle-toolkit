# -*- coding: utf-8 -*-
"""量化「手部/脚部部件」在指定动作下的可见性，用于逐条修改的必要性评估。

判据（三条同时看，缺一即不可信）：
  1. 手部 8 个参数的实际渲染值（走 page 自己的 __l2play 与 coreModel.update 之后读）
  2. 手臂/手部 drawable 的 visible + opacity（不是只看个数）
  3. 画面肤色像素占比（真 GPU 上才有区分力，headless 单看状态会假绿）

⚠️ 不用 setParameterValueById 直接写参（会被 loadParameters 覆盖，量出假 0）。

用法:
  py -3 scripts/diag/hand_visibility_meter.py --port 8778 --groups complete,touch_body,mail
"""
import argparse
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

HOOK = r"""
(function(){
  var t=0;
  function pat(){
    if(!(window.PIXI && window.PIXI.Container)){ if(t++<800) setTimeout(pat,20); return; }
    var pr=window.PIXI.Container.prototype;
    if(pr.__hvm) return; pr.__hvm=true;
    var o=pr.addChild;
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
    try{ var ix=core.getParameterIndex(H[i]); pv[H[i]]= ix>=0 ? +core.getParameterValueByIndex(ix).toFixed(2) : 'NP'; }
    catch(e){ pv[H[i]]='E'; }
  }
  var n=core.getDrawableCount();
  var visSum=0, ids=[];
  for(var j=0;j<n;j++){
    try{ if(core.getDrawableDynamicFlagIsVisible(j)) visSum++; }catch(e){}
    try{ ids.push(core.getDrawableId(j)); }catch(e){ ids.push('#'+j); }
  }
  var g=''; try{ g=m.internalModel.motionManager.state.currentGroup||''; }catch(e){}
  return JSON.stringify({g:g, pv:pv, n:n, visSum:visSum});
})()
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8778)
    ap.add_argument('--model', default='ougen_8')
    ap.add_argument('--groups', default='idle,complete,touch_body,mail')
    ap.add_argument('--tag', default='')
    ap.add_argument('--shot-dir', default='')
    a = ap.parse_args()

    url = 'http://127.0.0.1:%d/gallery_v2/index.html?ship=%s' % (a.port, a.model)
    groups = [g for g in a.groups.split(',') if g]
    shot_dir = a.shot_dir or os.path.join(ROOT, '.diag', 'hand_meter')
    os.makedirs(shot_dir, exist_ok=True)

    pg = Page(a.port + 1500, os.path.join(ROOT, '.diag', 'chrome_hvm_%d' % a.port), url, (1400, 1000))
    rows = []
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': url})
        for _ in range(40):
            time.sleep(1)
            if pg.ev('window.__m?1:0') == 1:
                break
        else:
            print('[INVALID] 模型未就绪')
            return 2
        time.sleep(2)
        for g in groups:
            st = pg.ev("""(function(){
              if(window.__l2play){ window.__l2play(__G__); return 'PLAYED'; }
              var s=document.getElementById('l2Motion');
              if(!s) return 'NO_SEL'; s.value=__G__; s.dispatchEvent(new Event('change')); return 'CH';})()"""
                        .replace('__G__', json.dumps(g)))
            # 采两次：t+1.2s（动作中段）与 t+3.5s（越过常见最长 2-3s 段）
            pts = []
            for wait in (1.2, 2.3):
                time.sleep(wait)
                d = pg.ev(DUMP)
                try:
                    pts.append(json.loads(d))
                except Exception:  # noqa: BLE001
                    pts.append({'err': str(d)[:80]})
            if a.tag:
                pg.shot(os.path.join(shot_dir, '%s_%s_%s.png' % (a.tag, a.model, g)))
            rows.append((g, st, pts))
    finally:
        pg.close()

    print('=== %s 手部参数与可见件数（port %d%s）===' % (a.model, a.port, ' / ' + a.tag if a.tag else ''))
    for g, st, pts in rows:
        for k, d in enumerate(pts):
            if 'err' in d:
                print('  %-14s %s  t%s ERR %s' % (g, st, k + 1, d['err']))
                continue
            hand = [v for kk, v in d['pv'].items() if isinstance(v, (int, float))]
            nz = sum(1 for v in hand if abs(v) > 0.5)
            print('  %-14s %-8s g=%-14s vis=%3d  hand非零=%d/8  %s'
                  % (g, 't%d' % (k + 1), d['g'], d['visSum'], nz,
                     ' '.join('%s=%.1f' % (kk.replace('Hand', 'H'), v)
                              for kk, v in sorted(d['pv'].items()) if isinstance(v, (int, float)))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
