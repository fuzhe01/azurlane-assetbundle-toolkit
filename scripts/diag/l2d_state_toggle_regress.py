# -*- coding: utf-8 -*-
"""`STATE_TOGGLES` 条目的**未让渡回归**验收（2026-10-28）。

为什么需要独立一支：本轮的让渡修法只在 `costumeToggle` 里对**同名 id** 置
`_costumeOwned=true`，`toggleState` 里再收回。aersasi_2 的 `touch_drag1`（墨镜）
**不在装扮热区清单里**（`costume_params.json` 只有 ougen_8）⇒ 它永远走未让渡分支。
如果修法写错（比如无条件置 owned、或 stateApply 重放时读不到 pins 就什么都不写），
这里会立刻红 —— 这就是「未让渡条目零回归」的守门。

判据（走产品自己的点击入口，不直接调 toggleState）：
  ① `__stateTogglesInfo()` 里该条目 `owned` 恒 false（让渡没有被误施加）
  ② 真实点击 trigger 区 → 下一帧 `_on` 翻到另一端，且 `core.update` **入口**收敛到该端
  ③ 再点一次 → 翻回另一端
  ④ 每次切换都必须先出现中间值（tween 真的在推进，不是瞬跳）
  ⑤ 阴性对照：点画面外，`_on` 不变

用法：
  py -3 scripts/diag/l2d_state_toggle_regress.py [皮肤key] [参数id]
  py -3 scripts/diag/l2d_state_toggle_regress.py aersasi_2 touch_drag1
退出码：0 全过 / 1 判据失败 / 2 环境故障 / 3 仪器红（帧源停摆）
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'aersasi_2'
PID = sys.argv[2] if len(sys.argv) > 2 else 'touch_drag1'
URL = os.environ.get('GALLERY_URL',
                     'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2')
PORT = int(os.environ.get('GALLERY_PORT', '9407'))
PROFILE = os.environ.get('GALLERY_PROFILE', r'D:\azur\.diag\sttog_prof')

CLOSE_LOGIN = """(function(){var b=document.querySelector('#gOpt button[data-k=login]');
   if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()"""
OPEN_SHIP = """(function(){var k=%s;
  var s=(window.GALLERY.ships||[]).find(function(x){
     return (x.skins||[]).some(function(o){return o.key===k;});});
  if(!s) return 'NO_SHIP';
  var c=[...document.querySelectorAll('.card')].find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()"""
PICK_SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
   return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
TO_L2D = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
   return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
   if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""

# core.update **入口**采样：渲染真正读到的值。不用 getParameterValueById，那只是
# "最后一次写入"，在 beforeModelUpdate 里写的值会与它不一致（本轮 §158 续六 的教训）。
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
"""

# trigger 区的屏幕点：**必须**走页面自己的 `__L2_SCREENOF`（用 `localHit` 做网格反解）。
# ⚠️ 第十条仪器 bug（2026-10-28）：本探针首版自己算 `__L2_HITINFO` 的画布中心 →
#   `(Vx+cux/2)*ppu` 再 toGlobal，结果 x=152050px（画布只有 1400 宽）。
#   原因是 `geomOf` 取的 `getDrawableVertexPositions` **已经是画布像素坐标**（含 *ppu 与
#   居中平移），再套一次 V→Px 等于乘了两遍。错点直接落到屏幕外 ⇒ 点击没反应，而阴性对照
#   照样绿 ⇒ 看起来像「产品点击无效」。凡是「探针算坐标」的地方一律改用页面出口。
SCREEN_OF_HIT = """JSON.stringify(window.__L2_SCREENOF(%s)||null)"""


def click(pg, cx, cy):
    for typ in ('mousePressed', 'mouseReleased'):
        pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': cx, 'y': cy,
                                            'button': 'left', 'clickCount': 1})
        time.sleep(0.08)


def take(pg, seconds):
    pg.ev("window.__u=[];")
    time.sleep(seconds)
    return json.loads(pg.ev("JSON.stringify(window.__u)"))


def info(pg):
    raw = pg.ev("JSON.stringify(__stateTogglesInfo?__stateTogglesInfo():[])") or '[]'
    return next((t for t in json.loads(raw) if t.get('id') == PID), None)


def preflight(url):
    try:
        with urllib.request.urlopen(url.split('#')[0], timeout=5) as r:
            return r.status == 200
    except Exception as exc:  # noqa: BLE001
        print('[FAIL] 服务不可达:', exc)
        return False


LIVE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  var t=(__stateTogglesInfo?__stateTogglesInfo():[]).find(function(x){
     return x.id===%s;})||null;
  var cur=null; try{ cur=m.internalModel.coreModel.getParameterValueById(%s); }catch(e){}
  var u=window.__u||[];
  return JSON.stringify({on:t&&t.on, tw:t&&t.tw, owned:t&&t.owned,
                         cur:(cur===null?null:+cur.toFixed(4)),
                         n:u.length, last:(u.length?u[u.length-1]:null)});
})()"""


def main():
    if not preflight(URL):
        return 2
    pg = Page(PORT, PROFILE, URL, (1400, 1000), gpu=True, keepalive=False)
    try:
        time.sleep(4)
        pg.ev(CLOSE_LOGIN); time.sleep(0.9)
        print('开卡:', pg.ev(OPEN_SHIP % json.dumps(KEY)), end=' '); time.sleep(1.6)
        print('选肤:', pg.ev(PICK_SKIN % json.dumps(KEY)), end=' '); time.sleep(1.3)
        print('切L2D:', pg.ev(TO_L2D))
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('打桩 core.update:', pg.ev(PATCH % json.dumps(PID)))
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(3.0)
        print('帧源闸: %.1f fps' % pg.require_frames(2.0))

        t = info(pg)
        print('\n① __stateTogglesInfo[%s]: %s' % (PID, t))
        if not t:
            print('[FAIL] 该皮肤没有 %s 的 STATE_TOGGLES 条目（本轮回归对象选错了？）' % PID)
            return 2
        if t.get('owned'):
            print('[FAIL] ①未让渡条目被误施加让渡（owned=true）—— 修法越界了')
            return 1
        print('   ① PASS owned=false')
        onV, offV = t['onV'], t['offV']

        scr = pg.ev(SCREEN_OF_HIT % json.dumps(t['trigger']))
        print('\n② trigger 区屏幕点:', scr)
        if scr in ('null', '', None):
            print('[FAIL] __L2_SCREENOF 定位不到 trigger 区:', t['trigger']); return 2
        sc = json.loads(scr)
        print('   网格命中 %s 个点，取点 (%s,%s)，离区边 %s 格'
              % (sc.get('n'), sc.get('cx'), sc.get('cy'), sc.get('edge')))

        fails = []
        seq = []
        for i in range(2):
            before = info(pg)['on']
            pre = json.loads(pg.ev(LIVE % (json.dumps(PID), json.dumps(PID))))
            print('\n第 %d 次点击前: _on=%s  raw(getParameterValueById)=%s  '
                  'entry_last=%s  tw=%s  owned=%s'
                  % (i + 1, pre['on'], pre['cur'], pre['last'], pre['tw'], pre['owned']))
            pg.ev("window.__u=[];")
            click(pg, sc['cx'], sc['cy'])
            time.sleep(0.30)
            early = json.loads(pg.ev(LIVE % (json.dumps(PID), json.dumps(PID))))
            time.sleep(1.5)
            late = json.loads(pg.ev(LIVE % (json.dumps(PID), json.dumps(PID))))
            vals = json.loads(pg.ev("JSON.stringify(window.__u)"))
            after = late['on']
            expect = offV if abs(before - onV) < 1e-6 else onV
            mids = [v for v in vals if v is not None and
                    min(onV, offV) + 1e-3 < v < max(onV, offV) - 1e-3]
            tail = [v for v in vals if v is not None][-20:]
            conv = bool(tail) and all(abs(v - expect) < 0.5 for v in tail)
            seq.append((before, after, expect, len(mids), conv, sorted(set(vals))))
            print('\n第 %d 次点击: _on %s → %s（期望 %s）' % (i + 1, before, after, expect))
            print('   0.30s 时: tw=%s cur=%s entry_n=%d last=%s'
                  % (early['tw'], early['cur'], early['n'], early['last']))
            print('   1.80s 时: tw=%s cur=%s entry_n=%d last=%s'
                  % (late['tw'], late['cur'], late['n'], late['last']))
            print('   update 入口 n=%d 帧，distinct 前 10=%s'
                  % (len(vals), sorted(set(vals))[:10]))
            print('   中间值 %d 个，尾 20 帧收敛到 %s: %s' % (len(mids), expect, conv))
            pg.require_frames(1.0)
            if abs(after - expect) > 1e-6:
                fails.append('第%d次点击 _on 没翻到另一端（%s→%s，期望 %s）'
                             % (i + 1, before, after, expect))
            if not conv:
                fails.append('第%d次点击后 update 入口未收敛到 %s（尾帧 %s，1.8s 时 cur=%s）'
                             % (i + 1, expect, tail[:6], late['cur']))
            if len(mids) < 3:
                fails.append('第%d次点击没有中间值（%d 个，1.8s 时 cur=%s）⇒ tween 没推进/瞬跳'
                             % (i + 1, len(mids), late['cur']))

        # ---------- ⑤ 阴性对照：点画面外 ----------
        before = info(pg)['on']
        click(pg, 2, 2)
        time.sleep(1.0)
        after = info(pg)['on']
        print('\n⑤ 阴性对照（点画面外 2,2）: _on %s → %s' % (before, after))
        if abs(after - before) > 1e-6:
            fails.append('阴性对照失败：点画面外也改变了 _on（%s→%s）⇒ 判据无区分力'
                         % (before, after))
        else:
            print('   PASS 点画面外不改变状态')

        print('\n' + '=' * 62)
        if seq:
            print('切换序列:', [(a, b) for a, b, *_ in seq])
        for f in fails:
            print('  FAIL', f)
        if not fails:
            print('  PASS ① owned 恒 false（未让渡条目零回归）')
            print('  PASS ② 真实点击 → _on 翻转，且 core.update 入口收敛到目标端')
            print('  PASS ③ 再点一次翻回（往返各一次都验）')
            print('  PASS ④ 每次切换都出现中间值（tween 真在推进）')
            print('  PASS ⑤ 阴性对照不改变状态')
        print('总判定:', 'PASS' if not fails else 'FAIL')
        return 0 if not fails else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
