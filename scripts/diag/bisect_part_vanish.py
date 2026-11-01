# -*- coding: utf-8 -*-
"""按提交二分「部件消失」的引入点：只换页面（index.html），数据固定用当前可用版本。

★ 为什么这样切变量
  画廊渲染结果 = 页面代码(index.html) × 数据(model3/motion3) × 模型资产。
  用户报的问题是「修好之后想回溯引入点」，因此当前数据是**有价值的那一版**；
  固定数据、只换页面，命中的就是页面侧改动，反之则不命中（再换数据侧）。

★ 为什么不用新端口/新目录
  8778 已服务本项目 Output/，Live2D 与 vendor 都在正确相对位置。
  只需把候选提交的页面落成 `gallery_v2/_bis.html` 再打开它，**不需要重启服务**。
  该文件用完即删（Output/ 被 .gitignore 忽略，且不入库）。

★ 判据
  逐 drawable 按 Id 对齐比 `vis`（不是 opacity —— §137 实证 op=1 却 vis=0 真实存在）。
  基准 = 最新提交那一次的快照。报「基准 vis=1、候选 vis=0」的件数 = 候选缺少的部件数。

用法:
  py -3 scripts/diag/bisect_part_vanish.py ougen_8 idle 36504d8 45a5f3c 11dae88
  py -3 scripts/diag/bisect_part_vanish.py ougen_8 idle --auto   # 自动取 10-21 之后的全部
"""
import json
import os
import subprocess
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

BASE = 'http://127.0.0.1:8778'
BIS = os.path.join(ROOT, 'Output', 'gallery_v2', '_bis.html')
PORT = 9330

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__bisHook) return; proto.__bisHook=true;
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
  var m=window.__l2model; if(!m) return JSON.stringify({err:'NO_MODEL'});
  var core=m.internalModel.coreModel; if(!core) return JSON.stringify({err:'NO_CORE'});
  var n=0; try{ n=core.getDrawableCount(); }catch(e){ return JSON.stringify({err:String(e)}); }
  var vis=[],ids=[],op=[];
  for(var i=0;i<n;i++){
    var s='#'+i; try{ s=core.getDrawableId(i)||s; }catch(e){}
    ids.push(s);
    try{ vis.push(core.getDrawableDynamicFlagIsVisible(i)?1:0); }catch(e){ vis.push(null); }
    try{ op.push(+core.getDrawableOpacity(i).toFixed(3)); }catch(e){ op.push(null); }
  }
  var g=''; try{ g=m.internalModel.motionManager.state.currentGroup||''; }catch(e){}
  return JSON.stringify({n:n,g:g,ids:ids,vis:vis,op:op});
})()
"""


def commits_since(since='2026-10-21', path='gallery_src/index.html'):
    out = subprocess.run(
        ['git', '--no-pager', 'log', '--reverse', '--format=%h|%ad|%s', '--date=short',
         '--since=' + since, 'HEAD', '--', path],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout.strip().splitlines()
    return [l.split('|', 2) for l in out if l]


def materialize(commit):
    r = subprocess.run(['git', 'show', '%s:gallery_src/index.html' % commit],
                       cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        return None
    with open(BIS, 'wb') as f:
        f.write(r.stdout)
    return len(r.stdout)


def probe(key, clip, tag):
    url = BASE + '/gallery_v2/_bis.html'
    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_bis'), url, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': url})
        time.sleep(3)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        st = pg.ev("""(function(){var s=(window.GALLERY&&GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===__K__;});});
          if(!s) return 'NO_SHIP'; var c=[].slice.call(document.querySelectorAll('.card')).find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK';})()""".replace('__K__', json.dumps(key)))
        time.sleep(1.8)
        pg.ev("""(function(){var d=[].slice.call(document.querySelectorAll('#mSkins .skin'))
           .find(function(e){return e.dataset.k===__K__;}); if(d) d.click(); return 1;})()"""
               .replace('__K__', json.dumps(key)))
        time.sleep(1.5)
        pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab'))
           .find(function(e){return e.dataset.k==='live2d';});
           if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        for _ in range(40):
            time.sleep(1)
            if pg.ev("window.__l2model?1:0") == 1:
                break
        else:
            return {'err': 'MODEL_NOT_READY', 'card': st}
        if clip:
            pg.ev("""(function(){ if(window.__l2play){ window.__l2play(__G__); return 1; }
               var s=document.getElementById('l2Motion');
               if(s){ s.value=__G__; s.dispatchEvent(new Event('change')); } return 1;})()"""
                   .replace('__G__', json.dumps(clip)))
        time.sleep(6)
        d = pg.ev(DUMP)
        return json.loads(d) if d and d.strip().startswith('{') else {'err': str(d)[:150]}
    finally:
        pg.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    key = args[0] if args else 'ougen_8'
    clip = args[1] if len(args) > 1 else 'idle'
    lst = [c for c in args[2:] if not c.startswith('--')]
    if '--auto' in sys.argv:
        lst = [c[0] for c in commits_since()]

    try:
        with urllib.request.urlopen(BASE + '/gallery_v2/index.html', timeout=5) as r:
            if r.status != 200:
                print('[INVALID] 8778 HTTP %s' % r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 8778 不可达: %s' % e); return 2

    print('候选提交 %d 个，模型 %s，动作 %s\n' % (len(lst), key, clip))
    ref, rows = None, []
    for i, c in enumerate(lst):
        n = materialize(c)
        if n is None:
            print('  %-8s SKIP (取不到 index.html)' % c); continue
        r = probe(key, clip, c)
        if 'err' in r:
            print('  %-8s ERR %s' % (c, r['err'])); rows.append((c, None)); continue
        rows.append((c, r))
        if i == 0:
            ref = r
        print('  %-8s html=%6dB n=%d group=%r  vis=1 件数 %d'
              % (c, n, r['n'], r.get('g'), sum(1 for v in r['vis'] if v == 1)))

    ref = ref or next((r for _, r in rows if r), None)
    if not ref:
        print('\n[INVALID] 没有一次成功取到数据'); return 2

    print('\n=== 相对第一行（%s）的差异：vis 1→0 的件（= 该提交缺少的部件）===' % lst[0])
    rmap = {v: i for i, v in enumerate(ref['ids'])}
    for c, r in rows:
        if not r:
            continue
        idx = {v: i for i, v in enumerate(r['ids'])}
        lost, gained = [], []
        for name, ri in rmap.items():
            if name not in idx:
                continue
            a, b = ref['vis'][ri], r['vis'][idx[name]]
            if a == 1 and b == 0:
                lost.append(name)
            elif a == 0 and b == 1:
                gained.append(name)
        print('  %-8s lost=%2d  gained=%2d  %s'
              % (c, len(lost), len(gained),
                 ('lost: ' + ','.join(lost[:12])) if lost else ''))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    finally:
        try:
            if os.path.exists(BIS):
                os.remove(BIS)
        except OSError:
            pass
