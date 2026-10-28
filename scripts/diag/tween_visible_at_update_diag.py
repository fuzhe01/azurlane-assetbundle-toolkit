"""追查矛盾：同一次点击，为什么 `core.update` 入口只看到 [-1,0,1] 而没有 tween 中间值。

两轮读数互相矛盾：
  · 打桩 `setParameterValueById` 的探针：2171(tween) 写了 0.002/0.009/0.022… 共 28 次中间值，
    2478(让渡重放) 写了同样的中间值 ⇒ 写入侧**确实**在渐变。
  · 打桩 `core.update` 的探针：update 入口 distinct 只有 [-1, 0, 1] ⇒ 渲染侧**没**看到渐变。
「写入侧有、读取侧无」只有几种可能，本探针一次同时记录全部候选，避免继续猜测：
  a) `pins[PID]` 在 update 时刻是否真的持有 tween 值（→ 若为 undefined，说明 pins 被换源了）；
  b) tween 对象在 update 时刻是否还活着、`k` 走到第几（→ 若 k 一直 ~0 或直接 1，说明时间基错）；
  c) update 每帧被调用**几次**（→ 若 >1，第二次调用可能在写入之前，采样点选错）；
  d) 写入的**时间戳**序列（→ 若 tween 的 28 次写入集中在 2 帧内，说明 k 走得太快、
     实为帧率极高导致的"跳帧渐变"，而不是没渐变）。

判据：一次性给出四项实测值，据此定性，不再做第三种猜测。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

PID = 'ShoseOff'
KEY = 'ougen_8'
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
  var core=m.internalModel.coreModel;
  if(core.__wrapped) return 'ALREADY';
  core.__wrapped=true;
  window.__u=[];            /* update 入口样本 */
  window.__w=[];            /* 写入样本 */
  window.__t0=performance.now();
  function pins(){ var pm=(window.__costumePinsByModel||{})[%s]; return pm?pm[%s]:undefined; }
  function twinfo(){ var tb=(window.__costumeTweens||{})[%s]; var t=tb?tb[%s]:null;
    if(!t) return null;
    return {k:+((performance.now()-t.t0)/t.dur).toFixed(3),
            age:+(performance.now()-t.t0).toFixed(0), dur:t.dur,
            from:+t.from.toFixed(3), to:+t.to.toFixed(3)}; }
  var iu=core.update.bind(core);
  core.update=function(){
    var v=null; try{ v=+this.getParameterValueById(%s).toFixed(4); }catch(e){}
    window.__u.push([+(performance.now()-window.__t0).toFixed(0), v,
                     pins()===undefined?null:+pins().toFixed(4), twinfo()]);
    return iu.apply(this, arguments);
  };
  var spv=core.setParameterValueById.bind(core);
  core.setParameterValueById=function(k,v){
    if(k===%s) window.__w.push([+(performance.now()-window.__t0).toFixed(0), +v.toFixed(4)]);
    return spv(k,v); };
  return 'OK';
})()
""" % (json.dumps(KEY), json.dumps(PID), json.dumps(KEY), json.dumps(PID),
       json.dumps(PID), json.dumps(PID))


def main():
    pg = open_page(URL, win=(1400, 1000), tag='chase')
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
        time.sleep(0.4)
        pg.ev("window.__u=[]; window.__w=[]; window.__t0=performance.now();")
        time.sleep(0.6)
        print('切换:', pg.ev("window.__costumeToggle(%s)" % json.dumps(PID)))
        time.sleep(1.5)
        d = json.loads(pg.ev("JSON.stringify({u:window.__u, w:window.__w})"))
    finally:
        pg.close()
    u, w = d['u'], d['w']
    print('\n== a) update 入口值 / pins 值 / tween 状态（点击后前 12 帧）==')
    print('  %-6s %-9s %-9s %s' % ('ms', 'updateVal', 'pinsVal', 'tween'))
    for r in u[:12]:
        print('  %-6d %-9s %-9s %s' % (r[0], r[1], r[2], r[3]))
    print('\n== b) update 入口 distinct 值 ==')
    print('  ', sorted(set(x[1] for x in u if x[1] is not None))[:20])
    print('  pins 值 distinct:', sorted(set(x[2] for x in u if x[2] is not None))[:20])
    # c) 每帧 update 次数：按 ms 聚类
    ms = [x[0] for x in u]
    gaps = [ms[i + 1] - ms[i] for i in range(len(ms) - 1)]
    print('\n== c) update 调用间隔（ms）前 15 ==', gaps[:15])
    print('   样本总数 %d, 覆盖 %d ms' % (len(u), (ms[-1] - ms[0]) if len(ms) > 1 else 0))
    print('\n== d) 写入时间戳（前 16 条，看是否集中在几帧内）==')
    for r in w[:16]:
        print('  %-6d %s' % (r[0], r[1]))
    tw = [x for x in u if x[3]]
    if tw:
        print('\n   tween 存活期间的 update 样本数:', len(tw))
        print('   k 序列:', [x[3]['k'] for x in tw][:20])
    return 0


if __name__ == '__main__':
    sys.exit(main())
