"""§139 判据落地：逐个换装参数做「改它 → 截图差异面」的局部性验证。

判据（来自 §139，项目已确认口径）：
  ① 改它能看见目标部件变化
  ② 差异面**小且集中** ⇒ 局部开关（可做互动区）
     差异面大、横跨全身 ⇒ 姿势/形态参数（不能当开关）

⚠️ 关键前提（2026-10-24 第一版踩的坑）：
    idle 在持续呼吸，两个间隔 1.5s 的截图本底差异就有 7.5%，
    **比所有候选参数的差异（4~8%）还大**，比例尺被淹没，判据全部失效。
   ⇒ 必须先**冻结动作推进**再测。做法：把 mdl.autoUpdate 置 false，
     之后 params 由我们直接写、截图不再受动画影响。

用法: py -3 scripts/diag/verify_costume_locality.py ougen_8
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
from PIL import Image, ImageChops  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PORT = 9461
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'costume_locality2')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCL2) return; proto.__dshHookCL2=true;
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

# 冻结：autoUpdate=false 后 PIXI ticker 不再推进模型；设为参数后手动 updateOnce
FREEZE = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  try{ m.autoUpdate=false; }catch(e){ return 'ERR:'+e; }
  return 'FROZEN';
})()
"""

# 冻结状态下改参数并重绘一帧
SETPARAM = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var core=m.internalModel.coreModel;
  var i=core.getParameterIndex(%s);
  if(i<0) return 'NO_IDX';
  core.setParameterValueByIndex(i, %s);
  // 冻结后需要手动让它按当前参数重绘一次
  try{ m.internalModel.update(0, performance.now()); }catch(e){}
  try{ m.update(0); }catch(e){}
  return 'SET:'+core.getParameterValueByIndex(i).toFixed(3);
})()
"""


def crop_view(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    return im.crop((int(w * .42), int(h * .10), int(w * .99), int(h * .92)))


def diff_px(a, b):
    w = min(a.size[0], b.size[0]); h = min(a.size[1], b.size[1])
    d = ImageChops.difference(a.crop((0, 0, w, h)), b.crop((0, 0, w, h))).convert('L')
    hist = d.histogram()
    tot = sum(hist)
    big = sum(hist[25:])
    return big, tot, (big * 100.0 / tot if tot else 0.0)


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    table = json.load(open(os.path.join(ROOT, '.diag', 'costume_scan', 'costume_by_range.json'),
                           encoding='utf-8'))
    cands = table.get(KEY, {})
    if not cands:
        print('[FAIL] 无候选表'); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_cl2%d' % PORT), URL, (1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(11)

        print('冻结:', pg.ev(FREEZE))
        time.sleep(0.5)

        # 冻结后本底：不动参数，隔 2s 两张
        p0 = os.path.join(OUT, '_b0.png'); pg.shot(p0)
        time.sleep(2.0)
        p1 = os.path.join(OUT, '_b1.png'); pg.shot(p1)
        n0, _, r0 = diff_px(crop_view(p0), crop_view(p1))
        print('冻结后本底: %d px = %.3f%%' % (n0, r0))
        if r0 > 0.5:
            print('[WARN] 冻结无效（本底 %.2f%% 仍偏高）——判据可能不可靠' % r0)

        rows = []
        for pid, info in sorted(cands.items()):
            lo, hi = info['lo'], info['hi']
            rh = pg.ev(SETPARAM % (json.dumps(pid), hi))
            time.sleep(0.8)
            ph = os.path.join(OUT, '%s_hi.png' % pid); pg.shot(ph)
            rl = pg.ev(SETPARAM % (json.dumps(pid), lo))
            time.sleep(0.8)
            pl = os.path.join(OUT, '%s_lo.png' % pid); pg.shot(pl)
            n, tot, ratio = diff_px(crop_view(ph), crop_view(pl))
            if ratio < max(r0 * 2, 0.3):
                verdict = '几乎无视觉变化'
            elif ratio < 3.0:
                verdict = '局部开关'
            else:
                verdict = '影响面大(疑姿势)'
            rows.append((pid, info['label'], ratio, verdict))
            print('%-16s %-8s %6.2f%%  %-16s (%s / %s)' % (pid, info['label'], ratio, verdict, rh, rl))

        print('\n=== 汇总 ===')
        ok = [r for r in rows if r[3] == '局部开关']
        print('确认局部开关: %d / %d' % (len(ok), len(rows)))
        json.dump([{'id': r[0], 'label': r[1], 'ratio': r[2], 'verdict': r[3]} for r in rows],
                  open(os.path.join(OUT, 'locality.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())