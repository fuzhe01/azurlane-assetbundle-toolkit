"""追踪「60fps → 1fps 衰减」的机制：是不是 GPU 进程崩溃后回退到软件渲染。

已测事实（`fps_timeline_after_load_diag`，真 GPU、同一页面、不点击）：
  加载后就绪 ≈60 fps → 59 → 56 → 14.6 → 4 → 1 fps，单调衰减；
  `visibilityState=visible`、`hasFocus=true` 全程不变；ΔrAF 与 Δcore.update 完全相等
  （差恒为 1）⇒ 不是节流、不是 ticker 单侧停摆，而是**每帧工作本身变慢**。

最可能的机制（必须验，不许猜）：WebGL 上下文来自独立 GPU 进程，一旦该进程崩溃或被回收，
  Chrome 会把还活着的 canvas 切到 SwiftShader 软件渲染 —— 帧率随即跌到个位数，
  而页面侧一切"正常"。这与 §137 记录的 SwiftShader 偏差同源，但这里是**运行中切换**，
  不是启动参数问题，所以 `--use-angle` 修不了它。

判据（三条同时取，任一单独都不足以定性）：
  ① 每秒读一次 `WEBGL_debug_renderer_info` 的 UNMASKED_RENDERER_WEBGL：
     从 `ANGLE (NVIDIA ...)` 变成 `SwiftShader` ⇒ 回退成立；
  ② 监听 `webglcontextlost` / `webglcontextrestored`：直接证据；
  ③ CDP `SystemInfo.getInfo` 取 GPU 设备信息，并记录页面 console 是否出现
     `GPU process` / `context lost` / `out of memory` 类消息。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

INSTALL = r"""
(function(){
  if(window.__glmon) return 'ALREADY';
  window.__glmon={lost:[], restored:[], samples:[], errs:[]};
  window.addEventListener('webglcontextlost', function(){ window.__glmon.lost.push(Date.now()); }, true);
  window.addEventListener('webglcontextrestored', function(){ window.__glmon.restored.push(Date.now()); }, true);
  window.addEventListener('error', function(e){
    try{ window.__glmon.errs.push(String(e && (e.message||e.type))); }catch(_){}
  }, true);
  window.__glSample=function(){
    var out=null;
    try{
      var cv=document.querySelector('canvas');
      var gl=cv && (cv.getContext('webgl2')||cv.getContext('webgl')||cv.getContext('experimental-webgl'));
      if(gl){
        var dbg=gl.getExtension('WEBGL_debug_renderer_info');
        out={ v:dbg?gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),
              vendor:dbg?gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL):null,
              lost:gl.isContextLost() };
      }
    }catch(e){ out={err:String(e)}; }
    return out;
  };
  return 'OK';
})()
"""

SAMPLE = r"""
JSON.stringify({
  ms: +(performance.now()-window.__tm0).toFixed(0),
  gl: window.__glSample(),
  raf: window.__raf, upd: window.__upd,
  lost: (window.__glmon||{}).lost||[], restored: (window.__glmon||{}).restored||[],
  errs: ((window.__glmon||{}).errs||[]).slice(-3),
  ticker: window.__l2TickerState?__l2TickerState():null
})
"""


def main():
    pg = open_page(URL, win=(1400, 1000), tag='glmon')
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        for js, wait in (
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
        ):
            pg.ev(js)
            if wait:
                time.sleep(wait)
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('装监控:', pg.ev(INSTALL))
        pg.ev("""window.__raf=0; window.__upd=0; window.__tm0=performance.now();
          (function loop(){ window.__raf++; requestAnimationFrame(loop); })();
          (function(){ var m=window.__l2ModelRef&&window.__l2ModelRef();
            if(m&&m.internalModel){ var c=m.internalModel.coreModel;
              if(!c.__glw){ c.__glw=true; var iu=c.update.bind(c);
                c.update=function(){ window.__upd++; return iu.apply(this,arguments); }; } } })();""")
        print('\n  %-7s %-6s %-6s %s' % ('ms', 'raf', 'upd', 'UNMASKED_RENDERER_WEBGL'))
        prev = None
        for i in range(16):
            s = json.loads(pg.ev(SAMPLE))
            gl = s.get('gl') or {}
            r = gl.get('v') or '?'
            r = r if len(r) < 78 else r[:78]
            print('  %-7d %-6d %-6d %s' % (s['ms'], s['raf'], s['upd'], r))
            if prev and s['ms'] > prev['ms']:
                dm = s['ms'] - prev['ms']
                print('         ↑ %d ms 内 Δraf=%d → %.1f fps | lost=%s restored=%s errs=%s'
                      % (dm, s['raf'] - prev['raf'], (s['raf'] - prev['raf']) * 1000.0 / dm,
                         s['lost'], s['restored'], s['errs']))
            if gl.get('lost'):
                print('         !! gl.isContextLost() = True')
            prev = s
            time.sleep(1.0)
        try:
            info = pg.cmd('SystemInfo.getInfo', {})
            devs = (info or {}).get('gpu', {}).get('devices', [])
            print('\nCDP gpu.devices:', json.dumps(devs, ensure_ascii=False)[:300])
        except Exception as e:  # noqa: BLE001
            print('\nSystemInfo.getInfo 不可用:', e)
    finally:
        pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
