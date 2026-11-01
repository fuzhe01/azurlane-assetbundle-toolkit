"""部件消失取证：同动作、同模型，本仓库 vs 旧画廊，逐 drawable 比不透明度。

用户目视：ougen_8 的 idle / idle9 / mail 里左脚、左腿、右手缺失。
上一轮我补入了 m_ConstantClip 定值曲线（+18839 条），技能明确警告过：
   「补定值曲线有风险，可能把参数钉死在错误值上」，
   必须做「定值 == moc3 默认值」的审计，否则会把部件钉成不可见。
审计已通过（等于默认值），所以要看运行时是否另有原因。

本脚本比的是**同一动作下**两边的 drawable 不透明度集合：
若本仓库有部件透明度为 0 而旧画廊不为 0 → 是本轮改动引入的回归。

用法: py -3 .diag/ab_part_opacity.py [key] [clip]
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
OUT = os.path.join(ROOT, '.diag', 'part_ab')
os.makedirs(OUT, exist_ok=True)

SITES = [('old', 'http://127.0.0.1:8777/gallery_v2/index.html', 9310),
         ('new', 'http://127.0.0.1:8778/gallery_v2/index.html', 9311)]

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookAB) return; proto.__dshHookAB=true;
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
  var core=m.internalModel.coreModel;
  var n=0; try{ n=core.getDrawableCount(); }catch(e){ return JSON.stringify({err:String(e)}); }
  var ops=[];
  for(var i=0;i<n;i++){ try{ ops.push(+core.getDrawableOpacity(i).toFixed(3)); }catch(e){ ops.push(null); } }
  return JSON.stringify({n:n, ops:ops});
})()
"""


def run_site(tag, url, port, wait_ready=True):
    pg = Page(port, os.path.join(ROOT, '.diag', 'chrome_ab%d' % port), url, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': url})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        step = {}
        step['card'] = pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD';
          c.click(); return 'OK';})()
        """ % json.dumps(KEY))
        time.sleep(1.5)
        step['skin'] = pg.ev("""
        (function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
             return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()
        """ % json.dumps(KEY))
        time.sleep(1.2)
        step['tab'] = pg.ev("""
        (function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
             return e.dataset.k==='live2d';});
          if(!t) return 'NO_TAB'; if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()
        """)
        time.sleep(9)
        print('  [%s] 步骤 %s  模型 %s' % (tag, step, pg.ev("typeof window.__l2model")))

        r = pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(!s) return 'NO_SEL';
                   if(![...s.options].some(function(o){return o.value===%s;})) return 'NO_GROUP';
                   s.value=%s;
                   if(window.__l2play){ window.__l2play(%s); return 'PLAYED'; }
                   return 'NO_HOOK';})()""" % (json.dumps(CLIP), json.dumps(CLIP), json.dumps(CLIP)))
        time.sleep(6)
        pg.shot(os.path.join(OUT, '%s_%s_%s.png' % (CLIP, KEY, tag)))
        d = pg.ev(DUMP)
        print('  [%s] play=%s' % (tag, r))
        return json.loads(d) if d and d.startswith('{') else {'err': d}
    finally:
        pg.close()


def main():
    for tag, url, _ in SITES:
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                if r.status != 200:
                    print('[INVALID] %s HTTP %s' % (tag, r.status)); return 2
        except Exception as e:  # noqa: BLE001
            print('[INVALID] %s 不可达: %s' % (tag, e)); return 2

    res = {}
    for tag, url, port in SITES:
        res[tag] = run_site(tag, url, port)

    o, n = res.get('old', {}), res.get('new', {})
    if 'err' in o or 'err' in n:
        print('\n[INVALID] 有一侧取不到数据: old=%s new=%s' % (o.get('err'), n.get('err')))
        return 2
    if o['n'] != n['n']:
        print('\n[INVALID] drawable 数量不一致 old=%d new=%d' % (o['n'], n['n']))
        return 2

    worse, better, same = [], [], 0
    for i in range(o['n']):
        a, b = o['ops'][i], n['ops'][i]
        if a is None or b is None:
            continue
        if b < 0.02 and a >= 0.02:
            worse.append((i, a, b))
        elif b >= 0.02 and a < 0.02:
            better.append((i, a, b))
        else:
            same += 1

    print('\n=== %s / %s 逐 drawable 不透明度对比（%d 个）===' % (KEY, CLIP, o['n']))
    print('  一致             : %d' % same)
    print('  新版不可见而旧版可见（回归嫌疑）: %d' % len(worse))
    print('  旧版不可见而新版可见（改善）    : %d' % len(better))
    if worse[:10]:
        print('\n  回归嫌疑明细（drawable, 旧op, 新op）:')
        for x in worse[:15]:
            print('    %d  旧 %.3f  新 %.3f' % x)
    o0 = sum(1 for v in o['ops'] if v is not None and v < 0.02)
    n0 = sum(1 for v in n['ops'] if v is not None and v < 0.02)
    print('\n  不可见部件总数: 旧 %d / 新 %d' % (o0, n0))
    return 0


if __name__ == '__main__':
    sys.exit(main())