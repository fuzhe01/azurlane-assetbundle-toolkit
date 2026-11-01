"""决定性诊断：一次真实点击到底走了**哪条**产品路径（2026-10-29）。

为什么需要它
------------
`l2d_costume_hotzone_verify.py` 在 `ougen_8/ShoseOff` 上报「参数值没变(0→0)」，
但同一份输出里 pins 稳态 lo↔hi 的差异又**点名**到该参数的 5 个驱动件。
两个读数不能同口径解释，必须先把「点击有没有真的进到装扮切换」这件事本身测死，
否则会像前几轮那样在错误的层上反复改（假红 → 改产品 → 改坏真功能）。

产品里同一坐标有**三条互斥分支**（`gallery_src/index.html` onUp）：
  ① `stateFind(name)` 命中 → `toggleState`   —— 手工接线区（ougen_8 的鞋是 `touchdrag17`）
  ② `costumeHitAt` 命中 → `costumeToggle`    —— 参数型热区（本需求的主角）
  ③ 都没有 → 走动作组 `play()`
① 优先于 ② 是**故意**的（老的手工接线已验收，不能被自动热区盖掉）。
⇒ 「点鞋没反应」既可能是 ② 没进，也可能根本是 ① 抢先了 —— 这条必须先分清。

判据（不猜，全部读产品自己的副作用）
  ① `__costumeLog` 新增条目      —— 只有 `costumeToggle` 写它（onUp 走 ② 的硬证据）
  ② `#l2Hit` 提示文字            —— ①写「<label> ▸ on/off」、②写「<label> · <id> → <to>」
  ③ `pins[ShoseOff]` 是否被写    —— ② 会立刻接管 pin；① 不碰 pins（改的是 t._on）
  ④ `__stateTogglesInfo()` 的 `_last/_on/_tw` —— ① 走这条时这些会变
  ⑤ 参数读数（core + pin）三处齐读，用来分清「值被拉回」与「压根没写」

用法:
  py -3 scripts/diag/l2d_click_path_diag.py [模型key] [参数id]
  py -3 scripts/diag/l2d_click_path_diag.py ougen_8 ShoseOff
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'


def preflight(url):
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达: %s' % e)
        return False


# 点击四周的**全量副作用**（一次 evaluate 取齐，避免多次往返之间状态又变）
STATE = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, id=%s;
  var pin=(window.__costumePinsByModel||{})[%s]||{};
  var tw=(window.__costumeTweens||{})[%s]||{};
  var log=(window.__costumeLog||[]).slice(-6);
  var pill=(document.getElementById('l2Hit')||{}).textContent||'';
  var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]);
  var s=null; for(var i=0;i<st.length;i++) if(st[i].id===id) s=st[i];
  var v=null; try{ v=+c.getParameterValueById(id).toFixed(4); }catch(e){}
  return JSON.stringify({v:v, pin:(pin[id]===undefined?null:pin[id]),
    tween:(tw[id]?{from:tw[id].from,to:tw[id].to}:null),
    logLen:(window.__costumeLog||[]).length, log:log, pill:pill,
    st:(s?{owned:s.owned,on:s.on,tw:s.tw}:null),
    grp:(m.internalModel.motionManager.state.currentGroup||'null')});
})()
"""


def main():
    if not preflight(BASE):
        return 2
    pg = Page(9406, r'D:\azur\.diag\czh_prof', BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('开卡:', pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()""" % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                             % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
        for _ in range(60):
            if pg.ev("(function(){ return ((window.__l2ModelRef&&__l2ModelRef())"
                     " && window.__costumeBoxes && __costumeBoxes().length) ? 1 : 0; })()") == 1:
                break
            time.sleep(1.0)
        if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") != 1:
            print('[FAIL] 模型未加载'); return 2
        print('帧源:', pg.detach_frames(60))
        time.sleep(2.5)
        print('  fps %.1f' % pg.require_frames(2.0))

        state = STATE % (json.dumps(PID), json.dumps(KEY), json.dumps(KEY))
        sc = json.loads(pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID)) or 'null')
        if not sc:
            print('[FAIL] 该参数热区在视口内点不到'); return 1
        cx, cy = sc['cx'], sc['cy']
        print('\n屏幕点 (%d,%d)  edge=%s' % (cx, cy, sc.get('edge')))

        # 三条分支各自的命中情况**在同一个时刻**取，否则「①抢先」这个结论无法成立
        probe = """(function(){
          var r=window.__l2ModelRef().app.renderer;
          var wrap=(document.querySelector('#l2wrap')||document.querySelector('#l2stage')||{});
          return JSON.stringify({
            costume:(typeof window.__costumeHit==='function'?(window.__costumeHit(%d,%d)||{}).id||null):'NO_FN',
            handarea:(typeof window.__L2_HIT==='function'?window.__L2_HIT(%d,%d):'NO_FN'),
            handall:(typeof window.__L2_HITALL==='function'?window.__L2_HITALL(%d,%d):'NO_FN')
          });})()""" % (cx, cy, cx, cy, cx, cy)
        print('同时刻三路命中:', pg.ev(probe))

        s0 = json.loads(pg.ev(state))
        print('\n点击前:', json.dumps(s0, ensure_ascii=False))

        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': cx, 'y': cy,
                                               'button': 'left', 'clickCount': 1})
            time.sleep(0.08)
        print('   已派发 mousePressed/mouseReleased')

        for tag, wait in (('+0.35s', 0.35), ('+1.2s', 0.85), ('+3.0s', 1.8)):
            time.sleep(wait)
            s = json.loads(pg.ev(state))
            print('\n点击后 %s:' % tag, json.dumps(s, ensure_ascii=False))
            if s.get('logLen', 0) > s0.get('logLen', 0):
                print('   ★ costumeLog 新增 %d 条 ⇒ onUp 走的是 ② costumeToggle（参数热区）'
                      % (s['logLen'] - s0['logLen']))
            elif '→' in (s.get('pill') or ''):
                print('   ★ 提示文字含 "→" ⇒ 走的是 ② costumeToggle')
            elif '▸' in (s.get('pill') or ''):
                print('   ★ 提示文字含 "▸" ⇒ 走的是 ① toggleState（手工接线区抢先）')
            else:
                print('   ⚠️ 提示文字未变、costumeLog 未增 ⇒ 三条分支都没进'
                      '（点击落在空白/动作区，或 onDown 的 freshGeo 没命中）')

        print('\n' + '=' * 62)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
