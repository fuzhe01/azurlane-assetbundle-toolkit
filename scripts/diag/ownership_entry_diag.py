# -*- coding: utf-8 -*-
"""决定性测量：`pins` 写进去的值，到底有没有到达**渲染读到的那个值**——
分别在 `_costumeOwned=false`（未让渡）与 `=true`（已让渡）两种状态下测。

为什么必须做这一步（2026-10-28）：
  `l2d_costume_hotzone_verify.py` 的 ④ 层用 `pins` 把参数稳在 lo / hi 两端再比 drawable，
  实测「17 个 drawable 变化，但与 ShoseOff 驱动集合 [460,461] 的交集为空」⇒ 判 FAIL。
  但 ④b（pin 到 lo 后**真实点击**）却能拿到 24 个变化、参数 -1→1。
  两者唯一差别是**点击让 `_costumeOwned` 变 true**。于是有两种可能，处置完全相反：
    (a) 产品问题：让渡之后 pins 也到不了渲染；
    (b) 探针问题：④ 层是在**未让渡**状态下比的，那时 `stateApply` 每帧写 `_on`
        —— 正是本轮修掉的那个 bug，未让渡态本来就该"pin 无效"。
  用 `core.update` **入口**采样即可一次分清（入口值 = 渲染真正读到的值，
  而 `getParameterValueById` 只反映"最后一次写入"，两者会不一致）。

判据：
  阶段 A（未让渡）: pin lo / pin hi 时，entry 恒等于 `_on`（=stateCurOn，不随 pin 变）
  阶段 B（真实点击 → owned=true）
  阶段 C（已让渡）: pin lo → entry 收敛到 lo；pin hi → entry 收敛到 hi
  ⇒ A 恒 `_on` 且 C 跟随 pin = 探针问题(b)；A 与 C 都恒 `_on` = 产品问题(a)。

用法：py -3 scripts/diag/ownership_entry_diag.py
"""
import json
import os
import sys
import time

sys.path.insert(0, r'd:\azur\scripts\diag')
from gallery_ui_shots import Page  # noqa: E402

PID = 'ShoseOff'
KEY = 'ougen_8'
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

PIN = """(function(){var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
  if(!pm[%s]) pm[%s]=Object.create(null); pm[%s][%s]=%s; return 1;})()"""
UNPIN = """(function(){var pm=(window.__costumePinsByModel||{})[%s]||{}; delete pm[%s]; return 1;})()"""


def sample(pg, seconds=1.2):
    """在 core.update 入口连续采样，返回去重后的值集合与帧数。"""
    pg.ev("window.__u=[];")
    time.sleep(seconds)
    a = json.loads(pg.ev("JSON.stringify(window.__u)"))
    return sorted(set(a)), len(a)


def phase(pg, label, val):
    if val is None:
        pg.ev(UNPIN % (json.dumps(KEY), json.dumps(PID)))
    else:
        pg.ev(PIN % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY),
                     json.dumps(PID), json.dumps(val)))
    pg.require_frames(1.0)
    ds, n = sample(pg, 1.2)
    own = json.loads(pg.ev("JSON.stringify(__stateTogglesInfo())") or '[]')
    owned = (own[0] or {}).get('owned') if own else None
    time.sleep(0.35)
    ds2, n2 = sample(pg, 1.2)
    print('  %-14s pin=%-5s owned=%-5s entry%d帧=%s  (再采 %d 帧=%s)'
          % (label, val, owned, n, ds[:8], n2, ds2[:8]))
    return ds, owned


def main():
    pg = Page(9406, r'D:\azur\.diag\own_prof', URL, (1400, 1000), gpu=True, keepalive=False)
    try:
        time.sleep(4)
        pg.ev(CLOSE_LOGIN); time.sleep(0.9)
        print('开卡:', pg.ev(OPEN_SHIP), end=' '); time.sleep(1.6)
        print('选肤:', pg.ev(PICK_SKIN), end=' '); time.sleep(1.3)
        print('切L2D:', pg.ev(TO_L2D))
        t0 = time.time()
        while time.time() - t0 < 90:
            if pg.ev("(function(){return (window.__l2ModelRef&&window.__l2ModelRef())?1:0;})()") == 1:
                break
            time.sleep(1.0)
        print('打桩:', pg.ev(PATCH))
        print('解耦:', pg.detach_frames(60))
        time.sleep(3.0)
        print('帧源闸: %.1f fps' % pg.require_frames(2.0))
        print('  __stateTogglesInfo:', pg.ev("JSON.stringify(__stateTogglesInfo())"))

        print('\n阶段 A：未让渡（未点击）时，pins 能否到达渲染')
        a_lo, ownedA = phase(pg, 'A/pin-lo', -1)
        a_hi, _ = phase(pg, 'A/pin-hi', 1)
        pg.ev(UNPIN % (json.dumps(KEY), json.dumps(PID)))
        time.sleep(0.4)

        print('\n阶段 B：真实点击一次（走 onUp → costumeToggle）')
        scr = json.loads(pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID)))
        print('  屏幕点:', scr)
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': scr['cx'], 'y': scr['cy'],
                                                'button': 'left', 'clickCount': 1})
            time.sleep(0.08)
        time.sleep(2.0)
        print('  点击后 __stateTogglesInfo:', pg.ev("JSON.stringify(__stateTogglesInfo())"))
        pg.require_frames(1.0)
        ds, n = sample(pg, 1.0)
        print('  点击后 entry=%.1f帧=%s' % (n, ds[:8]))

        print('\n阶段 C：已让渡后，pins 能否到达渲染')
        c_lo, ownedC = phase(pg, 'C/pin-lo', -1)
        c_hi, _ = phase(pg, 'C/pin-hi', 1)
        pg.ev(UNPIN % (json.dumps(KEY), json.dumps(PID)))
        pg.require_frames(1.0)

        print('\n' + '=' * 62)
        A_follows = (set(a_lo) <= {-1.0} and set(a_hi) <= {1.0})
        C_follows = (set(c_lo) <= {-1.0} and set(c_hi) <= {1.0})
        print('阶段A pin 是否落到渲染 (未让渡):', A_follows, '  entry:', a_lo, a_hi)
        print('阶段C pin 是否落到渲染 (已让渡):', C_follows, '  entry:', c_lo, c_hi)
        if (not A_follows) and C_follows:
            print('结论: 探针问题 —— ④ 层必须在**已让渡**状态下用 pins 比；未让渡态本就该被 _on 覆盖')
        elif A_follows and C_follows:
            print('结论: 两种状态下 pin 都能到渲染 —— ④ 的 0 交集另有原因（数据/映射）')
        else:
            print('结论: 已让渡后 pin 仍到不了渲染 —— 产品问题（让渡分支没生效）')
    finally:
        pg.close()


if __name__ == '__main__':
    main()
