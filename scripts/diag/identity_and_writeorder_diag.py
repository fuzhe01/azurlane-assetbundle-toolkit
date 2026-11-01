"""定性：stateApply 写的 `core` / 装扮 tween 写的 `cm` / stateTick 写的 `c2`
是不是 `__l2ModelRef().internalModel.coreModel` 这**同一个对象**。

为什么必须先测这个（修法的前提）：stateApply 每帧末无条件 `core.setParameterValueById(t.id, t._on)`。
  · 若三处同一对象 → 它直接盖掉装扮 tween 写进去的中间值 ⇒ 让 stateApply 跳过「被装扮接管」的
    参数即可，改动面极小。
  · 若不同 → 还有第三条路径，改这些地方不会生效。

判据用**功能同一性**而不是引用相等：在参考对象上打桩 `setParameterValueById`，然后
  ① 调 `window.__costumeToggle('ShoseOff')`（产品自己的入口，不绕过），
  ② 等 tween 跑完，
看打桩是否收到来自 1762(stateTick) / 2164(tween `cm`) / 2468(stateApply `core`) 的写入。
源码里 `stage.children[0]` 的取用有同步时序差（`captureActionState` 在模型加载后才有值），
所以"看起来同一个"不算证据，必须运行时时点死。

输出：每条写入 帧号 + 栈里第一条 index.html 行号 + 值；
最后按行号聚合，报 distinct 值集合 —— 若 2468 每题帧都写 `-1` 而 tween 写了中间值，
即写序冲突成立。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

MODEL, PID = 'ougen_8', 'ShoseOff'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

CLOSE_LOGIN = """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
   if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()"""
OPEN_SHIP = """(function(){var s=(window.GALLERY.ships||[]).find(function(x){
     return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  if(!s) return 'NO_SHIP';
  var c=[...document.querySelectorAll('.card')].find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()"""
PICK_SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
   return e.dataset.k=='ougen_8';}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
TO_L2D = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
   return e.dataset.k=='live2d';}); if(!t) return 'NO_TAB';
   if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""

# 打桩 + 记录。frame 号由 ticker 侧累加（每帧一次），写入者靠栈里第一条 index.html 行号识别。
PATCH = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return 'NO_MODEL';
  var core=m.internalModel.coreModel;
  window.__wlog=[];
  window.__frame=0;
  var app=null; try{ app=m.parent; }catch(e){}
  function who(){
    try{ var st=(new Error()).stack.split('\n');
      for(var i=0;i<st.length;i++){
        var mt=st[i].match(/index\.html[^:]*:(\d+):(\d+)/);
        if(mt) return +mt[1];
      }
    }catch(e){}
    return -1;
  }
  var spv=core.setParameterValueById.bind(core);
  core.setParameterValueById=function(k,v){
    var ln=who();
    if(k===window.__PIDWATCH)
      window.__wlog.push([window.__frame, ln, +v, +performance.now().toFixed(0)]);
    return spv(k,v);
  };
  window.__PIDWATCH=%s;
  window.__patched=true;
  return 'OK';
})()
""" % ('"'+PID+'"')

# core.update 入口采样：ticker 每帧一次，读的是「本帧最终交出去的那个值」
FRAME_TICK = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m) return 'NO_MODEL';
  var core=m.internalModel.coreModel, im=m.internalModel;
  if(window.__frameTickAdded) return 'ALREADY';
  window.__frameTickAdded=true;
  window.__uentries=[];
  im.on('beforeModelUpdate', function(){
    window.__frame++;
    try{ window.__uentries.push([window.__frame, +core.getParameterValueById(window.__PIDWATCH).toFixed(4)]); }catch(e){}
  });
  return 'OK';
})()
"""

DUMP = r"""
JSON.stringify({
  writes: window.__wlog||[],
  frames: window.__frame,
  entries: window.__uentries||[],
  patched: !!window.__patched
})
"""


def main():
    pg = open_page(URL, win=(1400, 1000), tag='ident')
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        print(pg.ev(CLOSE_LOGIN), end=' ')
        time.sleep(0.9)
        print('开卡:', pg.ev(OPEN_SHIP), end=' ')
        time.sleep(1.6)
        print('选肤:', pg.ev(PICK_SKIN), end=' ')
        time.sleep(1.3)
        print('切L2D:', pg.ev(TO_L2D))
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('打桩:', pg.ev(PATCH))
        print('帧采样:', pg.ev(FRAME_TICK))
        time.sleep(0.5)
        pg.ev("window.__wlog=[]; window.__uentries=[];")
        print('切换:', pg.ev("window.__costumeToggle(%s)" % ('"'+PID+'"')))
        time.sleep(2.0)
        d = pg.ev(DUMP)
    finally:
        pg.close()
    if isinstance(d, str):
        import json as J
        d = J.loads(d)
    if not d.get('patched'):
        print('[FAIL] 打桩未生效:', d)
        return 2
    w = d['writes']
    print('\n== 写入者按行号聚合 ==')
    agg = {}
    for fr, ln, v, t in w:
        agg.setdefault(ln, []).append(v)
    for ln in sorted(agg):
        vs = agg[ln]
        print('  line %-5s n=%-4d distinct=%s  first/last=%s/%s'
              % (ln, len(vs), sorted(set(round(x, 3) for x in vs))[:8], vs[0], vs[-1]))
    print('\n== 前 12 条写入（帧, 行, 值, 毫秒）==')
    for r in w[:12]:
        print('  ', r)
    print('  帧总数:', d['frames'])
    ent = [e[1] for e in d['entries']]
    print('\n== core.update 入口取值（去重）==')
    print('  distinct:', sorted(set(ent))[:12])
    mid = [v for v in ent if -0.98 < v < 0.98]
    print('  中间值(0<|v|<1) 个数:', len(mid), '前几个:', mid[:8])
    return 0 if d['patched'] else 1


if __name__ == '__main__':
    sys.exit(main())
