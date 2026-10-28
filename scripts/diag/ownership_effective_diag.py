"""查「让渡标记是否生效」：为什么修后 2488 行仍每帧写 -1。

现象（identity_and_writeorder_diag 修后读数，真 GPU 60fps）：
  · 事实 A：2171(tween) 写了中间值 0.002→1，2478(让渡分支重放) 写了同样的中间值 →
            渐变**确实**到过 coreModel；core.update 入口出现 25 个中间值 ⇒ 产品缺陷真被修好。
  · 事实 B：2488(原 `_on` 分支) 仍被打了 29 次 **-1** ⇒ 让渡标记没生效，或生效前已写过。
两个事实必须分开解释，否则会误判「修法无效」。

判据（三选一，决定性）：
  ① 点击后立即读 `STATE_TOGGLES`/STOGS 条目的 `_costumeOwned` —— true 则标记生效；
  ② 若为 false → 看 `costumeToggle` 是否根本没进让渡分支（例：`STOGS` 里那个条目被换肤重建，
     或 `it.id` 与 `t.id` 大小写/前后空白不一致）；
  ③ 若为 true 但仍 2488 写 -1 → 说明还有**第二个** stateApply 监听器（多次进 renderLive2D
     未 off），本次一并检出。

为什么这一查必须做：让渡一旦没生效，tween 结束（twBy 清空）后 2488 就会每帧把值钉回 -1，
  用户看到的是「点一下动了、然后自己弹回去」，比"完全不动"更糟。

由于 STOGS 是 renderLive2D 内部 const（不在 window 上），本探针**只能**通过页面上可观察的
副作用判定：把 stateApply 是否写 -1 与 core.update 入口值按帧对齐看。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

PID = 'ShoseOff'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

CLOSE_LOGIN = """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
   if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()"""
OPEN_SHIP = """(function(){var s=(window.GALLERY.ships||[]).find(function(x){
     return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD'; c.click(); return 'OK';})()"""
PICK_SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
   return e.dataset.k=='ougen_8';}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
TO_L2D = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
   return e.dataset.k=='live2d';}); if(!t) return 'NO_TAB';
   if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""

PATCH = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return 'NO_MODEL';
  var core=m.internalModel.coreModel, im=m.internalModel;
  window.__wlog=[]; window.__frames=0; window.__nHandlers=0;
  function who(){ try{ var st=(new Error()).stack.split('\n');
    for(var i=0;i<st.length;i++){ var mt=st[i].match(/index\.html[^:]*:(\d+):(\d+)/);
      if(mt) return +mt[1]; } }catch(e){} return -1; }
  var spv=core.setParameterValueById.bind(core);
  core.setParameterValueById=function(k,v){
    if(k===%s) window.__wlog.push([window.__frames, who(), +v.toFixed(4)]);
    return spv(k,v); };
  /* 数 beforeModelUpdate 上的 stateApply 监听器个数：>1 说明重复注册（旧修复的候选解释） */
  try{ var ev=im._model&&im._model; }catch(e){}
  try{
    var l=im._listeners||im.listeners||im._events;
    if(l&&l.beforeModelUpdate) window.__nHandlers=(l.beforeModelUpdate||[]).length;
  }catch(e){}
  im.on('beforeModelUpdate', function(){
    window.__frames++;
    try{ window.__wlog.push([window.__frames, 'ENTRY', +core.getParameterValueById(%s).toFixed(4)]); }catch(e){}
  });
  return JSON.stringify({cores:1, handlers:window.__nHandlers});
})()
""" % (json.dumps(PID), json.dumps(PID))

DUMP = "JSON.stringify({w:window.__wlog||[], f:window.__frames})"


def main():
    pg = open_page(URL, win=(1400, 1000), tag='own')
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
        time.sleep(0.6)
        pg.ev("window.__wlog=[];")
        print('切换:', pg.ev("window.__costumeToggle(%s)" % json.dumps(PID)))
        time.sleep(2.5)
        d = pg.ev(DUMP)
    finally:
        pg.close()
    if isinstance(d, str):
        d = json.loads(d)
    w = d['w']
    print('\n== 按帧看 2171(tween)/2478(让渡重放)/2488(原_on) 谁在写 ==')
    byfr = {}
    for fr, ln, v in w:
        byfr.setdefault(fr, []).append((ln, v))
    clicks = [fr for fr in sorted(byfr) if any(ln == 2171 for ln, _ in byfr[fr])]
    print('  tween 出现的帧范围:', (clicks[0], clicks[-1]) if clicks else None)
    last = clicks[-1] if clicks else None
    print('\n  %-6s %s' % ('frame', 'writes(line:value)'))
    for fr in sorted(byfr)[:6] + sorted(byfr)[-8:]:
        print('  %-6s %s' % (fr, ' '.join('%s:%s' % (ln, v) for ln, v in byfr[fr])))
    print('\n== tween 结束之后的帧里，2488 是否仍在写 -1 ==')
    if last:
        after = [fr for fr in byfr if fr > last]
        w488 = [fr for fr in after if any(ln == 2488 for ln, _ in byfr[fr])]
        print('  tween 结束后总帧数:', len(after), ' 其中 2488 写过的帧数:', len(w488))
        if w488:
            vals = [v for fr in w488 for ln, v in byfr[fr] if ln == 2488]
            print('  这些 -1 之后，ENTRY 读到的是:', 
                  [v for fr in w488[:6] for ln, v in byfr[fr] if ln == 'ENTRY'])
    print('\n== 帧末 ENTRY 序列（点击段）==')
    if clicks:
        for fr in range(clicks[0], min(clicks[0] + 8, clicks[-1] + 2)):
            e = [v for ln, v in byfr.get(fr, []) if ln == 'ENTRY']
            print('  frame %-5d ENTRY=%s' % (fr, e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
