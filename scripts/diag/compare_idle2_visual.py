# -*- coding: utf-8 -*-
"""验证核心分歧：组名 = idle2 时，画面到底是不是 idle2。

背景（2026-10-24 关键反思）：
  用户观察「touch_idle1 最后停在默认 idle 循环」，
  而我的探针看到 state.currentGroup = idle2。
  两者可能都对——因为**组名是意图，画面是结果**。

  上一轮已记录未解问题：动作播放期间曲线值到不了目标
  （ParamAngleX 恒 0 而非 -18.367、p194 只到 2.098 而非 10.0）。

  若曲线求值被压制，则「组名切到 idle2」但「参数没被 idle2 驱动」，
  画面停留在默认姿态 → 用户看到的确实就是默认 idle。

本脚本用**画面**而非组名做判据（真 GPU 有头 Edge）：
  1. 让画面稳定在默认 idle  → 截图 A
  2. 强制播 idle2          → 截图 B
  3. 播 touch_idle1 等回落  → 截图 C（同时记录组名）
  然后比较 A/B/C 两两差异：
    · 若 B ≈ A  → idle2 与 idle 画面相同，曲线确实没生效（组名判据失效）
    · 若 B ≠ A 且 C ≈ A → 回落画面是默认 idle（复现用户观察）
    · 若 B ≠ A 且 C ≈ B → 回落画面确实是 idle2（我的观察对，用户可能是缓存）

⚠️ idle 有呼吸循环，像素差异本底 6%~44%（§已有记录），
   所以判据用「显著差异像素占比」并把基线差异一起打印，不做绝对阈值断言。
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

import ensure_servers  # noqa: E402
from cdp_helper import open_page  # noqa: E402
from PIL import Image, ImageChops, ImageStat  # noqa: E402

KEY = 'ougen_8'
GROUP = 'touch_idle1'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'idle2_visual')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookIV) return;
    proto.__dshHookIV=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c&&c.internalModel&&c.internalModel.coreModel){
          if(c.destroyed!==true) window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
})();
"""

SNAP = """
(function(){
  try{
    var m=window.__l2model;
    if(!m) return JSON.stringify({err:'no model'});
    var im=m.internalModel, cm=im.coreModel, mm=im.motionManager;
    return JSON.stringify({g:(mm.state||{}).currentGroup});
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""

# 直接强制切到某组（走页面自己的入口，不绕库）
FORCE = """(function(){
  try{ if(window.__l2play) window.__l2play(%s, 3); return 1; }catch(e){ return 'E:'+e; }
})()"""


def diff(a, b):
    """返回 (平均差, 显著差异像素百分比)。裁掉左边缘避免工具条干扰。"""
    w = min(a.size[0], b.size[0])
    h = min(a.size[1], b.size[1])
    box = (int(w * .30), int(h * .06), int(w * .99), int(h * .96))
    aa = a.crop(box)
    bb = b.crop(box)
    if aa.size != bb.size:
        bb = bb.resize(aa.size)
    d = ImageChops.difference(aa, bb).convert('L')
    hist = d.histogram()
    tot = sum(hist)
    return ImageStat.Stat(d).mean[0], sum(hist[25:]) * 100.0 / tot


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='iv', win=(1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              "if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(15)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        # 1) 默认 idle 基线
        pg.ev(FORCE % json.dumps('idle'))
        time.sleep(2.5)
        pA = os.path.join(OUT, 'A_idle.png')
        pg.shot(pA)
        gA = json.loads(pg.ev(SNAP)).get('g')
        print('A 默认 idle   组名=%s  -> %s' % (gA, pA))

        # 2) 强制 idle2
        pg.ev(FORCE % json.dumps('idle2'))
        time.sleep(2.5)
        pB = os.path.join(OUT, 'B_idle2.png')
        pg.shot(pB)
        gB = json.loads(pg.ev(SNAP)).get('g')
        print('B 强制 idle2  组名=%s  -> %s' % (gB, pB))

        # 3) 播 touch_idle1 并等回落
        pg.ev(FORCE % json.dumps(GROUP))
        time.sleep(5.0)          # 1.5s 动作 + 0.6 余量 + 缓冲
        pC = os.path.join(OUT, 'C_after_fallback.png')
        pg.shot(pC)
        gC = json.loads(pg.ev(SNAP)).get('g')
        print('C 回落之后    组名=%s  -> %s' % (gC, pC))

        # 4) 再取一张 idle2 的，验证呼吸本底
        pg.ev(FORCE % json.dumps('idle2'))
        time.sleep(2.5)
        pB2 = os.path.join(OUT, 'B2_idle2_again.png')
        pg.shot(pB2)

        A = Image.open(pA).convert('RGB')
        B = Image.open(pB).convert('RGB')
        C = Image.open(pC).convert('RGB')
        B2 = Image.open(pB2).convert('RGB')

        print('\n=== 像素对比（平均差 / 显著差异占比）===')
        ba = diff(B, B2)
        print('  B vs B2   (idle2 自身呼吸本底)   mean=%6.2f  pct=%5.2f%%' % ba)
        ab = diff(A, B)
        print('  A vs B    (idle  vs idle2)       mean=%6.2f  pct=%5.2f%%' % ab)
        ac = diff(A, C)
        print('  A vs C    (idle  vs 回落后)      mean=%6.2f  pct=%5.2f%%' % ac)
        bc = diff(B, C)
        print('  B vs C    (idle2 vs 回落后)      mean=%6.2f  pct=%5.2f%%' % bc)

        print('\n=== 判定 ===')
        print('  回落时的组名 =', gC)
        print()
        if ab[1] <= ba[1] * 1.5:
            print('==> idle2 与 idle 画面几乎相同（%.2f%% ≈ 本底 %.2f%%）' % (ab[1], ba[1]))
            print('    ⇒ 曲线没真正生效，「组名」判据失效；你看画面是对的，我看组名是错的')
        elif bc[1] < ac[1] * 0.7:
            print('==> 回落画面更接近 idle2（C-B=%.2f%% < C-A=%.2f%%）' % (bc[1], ac[1]))
            print('    ⇒ 回落确实到了 idle2 的姿态；你看到默认 idle 可能是缓存旧前端')
        elif ac[1] < bc[1] * 0.7:
            print('==> 回落画面更接近默认 idle（C-A=%.2f%% < C-B=%.2f%%）' % (ac[1], bc[1]))
            print('    ⇒ 复现了你的观察：组名 idle2 但画面是默认 idle')
        else:
            print('==> 三者差异相当，无法区分（本底太大）；需换几何判据')
        print('\n截图目录:', OUT)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
