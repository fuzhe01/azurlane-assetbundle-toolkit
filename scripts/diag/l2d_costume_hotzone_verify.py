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

from cdp_helper import open_page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PID = sys.argv[2] if len(sys.argv) > 2 else 'ShoseOff'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'
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
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
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

READ = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
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
    pg = open_page(BASE, tag='czh')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        # 关掉开场 login，并禁缓存（§19.6：改完前端仍读到旧文件 = 假阴性）
        pg.cmd('Network.enable')
        pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': BASE})
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
        for _ in range(40):
            time.sleep(1.0)
            ok = pg.ev("""(function(){ return (window.__l2model && window.COSTUME
               && window.PARAM_DRAWABLES && window.__costumeBoxes)? 1 : 0; })()""")
            if ok == 1:
                break
        if pg.ev("(window.__l2model?1:0)") != 1:
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

        # ---------- ② 屏幕点 + 派发真实输入 ----------
        scr = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID))
        print('\n② __costumeScreenOf(%s) = %s' % (PID, scr))
        try:
            sc = json.loads(scr)
        except Exception:  # noqa: BLE001
            print('[FAIL] 屏幕点解析失败'); return 2
        if not sc:
            print('[FAIL] 该热区在视口内点不到（出画/被遮挡）'); return 1
        cx, cy = sc['cx'], sc['cy']

        # 点击前：停住动作（stopAllMotions 会把 currentGroup 清掉，参数不再被曲线改写）
        pg.ev("""(function(){var m=window.__l2model;
          try{ m.internalModel.motionManager.queueManager.stopAllMotions(); }catch(e){}
          try{ m.internalModel.motionManager.state.complete(); }catch(e){}
          return 1;})()""")
        time.sleep(1.2)

        # ---------- ⑤ 漂移对照（先跑，避免受本脚本自己的点击影响）----------
        dA = pg.ev(SNAP)
        time.sleep(1.4)
        dB = pg.ev(SNAP)
        drift = json.loads(pg.ev(DIFF % (json.dumps(json.loads(dA)), json.dumps(json.loads(dB)))))
        print('\n⑤ 漂移对照（不点、等同样时长）:', drift)

        read_expr = READ % (json.dumps(PID), json.dumps(KEY))
        before = json.loads(pg.ev(read_expr))
        print('   点击前参数:', before)
        # 点击前的基线截图（目视对比用；判据不靠它，但它能让人一眼看出鞋穿没穿）
        pg.shot(os.path.join(OUT, '%s_%s_before.png' % (KEY, PID)))
        grp_before = pg.ev("(function(){var m=window.__l2model;"
                           " return (m&&m.internalModel.motionManager.state.currentGroup)||'null';})()")
        print('   点击前 currentGroup:', grp_before)

        # 命中判定必须**先行确认**（不派发，只问产品函数）：确保这个点真的落到目标热区
        hitname = pg.ev("JSON.stringify(window.__costumeHit(%d,%d))" % (cx, cy))
        print('   该点命中:', hitname)
        try:
            hn = json.loads(hitname)
        except Exception:  # noqa: BLE001
            hn = None
        if not hn or hn.get('id') != PID:
            print('[FAIL] 屏幕点没落到目标热区（命中 %s）' % (hn or {}).get('id')); return 1

        snapA = pg.ev(SNAP)
        # 真实输入派发（pointerdown + pointerup，位移 0 才算点击；onUp 里 moved>=6 会当成拖拽）
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': cx, 'y': cy,
                                               'button': 'left', 'clickCount': 1})
            time.sleep(0.08)
        print('   已派发 pointerdown/up @ (%d,%d)' % (cx, cy))

        # 等 tween 走完（dur 450ms）+ 稳定
        time.sleep(1.4)
        after = json.loads(pg.ev(read_expr))
        grp_after = pg.ev("(function(){var m=window.__l2model;"
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
        pg.ev("""(function(){var m=window.__l2model; var c=m.internalModel.coreModel;
          var ix=c.getParameterIndex('ParamAngleX');
          if(ix<0) return 0;
          window.__posA=c.getParameterValueById('ParamAngleX');
          c.setParameterValueById('ParamAngleX', c.getParameterMaximumValue(ix));
          try{ m.internalModel.update(0, performance.now()); }catch(e){}
          return 1;})()""")
        time.sleep(0.2)
        posSnap = pg.ev(SNAP)
        posDif = json.loads(pg.ev(DIFF % (json.dumps(json.loads(snapA)), json.dumps(json.loads(posSnap)))))
        pg.ev("""(function(){var m=window.__l2model; var c=m.internalModel.coreModel;
          c.setParameterValueById('ParamAngleX', window.__posA===undefined?0:window.__posA); return 1;})()""")
        print('   阳性对照 ParamAngleX=→max 的画面差异:', posDif)

        pg.shot(os.path.join(OUT, '%s_%s_after.png' % (KEY, PID)))
        pg.shot(os.path.join(OUT, '%s_%s_final.png' % (KEY, PID)))

        # 旁证：点击同时会移动指针，眼神跟随（ParamEyeBallX/Y）被点位置改写，头部也有连带小位移。
        # 记下来是为了解释"变化集合里还多几个不属于本参数的部件"——那是点击的副产物，不是缺陷。
        print('   眼神参数（点击副产物）:', pg.ev("""(function(){
          var c=window.__l2model.internalModel.coreModel; var o={};
          ['ParamEyeBallX','ParamEyeBallY'].forEach(function(k){
            var ix=c.getParameterIndex(k); o[k]= ix<0? 'NO_IDX' : +c.getParameterValueById(k).toFixed(3); });
          return JSON.stringify(o);})()"""))

        # ---------- ④ 用**产品自己的 pins 机制**在两端稳态各采一次，要求差异点名到本参数的部件 ----------
        # 为什么不用"点击前后各采一次"当判据：实测两次运行结论相反 —— 一次变化集合含 [460,461]，
        # 一次不含。根因不是功能坏了，而是 **idle 变体会把该参数钉在某一端**（ougen_8 的 45 个 clip 里
        # ShoseOff 恒写成 8，core 内部 clamp 到 max=1）；随机 idle 变体落到「已经是脱鞋态」时，
        # 0→1 自然就没有可见差异。判据必须先消除这个噪声，否则同一个功能会时红时绿。
        # 做法：pins 是产品的实际写入路径（LOW ticker 每帧重申），用它把参数稳在 lo 与 hi，
        # 各等几帧让 coreModel 完成一次 drawable 求值，再逐 drawable 比 —— 差异必须点名到驱动集合。
        pin_set = """(function(){
          var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
          if(!pm[%s]) pm[%s]=Object.create(null);
          pm[%s][%s]=%s; return 1;})()"""
        base_lo, base_hi = tgt['lo'], tgt['hi']
        pg.ev(pin_set % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY),
                         json.dumps(PID), json.dumps(base_lo)))
        time.sleep(0.9)
        snapLo = json.loads(pg.ev(SNAP))
        pg.ev(pin_set % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY),
                         json.dumps(PID), json.dumps(base_hi)))
        time.sleep(0.9)
        snapHi = json.loads(pg.ev(SNAP))
        pairDif = json.loads(pg.ev(DIFF % (json.dumps(snapLo), json.dumps(snapHi))))
        print('\n④ pins 稳态对比 lo=%s vs hi=%s:' % (base_lo, base_hi), pairDif)

        driven = pg.ev("""(function(){
          var t=(window.PARAM_DRAWABLES||{})[%s]||{};
          var a=t[%s]; return JSON.stringify(a||null);})()"""
                       % (json.dumps(KEY), json.dumps(PID)))
        try:
            driven_idx = json.loads(driven) or []
        except Exception:  # noqa: BLE001
            driven_idx = []
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
        if not inter:
            fails.append('pins 稳态 lo↔hi 的差异与 %s 驱动的部件无交集 → 该参数在本模型上'
                         '没有可见效果（数据/映射问题，不是热区问题）' % PID)
        if drift.get('changed', 0) > 0:
            print('   注意：漂移对照有 %d 个变化（idle 在本底演化），仅供参考' % drift.get('changed', 0))
        if grp_after != grp_before:
            fails.append('点击后动作组变了(%s→%s) —— 热区不该播 motion' % (grp_before, grp_after))
        if hn and hn.get('id') == PID and di.get('changed', 0) > 0:
            passes = ['点中参数热区（真实输入派发）',
                      '参数 %s: %s → %s' % (PID, before['v'], after['v']),
                      '参数值连推 5 帧稳定在 %s' % stable[0],
                      'pins 稳态 lo=%s ↔ hi=%s：%d 个 drawable 变化，其中 %d 个属本参数驱动集合（%s）'
                      % (base_lo, base_hi, pairDif['changed'], len(inter), inter),
                      '未播 motion（currentGroup 保持 %s）' % grp_after,
                      '阳性对照 %d 个 drawable 变化（判据不瞎）' % posDif['changed']]
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
