"""隔离「点击前的准备动作」是否会让真实点击失效（2026-10-29）。

为什么需要它
------------
`l2d_click_path_diag.py`（不 prepare）实测：点 (556,335) → `pins[ShoseOff]` 被写、
`__costumeLog` +1、`owned:true`、参数 0→1 ⇒ onUp 的 ② 分支（参数型互动区）**本身是好的**。

但 `l2d_costume_hotzone_verify.py` 在**同一个参数、同一台机器**上点击恒为
`pin=None` / 参数 0→0 / `owned:false` ⇒ ② 从未被调用。两份脚本的点击派发代码逐字相同
（`Input.dispatchMouseEvent` mousePressed→mouseReleased，间隔 80ms），唯一差别是准备动作：

    verify 在取屏幕点之前做了
      ① `mm.queueManager.stopAllMotions()` + `mm.state.complete()`
      ② 一次 `__costumeScreenOf(id)` 网格反解（同步阻塞主线程约 300 ms，上千次几何判定）
      ③ 取 `SNAP`（遍历 842 个 drawable 顶点，同步阻塞数百 ms）
      ④ 派发前用 `__costumeHit(cx,cy)` 复核命中

三者任一都可能让真实点击落空：
  · `state.complete()` 之后 motionManager 会在下一帧 startRandomMotion(idle)，
    姿态在两个 pointer 事件之间重新开始演化 ⇒ 按下与抬起判到不同的几何；
  · 长时间的同步阻塞会让「按下」与「抬起」之间跨过多次 ticker 更新 ⇒ 同理；
  · 或者事件根本没有到达 `#l2wrap`（被别的元素盖住）⇒ onDown 没跑、`dragging` 恒 false。

本探针把这三件事做成**开关**，同一坐标、同一次运行里对比 4 组：
    A 裸点（对照，等价 click_path_diag）
    B 只 stopMotions+complete
    C 只先跑一次 ScreenOf + SNAP（同步阻塞）
    D B+C（等价 verify 的准备）
并在**安装捕获阶段的全局事件监听**，记录 pointerdown/pointerup 的 `target` 与坐标 ——
这一条能直接回答「事件到底进没进 #l2wrap」，而不用靠推测。

判据（全部读产品自己的副作用）
  · `dragging`：靠 onUp 的后续副作用间接判（若无任何分支生效 = 事件没到 / moved>=6）
  · `__costumeLog` 增量     ⇒ ② 进入（costumeToggle 被调用）
  · `pins[ShoseOff]` 被写   ⇒ ② 进入
  · pill 含 `▸`            ⇒ ① 进入（手工状态区抢先）
  · pill 含 `→`            ⇒ ② 进入
  · `evt` 记录里的 target    ⇒ 事件是否到达 wrap（DOM 层）

用法:
  py -3 scripts/diag/l2d_click_prep_diag.py [模型key] [参数id]
  py -3 scripts/diag/l2d_click_prep_diag.py ougen_8 ShoseOff
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
PORT = 9408
PROF = r'D:\azur\.diag\czh4_prof'

# 捕获阶段的事件记录（target 能直接回答「事件有没有到 #l2wrap」）
EVLOG_INSTALL = r"""(function(){
  window.__pdLog=[];
  function rec(e){
    var t=e.target||{};
    window.__pdLog.push({ty:e.type, tx:e.clientX, ty2:e.clientY, b:e.button,
      tg:(t.id||t.className||t.nodeName||'?')+'',
      tag:(t.tagName||'?')+''});
    if(window.__pdLog.length>40) window.__pdLog.shift();
  }
  ['pointerdown','pointerup','mousedown','mouseup','pointercancel'].forEach(function(n){
    window.addEventListener(n, rec, true); });
  return 'OK';
})()"""

EVLOG_READ = r"""(function(){ return JSON.stringify(window.__pdLog||[]); })()"""

# 点前后一次取齐的全量副作用
READ = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, id='__ID__', pk='__KEY__';
  var pin=(window.__costumePinsByModel||{})[pk]||{};
  var tw=((window.__costumeTweens||{})[pk])||{};
  var g=(window.__costumeGeoByModel||{})[pk]||[];
  var tgt=null; for(var i=0;i<g.length;i++) if(g[i].id===id) tgt=g[i];
  var bx=tgt?tgt.box:null;
  var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]);
  var s=null; for(var k=0;k<st.length;k++) if(st[k].id===id) s=st[k];
  var v=null; try{ v=+c.getParameterValueById(id).toFixed(4); }catch(e){}
  var pill=(document.getElementById('l2Hit')||{}).textContent||'';
  return JSON.stringify({
    v:v, pin:(pin[id]===undefined?null:pin[id]),
    tw:(tw[id]?{from:+tw[id].from.toFixed(3), to:+tw[id].to.toFixed(3)}:null),
    logLen:(window.__costumeLog||[]).length,
    pill:pill, st:(s?{owned:s.owned,on:s.on,tw:s.tw}:null),
    grp:(m.internalModel.motionManager.state.currentGroup||'null'),
    ibox:(bx?{x0:+bx.x0.toFixed(2),y0:+bx.y0.toFixed(2),x1:+bx.x1.toFixed(2),y1:+bx.y1.toFixed(2)}:null)});
})()""".replace('__ID__', PID).replace('__KEY__', KEY)

SNAP = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, n=core.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){
    var op=0; try{ op=+core.getDrawableOpacity(i); }catch(e){}
    out.push([i,+op.toFixed(4)]);
  }
  return JSON.stringify({n:n,rows:out});
})()"""

STOPMOTIONS = r"""(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m) return 'NO_MODEL';
  try{ m.internalModel.motionManager.queueManager.stopAllMotions(); }catch(e){}
  try{ m.internalModel.motionManager.state.complete(); }catch(e){}
  return 'OK';})()"""


def preflight(url):
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达: %s' % e)
        return False


def read(pg):
    t0 = time.time()
    out = pg.ev(READ)
    print('     [t] read %.0f ms' % ((time.time() - t0) * 1000))
    try:
        return json.loads(out)
    except Exception:  # noqa: BLE001
        return {'err': out}


def click(pg, cx, cy):
    for typ in ('mousePressed', 'mouseReleased'):
        t0 = time.time()
        pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': cx, 'y': cy,
                                           'button': 'left', 'clickCount': 1})
        print('     [t] %s 返回 %.0f ms' % (typ, (time.time() - t0) * 1000))
        time.sleep(0.08)


def point_of(pg):
    """与产品同一条反解（__costumeScreenOf），并紧贴复核命中。"""
    t0 = time.time()
    sc = json.loads(pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID)) or 'null')
    print('     [t] ScreenOf %.0f ms -> %s' % ((time.time() - t0) * 1000,
                                              None if not sc else (sc['cx'], sc['cy'])))
    if not sc:
        return None
    for i in range(4):
        t1 = time.time()
        hn = json.loads(pg.ev("JSON.stringify(window.__costumeHit(%d,%d))"
                              % (sc['cx'], sc['cy'])) or 'null')
        print('     [t] 命中复核#%d %.0f ms -> %s' % (i, (time.time() - t1) * 1000,
                                                   None if not hn else hn.get('id')))
        if hn and hn.get('id') == PID:
            return sc
        time.sleep(1.0)
        t2 = time.time()
        sc = json.loads(pg.ev("JSON.stringify(window.__costumeScreenOf(%s))"
                              % json.dumps(PID)) or 'null')
        print('     [t] 重取点 %.0f ms' % ((time.time() - t2) * 1000))
        if not sc:
            return None
    return None


def main():
    if not preflight(BASE):
        return 2
    pg = Page(PORT, PROF, BASE, (1400, 1000), gpu=True, keepalive=True)
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
        print('事件记录器:', pg.ev(EVLOG_INSTALL))
        print('wrap 存在:', pg.ev("!!document.getElementById('l2wrap')"))

        # 四组：A 裸点 / B 只 stopMotions / C 只同步阻塞(ScreenOf+SNAP) / D 全 prep（等价 verify）
        groups = [('A 裸点（对照）', False, False),
                  ('B 只 stopMotions+complete', True, False),
                  ('C 只 ScreenOf+SNAP 阻塞', False, True),
                  ('D 全 prep（等价 verify）', True, True)]
        verdicts = {}
        for name, do_stop, do_block in groups:
            print('\n' + '-' * 62)
            print('组 %s' % name)
            # 每组开始前清掉本探针写过的 pin/tween，回到「未让渡 + 无 pin」起点
            pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]; if(pm) delete pm[%s];
              var tw=(window.__costumeTweens||{})[%s]; if(tw) delete tw[%s];
              return 1;})()""" % (json.dumps(KEY), json.dumps(PID),
                                  json.dumps(KEY), json.dumps(PID)))
            time.sleep(0.3)
            if do_stop:
                print('   prep: stopAllMotions ->', pg.ev(STOPMOTIONS))
                time.sleep(1.2)
            if do_block:
                t0 = time.time()
                pg.ev(SNAP)
                _ = point_of(pg)
                print('   prep: 同步阻塞 %d ms（SNAP + ScreenOf）' % int((time.time() - t0) * 1000))
            pg.ev("(function(){ window.__pdLog=[]; return 1; })()")
            sc = point_of(pg)
            if not sc:
                print('   [SKIP] 取不到合法命中点'); verdicts[name] = 'NO_POINT'; continue
            cx, cy = sc['cx'], sc['cy']
            elem = pg.ev("(function(){var e=document.elementFromPoint(%d,%d);"
                         " if(!e) return 'NONE'; return (e.id||e.className||e.tagName)+'';})()"
                         % (cx, cy))
            print('   点 (%d,%d) edge=%s 命中复核=%s  elementFromPoint=%s'
                  % (cx, cy, sc.get('edge'),
                     pg.ev("JSON.stringify(window.__costumeHit(%d,%d))" % (cx, cy))[:60], elem))
            s0 = read(pg)
            click(pg, cx, cy)
            time.sleep(1.6)
            s1 = read(pg)
            ev = json.loads(pg.ev(EVLOG_READ) or '[]')
            print('   点前: v=%s pin=%s logLen=%s owned=%s pill=%r'
                  % (s0.get('v'), s0.get('pin'), s0.get('logLen'),
                     (s0.get('st') or {}).get('owned'), s0.get('pill')))
            print('   点后: v=%s pin=%s logLen=%s owned=%s pill=%r'
                  % (s1.get('v'), s1.get('pin'), s1.get('logLen'),
                     (s1.get('st') or {}).get('owned'), s1.get('pill')))
            print('   按下前后事件: %s'
                  % json.dumps([(e['ty'], e['tg'], e['tx'], e['ty2'], e['b']) for e in ev],
                               ensure_ascii=False))
            hit2 = (s1.get('logLen', 0) > s0.get('logLen', 0)) or (s1.get('pin') is not None)
            if hit2:
                verdicts[name] = '② costumeToggle 命中'
            elif '▸' in (s1.get('pill') or ''):
                verdicts[name] = '① toggleState 命中'
            else:
                verdicts[name] = '三条分支都没进（事件没到 / moved>=6 / 命中判空）'
            print('   => %s' % verdicts[name])
            # 复原：把这次点击造成的状态清掉，避免串到下一组
            pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]; if(pm) delete pm[%s];
              var tw=(window.__costumeTweens||{})[%s]; if(tw) delete tw[%s];
              var s=(window.__stateTogglesInfo?__stateTogglesInfo():[]);
              return 1;})()""" % (json.dumps(KEY), json.dumps(PID),
                                  json.dumps(KEY), json.dumps(PID)))
            try:
                pg.ev("""(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
                  if(!m) return 0; var c=m.internalModel.coreModel;
                  var ix=c.getParameterIndex(%s);
                  if(ix>=0) c.setParameterValueById(%s, c.getParameterDefaultValue(ix));
                  return 1;})()""" % (json.dumps(PID), json.dumps(PID)))
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.6)

        print('\n' + '=' * 62)
        for k, v in verdicts.items():
            print('  %-28s %s' % (k, v))
        print('=' * 62)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
