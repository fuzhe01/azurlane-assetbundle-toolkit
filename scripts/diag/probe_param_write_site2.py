"""决定性实验（修正版）：参数写在 beforeModelUpdate vs LOW ticker，哪个真的进画面。

## 为什么必须重做（2026-10-24 实测推翻任务书「约束 A」）

vendor 源码 `pixi-live2d-display-cubism4-patched.js:5443-5454` 的真实顺序：

    const motionUpdated = this.motionManager.update(this.coreModel, now);   // ① 动作曲线铺参数值
    model.saveParameters();                                                 // ② 存档
    ...
    this.emit("beforeModelUpdate");                                         // ③
    model.update();                                                         // ④ ★ 只在这里按参数值算 drawable
    model.loadParameters();                                                 // ⑤ 把参数值改回 ② 的存档

- ⑤ 覆盖的是 `_parameterValues`（参数值数组），**画面（drawable）在 ④ 已经算定**，
  所以「写 1 读回 0」为真，但它**不等于**"渲染没生效"。
- 挂在 app.ticker LOW（在 ④ 之后）写参数：本帧 drawable 已算完；**下一帧 ① 又会用动作曲线
  把参数值盖掉**，④ 于是按动作值重算 → 写进去的值**永远进不了画面**。
  对「被当前动作驱动」的参数（换装参数基本都在 idle 的定值曲线里）这是必然结果。

## 本探针测什么

三个写入位置 × 同样的驱动部件读法，判据落在 drawable（技能 §20.3），避免像素哈希/呼吸噪声：

  W1 beforeModelUpdate 写   → 在 ④ 之前，应当影响画面
  W2 LOW ticker 写          → 在 ④ 之后，预计影响不到画面
  采样点统一放在 **LOW ticker 末尾**（此时 ④ 已跑完，读到的就是"这一帧真正画出去"的状态），
  并且采样器比两个写入者**后注册**（同优先级按注册序执行）。

两个值各跑一段，比 driven drawable 的 opacity / bbox。

用法: py -3 scripts/diag/probe_param_write_site2.py [模型] [参数] [v0] [v1]
      py -3 scripts/diag/probe_param_write_site2.py ougen_8 ShoseOff 0 1
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
  var pr=window.PIXI.Container.prototype;if(pr.__ws2)return;pr.__ws2=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

INSTALL = r"""
(function(){
  var m=window.__l2model;
  if(!m) return 'NO_MODEL';
  var im=m.internalModel, core=im.coreModel, pid=%s;
  var drv=((window.PARAM_DRAWABLES||{})[%s]||{})[%s]||[];

  /* 找到页面真正在跑模型更新的那个 Ticker：vendor 用 Ticker.shared.add(onTickerUpdate)。
     实测 mdl.parent 链上没有带 ticker 的 Application（pixi6 的 app.ticker 是独立实例），
     所以必须直接用 PIXI.Ticker.shared —— 这也解释了「LOW ticker 拿不到 app」的老问题。 */
  var T=window.PIXI.Ticker.shared;
  var LOW=(window.PIXI.UPDATE_PRIORITY&&window.PIXI.UPDATE_PRIORITY.LOW)||-25;

  window.__w2={on:true, rows:[], drv:drv, mode:'none', v:null};

  /* 写入者 1：beforeModelUpdate（④ model.update 之前） */
  im.on('beforeModelUpdate', function(){
    if(window.__w2.mode==='pre' && window.__w2.v!==null)
      try{ core.setParameterValueById(pid, window.__w2.v); }catch(e){}
  });
  /* 写入者 2：LOW ticker（④ 之后） */
  T.add(function(){
    if(window.__w2.mode==='low' && window.__w2.v!==null)
      try{ core.setParameterValueById(pid, window.__w2.v); }catch(e){}
  }, null, LOW);
  /* 采样器：同样 LOW、但在写入者之后注册 → 读到的是本帧 ④ 算完的真实状态 */
  T.add(function(){
    if(!window.__w2.on) return;
    var r={t:Math.round(performance.now()), v:null, pin:null, d:[],
           g:(im.motionManager.state||{}).currentGroup||null};
    try{ r.v=+core.getParameterValueById(pid).toFixed(4); }catch(e){}
    for(var k=0;k<drv.length;k++){
      var i=drv[k], op=null, bx=null;
      try{ op=+core.getDrawableOpacity(i).toFixed(4); }catch(e){}
      try{ var p=core.getDrawableVertexPositions(i);
        if(p&&p.length>=2){ var xs=[],ys=[];
          for(var q=0;q+1<p.length;q+=2){xs.push(p[q]);ys.push(p[q+1]);}
          bx=[+Math.min.apply(null,xs).toFixed(3),+Math.min.apply(null,ys).toFixed(3),
              +Math.max.apply(null,xs).toFixed(3),+Math.max.apply(null,ys).toFixed(3)]; } }catch(e){}
      r.d.push([i,op,bx]);
    }
    window.__w2.rows.push(r);
    if(window.__w2.rows.length>400) window.__w2.rows.shift();
  }, null, LOW);
  return 'INSTALLED drv='+JSON.stringify(drv)+' tickerStarted='+T.started;
})()
"""


def preflight():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main():
    if not preflight():
        print('[INVALID] 服务不可达'); return 2
    pg = open_page(BASE, tag='ws2')
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
        print('装探针:', pg.ev(INSTALL % (json.dumps(PID), json.dumps(KEY), json.dumps(PID))))
        time.sleep(3.0)   # 让 idle 正常播起来

        def measure(mode, v, wait=1.3):
            pg.ev("(window.__w2.rows=[], window.__w2.mode=%s, window.__w2.v=%s, 1)"
                  % (json.dumps(mode), json.dumps(v)))
            time.sleep(wait)
            rows = json.loads(pg.ev("JSON.stringify(window.__w2.rows)") or '[]')
            return rows[-1] if rows else None

        print('\n%-22s %-8s %-10s %s' % ('写入位置', '设定值', '帧内参数', '驱动部件（op, bbox）'))
        got = {}
        for mode in ('pre', 'low'):
            for v in (V0, V1):
                r = measure(mode, v)
                got[(mode, v)] = r
                if not r:
                    print('%-22s %-8s (无采样)' % (mode, v)); continue
                dd = ' | '.join('%s op=%s bx=%s' % (d[0], d[1], d[2]) for d in r['d'])
                print('%-22s %-8s v=%-9s %s' % (mode, v, r['v'], dd))

        print('\n判定（driven 部件在 v0 vs v1 之间是否变化）：')
        for mode in ('pre', 'low'):
            a, b = got.get((mode, V0)), got.get((mode, V1))
            if not a or not b:
                print('  %-4s 无数据' % mode); continue
            changed = []
            for x, y in zip(a['d'], b['d']):
                dOp = abs((x[1] or 0) - (y[1] or 0))
                dBox = 0.0
                if x[2] and y[2]:
                    dBox = max(abs(x[2][k] - y[2][k]) for k in range(4))
                if dOp > 0.02 or dBox > 0.5:
                    changed.append((x[0], round(dOp, 3), round(dBox, 2)))
            print('  beforeModelUpdate 写 -> %d 个部件变化 %s'
                  % (len(changed), changed) if mode == 'pre'
                  else '  LOW ticker 写      -> %d 个部件变化 %s' % (len(changed), changed))
        pg.ev("(window.__w2.mode='none', window.__w2.v=null, 1)")
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
