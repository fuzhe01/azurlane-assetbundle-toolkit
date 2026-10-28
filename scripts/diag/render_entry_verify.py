"""最终验收：把采样点钉在 `coreModel.update()` **入口**（= 渲染真正读到的那个值）。

为什么不能用 `beforeModelUpdate` 监听器采样：它的执行顺序取决于注册先后（页面自己的 stateApply、
  装扮 tween、探针的监听器都挂在这个事件上），于是"读到 0 / 读到 -1"可能只是采样先于写入的假象 ——
  本轮已因此困惑过一次（2488 写 -1 但同帧 ENTRY 读到 0）。`core.update()` 是唯一没有歧义的时点：
  Cubism 在这一刻把参数数组算成 mesh，之前所有写入都已生效，之后才轮到手写。

同页自身对照（区分力证明，不必另起页面）：
  · 点击**前**一段时间：stateApply 未让渡，恒写 `_on`（ShoseOff 的 off 值 = -1）
      → update 入口应恒为 **-1**（= 修法前全世界看到的坏状态）。
  · 点击**后**：让渡生效，stateApply 改成重放装扮值，tween 每帧推进
      → update 入口应出现 **0<|v|<1 的中间值**，并收敛到 **1**（ShoseOff 的 on 值）且此后稳定。
  同一支探针在同一页面同时拿到"坏"与"好"两组读数 ⇒ 若修法无效，两段都会是 -1，区分力成立。

判据（三条全绿才算过）：
  ① 点击前：update 入口 distinct == {-1}
  ② 点击后：中间值个数 >= 5（0.45s @60fps 的 tween 应有约 27 帧）
  ③ tween 结束后 30 帧内：update 入口恒为 1（不回落）—— 这条防"点一下动了然后自己弹回去"

⚠️ **本探针曾 3 次里 1 PASS / 2 FAIL，根因是仪器而不是产品**（2026-10-28）：
  headless 下浏览器会在页面加载 18–30 秒后把出帧源降到精确 1 Hz 甚至完全停掉 rAF
  （实测 `vis=hidden`、`gapMax` 193→1016 ms；**零产品代码的极简页同样发生**）。
  帧一停，`core.update` 入口的采样就只覆盖到 tween 的前几帧 ⇒ ②③ 随机失败。
  修法见 `gallery_ui_shots.Page.detach_frames()`：把渲染循环从 rAF 解耦，用定时器
  以 60 Hz 调 `ticker.update(now)`。实测同一页 rAF 侧 0.0 fps、推帧侧稳定 59.4–61.0。
  **所以本探针现在必须在解耦模式下跑，并在采样前后各过一次 `require_frames()` 闸**：
  闸红了直接抛错，绝不带着"冻结的采样"去判产品。
  ⚠️ 另外不再调 `Network.setCacheDisabled` + `Page.navigate`：那是为绕缓存写的，
  而一个 websocket 连接只有**一个页面**，`Page.navigate` 之后 `Page` 类的心跳/推帧
  都还挂在旧文档上（会读到过期状态）。现在直接以带 `#gallery_v2` 的 URL 打开新页。

⚠️ **解耦第一版只推了 `app.ticker`，`core.update` 一次都没跑**（2026-10-28，第八条仪器 bug）：
  pixi-live2d-display 把模型 update 挂在 **`PIXI.Ticker.shared`** 上
  （vendor/.../pixi-live2d-display-cubism4-patched.js:4936 `onTickerUpdate` 读 `tickerRef.shared`），
  而 `new PIXI.Application()` 默认 `sharedTicker:false` ⇒ 两个 ticker 是**不同实例**。
  只推 `app.ticker` 的现象极具欺骗性：画面照常渲染、推帧计数照样报 59.9 fps（假绿灯），
  但 `window.__u` 是**空数组**（n=0 帧），三条判据全 False。
  ⇒ `FRAME_DETACH` 现在两个 ticker 都推（`ntk=2`），`require_frames` 的报错行会带 `ntk`
  就是为了下次一眼看出"又只推了一个"。

⚠️ **闸的阈值不能用帧率**（同轮第九条）：解耦后每帧要真跑 `core.update` + `render`，
  1400x1000 实测单帧 9–27 ms、`setInterval(4)` 被浏览器钳到 ≈8–10 ms/次 ⇒ 帧率
  36.7（JIT 预热）→ 44 → 49，永远到不了 60。拿 55 判红时红的是**硬件成本**。
  `require_frames` 现在只判"`n` 在涨"（≥8 fps），可达上限只作诊断打印。

**当前实测（3 连跑，仪器可信）**：① 点击前 distinct=[-1]（n≈349 帧）
  ② 中间值 26 个（0.0054 → 0.99）③ 尾 30 帧恒 1。三次全 PASS。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from gallery_ui_shots import Page  # noqa: E402

PID = sys.argv[1] if len(sys.argv) > 1 else 'ShoseOff'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'

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
  window.__u=[];
  var iu=core.update.bind(core);
  core.__wrapped=true;
  core.update=function(){
    try{ window.__u.push(+this.getParameterValueById(%s).toFixed(4)); }catch(e){ window.__u.push(null); }
    return iu.apply(this, arguments);
  };
  return 'OK';
})()
""" % json.dumps(PID)


def main():
    pg = Page(9403, r'D:\azur\.diag\rev_prof', URL, (1400, 1000),
              gpu=True, keepalive=False)
    try:
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
        print('打桩 core.update:', pg.ev(PATCH))
        print('解耦帧源:', pg.detach_frames(60))
        # 先等过 JIT 预热期：解耦推帧前 10 秒实测 36→49 fps（每帧要真跑 core.update +
        # render），预热完到 54–58。**不能用 55 当闸**，那红的是硬件成本不是帧源。
        time.sleep(3.0)
        print('帧源闸: %.1f fps（诊断: 单帧成本 %sms ⇒ 可达约 %s）' % (
            pg.require_frames(2.0), pg.last_gate.get('cost'), pg.last_gate.get('reachable')))
        # ---- 段 1：点击前基线（自身对照的"坏"侧）----
        pg.ev("window.__u=[];")
        time.sleep(1.2)
        pre = json.loads(pg.ev("JSON.stringify(window.__u)"))
        pg.require_frames(1.0)
        pg.ev("window.__u=[];")
        time.sleep(0.05)
        r = pg.ev("window.__costumeToggle(%s)" % json.dumps(PID))
        time.sleep(2.2)
        post = json.loads(pg.ev("JSON.stringify(window.__u)"))
        print('采后帧源闸: %.1f fps' % pg.require_frames(2.0))
    finally:
        pg.close()
    print('\n点击结果:', r)
    ds = sorted(set(pre))
    print('\n① 点击前 update 入口 distinct:', ds, '（n=%d 帧）' % len(pre))
    mid = [v for v in post if v is not None and 0.001 < abs(v) < 0.999]
    print('② 点击后中间值个数:', len(mid))
    print('   点击后 distinct(前12):', sorted(set(post))[:12])
    tail = [v for v in post if v is not None][-30:]
    print('③ tween 后 30 帧:', sorted(set(tail)))
    ok1 = ds == [-1]
    ok2 = len(mid) >= 5
    ok3 = len(tail) == 30 and set(tail) == {1}
    print('\n判据 ①点击前恒 -1 :', ok1)
    print('判据 ②出现中间值   :', ok2)
    print('判据 ③稳态收敛到 1 :', ok3)
    print('总判定:', 'PASS' if (ok1 and ok2 and ok3) else 'FAIL')
    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == '__main__':
    sys.exit(main())
