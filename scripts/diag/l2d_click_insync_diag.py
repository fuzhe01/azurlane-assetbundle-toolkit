"""同一点上 ① 与 ② 谁是生效者、① 会不会被 pins 覆盖 —— 2026-10-29。

要判死的两件事
--------------
产品 `onUp` 三支顺序：① `stateFind(localHit)` → ② `costumeHitAt` → ③ `play`。
① 的名字来自 `hitAt()`，而 `hitAt` 对**重叠判定区随机挑一个**（A3 规则）。
`ougen_8` 唯一的 STOGS 条目是 `touchdrag17 → ShoseOff`，而鞋的参数热区 `ShoseOff`
就在同一部位 ⇒ 同一点可能走 ① 也可能走 ②。

M1 **同一部位的两个热点，自然点击分别落哪一支**
   用产品自己的反解出口取屏幕点：`__L2_SCREENOF('touchdrag17')`（判定区，走 `localHit`）
   与 `__costumeScreenOf('ShoseOff')`（参数热区，走 `costumeHitAt`），各自连点 N 轮统计。
M2 **① 会被 `pins` 在同一事件里覆盖**（真 bug 候选，用户报的「互动区被另一个互动区覆盖」）
   `stateApply` 末尾有一段**无条件**重放：
     ```js
     { const cs=(window.__costumePinsByModel||{})[sk.key];
       if(cs) for(const k in cs) core.setParameterValueById(k, cs[k]); }
     ```
   它在 `_tw`/`_on` 写入**之后**、同一个 `beforeModelUpdate` 内跑。⇒ 只要 `pins['ShoseOff']`
   存在（② 走过一次就建），之后任何 ① 的写入**当帧即被抹掉**：pill 照样报 `▸ off`（谎报），
   画面纹丝不动。**判据 = 同一轮里 branch 落 ① 但像素变化为 0。**

🔴 必须页内同步派发
------------------
`onDown` 用**按下那一刻**的新鲜几何定 `cosDown`，`onUp` 再补算一次 —— 两个时刻两套几何。
CDP 派发 `mousePressed`/`mouseReleased` 实测间隔 **4.6–29.9 秒**（本机 headless 上
`Page.cmd` 往返会逐条恶化），两次几何必然不同 ⇒ 输出「三条分支都没进」的假红。
本探针把 down/up 放进**同一个 JS 任务**同步 dispatch，间隔 0 ms，且用产品自己监听的
同一对节点（`#l2wrap` 的 pointerdown / window 的 pointerup）—— 不绕过任何产品入口。

仪器坑（都踩过，别重犯）
------------------------
1. **`__L2_HIT` / `__L2_HITALL` 吃模型坐标（V 空间），不是屏幕坐标**。把
   `__L2_SCREENOF` / `__costumeScreenOf` 返回的 (cx,cy) 直接喂给它们会**静默返回 `[]`**，
   看起来像「该点没有判定区」（本轮为此白绕一圈）。屏幕点只用于点击。
2. `__stateTogglesInfo()` 每次 `.map(t=>({...}))` 生成**新副本** ⇒ 往里写 `owned=false`
   是纯空操作。`_costumeOwned` 没有外部清除出口，只能靠产品自己的 `toggleState` 置回 false。
3. 内层函数自己已 `return JSON.stringify(...)`，外面**不许再包一层 `JSON.stringify`**
   （双串化后 `json.loads` 得到字符串，`r.get()` 抛 AttributeError）。
4. `_lastHit` 会让 `hitAt` 避开上一次抽中的名字 ⇒ 连点时分支序列**不是独立同分布**，
   统计里必须逐轮记录，不能只报总数。

判据
----
· 无 pin 时点判定区热点，branch=① 且像素变化 > 0          ⇒ ① 本身可用
· 点鞋热点后 `pins[ShoseOff]` 被写、像素变化 > 0            ⇒ ② 可用
· **阶段3/4 是 M2 的精确判据**（把 pin 钉成「模型当前显示值」再点，与 `_on` 奇偶无关）：
    - pin 钉成当前值后点判定区，branch=① 且像素 0 变化     ⇒ **M2 成立（真 bug）**
    - pin 钉成当前值后点判定区，branch=① 且画面有变化       ⇒ M2 已修
    - 正向对照（pin 建好立刻删掉再点）也必须变；若它不变，
      则阶段3 的「不变」**不能归因给 pins**，本探针此读数作废
· 某轮 pill/log/_on 全都没动                                ⇒ 先怀疑合成事件没被接纳，报 INVALID

⚠️ 分支定性只能看产品自己的 pill 文本，不能用 `dpin` 判 ②
  修复后 ① 会主动 `delete pins[id]`（收回让渡）⇒ `dpin=true`。
  2026-10-29 实测该写法把 ① 误判成 ②，直接毁掉 M2 判据。

⚠️ pin 里的旧值不能用「随便什么旧值」做判据
  ① 把值切到「当前值的反面」。旧值恰好等于那个反面时，清不清 pin 画面都一样
  ⇒ 像素变化 0 会被误读成 M2 仍在（同一轮里白红过一次）。故必须显式钉值。

用法:
  py -3 scripts/diag/l2d_click_insync_diag.py [模型key] [参数id] [轮数]
  py -3 scripts/diag/l2d_click_insync_diag.py ougen_8 ShoseOff 8
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
NAT = int(sys.argv[3]) if len(sys.argv) > 3 else 8
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = 9416
PROF = r'D:\azur\.diag\insync_prof'
SAMPLE = os.path.join(ROOT, '.diag', 'insync')
os.makedirs(SAMPLE, exist_ok=True)

INSYNC = r"""(function(key,pid,cx,cy){
  var wrap=document.getElementById('l2wrap');
  var out={cx:cx,cy:cy,invalid:[]};
  var PIN=(window.__costumePinsByModel||{})[key]||null;
  var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]), s=null;
  for(var i=0;i<st.length;i++) if(st[i].id===pid) s=st[i];
  var pill=function(){ return (document.getElementById('l2Hit')||{}).textContent||''; };
  out.cosPre=(function(){ try{ var b=window.__costumeHit(cx,cy); return b?b.id:null; }
                         catch(e){ return 'EXC:'+e; } })();
  out.log0=(window.__costumeLog||[]).length;
  out.pin0=(PIN&&PIN[pid]!==undefined)?+PIN[pid]:null;
  out.on0=s?s.on:null; out.owned0=s?!!s.owned:null; out.tw0=s?!!s.tw:null;
  out.pill0=pill();

  var base={bubbles:false,cancelable:true,composed:true,clientX:cx,clientY:cy,
            button:0,buttons:1,pointerId:77,pointerType:'mouse',isPrimary:true,view:window};
  var dn={}; for(var a in base) dn[a]=base[a];
  var up={}; for(var b2 in base) up[b2]=base[b2]; up.buttons=0;
  try{ wrap.dispatchEvent(new PointerEvent('pointerdown',dn)); }
  catch(e){ out.invalid.push('down:'+e); }
  try{ window.dispatchEvent(new PointerEvent('pointerup',up)); }
  catch(e){ out.invalid.push('up:'+e); }

  out.log1=(window.__costumeLog||[]).length;
  out.pin1=(PIN&&PIN[pid]!==undefined)?+PIN[pid]:null;
  var st2=(window.__stateTogglesInfo?__stateTogglesInfo():[]), s2=null;
  for(var i2=0;i2<st2.length;i2++) if(st2[i2].id===pid) s2=st2[i2];
  out.on1=s2?s2.on:null; out.owned1=s2?!!s2.owned:null; out.tw1=s2?!!s2.tw:null;
  out.pill1=pill();
  out.dlog=out.log1-out.log0;
  out.dpin=(out.pin1!==out.pin0);
  out.don=(out.on1!==out.on0);
  out.dpill=(out.pill1!==out.pill0);

  /* 分支定性：**只看产品自己的 pill 文本**，不看副作用差分。
     ① toggleState  写 `<label> ▸ on/off`
     ② costumeToggle 写 `<label> · <id> → <to>`
     ⚠️ 不能用 `dpin` 判 ② —— 修复后 ① 会主动 `delete pins[id]`（收回让渡），
     那也让 dpin=true；2026-10-29 实测把 ① 误判成 ②，直接毁掉 M2 判据。 */
  if(out.dpill && out.pill1.indexOf('\u25b8')>=0) out.branch='1 toggleState';
  else if(out.dpill && (out.pill1.indexOf('\u2192')>=0 || out.pill1.indexOf('\u00b7')>=0))
    out.branch='2 costumeToggle';
  else if(out.dlog>0) out.branch='2 costumeToggle';
  else if(out.don || (out.tw1 && !out.tw0)) out.branch='1 toggleState';
  else if(out.dpin) out.branch='? dpin';
  else out.branch='none';
  return JSON.stringify(out);
})"""

READ = r"""(function(){
  var key='__KEY__', pid='__ID__';
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel;
  var pm=(window.__costumePinsByModel||{})[key]||{};
  var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]); var s=null;
  for(var i=0;i<st.length;i++) if(st[i].id===pid) s=st[i];
  var v=null; try{ v=+c.getParameterValueById(pid).toFixed(3); }catch(e){}
  var pill=(document.getElementById('l2Hit')||{}).textContent||'';
  return JSON.stringify({v:v, pin:(pm[pid]===undefined?null:+pm[pid]), on:(s?s.on:null),
    owned:(s?!!s.owned:null), tw:(s?!!s.tw:null), logLen:(window.__costumeLog||[]).length,
    pill:pill, grp:(m.internalModel.motionManager.state.currentGroup||'null')});
})()""".replace('__KEY__', KEY).replace('__ID__', PID)

SNAP = r"""(function(){
  var m=(window.__l2ModelRef&&window.__l2ModelRef())||null;
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel, n=c.getDrawableCount(), o=[];
  for(var i=0;i<n;i++){ var op=0; try{ op=+c.getDrawableOpacity(i); }catch(e){}
    o.push(+op.toFixed(3)); }
  return JSON.stringify({n:n,rows:o});
})()"""

# 只清**真实**可写引用（挂在 window 上的 pins/tweens）。`_costumeOwned` 无外部清除出口，
# 由产品自己的 `toggleState` 置回 false（见文件头仪器坑 2）。
CLEAR = r"""(function(){
  var key='__KEY__', pid='__ID__';
  var pm=(window.__costumePinsByModel||{})[key]; if(pm) delete pm[pid];
  var tw=(window.__costumeTweens||{})[key]; if(tw) delete tw[pid];
  return 'ok';
})()""".replace('__KEY__', KEY).replace('__ID__', PID)

# 精确 M2 判据用：把 pins[id] 钉成 **模型当前显示的值**（= `_on`）。
# 为什么必须这么钉（否则会得到与奇偶相关的假红/假绿）：
# ① `toggleState` 把值切到「当前值的反面」。
#   · 若 pin 里的旧值恰好 **等于** 那个反面 → 清不清 pin 画面都一样 ⇒ 像素变化 0，
#     会被误读成「M2 仍在」。2026-10-29 实测阶段3 第1轮就是这样白红了一次。
#   · 若 pin 里的旧值恰好 **不等于** 反面，但那只是运气。
# 钉成「当前显示值」后语义变干净：
#   · 未修（pins 重放赢） ⇒ 画面应恒不变（像素变化 0）
#   · 已修（`toggleState` 清 pin） ⇒ ① 真的生效、画面必变
# 判据因此与点击次数、`_on` 奇偶完全无关。
SETPIN = r"""(function(){
  var key='__KEY__', pid='__ID__';
  var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]), s=null;
  for(var i=0;i<st.length;i++) if(st[i].id===pid) s=st[i];
  if(!s) return JSON.stringify({err:'NO_STOG'});
  if(typeof s.on!=='number'||!isFinite(s.on)) return JSON.stringify({err:'NO_ON'});
  var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null))[key];
  if(!pm){ pm=window.__costumePinsByModel[key]=Object.create(null); }
  pm[pid]=s.on;
  var tw=(window.__costumeTweens||{})[key]; if(tw) delete tw[pid];
  return JSON.stringify({pinned:s.on, onV:s.onV, offV:s.offV});
})()""".replace('__KEY__', KEY).replace('__ID__', PID)

# 正对照：同一坐标、pin 钉成当前值、但**立刻删掉** pin 再点 ⇒ 必变。
# 用来证明「不变」确实是 pins 造成的，而不是坐标/合成事件/帧源的问题。
SETPIN_DROP = r"""(function(){
  var key='__KEY__', pid='__ID__';
  var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]), s=null;
  for(var i=0;i<st.length;i++) if(st[i].id===pid) s=st[i];
  if(!s) return JSON.stringify({err:'NO_STOG'});
  if(typeof s.on!=='number'||!isFinite(s.on)) return JSON.stringify({err:'NO_ON'});
  var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null))[key];
  if(!pm){ pm=window.__costumePinsByModel[key]=Object.create(null); }
  pm[pid]=s.on;
  delete pm[pid];
  return JSON.stringify({dropped:true, was:s.on});
})()""".replace('__KEY__', KEY).replace('__ID__', PID)


def jj(pg, expr):
    out = pg.ev(expr)
    try:
        v = json.loads(out)
    except Exception:  # noqa: BLE001
        return {'err': str(out)[:300]}
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:  # noqa: BLE001
            return {'err': v[:300]}
    return v


def dv(a, b):
    ra, rb = a.get('rows') or [], b.get('rows') or []
    n = min(len(ra), len(rb))
    idx = [i for i in range(n) if abs(ra[i] - rb[i]) > 0.02]
    return len(idx), idx[:10]


def click(pg, cx, cy):
    return jj(pg, '(%s)(%s,%s,%d,%d)' % (INSYNC, json.dumps(KEY), json.dumps(PID), cx, cy))


def round_(pg, cx, cy, tag):
    sn0 = jj(pg, SNAP)
    r = click(pg, cx, cy)
    if 'branch' not in r:
        print('  [%-8s] EXC %s' % (tag, r.get('err')))
        return dict(r=r, nch=-1, chg=[], post={})
    time.sleep(0.85)
    sn1 = jj(pg, SNAP)
    nch, chg = dv(sn0, sn1)
    post = jj(pg, READ)
    print('  [%-8s] 分支=%-16s  on %s→%s pin %s→%s log+%d  pill %r→%r'
          % (tag, r.get('branch'), r.get('on0'), r.get('on1'),
             r.get('pin0'), r.get('pin1'), r.get('dlog'), r.get('pill0'), r.get('pill1')))
    print('             画面变化 %2d %s   (点后 v=%s pin=%s owned=%s tw=%s)'
          % (nch, chg, post.get('v'), post.get('pin'), post.get('owned'), post.get('tw')))
    if r.get('invalid'):
        print('             ⚠️ INVALID: %s' % r['invalid'])
    return dict(r=r, nch=nch, chg=chg, post=post)


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as resp:
            if resp.status != 200:
                print('[INVALID] HTTP %s' % resp.status); return 2
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
        ok = 0
        for _ in range(90):
            if pg.ev("(function(){ return (window.__l2ModelRef&&__l2ModelRef())?1:0; })()") == 1:
                ok = 1
                break
            time.sleep(1.0)
        if not ok:
            print('[INVALID] 模型未加载'); return 2

        a = pg.ev("(function(){var t=window.__l2TickerState&&__l2TickerState(); return t?t.lastTime:-1;})()")
        time.sleep(1.5)
        b = pg.ev("(function(){var t=window.__l2TickerState&&__l2TickerState(); return t?t.lastTime:-1;})()")
        print('帧源推进 %.0f ms / 1.5s' % (b - a))
        if b - a < 500:
            print('[INVALID] rAF 停摆，本次读数无效'); return 2

        # 与产品同源核对 trigger
        trig = pg.ev("(function(){var st=(window.__stateTogglesInfo?__stateTogglesInfo():[]);"
                     " var o=[]; for(var i=0;i<st.length;i++) if(st[i].id===%s)"
                     " o.push(st[i].trigger); return o.join(',');})()" % json.dumps(PID))
        print('STATE_TOGGLES 里 %s 的 trigger = %r' % (PID, trig))
        if not trig:
            print('[INVALID] 产品里没有该参数的 STOGS 条目，① 分支不可能发生'); return 2

        pS = jj(pg, "JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID))
        if not pS or 'cx' not in pS:
            print('[INVALID] __costumeScreenOf(%s) 取不到点: %s' % (PID, pS)); return 2
        sx, sy = pS['cx'], pS['cy']

        pT = jj(pg, "JSON.stringify(window.__L2_SCREENOF(%s))" % json.dumps(trig))
        if not pT or 'cx' not in pT:
            print('[INVALID] __L2_SCREENOF(%s) 取不到点: %s' % (trig, pT)); return 2
        tx, ty = pT['cx'], pT['cy']

        # `__costumeScreenOf` 只保证「离参数热区边缘最远」，**不保证避开 STATE_TOGGLES 的 trigger 区**。
        # 而 onUp 是 ① 优先 ⇒ 代表点若落在 trigger 区内，`② costumeToggle` 这一支永远验不到
        # （实测：换一次运行就是 (557,335) 落 ②、(567,359) 落 ①，同一参数同一脚本）。
        # 故在参数热区内再筛一个**不在 trigger 包围盒内**的点专供 ② 用；筛不到就明说 ② 不可达。
        find2 = jj(pg, r"""(function(pid, tbox){
          var b=null, cb=null;
          try{ cb=window.__costumeScreenOf(pid); }catch(e){ return JSON.stringify({err:'EXC '+e}); }
          if(!cb||!cb.box) return JSON.stringify({err:'NO_BOX'});
          b=cb.box;
          var ok=function(x,y){
            if(!(x>=b[0]&&x<=b[2]&&y>=b[1]&&y<=b[3])) return false;
            var c=null; try{ c=window.__costumeHit(x,y); }catch(e){ return false; }
            if(!c||c.id!==pid) return false;
            if(tbox){
              var m=2;
              if(x>=tbox[0]-m&&x<=tbox[2]+m&&y>=tbox[1]-m&&y<=tbox[3]+m) return false;
            }
            return true; };
          var tried=0;
          for(var fy=0.12;fy<=0.881;fy+=0.19){
            for(var fx=0.12;fx<=0.881;fx+=0.19){
              var x=Math.round(b[0]+(b[2]-b[0])*fx), y=Math.round(b[1]+(b[3]-b[1])*fy);
              tried++;
              if(ok(x,y)) return JSON.stringify({cx:x,cy:y,tried:tried});
            } }
          return JSON.stringify({err:'ALL_IN_TRIGGER',tried:tried});
        })(%s, %s)""" % (json.dumps(PID), json.dumps(pT.get('box'))))
        if find2 and 'cx' in find2:
            s2x, s2y = find2['cx'], find2['cy']
            print('避开 trigger 区的参数热区点 (%d,%d)（试了 %d 个候选）'
                  % (s2x, s2y, find2.get('tried') or 0))
        else:
            s2x = s2y = None
            print('⚠️ 参数热区内找不到避开 trigger 区包围盒的点: %s ⇒ ② 这一支在本几何下不可达'
                  % (find2.get('err') if find2 else '?'))

        print('参数热区点 (%d,%d) box=%s edge=%s' % (sx, sy, pS.get('box'), pS.get('edge')))
        print('判定区点   (%d,%d) box=%s edge=%s n=%s'
              % (tx, ty, pT.get('box'), pT.get('edge'), pT.get('n')))
        B1, B2 = pS.get('box'), pT.get('box')
        inter = None
        if B1 and B2:
            inter = not (B1[2] < B2[0] or B2[2] < B1[0] or B1[3] < B2[1] or B2[3] < B1[1])
            print('两区屏幕包围盒：%s  (鞋%s  区%s)' % ('相交' if inter else '不相交', B1, B2))
        print('距离：dx=%d dy=%d' % (abs(tx - sx), abs(ty - sy)))
        pg.shot(os.path.join(SAMPLE, 'ref.png'))

        print('\n===== 阶段 1：无 pin，点判定区热点 3 轮（验 ① 本身可用）=====')
        print(' reset:', pg.ev(CLEAR)); time.sleep(0.4)
        r1 = [round_(pg, tx, ty, '①无pin%d' % (i + 1)) for i in range(3)]

        print('\n===== 阶段 2：点参数热区 2 轮（验 ② 并建立 pins）=====')
        if s2x is None:
            print('  SKIP —— 该几何下参数热区被 trigger 区整个覆盖，② 不可达（不是失败，是几何事实）')
            r2 = []
        else:
            print(' 用点 (%d,%d)' % (s2x, s2y))
            print(' reset:', pg.ev(CLEAR)); time.sleep(0.4)
            r2 = [round_(pg, s2x, s2y, '②建pin%d' % (i + 1)) for i in range(2)]

        print('\n===== 阶段 3：pin 钉成「模型当前显示值」，点判定区热点 3 轮（M2 精确判据）=====')
        print('  语义：pin 值与 ① 现在的显示值相同。未修（pins 重放赢）⇒ 画面应恒不变；')
        print('        已修（toggleState 清 pin）⇒ ① 真生效、画面必变。与 _on 奇偶无关。')
        r3 = []
        for i in range(3):
            sp = jj(pg, SETPIN)
            if 'err' in sp:
                print('  [SKIP] SETPIN 失败: %s' % sp['err']); break
            print('  pin 钉成 %s（onV=%s offV=%s）' % (sp.get('pinned'), sp.get('onV'),
                                                     sp.get('offV')))
            time.sleep(0.4)
            r3.append(round_(pg, tx, ty, '①有pin%d' % (i + 1)))

        print('\n===== 阶段 4：同一坐标，pin 建好立刻删掉 → 点（正向对照）=====')
        print('  这一阶段必变。若它也不变，则阶段3 的「不变」不能归因给 pins。')
        r4 = []
        for i in range(2):
            sp = jj(pg, SETPIN_DROP)
            if 'err' in sp:
                print('  [SKIP] SETPIN_DROP 失败: %s' % sp['err']); break
            time.sleep(0.4)
            r4.append(round_(pg, tx, ty, '①删pin%d' % (i + 1)))

        print('\n===== 阶段 5：参数热区自然点击 %d 轮（M1 分布）=====' % NAT)
        if s2x is None:
            print('  SKIP —— 同上，② 的代表点不可得')
            nat = []
        else:
            print(' reset:', pg.ev(CLEAR)); time.sleep(0.4)
            nat = [round_(pg, s2x, s2y, '鞋%d' % (i + 1)) for i in range(NAT)]

        print('\n===== 阶段 6：判定区热点自然点击 %d 轮（M1 分布）=====' % NAT)
        print(' reset:', pg.ev(CLEAR)); time.sleep(0.4)
        trg = [round_(pg, tx, ty, '区%d' % (i + 1)) for i in range(NAT)]
        print(' reset:', pg.ev(CLEAR)); time.sleep(0.4)

        print('\n' + '=' * 74)
        print('判定汇总')

        def stat(name, rows):
            if not rows:
                print('  %-22s SKIP（本几何下不可达）' % name)
                return 0, 0, 0, 0
            b1 = sum(1 for x in rows if (x['r'].get('branch') or '').startswith('1'))
            b2 = sum(1 for x in rows if (x['r'].get('branch') or '').startswith('2'))
            bn = sum(1 for x in rows if (x['r'].get('branch') or '') == 'none')
            nz = sum(1 for x in rows if x['nch'] == 0)
            print('  %-22s ①=%d ②=%d none=%d  像素变化 0 的轮数=%d / %d'
                  % (name, b1, b2, bn, nz, len(rows)))
            return b1, b2, bn, nz

        a1 = stat('阶段1 ①无pin', r1)
        a2 = stat('阶段2 ②建pin', r2)
        a3 = stat('阶段3 pin=当前值', r3)
        a4 = stat('阶段4 正向对照', r4)
        s1 = stat('阶段5 鞋热点自然', nat)
        s2 = stat('阶段6 判定区自然', trg)

        v = []
        if a1[0] > 0 and (len(r1) - a1[3]) > 0:
            v.append('① 本身可用：无 pin 时点判定区热点，%d/%d 轮改画面'
                     % (len(r1) - a1[3], len(r1)))
        if a1[0] == 0:
            v.append('⚠️ 阶段1 无一轮落 ① ⇒ 该反解点在本探针的合成事件下走不到 ①，'
                     '下面关于 M2 的读数不可采信（先查合成事件是否被产品接纳）')
        if r2 and a2[3] == 0:
            v.append('② 可用：参数热区点击 %d/%d 轮改画面' % (len(r2), len(r2)))
        if r2 and a2[3] > 0:
            v.append('⚠️ ② 有 %d/%d 轮像素 0 变化 —— 两态等距时取同一端属正常，'
                     '但连点必有一轮该变，故仍提示另查' % (a2[3], len(r2)))
        # M2 精确判据：pin 钉成「当前显示值」，① 若真生效必改画面
        m2_rounds = [x for x in r3 if (x['r'].get('branch') or '').startswith('1')]
        m2_stuck = [x for x in m2_rounds if x['nch'] == 0]
        b2_in_r3 = [x for x in r3 if (x['r'].get('branch') or '').startswith('2')]
        if b2_in_r3:
            v.append('ℹ️ 阶段3 有 %d/%d 轮被 ② 抢走（pin 期该坐标仍落 ②），'
                     '这些轮不参与 M2 判定' % (len(b2_in_r3), len(r3)))
        if m2_stuck:
            v.append('🔴 M2 成立：pin 钉成当前值后，%d/%d 轮落 ① 且**像素 0 变化**，'
                     'pill 报 %r ⇒ ① 的写入被同事件末尾的 pins 重放覆盖'
                     % (len(m2_stuck), len(m2_rounds), m2_stuck[0]['r'].get('pill1')))
        elif m2_rounds:
            v.append('✅ M2 不成立（已修）：pin 钉成当前值后，%d/%d 轮落 ① 且画面全部有变化'
                     % (len(m2_rounds), len(m2_rounds)))
        # 正向对照必须变，否则上面「不变」不能归因给 pins
        ctrl_ok = a4[0] > 0 and (len(r4) - a4[3]) == len(r4)
        if r4 and ctrl_ok:
            v.append('✅ 正向对照通过：同一坐标、pin 建好即删，%d/%d 轮全部改画面 '
                     '⇒ 差异确实来自 pins，不是坐标/合成事件/帧源问题' % (len(r4), len(r4)))
        elif r4:
            v.append('⚠️ 正向对照没全绿（%d/%d 轮改画面）⇒ 阶段3 的「不变」无归因价值，'
                     '本探针此读数作废' % (len(r4) - a4[3], len(r4)))
        if s1[0] > 0 and s1[1] > 0:
            v.append('🔴 M1 成立：参数热区自然点击随机落 ①=%d / ②=%d（hitAt 的 A3 随机抽取）'
                     % (s1[0], s1[1]))
        elif nat and s1[1] == len(nat):
            v.append('M1 不成立于参数热区：%d 轮全落 ②（该点 hitAll 未含 %s）'
                     % (len(nat), trig))
        elif nat and s1[0] == len(nat):
            v.append('⚠️ 参数热区点被 trigger 区整个覆盖：%d 轮全落 ① ⇒ 该点不能用来验 ②'
                     % len(nat))
        if s2[0] > 0 and s2[1] > 0:
            v.append('判定区热点两支都出现（①=%d ②=%d / %d 轮）' % (s2[0], s2[1], len(trg)))
        elif trg and s2[0] == len(trg):
            v.append('判定区热点 %d 轮全落 ①（该几何下判定区优先，符合 onUp 顺序）'
                     % len(trg))
        for x in v:
            print('  · ' + x)

        pg.shot(os.path.join(SAMPLE, 'final.png'))
        print('\n截图目录: %s' % SAMPLE)
        return 0
    finally:
        try: pg._hb_stop.set()
        except Exception: pass
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
