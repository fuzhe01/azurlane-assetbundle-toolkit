# -*- coding: utf-8 -*-
"""右手/左脚消失：新旧画廊逐 drawable 对账（按 Id 对齐，同时采 opacity 与 vis）。

★ 为什么不能只比 opacity（上一轮的教训，§144 B / §137 新发现 1）：
  §137 已实证 op=1 却 vis=0 的件真实存在（ArtMesh255~258），
  只比 opacity 会把「渲染可见性差异」整类漏掉。

★ 为什么必须按 Id 对齐（cmp_drawable_opacity.py 的 docstring）：
  两套页面不保证同一 drawable 下标顺序，按下标比就是在比两个不同的东西。

用法:
  py -3 scripts/diag/ab_right_hand_diff.py ougen_8 idle
  py -3 scripts/diag/ab_right_hand_diff.py ougen_8 touch_idle14
  py -3 scripts/diag/ab_right_hand_diff.py --list          # 只看两边能不能打开
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

OUT = os.path.join(ROOT, '.diag', 'ab_hand')
os.makedirs(OUT, exist_ok=True)

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9320),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9321)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookHand) return; proto.__dshHookHand=true;
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

# op / vis / ro 全采；vis 用箭头函数转调，避免解构丢 this（§137 handdebug bug 1）
DUMP = r"""
(function(){
  var m=window.__l2model; if(!m) return JSON.stringify({err:'NO_MODEL'});
  var core=m.internalModel.coreModel; if(!core) return JSON.stringify({err:'NO_CORE'});
  var n=0; try{ n=core.getDrawableCount(); }catch(e){ return JSON.stringify({err:String(e)}); }
  var op=[],vis=[],ro=[],ids=[];
  for(var i=0;i<n;i++){
    var s='#'+i; try{ s=core.getDrawableId(i)||s; }catch(e){}
    ids.push(s);
    try{ op.push(+core.getDrawableOpacity(i).toFixed(3)); }catch(e){ op.push(null); }
    try{ vis.push(core.getDrawableDynamicFlagIsVisible(i)?1:0); }catch(e){ vis.push(null); }
    try{ ro.push(core.getDrawableRenderOrder(i)); }catch(e){ ro.push(null); }
  }
  var g=''; try{ g=m.internalModel.motionManager.state.currentGroup||''; }catch(e){}
  return JSON.stringify({n:n,g:g,ids:ids,op:op,vis:vis,ro:ro});
})()
"""

CLICK_SHIP = r"""
(function(){var s=(window.GALLERY.ships||[]).find(function(x){
   return (x.skins||[]).some(function(k){return k.key===__K__;});});
  if(!s) return 'NO_SHIP';
  var c=[].slice.call(document.querySelectorAll('.card')).find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD';
  c.click(); return 'OK';})()
"""


def ready(pg):
    for _ in range(60):
        time.sleep(1)
        if pg.ev("window.__l2model?1:0") == 1:
            return True
    return False


def open_model(pg, url, key, clip):
    """优先用 ?ship=&motion=（新版有）；没有就走卡片→皮肤→Live2D 标签。"""
    step = {}
    if '?' not in url:
        pass
    pg.cmd('Page.navigate', {'url': url})
    time.sleep(3)
    # 关掉可能的开场 login
    step['login'] = pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
       if(b&&(b.classList.contains('on')||b.dataset.on==='1')){b.click();return 'OFF';} return 'NA';})()""")
    time.sleep(0.8)
    step['card'] = pg.ev(CLICK_SHIP.replace('__K__', json.dumps(key)))
    time.sleep(1.8)
    step['skin'] = pg.ev("""(function(){var d=[].slice.call(document.querySelectorAll('#mSkins .skin'))
       .find(function(e){return e.dataset.k===__K__;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                         .replace('__K__', json.dumps(key)))
    time.sleep(1.5)
    step['tab'] = pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab'))
       .find(function(e){return e.dataset.k==='live2d';});
       if(!t) return 'NO_TAB'; if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()""")
    ok = ready(pg)
    step['ready'] = ok
    if not ok:
        return step, None
    if clip:
        step['play'] = pg.ev("""(function(){var s=document.getElementById('l2Motion');
           if(!s) return 'NO_SEL';
           if(![].slice.call(s.options).some(function(o){return o.value===__G__;})) return 'NO_GROUP';
           if(window.__l2play){ window.__l2play(__G__); return 'PLAYED'; }
           s.value=__G__; s.dispatchEvent(new Event('change')); return 'CHANGED';})()"""
                              .replace('__G__', json.dumps(clip)))
    return step, pg.ev(DUMP)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    key = args[0] if args else 'ougen_8'
    clip = args[1] if len(args) > 1 else 'idle'

    for tag, url, _ in SITES:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                if r.status != 200:
                    print('[INVALID] %s HTTP %s' % (tag, r.status)); return 2
        except Exception as e:  # noqa: BLE001
            print('[INVALID] %s 不可达: %s' % (tag, e)); return 2

    res = {}
    for tag, url, port in SITES:
        pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_hand%d' % port), url, (1400, 1000))
        try:
            pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
            pg.cmd('Network.enable')
            pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
            step, d = open_model(pg, url, key, clip)
            print('  [%s] 步骤 %s' % (tag, step))
            time.sleep(6)
            pg.shot(os.path.join(OUT, '%s_%s_%s.png' % (clip, key, tag)))
            d = pg.ev(DUMP) or d
            res[tag] = json.loads(d) if d and d.strip().startswith('{') else {'err': str(d)[:200]}
        except Exception as e:  # noqa: BLE001
            res[tag] = {'err': '%s: %s' % (type(e).__name__, str(e)[:200])}
        finally:
            pg.close()

    o, n = res.get('old', {}), res.get('new', {})
    for t in ('old', 'new'):
        r = res[t]
        if 'err' in r:
            print('\n[INVALID] %s 取不到数据: %s' % (t, r['err']))
            return 2
        print('  %s: n=%d group=%r' % (t, r['n'], r.get('g')))

    oi, ni = o['ids'], n['ids']
    if oi != ni:
        print('\n[注意] drawable Id 序列不一一对应：old %d / new %d' % (len(oi), len(ni)))
        print('  转为按 Id 名字对齐\n')
    oidx = {v: i for i, v in enumerate(oi)}
    nidx = {v: i for i, v in enumerate(ni)}
    common = [v for v in oi if v in nidx]

    print('=== %s / %s 按 Id 对齐对账（共同 %d 件）===' % (key, clip, len(common)))
    op_gap, vis_gap, both = [], [], 0
    for name in common:
        a, b = oidx[name], nidx[name]
        oo, no = o['op'][a], n['op'][b]
        ov, nv = o['vis'][a], n['vis'][b]
        if oo is None or no is None:
            continue
        dop = abs(no - oo)
        if ov != nv or dop > 0.02:
            both += 1
            rec = (name, oo, no, ov, nv, o['ro'][a], n['ro'][b])
            if ov != nv:
                vis_gap.append(rec)
            if dop > 0.02:
                op_gap.append(rec)

    print('  完全一致          : %d' % (len(common) - both))
    print('  vis 不同          : %d' % len(vis_gap))
    print('  opacity 差 >0.02  : %d' % len(op_gap))
    for label, lst in (('vis 不同', vis_gap), ('op 差', op_gap)):
        if lst:
            print('\n  --- %s 明细（Id, 旧op, 新op, 旧vis, 新vis, 旧ro, 新ro）---' % label)
            for r in lst[:40]:
                print('    %-22s 旧op=%.3f 新op=%.3f  旧vis=%s 新vis=%s  ro %s->%s' % r)
    print('\n  截图: %s' % OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
