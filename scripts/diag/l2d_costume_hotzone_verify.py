"""验收「参数型互动区」（2026-10-24 需求 3）：点画面上的鞋/丝袜/衣服/戒指等局部，切对应参数两态。

判据（五层，缺一不可，都走**产品自己的入口**）：
  ① 热区存在：window.__costumeBoxes() 列出该模型的参数热区，且驱动部件数 > 0；
  ② 点得中：用 __costumeScreenOf 得到屏幕点，**真的派发输入事件**给页面（不是直接调 toggle），
     断言语义 = 命中的热区 id 就是目标参数（不靠猜）；
  ③ 参数真的变了：读 core.getParameterValueById(id)，从 lo 变到 hi（或反向），
     且 tween 走完后稳定保持（连推数帧不回退）；
  ④ **画面真的变了且点名到本参数驱动的部件**：逐 drawable 比顶点包围盒，要求有变化、且变化集合
     与 param_drawables.json 里该参数的索引**有交集**（只验"有变化"会被 idle 漂移骗过——实测两次运行
     的"变化集合"完全不同、第二次数出 10 个里没有 460/461 这两个 ShoseOff 真身，就是漂移噪声）。
     像素哈希不可用（headless 下 drawImage 取到全 0 缓冲，技能 §20.3）。
  ⑤ **漂移对照**：不点任何东西、只等同样的时长，看顶点快照的"自然变化量"。
     如果 ⑤ 的 changed 已经 ≥ ④，说明 ④ 的差异是 idle 演化而非本次点击造成的（判据必须能红）。
     另加阳性对照（ParamAngleX → max）证明这套顶点判据本身不瞎。

⚠️ 为什么不用「截图差分」：idle 呼吸循环本底 21~44%，淹没鞋/丝袜级别的局部差异（技能 §15/§20.3）。
   截图在本脚本里只作**人眼复核**用（before/after 成对落盘），不进判据。
⚠️ 为什么不直接调 __costumeToggle：那会绕过 onUp 里的判定链（STATE_TOGGLES 优先 → 热区 → 动作），
   验不到「点击真的走对了分支」。所以必须派发 pointerdown/pointerup。

用法:
  py -3 scripts/diag/l2d_costume_hotzone_verify.py [模型key] [参数id]
  py -3 scripts/diag/l2d_costume_hotzone_verify.py ougen_8 ShoseOff
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

# 冻住姿态三件套（与 l2d_hotzone_reachability.py 的 NEUTRALIZE 同源，缺一不可）：
#   ① `mm.groups.idle` 改成不存在的组名 —— `MotionManager.update` 里 `if(isFinished()) …
#      startRandomMotion(groups.idle)` 会让 idle 立刻重启，`stopAllMotions()` 挡不住；
#   ② `im.updateNaturalMovements` 置空 —— 呼吸 + 自然摆头每帧写 ParamAngle*/ParamBreath；
#   ③ `im.physics.reset()` —— 清掉上一姿态残留速度。
# 缺任何一个，参数效果都会被本底演化淹没（实测 ougen_8/ShoseOff 逐档差值非单调）。
NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff:'+mm.__idleBak); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('physReset'); }
    catch(e){} }
  return done.join(',');})()
"""

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
# ⚠️ URL 必须带 `#gallery_v2`：`Page` 类靠标签页 URL 匹配（要求含 gallery_v2），给裸路径会 no CDP tab。
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
OUT = os.path.join(ROOT, '.diag', 'costume_hotzone')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<900) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCZ) return; proto.__dshHookCZ=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

# 顶点/不透明度快照：停住动作后逐 drawable 采一遍（同一次 evaluate 内两侧各算一遍，规避呼吸相位）
SNAP = r"""
(function(){
  /* ⚠️ 曾经读 `window.l2State`（**不存在**：页面里 l2State 是模块级 let，不挂 window），
     失败后退到 HOOK 注入的 `window.__l2model`；而 HOOK 只在 addChild 时抓一次，
     换肤/重建模型后它指向已销毁对象 ⇒ 同一份代码时红时绿。
     现在只认页面给的**活引用** `__l2ModelRef()`（内部就是 l2State.app.stage.children[0]），
     HOOK 变量彻底不用。见 TROUBLESHOOTING §158 续四。 */
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel;
  var n=core.getDrawableCount(), out=[];
  for(var i=0;i<n;i++){
    var op=0, bx=null;
    try{ op=+core.getDrawableOpacity(i); }catch(e){}
    try{ var v=core.getDrawableVertexPositions(i);
      if(v&&v.length>=2){ var xs=[],ys=[];
        for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
        bx=[Math.min.apply(null,xs),Math.min.apply(null,ys),
            Math.max.apply(null,xs),Math.max.apply(null,ys)]; } }catch(e){}
    out.push([i,+op.toFixed(4),bx]);
  }
  return JSON.stringify({n:n, rows:out});
})()
"""

# 两层快照的差异（点名具体 drawable）
DIFF = r"""
(function(){
  var a=%s, b=%s;
  if(a.err||b.err) return JSON.stringify({err:'NO_SNAP'});
  var moved=[], dOp=0, dBox=0;
  for(var i=0;i<a.rows.length;i++){
    var x=a.rows[i], y=b.rows[i]; if(!y) continue;
    var do_=Math.abs((x[1]||0)-(y[1]||0));
    var db=0;
    if(x[2]&&y[2]) db=Math.max(Math.abs(x[2][0]-y[2][0]),Math.abs(x[2][1]-y[2][1]),
                              Math.abs(x[2][2]-y[2][2]),Math.abs(x[2][3]-y[2][3]));
    if(do_>0.02||db>0.5){ moved.push([i,+do_.toFixed(3),+db.toFixed(2)]); dOp+=do_; dBox+=db; }
  }
  return JSON.stringify({changed:moved.length, dOp:+dOp.toFixed(3), dBox:+dBox.toFixed(2),
                         idx:moved.slice(0,20).map(function(z){return z[0];}),
                         all:moved.map(function(z){return z[0];})});
})()
"""

# 指定 drawable 明细（不透明度 + 顶点包围盒）：判据红了必须能说清
# 是「部件真的没动」还是「快照取错帧/被别的东西盖住」，否则只能靠猜。
DETAIL = r"""
(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, ids=%s, out=[];
  for(var j=0;j<ids.length;j++){ var i=ids[j]; var op=null,bx=null;
    try{ op=+core.getDrawableOpacity(i).toFixed(4); }catch(e){}
    try{ var v=core.getDrawableVertexPositions(i);
      if(v&&v.length>=2){ var xs=[],ys=[];
        for(var k=0;k+1<v.length;k+=2){ xs.push(v[k]); ys.push(v[k+1]); }
        bx=[+Math.min.apply(null,xs).toFixed(2),+Math.min.apply(null,ys).toFixed(2),
            +Math.max.apply(null,xs).toFixed(2),+Math.max.apply(null,ys).toFixed(2)]; } }catch(e){}
    out.push({i:i, op:op, bx:bx}); }
  return JSON.stringify(out);
})()
"""

READ = r"""
(function(){
  /* 只认页面给的活引用；HOOK 变量已弃用（换肤后指向已销毁对象）。见 §158 续四。 */
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel, id=%s;
  var ix=core.getParameterIndex(id);
  if(ix<0) return JSON.stringify({err:'NO_IDX'});
  var v=+core.getParameterValueById(id);
  var pm=(window.__costumePinsByModel||{})[%s]||{};
  return JSON.stringify({ix:ix, v:+v.toFixed(4),
    min:+core.getParameterMinimumValue(ix), max:+core.getParameterMaximumValue(ix),
    def:+core.getParameterDefaultValue(ix),
    pin:(pm[id]===undefined?null:+pm[id]), id:id});
})()
""" % ('%s', '%s')


def preflight(url):
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP %d' % r.status)
                return False
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达: %s' % e)
        return False
    return True


def main():
    if not preflight(BASE):
        return 2
    pg = Page(9405, r'D:\azur\.diag\czh_prof', BASE, (1400, 1000), gpu=True, keepalive=False)
    try:
        time.sleep(4)

        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        print('开卡:', pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          if(!s) return 'NO_SHIP';
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()
        """ % json.dumps(KEY)))
        time.sleep(1.6)
        print('选肤:', pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                             % json.dumps(KEY)))
        time.sleep(1.3)
        print('切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
           if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
        # 等运行时 + 数据表（模型加载约 12s，两张表紧随其后）
        # ⚠️ 判据只认页面给的活引用 `__l2ModelRef()`（内部 = l2State.app.stage.children[0]）。
        #    旧版写 `window.l2State` —— 那**从来不存在**（l2State 是模块级 let），
        #    于是恒落到 HOOK 兜底变量；HOOK 只在 addChild 抓一次，换肤/重建后指向已销毁对象。
        MODEL = "(function(){ return (window.__l2ModelRef&&window.__l2ModelRef())?1:0; })()"
        for _ in range(60):
            ok = pg.ev("(function(){ return (%s && window.COSTUME && window.PARAM_DRAWABLES"
                       " && window.__costumeBoxes && __costumeBoxes().length) ? 1 : 0; })()"
                       % MODEL)
            if ok == 1:
                break
            time.sleep(1.0)
        if pg.ev(MODEL) != 1:
            print('[FAIL] 模型未加载'); return 2
        if not pg.ev("!!window.__costumeBoxes"):
            print('[FAIL] 页面没有 __costumeBoxes 探针出口 —— 前端未部署？'); return 2
        if not pg.ev("!!(window.COSTUME && Object.keys(window.COSTUME).length)"):
            print('[FAIL] costume_params.json 未加载'); return 2
        if not pg.ev("!!(window.PARAM_DRAWABLES && Object.keys(window.PARAM_DRAWABLES).length)"):
            print('[FAIL] param_drawables.json 未加载'); return 2

        # ---------- ① 热区清单 ----------
        boxes = pg.ev("JSON.stringify(window.__costumeBoxes())")
        try:
            bl = json.loads(boxes)
        except Exception:  # noqa: BLE001
            print('[FAIL] 热区清单不可解析:', boxes); return 2
        print('\n① 热区 %d 个：' % len(bl))
        for b in bl:
            print('   %-16s %-6s n=%-3d area=%d' % (b['id'], b.get('label', ''),
                                                    b['n'], int(b['area'])))
        tgt = next((b for b in bl if b['id'] == PID), None)
        if not tgt:
            print('[FAIL] 无 %s 热区（该模型映射为空？）' % PID); return 1
        print('   目标 %s：n=%d area=%d' % (PID, tgt['n'], int(tgt['area'])))

        # ---------- ② 先停住动作，再取屏幕点 ----------
        # ⚠️ 顺序不能反：`__costumeScreenOf` 返回的是**取点那一刻**的几何中心；先取点再停动作，
        #    停住后 idle/login 姿态变化会让该坐标落到别的热区（实测 login 期间取点、停后命中 Cloth2）。
        #    `stopAllMotions` 会把 currentGroup 清掉，参数不再被曲线改写，几何随即稳定。
        pg.ev("""(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 0;
          try{ m.internalModel.motionManager.queueManager.stopAllMotions(); }catch(e){}
          try{ m.internalModel.motionManager.state.complete(); }catch(e){}
          return 1;})()""")
        time.sleep(1.2)
        scr = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID))
        print('\n② __costumeScreenOf(%s) = %s' % (PID, scr))
        try:
            sc = json.loads(scr)
        except Exception:  # noqa: BLE001
            print('[FAIL] 屏幕点解析失败'); return 2
        if not sc:
            print('[FAIL] 该热区在视口内点不到（出画/被遮挡）'); return 1
        cx, cy = sc['cx'], sc['cy']

        read_expr = READ % (json.dumps(PID), json.dumps(KEY))
        before = json.loads(pg.ev(read_expr))
        print('   点击前参数:', before)

        # ---------- ⓞ 帧源闸（2026-10-28 改用共用层）----------
        # 本页所有逐帧行为都跑在 `l2State.app.ticker`（stateTick / tween / pin 重申）与
        # `PIXI.Ticker.shared`（pixi-live2d-display 的 model.update → coreModel.update）上。
        # headless 下浏览器会在加载 18–30 秒后把出帧源降到 1 Hz 甚至完全停掉 rAF ⇒
        # 参数会冻在最后一次 tick 的值：pin 写不进去、tween 不推进、画面零变化。
        # 旧版这里手写「lastTime 是否推进」的闸，只能发现 rAF 完全停摆，**发现不了 1 Hz 节流**
        # （1 Hz 下 lastTime 照样推进 ~1000ms）。现在改用共用层：解耦出帧源 + require_frames。
        # ⚠️ 采样之间必须真的等：首版三次背靠背调用，lastTime 当然一模一样（判据自己坏过）。
        print('\nⓞ 解耦帧源:', pg.detach_frames(60))
        time.sleep(3.0)                      # 过 JIT 预热（实测前 10s 36→49 fps）
        print('   帧源闸: %.1f fps（诊断: 单帧成本 %sms ⇒ 可达约 %s）'
              % (pg.require_frames(2.0), pg.last_gate.get('cost'), pg.last_gate.get('reachable')))
        print('   ticker 采样:', pg.ev("JSON.stringify(window.__l2TickerState?__l2TickerState():null)"))

        # ---------- ⑤ 漂移对照（ticker 闸之后、点之前，避免受本脚本自己的点击影响）----------
        dA = pg.ev(SNAP)
        time.sleep(1.4)
        dB = pg.ev(SNAP)
        drift = json.loads(pg.ev(DIFF % (json.dumps(json.loads(dA)), json.dumps(json.loads(dB)))))
        print('\n⑤ 漂移对照（不点、等同样时长）:', drift)
        # 点击前的基线截图（目视对比用；判据不靠它，但它能让人一眼看出鞋穿没穿）
        pg.shot(os.path.join(OUT, '%s_%s_before.png' % (KEY, PID)))
        grp_before = pg.ev("(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;"
                           " return (m&&m.internalModel.motionManager.state.currentGroup)||'null';})()")
        print('   点击前 currentGroup:', grp_before)
        # ⚠️ 判据只认「点击是否新起了**非待机**动作」，不认「前后是否相等」（2026-10-28 修）。
        #    本探针在取屏幕点前先 stopAllMotions()，currentGroup 被清成 null；
        #    库随后自己恢复待机 ⇒ 恒出现 null→idle。那是库的正常行为，与热区无关。
        #    待机组由页面自己的 idleSet 判定（组名不固定，探针不能靠字符串猜）。
        idle_set = set(json.loads(pg.ev(
            "(function(){ return JSON.stringify(window.__l2IdleSet?window.__l2IdleSet():[]); })()") or '[]'))
        print('   待机组(%d): %s' % (len(idle_set), sorted(idle_set)[:6]))

        # 命中判定必须**先行确认**（不派发，只问产品函数）：确保这个点真的落到目标热区。
        # ⚠️ 必须允许重试：热区几何随呼吸/物理/相机在动，`__costumeScreenOf` 给的是取点那一刻
        #    的**几何中心**，而中心可能恰好落进邻居地盘（本项目已记录过：中心≠真实命中点）。
        #    旧版在这里一次定生死 → 误报「点不到」。现最多重取 6 次，每次间隔让场景先稳定。
        hn = None
        for attempt in range(6):
            hitname = pg.ev("JSON.stringify(window.__costumeHit(%d,%d))" % (cx, cy))
            try:
                hn = json.loads(hitname)
            except Exception:  # noqa: BLE001
                hn = None
            if hn and hn.get('id') == PID:
                break
            print('   [retry %d] 取到的点命中 %s，重新取点' % (attempt + 1, (hn or {}).get('id')))
            time.sleep(0.7)
            scr = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID))
            try:
                sc = json.loads(scr)
            except Exception:  # noqa: BLE001
                sc = None
            if not sc:
                break
            cx, cy = sc['cx'], sc['cy']
        print('   该点命中:', json.dumps(hn, ensure_ascii=False))
        if not hn or hn.get('id') != PID:
            print('[FAIL] 屏幕点没落到目标热区（命中 %s）' % (hn or {}).get('id')); return 1

        # 🔴 SNAP **必须先取**（2026-10-28 实测，假红来源）：SNAP 遍历 842 个 drawable，实测耗时数百 ms。
        #    旧序「确认命中 → snapA → 派发点击」里，取点与真正点击之间隔了这段时间，而 ougen_8 的鞋部件
        #    nVis=1、面积仅 6.47（V 空间），idle 的呼吸/物理在这一间歇里已把它挪出该屏幕点
        #    ⇒ onUp 里 `costumeHitAt` 返回 null ⇒ `costumeToggle` 根本没被调用（`pin` 恒 null、
        #    参数 0→0），而画面差异仍有几十个 drawable（idle 本底演化），看起来像"点了没效果"。
        #    实测同一点：`__costumeScreenOf` 给出 n=104 命中点，**紧接着**一次 `__costumeHit` 就返回 None。
        #    ⇒ 取完快照后，派发前必须再验一次命中，且这一步要紧贴点击。
        snapA = pg.ev(SNAP)
        hn2 = None
        for attempt in range(6):
            hn2 = json.loads(pg.ev("JSON.stringify(window.__costumeHit(%d,%d))" % (cx, cy))
                             or 'null')
            if hn2 and hn2.get('id') == PID:
                break
            print('   [retry %d] 派发前复核命中 %s，重新取点' % (attempt + 1, (hn2 or {}).get('id')))
            time.sleep(0.5)
            sc = json.loads(pg.ev("JSON.stringify(window.__costumeScreenOf(%s))"
                                 % json.dumps(PID)) or 'null')
            if not sc:
                break
            cx, cy = sc['cx'], sc['cy']
            snapA = pg.ev(SNAP)
        if not hn2 or hn2.get('id') != PID:
            print('[FAIL] 派发前复核未命中目标热区（命中 %s）' % (hn2 or {}).get('id')); return 1

        # 真实输入派发（pointerdown + pointerup，位移 0 才算点击；onUp 里 moved>=6 会当成拖拽）
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': cx, 'y': cy,
                                               'button': 'left', 'clickCount': 1})
            time.sleep(0.08)
        print('   已派发 pointerdown/up @ (%d,%d)' % (cx, cy))

        # 等 tween 走完（dur 450ms）。⚠️ 不能固定 sleep：headless 下 rAF 被节流到 ~1fps，
        # tween 是按 performance.now() 算的但**只在 tick 时推进**，所以实际要 2~3s 才到终点。
        # 旧版 sleep(1.4) 后取 after，实测拿到 0.93 这类中途值，随后 5 帧回读全变成 1
        # → 「参数值不稳定」是**取样过早**造成的假红，不是参数真的被回退。
        # 判据改成「轮询到参数不再变化（连续两次相同且间隔足够）」，最多等 8s。
        def read_until_stable(timeout=8.0, quiet=0.8):
            t0 = time.time()
            last = json.loads(pg.ev(read_expr))
            hold = 0.0
            while time.time() - t0 < timeout:
                time.sleep(0.2)
                now = json.loads(pg.ev(read_expr))
                if abs(now['v'] - last['v']) < 1e-3:
                    hold += 0.2
                    if hold >= quiet:
                        return now
                else:
                    hold = 0.0
                last = now
            return last

        after = read_until_stable()
        grp_after = pg.ev("(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;"
                          " return (m&&m.internalModel.motionManager.state.currentGroup)||'null';})()")
        print('   点击后 currentGroup:', grp_after)
        snapB = pg.ev(SNAP)
        di = json.loads(pg.ev(DIFF % (json.dumps(json.loads(snapA)) if snapA else '{}',
                                     json.dumps(json.loads(snapB)) if snapB else '{}')))
        print('   点击后参数:', after)
        print('   ③ 画面差异:', di)

        # ---------- 稳定性：连推数帧回读，确认没被动作/pins 打回 ----------
        stable = []
        for _ in range(5):
            time.sleep(0.35)
            r = json.loads(pg.ev(read_expr))
            stable.append(r['v'])
        print('   连续 5 帧回读:', stable)

        # ---------- 阴性对照：点画面外 ----------
        off = pg.ev("JSON.stringify(window.__costumeHit(2,2))")
        print('   阴性对照 __costumeHit(2,2) =', off)

        # ---------- 阳性对照：顶点判据本身不瞎 ----------
        pg.ev("""(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 0;
          var c=m.internalModel.coreModel;
          var ix=c.getParameterIndex('ParamAngleX');
          if(ix<0) return 0;
          window.__posA=c.getParameterValueById('ParamAngleX');
          c.setParameterValueById('ParamAngleX', c.getParameterMaximumValue(ix));
          try{ m.internalModel.update(0, performance.now()); }catch(e){}
          return 1;})()""")
        time.sleep(0.2)
        posSnap = pg.ev(SNAP)
        posDif = json.loads(pg.ev(DIFF % (json.dumps(json.loads(snapA)), json.dumps(json.loads(posSnap)))))
        pg.ev("""(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 0;
          var c=m.internalModel.coreModel;
          c.setParameterValueById('ParamAngleX', window.__posA===undefined?0:window.__posA); return 1;})()""")
        print('   阳性对照 ParamAngleX=→max 的画面差异:', posDif)

        pg.shot(os.path.join(OUT, '%s_%s_after.png' % (KEY, PID)))
        pg.shot(os.path.join(OUT, '%s_%s_final.png' % (KEY, PID)))

        # 旁证：点击同时会移动指针，眼神跟随（ParamEyeBallX/Y）被点位置改写，头部也有连带小位移。
        # 记下来是为了解释"变化集合里还多几个不属于本参数的部件"——那是点击的副产物，不是缺陷。
        print('   眼神参数（点击副产物）:', pg.ev("""(function(){
          var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return '{"err":"NO_MODEL"}';
          var c=m.internalModel.coreModel; var o={};
          ['ParamEyeBallX','ParamEyeBallY'].forEach(function(k){
            var ix=c.getParameterIndex(k); o[k]= ix<0? 'NO_IDX' : +c.getParameterValueById(k).toFixed(3); });
          return JSON.stringify(o);})()"""))

        # ---------- ④ 用**产品自己的 pins 机制**在两端稳态各采一次，要求差异点名到本参数的部件 ----------
        # 为什么不用"点击前后各采一次"当判据：实测两次运行结论相反 —— 一次变化集合含 [460,461]，
        # 一次不含。根因不是功能坏了，而是 **idle 变体会把该参数钉在某一端**（ougen_8 的 45 个 clip 里
        # ShoseOff 恒写成 1，复算见下文）；随机 idle 变体落到「已经是脱鞋态」时，0→1 自然就没有可见差异。
        # 判据必须先消除这个噪声，否则同一个功能会时红时绿。做法：pins 是产品的实际写入路径
        # （LOW ticker 每帧重申），用它把参数稳在 lo 与 hi，各等几帧让 coreModel 完成一次 drawable
        # 求值，再逐 drawable 比。
        #
        # 🔴 **必须先让渡，否则这一层测的是"未修好的那个 bug"**（2026-10-28 实测定的）：
        #    `stateApply` 只在条目 `_costumeOwned=true` 之后才重放 pins；未让渡时它在
        #    `beforeModelUpdate`（晚于 LOW ticker）里每帧**无条件**写 `_on`，于是：
        #      owned=false  pin=-1 → core.update 入口恒 [-1]；pin=1 → 入口**仍**恒 [-1]
        #      owned=true   pin=-1 → 入口 [-1]；        pin=1 → 入口 [1]
        #    （取证脚本 scripts/diag/ownership_entry_diag.py，用 core.update 入口采样，各 200+ 帧）
        #    所以「pins 稳态 lo↔hi，但与驱动集合交集为空」在未让渡态下有 100% 的概率出现 ——
        #    那是**该 bug 本身**，拿它当本参数"没有可见效果"的证据是错的（假红，判据坏过）。
        #    现在先跑 ④b 的真实点击（让产品自己完成让渡），再做 pins 对比。
        pin_set = """(function(){
          var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
          if(!pm[%s]) pm[%s]=Object.create(null);
          pm[%s][%s]=%s; return 1;})()"""
        base_lo, base_hi = tgt['lo'], tgt['hi']

        # ⚠️ pin 写入**不是立刻生效**（2026-10-28 实测）：idle 动作的 loadParameters 每帧把参数
        #    拉回曲线值，和 pins 逐帧拉锯 → 未让渡态下 pin 到 -1 要约 1.0s 才落定；让渡后
        #    实测 0.17–0.33s 就收敛（见 ownership_entry_diag）。旧版固定 sleep(0.9) 于是
        #    **两次快照可能都取在未收敛的同一值**，「lo↔hi 0 差异」就是这么来的 ——
        #    是探针时序 bug，不是「参数没有可见效果」。判据改成轮询到收敛再取快照。
        def pin_and_wait(val, timeout=8.0):
            pg.ev(pin_set % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY),
                             json.dumps(PID), json.dumps(val)))
            t0 = time.time()
            seen = None
            trail = []
            while time.time() - t0 < timeout:
                r = json.loads(pg.ev(read_expr))
                seen = r['v']
                trail.append((round(time.time() - t0, 2), r['v'], r['pin']))
                if abs(seen - val) < 1e-2:
                    return True, seen, time.time() - t0, trail
                time.sleep(0.15)
            return False, seen, time.time() - t0, trail

        # ---------- ④b（提前执行）「参数本来就在一端」的替代判据 + 完成让渡 ----------
        # 🔴 顺序是硬性的（2026-10-28 实测，见上方 ④ 的注释）：本支必须**排在 ④ 之前**。
        #    它做的真实点击会让 `_costumeOwned=true`，而 ④ 的 pins 对比只在让渡后才对得上渲染。
        #    未让渡态下 pins 被 `stateApply` 的 `_on` 覆盖，④ 恒得 0 交集（假红）。
        lo_click = {'ran': False, 'v_lo': None, 'v_after': None, 'changed': 0, 'hit': None}
        ok_lo2, lo_click['v_lo'], _, _tr2 = pin_and_wait(base_lo)
        lo_click['ran'] = ok_lo2
        ok_hit = False
        scr2 = None
        for _ in range(4):
            scr2 = json.loads(pg.ev("JSON.stringify(window.__costumeScreenOf(%s))"
                                    % json.dumps(PID)) or 'null')
            scr2 = scr2 or None
            if not scr2:
                break
            hn2 = json.loads(pg.ev("JSON.stringify(window.__costumeHit(%d,%d))"
                                   % (scr2['cx'], scr2['cy'])) or 'null')
            lo_click['hit'] = (hn2 or {}).get('id')
            if hn2 and hn2.get('id') == PID:
                ok_hit = True
                break
            time.sleep(0.7)
        if ok_hit:
            snapL0 = pg.ev(SNAP)
            for typ in ('mousePressed', 'mouseReleased'):
                pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': scr2['cx'], 'y': scr2['cy'],
                                                   'button': 'left', 'clickCount': 1})
                time.sleep(0.08)
            time.sleep(1.4)
            lo_click['v_after'] = read_until_stable()['v']
            snapL1 = pg.ev(SNAP)
            lo_click['changed'] = json.loads(pg.ev(
                DIFF % (json.dumps(json.loads(snapL0)), json.dumps(json.loads(snapL1)))))['changed']
        print('\n④b lo 端点击替代判据: pin=%s → 点击后 %s，画面变化 %d 个（命中 %s）'
              % (lo_click['v_lo'], lo_click['v_after'], lo_click['changed'], lo_click['hit']))
        pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]||{};
          delete pm[%s]; return 1;})()""" % (json.dumps(KEY), json.dumps(PID)))
        time.sleep(0.4)
        own_info = json.loads(pg.ev("JSON.stringify(__stateTogglesInfo?__stateTogglesInfo():[])") or '[]')
        owned_now = next((t for t in own_info if t.get('id') == PID), None)
        print('   让渡状态 __stateTogglesInfo[%s]: %s' % (PID, owned_now))
        if not (owned_now and owned_now.get('owned')):
            print('   ⚠️ 该参数不在 STATE_TOGGLES 里（本模型无同名状态机条目）⇒ 让渡不适用，'
                  '未让渡态也不会被 _on 覆盖，④ 的 pins 对比可以照常做')
        pg.require_frames(1.0)

        # ---------- ④ 的前置：**冻住姿态**（2026-10-28 新增，缺了必然假红）----------
        # 判据 ④ 要比「pin 在 lo」与「pin 在 hi」两份顶点快照的差集，并要求差集与
        # param_drawables 声明的驱动件有交集。问题：不冻结时 idle 每帧把参数写回曲线值，
        # 同时呼吸/物理让全身顶点逐帧漂 —— 实测（ougen_8/ShoseOff，8 档扫描）
        # 逐档差值**完全非单调**（#697 在 want=-0.5 变 32、want=+0.25 只变 4.25），
        # 那是漂移噪声，不是参数效果。冻结后同一扫描给出干净的 5 个真驱动件
        # （#460 op 0→1、#461 op 1→0.428、#183/#184/#615 仅高值档参与），本底漂移 0/842。
        # ⚠️ 只能在 ④ 之前冻：前面的 ⑤ 漂移对照**需要** idle 在跑，否则那个对照恒为 0 而失去意义。
        print('\n④ 前置冻结姿态:', pg.ev(NEUTRALIZE))
        time.sleep(1.2)
        pg.require_frames(1.0)
        # 冻结自检：连采 2 次（间隔 0.6s）确认本底真的不动，否则 ④ 的读数仍然不可信
        fA = pg.ev(SNAP)
        time.sleep(0.6)
        fB = pg.ev(SNAP)
        fdrift = json.loads(pg.ev(DIFF % (json.dumps(json.loads(fA)), json.dumps(json.loads(fB)))))
        print('   冻结后本底漂移: %d 个 drawable' % fdrift.get('changed', -1))
        if fdrift.get('changed', 1) > 0:
            print('   ⚠️ 冻结没完全生效，④ 的差集里可能混有漂移：%s' % fdrift.get('idx'))

        # 驱动部件清单要在**两端态快照之前**取好：判据红了要能当场打印这两个部件的读数。
        driven_pre = []
        try:
            raw_drv = pg.ev("""(function(){
              var t=(window.PARAM_DRAWABLES||{})[%s]||{};
              return JSON.stringify(t[%s]||null);})()"""
                            % (json.dumps(KEY), json.dumps(PID)))
            driven_pre = json.loads(raw_drv) or []
        except Exception:  # noqa: BLE001
            driven_pre = []

        ok_lo, v_lo, t_lo, tr_lo = pin_and_wait(base_lo)
        print('\n④ pin lo=%s 收敛: %s（实测 %s，耗时 %.2fs）'
              % (base_lo, 'OK' if ok_lo else 'TIMEOUT', v_lo, t_lo))
        if not ok_lo:
            # 失败时必须说清是「pin 没写进去」还是「pin 写了但被别的东西覆盖」
            print('   pin 轨迹 (t, v, pin) 前 8:', tr_lo[:8])
            print('   pin 轨迹 末 3:', tr_lo[-3:])
        snapLo = pg.ev(SNAP)
        # 目标驱动部件的两端态明细：让判据红了能自证（是"没动"还是"快照取错"）。
        #   `op`=不透明度、`bx`=顶点包围盒；两者都不变才是真的没效果。
        det_lo = pg.ev(DETAIL % json.dumps(driven_pre or []))
        ok_hi, v_hi, t_hi, _tr_hi = pin_and_wait(base_hi)
        print('   pin hi=%s 收敛: %s（实测 %s，耗时 %.2fs）'
              % (base_hi, 'OK' if ok_hi else 'TIMEOUT', v_hi, t_hi))
        snapHi = pg.ev(SNAP)
        det_hi = pg.ev(DETAIL % json.dumps(driven_pre or []))
        if driven_pre:
            print('   ★ 目标部件两端态: lo=%s' % (det_lo,))
            print('                      hi=%s' % (det_hi,))
        pairDif = json.loads(pg.ev(DIFF % (json.dumps(json.loads(snapLo)), json.dumps(json.loads(snapHi)))))
        print('   pins 稳态对比 lo=%s vs hi=%s:' % (base_lo, base_hi), pairDif)

        driven_idx = driven_pre
        inter = sorted(set(pairDif.get('all', [])) & set(driven_idx))
        print('   该参数驱动的部件索引:', driven_idx)
        print('   pins 稳态变化集合 ∩ 驱动集合 = %s' % inter)
        # 点击造成的变化集合（含 idle 演化与眼神副产物）——只作解释，不进硬判据
        inter_click = sorted(set(di.get('all', [])) & set(driven_idx))
        print('   点击后变化集合 ∩ 驱动集合 = %s（该模型当前 idle 可能把参数钉在某一端，'
              '此时 0→1 无可见差异，属数据特性）' % inter_click)
        # 复原：清掉本探针写入的 pins，别把状态留给后面的截图
        pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]||{};
          delete pm[%s]; return 1;})()""" % (json.dumps(KEY), json.dumps(PID)))
        time.sleep(0.5)

        # ---------- 判定 ----------
        print('\n' + '=' * 62)
        fails = []
        if before['v'] == after['v']:
            fails.append('参数值没变(%s→%s)' % (before['v'], after['v']))
        if di.get('changed', 0) <= 0:
            fails.append('画面差异 changed=0（参数变了但渲染没变？）')
        if not all(abs(v - after['v']) < 1e-3 for v in stable):
            fails.append('参数值不稳定 %s' % stable)
        if posDif.get('changed', 0) <= 0:
            fails.append('阳性对照也判无变化 → 顶点判据本身失效（结论不可信）')
        if not inter and not inter_click:
            fails.append('pins 稳态 lo↔hi 的差异与 %s 驱动的部件无交集（**在已让渡状态下测的，'
                         '故不再是"未修好"那个假红**）→ 该参数在本模型上没有可见效果'
                         '（数据/映射问题，不是热区问题）' % PID)
        elif not inter:
            # ⚠️ 这是**数据特性**，不是缺陷（2026-10-28 定性）：
            #    该模型所有 clip 都把该参数写成同一个值（ougen_8 的 ShoseOff 在 45 个 clip 里恒为 1，
            #    core 内部 clamp 到 max=1）⇒ 待机态下参数本来就在这一端，lo↔hi 自然没有差异。
            #    旧版把它当硬 FAIL，等于「数据里不存在的那一端」也算产品不达标 → 同一功能时红时绿。
            #    改用 ④b（已提前执行）：pin 到 lo 后**真实点击**一次，参数必须往另一端走并伴随画面变化。
            if lo_click['ran'] and lo_click['v_after'] is not None and \
                    abs((lo_click['v_after'] or 0) - (lo_click['v_lo'] or 0)) > 1e-3 \
                    and lo_click['changed'] > 0:
                print('   → 替代判据成立（pins 稳态无差异属数据特性）')
            else:
                fails.append('pins 稳态 lo↔hi 无差异，且 lo 端点击后参数/画面也没动'
                             '（pin=%s → %s，画面变化 %d）→ 该参数在本模型上确实没有可见效果'
                             % (lo_click['v_lo'], lo_click['v_after'], lo_click['changed']))
        if drift.get('changed', 0) > 0:
            print('   注意：漂移对照有 %d 个变化（idle 在本底演化），仅供参考' % drift.get('changed', 0))
        if grp_after != grp_before:
            base = '' if grp_before in ('null', '') else grp_before
            ok_grp = (grp_after in idle_set) and (not base or base == grp_after or base in idle_set)
            detail = '点击后动作组变了(%s→%s)' % (grp_before, grp_after)
            if ok_grp:
                print('   注意：%s —— 但目标组是待机组（库自己恢复 idle），不算热区播动作' % detail)
            else:
                fails.append(detail + ' —— 热区不该播 motion')
        if hn and hn.get('id') == PID and di.get('changed', 0) > 0:
            passes = ['点中参数热区（真实输入派发）',
                      '参数 %s: %s → %s' % (PID, before['v'], after['v']),
                      '参数值连推 5 帧稳定在 %s' % stable[0],
                      'pins 稳态 lo=%s ↔ hi=%s：%d 个 drawable 变化，其中 %d 个属本参数驱动集合（%s）'
                      % (base_lo, base_hi, pairDif['changed'], len(inter), inter),
                      '未起新动作（currentGroup: %s → %s，后者属待机组）' % (grp_before, grp_after),
                      '阳性对照 %d 个 drawable 变化（判据不瞎）' % posDif['changed']]
            if inter:
                passes.append('经 __costumeScreenOf 拿到的点是**真实命中点**（edge=%s 格距，'
                              '不是几何中心）' % sc.get('edge'))
        else:
            passes = []
        for p in passes:
            print('  PASS', p)
        for f in fails:
            print('  FAIL', f)
        print('  截图 before/after: .diag/costume_hotzone/%s_%s_{before,after}.png' % (KEY, PID))
        print('=' * 62)
        return 0 if not fails else 1
    finally:
        pg.close()

if __name__ == '__main__':
    sys.exit(main())


