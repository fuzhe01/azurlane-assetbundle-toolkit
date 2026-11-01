# -*- coding: utf-8 -*-
"""缺陷①定性：同一动作下，本仓库页面 vs 旧画廊独立页面，逐 drawable 比「是否曾经可见」。

背景（docs/TROUBLESHOOTING.md §146 / §144B）：
  用户目视 ougen_8 的左脚、部分左腿、右手手掌在很多动作里消失（mail 最明显）。
  §144B 曾把这类现象定性为「模型源包自身特性、非本仓库回归」，依据是旧画廊与本仓库
  841/842 drawable 一致 —— 但那一次比的是**静态首帧**，不是「整个动作过程中是否会消失」。

本脚本换判据：整个动作播放期间**逐帧**采样每个 drawable 的不透明度，
按 drawable 记 `max(op)`。判据落在「这个部件在这段动作里有没有出现过」，
与帧率、相位无关（这是为了绕开无头环境 fps≈3 导致的对齐失真）。

结论解读：
  · 两侧 max 都≈0      → 该动作里本来就不需要这个部件（未穿着换装层，正常）
  · 旧侧 >0 而新侧≈0   → **本仓库回归**，可修
  · 新侧 >0 而旧侧≈0   → 本仓库反而更好
  · 两侧都曾 >0        → 只是**时段性**消失（曲线的开合），旧画廊同样如此

用法: py -3 scripts/diag/verify_part_vanish_src.py ougen_8 mail
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

ARGV = [x for x in sys.argv[1:] if not x.startswith('--')]
KEY = ARGV[0] if ARGV else 'ougen_8'
CLIP = ARGV[1] if len(ARGV) > 1 else 'mail'
SECS = 26.0
SAMPLE_EVERY = 0.25

OLD_PAGE = ('http://127.0.0.1:8777/gallery_v2/_old_l2d_visual.html'
            '?m=../Live2D/%s/%s.model3.json&clip=%s&idx=0')
NEW_PAGE = 'http://127.0.0.1:8777/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__pvHook) return; proto.__pvHook=true;
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

DUMP = r"""
(function(){
  var m=window.__l2model || (window.__AB && window.__AB.model) || null;
  if(!m) return JSON.stringify({err:'NO_MODEL'});
  var core=m.internalModel.coreModel;
  var n=0; try{ n=core.getDrawableCount(); }catch(e){ return JSON.stringify({err:String(e)}); }
  var ops=[];
  for(var i=0;i<n;i++){
    var v=null; try{ v=+core.getDrawableOpacity(i).toFixed(3); }catch(e){}
    ops.push(v);
  }
  return JSON.stringify({n:n, ops:ops});
})()
"""


def sample_loop(pg, secs, every):
    """返回 (n, maxOps[])。max 取整个播放期的逐帧最大值。"""
    n, mx = 0, None
    errs = []
    t0 = time.time()
    while time.time() - t0 < secs:
        d = pg.ev(DUMP)
        if not (d and d.startswith('{')):
            errs.append(str(d)[:80])
            time.sleep(every)
            continue
        o = json.loads(d)
        if 'err' in o:
            errs.append(o['err'])
            time.sleep(every)
            continue
        n = o['n']
        if mx is None:
            mx = [0.0] * n
        for i, v in enumerate(o['ops']):
            if v is not None and v > mx[i]:
                mx[i] = v
        time.sleep(every)
    if mx is None:
        return None, None, (errs[0] if errs else 'NO_SAMPLE')
    return n, mx, None


def run_old():
    url = OLD_PAGE % (KEY, KEY, CLIP)
    pg = Page(9340, os.path.join(ROOT, '.diag', 'chrome_pvold'), url, (1000, 1000))
    try:
        for _ in range(25):
            time.sleep(2)
            if pg.ev("window.__AB && window.__AB.ready"):
                break
        err = pg.ev("window.__AB && window.__AB.err")
        grp = pg.ev("window.__AB && window.__AB.group")
        print('  [old] ready group=%s err=%s' % (grp, err))
        pg.ev("window.__l2model = window.__AB.model")
        pg.ev("window.__AB.play(%s)" % json.dumps(CLIP))
        return sample_loop(pg, SECS, SAMPLE_EVERY)
    finally:
        pg.close()


def run_new():
    pg = Page(9341, os.path.join(ROOT, '.diag', 'chrome_pvnew'), NEW_PAGE, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': NEW_PAGE})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        print('  [new] 卡片:', pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[].slice.call(document.querySelectorAll('.card')).find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK';})()
        """ % json.dumps(KEY)))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[].slice.call(document.querySelectorAll('#mSkins .skin')).find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab')).find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(10)
        if pg.ev("window.__l2model?1:0") != 1:
            return None, None, 'NO_MODEL'
        print('  [new] play:', pg.ev("""(function(){var s=document.getElementById('l2Motion');
           if(!s) return 'NO_SEL';
           if(![].slice.call(s.options).some(function(o){return o.value===%s;})) return 'NO_GROUP';
           s.value=%s; window.__l2play(%s); return 'PLAYED';})()"""
                                   % (json.dumps(CLIP), json.dumps(CLIP), json.dumps(CLIP))))
        return sample_loop(pg, SECS, SAMPLE_EVERY)
    finally:
        pg.close()


def main():
    print('缺陷①定性：%s / %s，逐帧取每个 drawable 的最大不透明度' % (KEY, CLIP))
    no, mo, eo = run_old()
    nn, mn, en = run_new()
    if eo or en:
        print('\n[INVALID] 取数失败 old=%s new=%s' % (eo, en))
        return 2
    if no != nn:
        print('\n[INVALID] drawable 数不一致 old=%s new=%s' % (no, nn))
        return 2

    only_old, only_new, both, neither = [], [], 0, 0
    for i in range(no):
        a, b = mo[i], mn[i]
        if a >= 0.02 and b < 0.02:
            only_old.append((i, a, b))
        elif b >= 0.02 and a < 0.02:
            only_new.append((i, a, b))
        elif a >= 0.02 and b >= 0.02:
            both += 1
        else:
            neither += 1

    print('\n=== 全动作期间「曾经可见」分类（共 %d 件）===' % no)
    print('  两侧都曾可见（时段性开合，非回归）: %d' % both)
    print('  两侧全程不可见（动作不需要）      : %d' % neither)
    print('  **只有旧侧可见 → 本仓库回归**     : %d' % len(only_old))
    print('  只有新侧可见（本仓库更好）        : %d' % len(only_new))
    if only_old:
        print('\n  回归明细（drawable#, 旧max, 新max）:')
        for x in only_old[:25]:
            print('    %-5d 旧 %.3f  新 %.3f' % x)
    if only_new:
        print('\n  新侧独有明细（drawable#, 旧max, 新max）:')
        for x in only_new[:25]:
            print('    %-5d 旧 %.3f  新 %.3f' % x)
    return 1 if only_old else 0


if __name__ == '__main__':
    sys.exit(main())
