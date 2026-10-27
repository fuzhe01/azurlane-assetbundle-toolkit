"""决定性实验：参数写在**哪个位置**才会真的进入本帧渲染。

背景（2026-10-24，推翻任务书里「约束 A」的实证）：
  vendor 源码 `Cubism4InternalModel.update()` 的真实顺序（pixi-live2d-display-cubism4-patched.js:5433）：
      motionManager.update(...)          ← 动作曲线铺参数值
      model.saveParameters()             ← 存档（此刻的值）
      emit("beforeModelUpdate")          ← 项目里 stateApply 挂在这里
      model.update()                     ← ★ 按当前参数值算 drawable 顶点/透明度（只有这里算）
      model.loadParameters()             ← 把参数值改回存档（"覆盖"的就是**参数值数组**，不是 drawable）

  ⇒ `loadParameters()` 覆盖的是 `_parameterValues`，而**画面**由 `model.update()` 在上一步已经算定。
    「写 1 读回 0」这个观测是真的（参数值被改回），但它**不等于**"渲染不生效"。
    反过来，挂在 app.ticker LOW（在 model.update 之后）写参数，只能改参数值数组，
    **本帧的 drawable 已经算完**，渲染读的是算好的 drawable ⇒ 写进去看不到任何画面变化。

  本探针同时测三种写入位置对 drawable 的实际影响：
    A. LOW ticker 写（= 项目现有 pins 机制 / 任务书「约束 A」推荐的位置）
    B. beforeModelUpdate 写（= stateApply 的位置）
    C. 直接写 + 手动 im.update()

  判据落在 **drawable 的 opacity/顶点**（技能 §20.3），点在具体部件上，不用像素哈希。
    每个位置记录：写入后该参数值（证明"参数值是否被覆盖"）与 drawable 是否真的变了（证明"渲染是否生效"）。
  用法: py -3 scripts/diag/probe_param_write_site.py ougen_8 ShoseOff 0 1
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
V0 = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
V1 = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){var t=0;function p(){if(!(window.PIXI&&window.PIXI.Container)){if(t++<900)setTimeout(p,20);return;}
  var pr=window.PIXI.Container.prototype;if(pr.__ws)return;pr.__ws=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

# 快照：驱动部件的 opacity + 顶点包围盒（不经截图）
SNAP = r"""
(function(){
  var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
  var core=m.internalModel.coreModel;
  var drv=((window.PARAM_DRAWABLES||{})[%s]||{})[%s]||[];
  var out=[], v=+core.getParameterValueById(%s);
  for(var k=0;k<drv.length;k++){
    var i=drv[k], op=null, bx=null;
    try{ op=+core.getDrawableOpacity(i).toFixed(4); }catch(e){}
    try{ var p=core.getDrawableVertexPositions(i);
      if(p&&p.length>=2){ var xs=[],ys=[];
        for(var q=0;q+1<p.length;q+=2){xs.push(p[q]);ys.push(p[q+1]);}
        bx=[+Math.min.apply(null,xs).toFixed(3),+Math.min.apply(null,ys).toFixed(3),
            +Math.max.apply(null,xs).toFixed(3),+Math.max.apply(null,ys).toFixed(3)]; } }catch(e){}
    out.push([i,op,bx]);
  }
  return JSON.stringify({v:+v.toFixed(4), d:out});
})()
""" % ('%s', '%s', '%s')


def preflight():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main():
    if not preflight():
        print('[INVALID] 服务不可达'); return 2
    pg = open_page(BASE, tag='wsite')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Network.enable'); pg.cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        pg.cmd('Page.navigate', {'url': BASE})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
              % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        for _ in range(40):
            time.sleep(1.0)
            if pg.ev("(window.__l2model && window.PARAM_DRAWABLES)?1:0") == 1:
                break
        if pg.ev("(window.__l2model?1:0)") != 1:
            print('[FAIL] 模型未加载'); return 2

        snap_expr = SNAP % (json.dumps(KEY), json.dumps(PID), json.dumps(PID))
        # 先把动作停掉（避免 motion 曲线与 pin 抢参数），再测三个写入位置
        pg.ev("""(function(){var m=window.__l2model;
          try{ m.internalModel.motionManager.queueManager.stopAllMotions(); }catch(e){}
          try{ m.internalModel.motionManager.state.complete(); }catch(e){}
          return 1;})()""")
        time.sleep(1.0)
        print('停动作后当前组:', pg.ev("(function(){var m=window.__l2model;"
                                       "return (m.internalModel.motionManager.state||{}).currentGroup||'null';})()"))

        app_expr = """(function(){var m=window.__l2model, n=m, app=null;
          while(n&&!app){ if(n.ticker&&n.renderer) app=n; n=n.parent; }
          return !!app;})()"""
        print('能拿到 app 对象:', pg.ev(app_expr))

        results = {}

        # ---------- A. LOW ticker 写（现状 pins 的方式） ----------
        pg.ev("""(function(){
          var m=window.__l2model, n=m, app=null;
          while(n&&!app){ if(n.ticker&&n.renderer) app=n; n=n.parent; }
          if(!app) return 0;
          var LOW=(window.PIXI.UPDATE_PRIORITY&&window.PIXI.UPDATE_PRIORITY.LOW)||-25;
          window.__wpin=%s;
          if(!window.__wtick){ window.__wtick=app.ticker.add(function(){
            if(window.__wpin===null) return;
            try{ m.internalModel.coreModel.setParameterValueById(%s, window.__wpin); }catch(e){}
          }, null, LOW); }
          return 1;})()""" % (json.dumps(V0), json.dumps(PID)))
        time.sleep(1.0)
        aLo = json.loads(pg.ev(snap_expr))
        pg.ev("(window.__wpin=%s, 1)" % json.dumps(V1))
        time.sleep(1.2)
        aHi = json.loads(pg.ev(snap_expr))
        results['A_LOW_ticker'] = (aLo, aHi)

        # ---------- B. beforeModelUpdate 写 ----------
        pg.ev("(window.__wpin=null, 1)")
        time.sleep(0.5)
        pg.ev("""(function(){
          var m=window.__l2model;
          window.__wpre=%s;
          if(!window.__wpreH){ window.__wpreH=true;
            m.internalModel.on('beforeModelUpdate', function(){
              if(window.__wpre===null) return;
              try{ m.internalModel.coreModel.setParameterValueById(%s, window.__wpre); }catch(e){}
            }); }
          return 1;})()""" % (json.dumps(V0), json.dumps(PID)))
        time.sleep(1.0)
        bLo = json.loads(pg.ev(snap_expr))
        pg.ev("(window.__wpre=%s, 1)" % json.dumps(V1))
        time.sleep(1.2)
        bHi = json.loads(pg.ev(snap_expr))
        results['B_beforeModelUpdate'] = (bLo, bHi)
        pg.ev("(window.__wpre=null, 1)")
        time.sleep(0.4)

        # ---------- C. 直接写 + 手动 im.update() ----------
        def direct(v):
            pg.ev("""(function(){var m=window.__l2model, c=m.internalModel.coreModel;
              c.setParameterValueById(%s, %s);
              try{ m.internalModel.update(0, performance.now()); }catch(e){}
              return 1;})()""" % (json.dumps(PID), json.dumps(v)))
            time.sleep(0.15)
            return json.loads(pg.ev(snap_expr))
        cLo = direct(V0)
        cHi = direct(V1)
        results['C_write_then_manual_update'] = (cLo, cHi)

        # ---------- 报告 ----------
        print('\n参数 %s，测试值 %s ↔ %s；判据 = 驱动部件 opacity/顶点是否变化' % (PID, V0, V1))
        for name in ('A_LOW_ticker', 'B_beforeModelUpdate', 'C_write_then_manual_update'):
            lo, hi = results[name]
            print('\n--- %s ---' % name)
            print('   写入 %s 后 参数值=%s；写入 %s 后 参数值=%s  %s'
                  % (V0, lo.get('v'), V1, hi.get('v'),
                     '← 参数值被 loadParameters 改回' if abs(hi.get('v', 0) - V1) > 1e-3 else '← 参数值保持'))
            for (a, b) in zip(lo.get('d', []), hi.get('d', [])):
                dOp = abs((a[1] or 0) - (b[1] or 0))
                dBox = 0.0
                if a[2] and b[2]:
                    dBox = max(abs(a[2][k] - b[2][k]) for k in range(4))
                flag = 'CHANGED' if (dOp > 0.02 or dBox > 0.5) else 'same'
                print('   drawable %-5s op %s→%s (Δ%+.4f)  bbox %s→%s (Δ%.2f)  %s'
                      % (a[0], a[1], b[1], (b[1] or 0) - (a[1] or 0), a[2], b[2], dBox, flag))
        # 收尾：清掉探针写入
        pg.ev("(window.__wpin=null, window.__wpre=null, 1)")
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
