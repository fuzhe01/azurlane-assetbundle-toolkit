"""一次性诊断：`gpu=True`（真 GPU / D3D11）能否把 Live2D 页的帧率从 ~1fps 提到 ~60fps。

背景链（都是实测，不是推测）：
  1. 上一轮结论「`--headless=new` 被判后台 → visibility=hidden → rAF 停摆」，
     唯一有效修法 `Emulation.setFocusEmulationEnabled(true)`。装上后确实从 7 帧/8s 提到 393 帧/8s。
  2. 但装上后重跑产品探针，仍见 ~1fps 指纹（pin 收敛 2.33s、1.5s 内 3 次写入）。
  3. 逐相位采样证明：首屏 60fps，切到 Live2D 后掉到 1fps，而 **visibility 全程 visible、hasFocus=true**
     ⇒ hidden 不是这一段的原因。
  4. 帧耗时分解：回调自身 work≈0ms、gapMed=16.9ms 但 gapP90≈1035ms ⇒ 不是节流（节流不会留下 16.9ms 的帧），
     是**周期性 ~1s 的整段阻塞**。longtask 全部 'unknown/window'（无 JS 归属）。
  5. GL 后端实测是 `ANGLE (SwiftShader Device (Subzero))` = **纯软件光栅化**。
     原因：`gallery_ui_shots.Page.__init__` 在 `gpu=False` 时**主动追加** `--use-angle=swiftshader`，
     而 `cdp_helper.open_page` 没有把 `gpu` 透传下去 ⇒ 全库探针一律跑软件渲染。

判据（决定性）：同一页面同一套操作，仅切换 `gpu` 参数；帧率必须差一个数量级才算定案。
  · gpu=True 下 ≥40fps ⇒ 之前的 1fps 全是软件渲染 + 大画布（990×570 模型 / 1370×871 画布）造成，
    与 rAF 保活、与产品逻辑都无关。
  · gpu=True 下仍 ~1fps ⇒ 另有原因（GPU 也不可用 / 驱动缺失），须继续查。
"""
import json
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"d:\azur"
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'
KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'

GLQ = """JSON.stringify((function(){
  var cv=document.querySelector('canvas');
  var ctx=cv&&(cv.getContext('webgl2')||cv.getContext('webgl'));
  if(!ctx) return 'NO_CTX';
  var d=ctx.getExtension('WEBGL_debug_renderer_info');
  return d?String(ctx.getParameter(d.UNMASKED_RENDERER_WEBGL)):String(ctx.getParameter(ctx.RENDERER));
})())"""

HB = """(function(){ if(window.__hb) return 'ALREADY';
  window.__hb={raf:0}; (function l(){window.__hb.raf++; requestAnimationFrame(l);})(); return 'OK';})()"""

RD = """JSON.stringify({raf:window.__hb.raf,
  tk:(window.__l2TickerState&&window.__l2TickerState())||{},
  vis:document.visibilityState})"""


def run(gpu, tag):
    port = random.randint(9510, 9899)
    prof = os.path.join(ROOT, '.diag', 'chrome_gpu_%s_%d' % (tag, port))
    pg = Page(port, prof, BASE, (1400, 1000), gpu=gpu)
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': BASE})
        time.sleep(3.5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              " if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
              % json.dumps(KEY))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis') t.click(); return 1;})()""")
        for _ in range(70):
            if pg.ev("(function(){return window.__costumeBoxes?1:0;})()") == 1:
                break
            time.sleep(1)
        time.sleep(1.5)
        print('[%s] GL: %s' % (tag, pg.ev(GLQ)))
        pg.ev(HB)
        prev = None
        for i in range(6):
            time.sleep(1.0)
            r = json.loads(pg.ev(RD))
            d = '' if prev is None else ' Δraf=%+d' % (r['raf'] - prev[0])
            print('[%s] t=%ds raf=%-5d vis=%-8s tk.lt=%-9s%s'
                  % (tag, i + 1, r['raf'], r['vis'],
                     (r.get('tk') or {}).get('lastTime'), d))
            prev = (r['raf'],)
        return 0
    finally:
        pg.close()


def main():
    for gpu, tag in ((False, 'swiftshader'), (True, 'gpu')):
        rc = run(gpu, tag)
        print('-' * 70)
        if rc:
            return rc
    return 0


if __name__ == '__main__':
    sys.exit(main())
