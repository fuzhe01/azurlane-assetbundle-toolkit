"""把 1fps 的耗时拆到具体环节：Cubism core.update / Pixi renderer.render / 其他。

已排除（都是实测，不是推测）：
  · 不是 SwiftShader 回退 —— UNMASKED_RENDERER_WEBGL 全程 `ANGLE (NVIDIA ... RTX 4070)`；
  · 不是 WebGL 上下文丢失 —— `webglcontextlost` 事件 0 次、`isContextLost()` 恒 false；
  · 不是浏览器节流 —— `visibilityState=visible`、`hasFocus=true`，且 ΔrAF 与 Δcore.update 完全相等；
  · 不是 ticker 单侧停摆 —— 两者同增同停。
⇒ 剩「每帧工作本身变慢」。本节把一帧拆成三段计时，看钱花在哪：
  A `coreModel.update()`（Cubism：参数→mesh）
  B `renderer.render()`（Pixi：上传 mesh/纹理、绘制调用）
  C 其余（事件、前端逻辑、GC、宿主合成）

对照（必须同场景，否则无区分力）：
  · 首屏（未进 Live2D 的静态立绘页）是否同样衰减 → 分「页面/宿主」还是「Live2D」；
  · `AL_GPU=0`（软件渲染）衰减形状是否相同 → 分「GPU 路径」还是「与后端无关的累积」。

判据：若 A 单调上升 → Cubism 侧累积（参数/mesh 数量、掩码），那是产品侧；
      若 B 单调上升而 A 平稳 → Pixi/GPU 上传累积；
      若 A、B 都平稳但帧间隔仍 1s → 时间在 C，属宿主/合成器，与产品无关。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

STEP_L2D = [
    ("""var b=document.querySelector('#gOpt button[data-k=login]');
        if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click();""", 0.9),
    ("""var s=(window.GALLERY.ships||[]).find(function(x){
          return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
        var c=[...document.querySelectorAll('.card')].find(function(e){
          return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click();""", 1.6),
    ("""var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
          return e.dataset.k=='ougen_8';}); if(d) d.click();""", 1.3),
    ("""var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
          return e.dataset.k=='live2d';}); if(t&&!t.classList.contains('dis')) t.click();""", 0),
]

INSTALL = r"""
(function(){
  if(window.__tm) return 'ALREADY';
  window.__tm={A:[], B:[], C:[], t0:performance.now()};
  var m=window.__l2ModelRef&&window.__l2ModelRef();
  if(m&&m.internalModel){
    var core=m.internalModel.coreModel;
    var iu=core.update.bind(core);
    core.update=function(){
      var a=performance.now(); var r=iu.apply(this,arguments);
      window.__tm.A.push(+(performance.now()-a).toFixed(2));
      return r;
    };
  }
  /* 用原型打桩而不是实例：`__l2ModelRef()` 返回的是模型，`.parent` 是 stage，拿不到 app.renderer。
     `PIXI.Renderer.prototype.render` 全局可见，每次 app 渲染调用一次，正好一帧一次。 */
  if(window.PIXI&&PIXI.Renderer&&PIXI.Renderer.prototype&&!PIXI.Renderer.prototype.__tm){
    var ir=PIXI.Renderer.prototype.render;
    PIXI.Renderer.prototype.render=function(){
      var b=performance.now(); var r2=ir.apply(this,arguments);
      window.__tm.B.push(+(performance.now()-b).toFixed(2));
      return r2;
    };
    PIXI.Renderer.prototype.__tm=true;
  }
  window.__raf=0; window.__prevEnd=0;
  function loop(){
    var now=performance.now();
    if(window.__prevEnd) window.__tm.C.push(+(now-window.__prevEnd).toFixed(2));
    window.__raf++; window.__prevEnd=now;
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  return 'OK';
})()
"""

SAMPLE = r"""
(function(){
  var t=window.__tm; if(!t) return JSON.stringify({ms:0,raf:0,nA:0,medA:null,maxA:null,
    nB:0,medB:null,maxB:null,medC:null,maxC:null});
  function med(a){ if(!a||!a.length) return null;
    var b=a.slice(-40).sort(function(x,y){return x-y;}); return b[b.length>>1]; }
  function mx(a){ if(!a||!a.length) return null;
    var b=Math.max.apply(null, a.slice(-40)); return +b.toFixed(1); }
  return JSON.stringify({ms:+(performance.now()-t.t0).toFixed(0), raf:window.__raf||0,
    nA:t.A.length, medA:med(t.A), maxA:mx(t.A),
    nB:t.B.length, medB:med(t.B), maxB:mx(t.B),
    medC:med(t.C), maxC:mx(t.C)});
})()
"""


def run(label, steps, install_after_load=True):
    print('\n===== %s =====' % label)
    pg = open_page(URL, win=(1400, 1000), tag=label[:6])
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        for js, wait in steps:
            pg.ev(js)
            if wait:
                time.sleep(wait)
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        if install_after_load:
            print('装计时:', pg.ev(INSTALL))
        print('  %-7s %-6s %-10s %-10s %-10s %-10s %s'
              % ('ms', 'raf', 'nA', 'medA/maxA', 'medB/maxB', 'medC/maxC', 'note'))
        prev = None
        for i in range(10):
            s = json.loads(pg.ev(SAMPLE))
            note = ''
            if prev and s['ms'] > prev['ms']:
                dm = s['ms'] - prev['ms']
                f = (s['raf'] - prev['raf']) * 1000.0 / dm
                note = '%.1f fps' % f
            print('  %-7s %-6s %-10s %-10s %-10s %-10s %s'
                  % (s['ms'], s['raf'], s['nA'],
                     '%s/%s' % (s['medA'], s['maxA']),
                     '%s/%s' % (s['medB'], s['maxB']),
                     '%s/%s' % (s['medC'], s['maxC']), note))
            prev = s
            time.sleep(1.0)
    finally:
        pg.close()


def main():
    run('l2d', STEP_L2D)
    # 对照 1：不进 Live2D（停在静态立绘），看是否同样衰减 —— 分「页面/宿主」还是「Live2D」
    run('static', STEP_L2D[:3], install_after_load=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
