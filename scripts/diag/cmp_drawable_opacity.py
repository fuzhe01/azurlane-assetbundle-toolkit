# -*- coding: utf-8 -*-
"""cmp_drawable_opacity.py — 按 drawable **名称**对齐，比较旧页面与本仓库页面的不透明度向量。

为什么必须按名称对齐：两套运行时（Cubism2 的旧页面 / Cubism4 的本仓库）不一定用同一个
drawable 下标顺序。直接比 `opacity[256]` 可能是在比两个不同的东西——本项目已踩过一次，
把「旧页面下标 256 恰好可见」误判成本仓库回归。

为什么必须重复 N 次：同一页面同一 URL 连跑多次，同一 drawable 的不透明度会在 0 与 1 之间
双峰摆动（实测 1/6、3/5）。**单次运行的结论不成立**，必须做重复性检验并报「可见次数/N」。

用法:
  py -3 scripts/diag/cmp_drawable_opacity.py old  [--n=6] [--clip=mail] [--key=ougen_8]
  py -3 scripts/diag/cmp_drawable_opacity.py new  [--n=6] [--clip=mail] [--key=ougen_8]
  py -3 scripts/diag/cmp_drawable_opacity.py both [--n=6]

输出：每个选项的「可见次数/N」，以及两边的名称集合差异。
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

ARGV = [a for a in sys.argv[1:] if not a.startswith('--')]
MODE = ARGV[0] if ARGV else 'both'
N = 6
CLIP = 'mail'
KEY = 'ougen_8'
PEEK = 4.0
for a in sys.argv[1:]:
    if a.startswith('--n='):
        N = int(a.split('=', 1)[1])
    elif a.startswith('--clip='):
        CLIP = a.split('=', 1)[1]
    elif a.startswith('--key='):
        KEY = a.split('=', 1)[1]
    elif a.startswith('--peek='):
        PEEK = float(a.split('=', 1)[1])

OLD_URL = ('http://127.0.0.1:8778/gallery_v2/_old_l2d_visual.html'
           '?m=../Live2D/%s/%s.model3.json&clip=%s&idx=0') % (KEY, KEY, CLIP)
NEW_URL = 'http://127.0.0.1:8777/gallery_v2/index.html'

# 关键点：两套运行时的 core 都挂在 internalModel.coreModel 上，但 Cubism2 版本
# 没有 `.coreModel` 这一层（直接就是实例）。两种都要兼容，否则 DUMP 恒 err。
DUMP = r"""
(function(){
  var A=window.__AB||{};
  var m=A.model||window.__l2model||null;
  if(!m) return JSON.stringify({err:'NO_MODEL'});
  var im=m.internalModel||m;
  var core=(im.coreModel&&im.coreModel.coreModel)||im.coreModel||m.coreModel;
  if(!core||!core.getDrawableCount) return JSON.stringify({err:'NO_CORE'});
  var n=core.getDrawableCount(), ops=[], ids=[];
  for(var i=0;i<n;i++){
    var v=0; try{ v=+core.getDrawableOpacity(i).toFixed(3); }catch(e){}
    ops.push(v);
    var s='#'+i; try{ s=core.getDrawableId(i)||s; }catch(e){}
    ids.push(s);
  }
  var g=''; try{ g=im.motionManager.state.currentGroup||''; }catch(e){}
  return JSON.stringify({n:n, g:g, ids:ids, ops:ops});
})()
"""

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__cmpHook) return; proto.__cmpHook=true;
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

CLICK_SHIP = r"""
(function(){var s=(window.GALLERY.ships||[]).find(function(x){
   return (x.skins||[]).some(function(k){return k.key===%s;});});
  if(!s) return 'NO_SHIP';
  var c=[].slice.call(document.querySelectorAll('.card')).find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(c) c.click(); return 'OK';})()
"""


def ready_old(pg):
    for _ in range(50):
        time.sleep(1)
        if pg.ev("!!(window.__AB&&window.__AB.model)"):
            return True
    return False


def ready_new(pg):
    for _ in range(50):
        time.sleep(1)
        if pg.ev("window.__l2model?1:0") == 1:
            return True
    return False


def play_old(pg):
    pg.ev("window.__AB.play(%s)" % json.dumps(CLIP))


def play_new(pg, pgclicked):
    if not pgclicked:
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        r = pg.ev(CLICK_SHIP % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[].slice.call(document.querySelectorAll('#mSkins .skin')).find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab')).find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(10)
        return r
    return 'REUSED'


def run_once(which, idx):
    if which == 'old':
        url, port = OLD_URL, 9470 + idx
        prof = os.path.join(ROOT, '.diag', 'chrome_cmpold%d' % idx)
    else:
        url, port = NEW_URL, 9480 + idx
        prof = os.path.join(ROOT, '.diag', 'chrome_cmpnew%d' % idx)
    pg = Page(port, prof, url, (1300, 1000))
    rec = {'which': which, 'run': idx, 'ok': False}
    try:
        if which == 'old':
            if not ready_old(pg):
                rec['err'] = 'NOT_READY'; return rec
            play_old(pg)
        else:
            pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
            pg.cmd('Page.navigate', {'url': url})
            time.sleep(4)
            print('    点卡片:', play_new(pg, False))
            if not ready_new(pg):
                rec['err'] = 'NOT_READY'; return rec
            r = pg.ev("""(function(){var s=document.getElementById('l2Motion');
               if(!s) return 'NO_SEL';
               s.value=%s; window.__l2play(%s); return 'PLAYED';})()"""
                       % (json.dumps(CLIP), json.dumps(CLIP)))
            print('    play:', r)
        best = None
        # 在整个播放窗口内反复采样，取每个 drawable 的最大值：
        # 「曾经可见」比「瞬时快照」可靠得多（瞬时快照会漏掉只出现几帧的部件）。
        t_end = time.time() + PEEK
        while time.time() < t_end:
            raw = pg.ev(DUMP)
            if isinstance(raw, str) and raw.startswith('{'):
                o = json.loads(raw)
                if o.get('n') and o.get('ops'):
                    if best is None:
                        best = o
                    else:
                        for i, v in enumerate(o['ops']):
                            if v > best['ops'][i]:
                                best['ops'][i] = v
            time.sleep(0.12)
        if best:
            rec.update(best); rec['ok'] = True
    finally:
        pg.close()
    return rec


def probe(which, n):
    runs = []
    for i in range(n):
        print('  [%s] 第 %d/%d 次 ...' % (which, i + 1, n), flush=True)
        r = run_once(which, i)
        if r.get('ok'):
            runs.append(r)
            nz = sum(1 for v in r['ops'] if v > 0.001)
            print('    n=%d 组=%s 非零 drawable=%d' % (r['n'], r.get('g'), nz))
        else:
            print('    失败:', r.get('err'))
    return runs


def summarize(which, runs):
    if not runs:
        print('[%s] 无有效运行' % which); return None
    n = runs[0]['n']
    ids = runs[0]['ids']
    print('\n=== [%s] %d 次有效运行，drawable n=%d ===' % (which, len(runs), n))
    # 按名称对齐（若各次 ids 相同则直接用）
    same_ids = all(r['ids'] == ids for r in runs)
    print('  各次 drawable 名称一致: %s' % same_ids)
    for i in range(n):
        vals = [r['ops'][i] for r in runs]
        vis = sum(1 for v in vals if v > 0.001)
        if vis == 0:
            continue
        if vis == len(runs) and len(runs) > 1:
            # 全部可见：只在数值有差异时提一句
            if len(set(vals)) > 1:
                print('  %-28s #%-4d 恒可见  值=%s' % (ids[i], i, sorted(set(vals))))
        else:
            print('  %-28s #%-4d 可见 %d/%d  各次值=%s' % (ids[i], i, vis, len(runs), vals))
    return {'which': which, 'ids': ids, 'runs': runs}


def main():
    summary = []
    if MODE in ('old', 'both'):
        summary.append(summarize('old', probe('old', N)))
    if MODE in ('new', 'both'):
        summary.append(summarize('new', probe('new', N)))

    if MODE == 'both' and len(summary) == 2 and all(summary):
        o, w = summary[0], summary[1]
        print('\n=== 名称集合差异 ===')
        so, sw = set(o['ids']), set(w['ids'])
        print('  旧有/新无: %d 个  %s' % (len(so - sw), sorted(so - sw)[:10]))
        print('  新有/旧无: %d 个  %s' % (len(sw - so), sorted(sw - so)[:10]))
        print('\n=== 按名称对齐后的「可见次数」差异 ===')
        ond = {o['ids'][i]: o['runs'] for i in range(len(o['ids']))}
        nnd = {w['ids'][i]: w['runs'] for i in range(len(w['ids']))}
        diff = 0
        for name in sorted(sw & so):
            ov = sum(1 for r in ond[name] if r['ops'][o['ids'].index(name)] > 0.001)
            nv = sum(1 for r in nnd[name] if r['ops'][w['ids'].index(name)] > 0.001)
            if ov != nv:
                diff += 1
                if diff <= 40:
                    print('  %-28s 旧可见 %d/%d   新可见 %d/%d'
                          % (name, ov, len(o['runs']), nv, len(w['runs'])))
        print('  合计不一致的 drawable: %d / %d' % (diff, len(sw & so)))
        print('  ⚠️ 判读门槛：**只有「旧 N/N 可见 且 新 0/N 可见」才算回归**；')
        print('     任一单次运行都不足以支撑结论（双峰摆动已实测到 1/6、3/5）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
