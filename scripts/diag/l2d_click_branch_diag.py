"""同一屏幕点为何有时走 ①（手工状态区）、有时走 ②（参数热区）——2026-10-29。

结论先行（本探针要证或否证的东西）
--------------------------------
产品 `onUp` 两支顺序是 ① `stateFind(localHit)` → ② `costumeHitAt(freshGeo)`。
① 的名字来自 `hitAt()`，而 `hitAt` 对**同一坐标的重叠判定区会随机挑一个**（A3 规则：
集合里多于一个时随机，且避开上一次刚播过的那个）。`ougen_8` 的 `touchdrag17`
（拖鞋那个 TouchDrag 标记）与鞋的参数热区 `ShoseOff` 在屏幕上是**同一个部位**。
⇒ 预测：同一坐标点击，命中集合含 `touchdrag17` 的那几轮会走 ①（且 `touchdrag17`
恰好是随机选中的那个），其余轮走 ②。① 写的是 `_on`（-1/1 硬切、无 pin、无 tween），
② 写的是 `pins` + 1 秒渐变 —— 两支对同一参数语义不同，用户看到的就是「点鞋时灵时不灵」。

🔴 **本探针禁止开推帧泵**（`detach_frames`）
  2026-10-29 实测：`setInterval(...,4)` 每次最多跑 3 次 `ticker.update()`，单次 20–30 ms
  ⇒ 主线程被占满 ⇒ **连 `1+1` 这种不含产品代码的 CDP 往返都从 31 ms 涨到 1882 ms**，
  `mousePressed`→`mouseReleased` 墙钟间隔 4.6 秒。而产品正是靠这两个时刻的几何判命中
  （`onDown` 的 `cosDown` + `onUp` 的补算）⇒ 间隔 4.6 秒时必然判到两个不同姿态，
  输出「三条分支都没进」的**假红**。这就是 `l2d_costume_hotzone_verify.py` 恒 FAIL 的真因。
  代价：不开泵时出帧靠真 rAF（实测 40.5 fps，keepalive 下稳定）。为防文档记载的
  「加载后 18–30 秒衰减到 1 Hz」，每轮点击前重发一次 `Page.bringToFront`。

判据
----
· `hitAll` 含 `touchdrag17` 且 `__L2_HIT` 返回 `touchdrag17` ⇒ 走 ①（pill 含 `▸`、`_on` 反向、无 pin）
· 否则 ⇒ 走 ②（`__costumeLog` +1、`pins` 被写、pill 含 `→`）
· 任何一轮「三条分支都没进」⇒ 先看「按下→抬起墙钟间隔」；>500 ms 即仪器无效，不许归因产品

用法:
  py -3 scripts/diag/l2d_click_branch_diag.py [模型key] [参数id] [轮数]
  py -3 scripts/diag/l2d_click_branch_diag.py ougen_8 ShoseOff 8
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
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 8
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = 9412
PROF = r'D:\azur\.diag\branch_prof'

READ = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, id='__ID__', pk='__KEY__';
  var pm=(window.__costumePinsByModel||{})[pk]||{};
  var lg=window.__costumeLog||[];
  var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]);
  var s=null; for(var i=0;i<st.length;i++) if(st[i].id===id) s=st[i];
  var v=null; try{ v=+c.getParameterValueById(id).toFixed(3); }catch(e){}
  var pill=(document.getElementById('l2Hit')||{}).textContent||'';
  var tw=((window.__costumeTweens||{})[pk]||{})[id];
  return JSON.stringify({v:v, pin:(pm[id]===undefined?null:pm[id]),
    tw:(tw?{to:+tw.to.toFixed(3)}:null), logLen:lg.length,
    on:(s?s.on:null), owned:(s?s.owned:null), pill:pill,
    grp:(m.internalModel.motionManager.state.currentGroup||'null')});
})()""".replace('__ID__', PID).replace('__KEY__', KEY)

RESET = r"""(function(){var pk='__KEY__', id='__ID__';
  var pm=(window.__costumePinsByModel||{})[pk]; if(pm) delete pm[id];
  var tw=(window.__costumeTweens||{})[pk]; if(tw) delete tw[id];
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(m){ var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]);
    for(var i=0;i<st.length;i++) if(st[i].id===id){ st[i].owned=false; } }
  return 'ok';})()""".replace('__ID__', PID).replace('__KEY__', KEY)

SNAP = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, n=core.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){ var op=0;
    try{ op=+core.getDrawableOpacity(i); }catch(e){}
    out.push(+op.toFixed(3)); }
  return JSON.stringify({n:n,rows:out});
})()"""


def j(expr, pg, tag=None):
    t0 = time.time()
    out = pg.ev(expr)
    if tag:
        print('     [t] %-18s %.0f ms' % (tag, (time.time() - t0) * 1000))
    try:
        return json.loads(out)
    except Exception:  # noqa: BLE001
        return {'err': str(out)[:200]}


def diff(a, b):
    ra, rb = a.get('rows') or [], b.get('rows') or []
    n = min(len(ra), len(rb))
    idx = [i for i in range(n) if abs(ra[i] - rb[i]) > 0.02]
    return len(idx), idx[:12]


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP %s' % r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达: %s' % e); return 2

    pg = Page(PORT, PROF, BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('开卡:', pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key==%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK';})()""" % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k==%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                             % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
        for _ in range(60):
            if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") == 1:
                break
            time.sleep(1.0)
        if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") != 1:
            print('[FAIL] 模型未加载'); return 2
        print('🔴 不调用 detach_frames（推帧泵会把 CDP 往返抬到秒级，见文件头）')
        # 只用 rAF 原生出帧；测一下往返与帧源是否健康
        t0 = time.time(); pg.ev('1+1'); rtt = (time.time() - t0) * 1000
        print('CDP 往返 1+1: %.0f ms   帧源 ticker.lastTime 是否推进: %s'
              % (rtt, pg.ev("(function(){var t=window.__l2TickerState&&__l2TickerState();"
                            " return t?JSON.stringify({last:t.lastTime}):'NONE';})()")))
        time.sleep(1.0)
        a = pg.ev("(function(){var t=window.__l2TickerState&&__l2TickerState(); return t?t.lastTime:-1;})()")
        time.sleep(1.5)
        b = pg.ev("(function(){var t=window.__l2TickerState&&__l2TickerState(); return t?t.lastTime:-1;})()")
        print('帧源推进: %.0f ms / 1.5s（>1000 即 rAF 在跑）' % (b - a))
        if b - a < 500:
            print('[INVALID] rAF 停摆，本次读数全部无效'); return 2

        # 这个参数的所有“名字来源”：手工状态区的 trigger 名
        trig = pg.ev("(function(){var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]);"
                     " var o=[]; for(var i=0;i<st.length;i++) if(st[i].id===%s)"
                     " o.push(st[i].trigger); return o.join(',');})()" % json.dumps(PID))
        print('该参数的手工状态区 trigger:', trig)

        rows = []
        for rnd in range(1, ROUNDS + 1):
            print('\n' + '-' * 60)
            print('第 %d 轮' % rnd)
            t0 = time.time(); pg.cmd('Page.bringToFront')
            print('     [t] bringToFront      %.0f ms' % ((time.time() - t0) * 1000))
            t0 = time.time(); pg.ev(RESET)
            print('     [t] RESET              %.0f ms' % ((time.time() - t0) * 1000))
            time.sleep(0.35)
            sc = j("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID), pg, 'ScreenOf')
            if not sc:
                print('  [SKIP] ScreenOf 取不到点'); continue
            cx, cy = sc['cx'], sc['cy']
            hit = j("JSON.stringify(window.__L2_HIT(%d,%d))" % (cx, cy), pg, '__L2_HIT')
            all_ = j("JSON.stringify(window.__L2_HITALL(%d,%d))" % (cx, cy), pg, '__L2_HITALL')
            print('  点 (%d,%d) edge=%s  含点候选=%s  本次抽中=%r'
                  % (cx, cy, sc.get('edge'),
                     all_ if isinstance(all_, list) else all_, hit))
            s0 = j(READ, pg, 'READ')
            sn0 = j(SNAP, pg, 'SNAP')
            t0 = time.time()
            pg.cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': cx, 'y': cy,
                                               'button': 'left', 'clickCount': 1})
            t1 = time.time()
            time.sleep(0.08)
            t2 = time.time()
            pg.cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': cx, 'y': cy,
                                               'button': 'left', 'clickCount': 1})
            t3 = time.time()
            gap = (t1 - t0) * 1000 + 80 + (t3 - t2) * 1000
            print('  按下→抬起墙钟间隔 %.0f ms' % gap)
            time.sleep(1.5)
            s1 = j(READ, pg, 'READ after')
            sn1 = j(SNAP, pg, 'SNAP after')
            nch, chg = diff(sn0, sn1)
            print('  点前 v=%s pin=%s on=%s logLen=%s owned=%s pill=%r'
                  % (s0.get('v'), s0.get('pin'), s0.get('on'), s0.get('logLen'),
                     s0.get('owned'), s0.get('pill')))
            print('  点后 v=%s pin=%s on=%s logLen=%s owned=%s pill=%r'
                  % (s1.get('v'), s1.get('pin'), s1.get('on'), s1.get('logLen'),
                     s1.get('owned'), s1.get('pill')))
            print('  画面变化 %d 件 %s' % (nch, chg))
            dlog = (s1.get('logLen') or 0) - (s0.get('logLen') or 0)
            if dlog > 0 or s1.get('pin') is not None:
                br = '② costumeToggle'
            elif '▸' in (s1.get('pill') or ''):
                br = '① toggleState'
            else:
                br = '都不是'
            print('  => %s（log+%d, pin=%s, 画面变化 %d）'
                  % (br, dlog, s1.get('pin'), nch))
            cand = all_ if isinstance(all_, list) else []
            rows.append(dict(rnd=rnd, cand=cand, pick=hit, br=br, nch=nch,
                             dv=((s1.get('v') or 0) - (s0.get('v') or 0)),
                             gap=gap))

        print('\n' + '=' * 74)
        print('%-3s %-46s %-16s %s' % ('轮', '含点候选（判定区）', '本次抽中', '落到'))
        for r in rows:
            print('%-3d %-46s %-16s %s (v%+.2f, 变化%d)'
                  % (r['rnd'], ','.join(r['cand'])[:46], str(r['pick'])[:16],
                     r['br'], r['dv'], r['nch']))
        print('=' * 74)
        bad = [r for r in rows if r['br'] == '都不是']
        print('未进任何分支的轮次: %d/%d' % (len(bad), len(rows)))
        if bad and min(r['gap'] for r in bad) > 500:
            print('⚠️ 这些轮次的点击派发间隔 >500 ms ⇒ **仪器无效**，不构成产品缺陷证据')
        b1 = [r for r in rows if r['br'].startswith('①')]
        b2 = [r for r in rows if r['br'].startswith('②')]
        print('① 轮次 %d 次，② 轮次 %d 次' % (len(b1), len(b2)))
        if b1 and b2:
            print('⇒ **同一坐标两支都会发生**：① 由 `hitAt` 的随机抽取决定（A3 规则），')
            print('  两支对同一参数语义不同（① 硬切 _on 无 tween，② pins + 渐变）⇒ 用户看到时灵时不灵。')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
