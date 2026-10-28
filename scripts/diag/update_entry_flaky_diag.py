"""定位不稳定的成因：为什么同一支 update 入口探针 2 次里 1 次只看到 [-1,0,1]。

已确认的真事实（不依赖本探针）：
  · `setParameterValueById` 打桩：2171(tween)/2478(让渡重放) 每帧写 0.002→1 的中间值，
    `pins[PID]` 与 update 入口取值 distinct 一致（25 个中间值）、`k` 0.042→0.757 线性推进。
  · 因此产品修法是有效的。剩下的是**判据侧**为什么有时读不到。

候选成因（本次一次性全部记录，靠数据定性，不再猜）：
  ① 首次点击时装扮热区表（costume_params.json）或 param_drawables.json 还没到 →
     `costumeBoxes()` 里没有 ShoseOff → `__costumeToggle` 返回 false（但它返回了 True）；
  ② 让渡标记 `_costumeOwned` 没置上（`__stateTogglesInfo()` 直接可见，本探针打印）；
  ③ `core.update` 上叠加了两个桩（`tween_visible_at_update_diag` 里已见 `wrapped=ALREADY`
     保护，但本支探针若被重复注入会串）—— 用 `__u` 长度与 60fps 期望对账；
  ④ 点击发生在模型刚加载、动作（login/idle）仍在驱动 ShoseOff 曲线的窗口内 →
     库的 loadParameters 在 tween 之后又把它拉回曲线值 ⇒ 中间值被冲掉；
     判据：打印点击时刻 `motionManager.state.currentGroup`。

判据：本探针重复 3 次，每次都先打印「点击前后 __stateTogglesInfo() / currentGroup」，
      再打印 update 入口 distinct。若 ①② 恒正常而 ④ 在 FAIL 次里显示有动作组在跑，
      则定性为 ④，判据必须加"先 stopAllMotions 再点"这道前置闸。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from cdp_helper import open_page  # noqa: E402

PID, KEY = 'ShoseOff', 'ougen_8'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

STEPS = {
    'login': """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
       if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""",
    'ship': """(function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key=='ougen_8';});});
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;});
      if(!c) return 'NO_CARD'; c.click(); return 'OK';})()""",
    'skin': """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k=='ougen_8';}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()""",
    'l2d': """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k=='live2d';}); if(!t) return 'NO_TAB';
       if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()""",
}

STATE = """JSON.stringify({
  boxes: (window.__costumeBoxes?__costumeBoxes().map(b=>b.id):null),
  toggles: (window.__stateTogglesInfo?__stateTogglesInfo():null),
  group: (function(){ try{ var m=window.__l2ModelRef();
      return m.internalModel.motionManager.state.currentGroup||null; }catch(e){ return 'ERR'; } })()
})"""

PATCH = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return 'NO_MODEL';
  var core=m.internalModel.coreModel;
  if(core.__u2wrapped) return 'ALREADY';
  core.__u2wrapped=true;
  window.__u2=[];
  var iu=core.update.bind(core);
  core.update=function(){
    try{ window.__u2.push(+this.getParameterValueById(%s).toFixed(4)); }catch(e){}
    return iu.apply(this, arguments);
  };
  return 'OK';
})()
""" % json.dumps(PID)


def one(run):
    pg = open_page(URL, win=(1400, 1000), tag='rep%d' % run)
    try:
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        for k in ('login', 'ship', 'skin', 'l2d'):
            r = pg.ev(STEPS[k])
            time.sleep({'login': .9, 'ship': 1.6, 'skin': 1.3, 'l2d': 0}[k])
            if k == 'l2d':
                print('  l2d:', r)
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        time.sleep(2.5)     # 让首屏 login/idle 走一段，模拟真实用户
        p = pg.ev(PATCH)
        pre = json.loads(pg.ev(STATE))
        pg.ev("window.__u2=[];")
        time.sleep(0.6)
        r = pg.ev("window.__costumeToggle(%s)" % json.dumps(PID))
        mid = json.loads(pg.ev(STATE))
        time.sleep(1.6)
        vals = json.loads(pg.ev("JSON.stringify(window.__u2)"))
    finally:
        pg.close()
    ds = sorted(set(vals))
    mids = [v for v in ds if 0.001 < abs(v) < 0.999]
    print('  patch=%s toggle=%s' % (p, r))
    print('  点击前 group=%s owned=%s 热区含 ShoseOff=%s'
          % (pre['group'], [(t['id'], t['owned']) for t in pre['toggles'] or []],
             'ShoseOff' in (pre['boxes'] or [])))
    print('  点击后 group=%s owned=%s'
          % (mid['group'], [(t['id'], t['owned']) for t in mid['toggles'] or []]))
    print('  update 入口: n=%d distinct(前10)=%s 中间值=%d'
          % (len(vals), ds[:10], len(mids)))
    return len(mids) >= 5, ds


def main():
    res = []
    for i in (1, 2, 3):
        print('\n===== RUN %d =====' % i)
        res.append(one(i))
    print('\n=== 汇总：中间值个数 %s ===' % [len(r[1]) for r in res])
    print('=== PASS/FAIL: %s ===' % ['PASS' if r[0] else 'FAIL' for r in res])
    return 0


if __name__ == '__main__':
    sys.exit(main())
