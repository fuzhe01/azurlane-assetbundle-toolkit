"""单帧终极实验：参数写在 beforeModelUpdate 时，**本帧** model.update() 是否按新值算 drawable。

## 为什么必须做（2026-10-24，前序实验互相矛盾）

- `probe_shoe_visual`（停动作 + 关呼吸/物理/表情，用产品 pins 的 LOW ticker）：pin=-1/0/1 →
  ArtMesh678 bbox 分别为 [-9.93,-1.14] / [-9.55,-0.95] / [-10.0,-1.27]，差异 0.4 单位 ⇒ 生效。
- `probe_param_write_site2` / `probe_write_site_matrix`（同样用 LOW，但动作在播）：两种写入位置
  都测不到差异 ⇒ 不生效。
- 三者对不上，说明「LOW 是否生效」取决于**动作是否在驱动该参数**，而这又引出更根本的疑点：
  页面 `app.ticker`（pixi Application 自己的 ticker）与模型 update 所在的 `Ticker.shared`
  是**两个独立 ticker**，两者的相对顺序没有保证 —— 任何"挂在 app.ticker 的 LOW 优先级"的
  时序假设都不可靠。

## 本探针绕开一切时序猜测，直接在**函数边界**测量

patch `core.update`（Cubism 核心的 drawable 求值函数）：
    const orig = core.update.bind(core);
    core.update = function(){
      const r = orig();                     // ← drawable 已按当前参数值算完
      // 此刻读 drawable：这就是本帧真正要被画出去的状态
      return r;
    };
于是「beforeModelUpdate 里写的值」与「本帧 drawable」之间的因果关系是**同一次调用内**确定的，
不依赖任何 ticker 顺序、不依赖帧数、不需要等若干秒。

判据：beforeModelUpdate 里把参数写成 v0 / v1，各采 1 帧的 `core.update` 后状态；
      若两者 drawable 不同 ⇒ 写在 beforeModelUpdate 对画面有效（任务书「约束 A」被证伪）。
      再把对照组放在**动作在播**与**动作停**两种条件下各跑一遍。

用法: py -3 scripts/diag/probe_singleframe_causal.py [模型] [参数] [v0] [v1]
      py -3 scripts/diag/probe_singleframe_causal.py ougen_8 ShoseOff 0 1
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
  var pr=window.PIXI.Container.prototype;if(pr.__sf)return;pr.__sf=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

# 安装：patch core.update，在其末尾（drawable 已算完）快照；beforeModelUpdate 里按设定写参数
INSTALL = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var im=m.internalModel, core=im.coreModel, pid=%s;
  var drv=((window.PARAM_DRAWABLES||{})[%s]||{})[%s]||[];
  window.__sf={drv:drv, mode:'none', v:null, last:null, n:0, preVal:null};

  /* ① beforeModelUpdate：model.update() 之前 —— 任务书所称「会被 loadParameters 覆盖」的位置 */
  im.on('beforeModelUpdate', function(){
    if(window.__sf.mode==='pre' && window.__sf.v!==null){
      try{ core.setParameterValueById(pid, window.__sf.v); }catch(e){}
      try{ window.__sf.preVal=+core.getParameterValueById(pid).toFixed(4); }catch(e){}
    }
  });

  /* ② patch core.update：函数返回时 drawable 已经算完 —— 此刻读到的是本帧真正要画的东西 */
  var orig=core.update.bind(core);
  core.update=function(){
    var r=orig.apply(null, arguments);
    try{
      var row={v:+core.getParameterValueById(pid).toFixed(4), pre:window.__sf.preVal,
               mode:window.__sf.mode, want:window.__sf.v, d:[]};
      for(var k=0;k<drv.length;k++){
        var i=drv[k], op=null, bx=null;
        try{ op=+core.getDrawableOpacity(i).toFixed(4); }catch(e){}
        try{ var p=core.getDrawableVertexPositions(i);
          if(p&&p.length>=2){ var xs=[],ys=[];
            for(var q=0;q+1<p.length;q+=2){xs.push(p[q]);ys.push(p[q+1]);}
            bx=[+Math.min.apply(null,xs).toFixed(3),+Math.min.apply(null,ys).toFixed(3),
                +Math.max.apply(null,xs).toFixed(3),+Math.max.apply(null,ys).toFixed(3)]; } }catch(e){}
        row.d.push([i,op,bx]);
      }
      window.__sf.last=row; window.__sf.n++;
    }catch(e){ window.__sf.err=String(e); }
    return r;
  };
  return 'INSTALLED drv='+JSON.stringify(drv);
})()
"""


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2
    pg = open_page(BASE, tag='sf', win=(1400, 1000))
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
        for _ in range(45):
            time.sleep(1.0)
            if pg.ev("(window.__l2model && window.PARAM_DRAWABLES)?1:0") == 1:
                break
        if pg.ev("(window.__l2model?1:0)") != 1:
            print('[FAIL] 模型未加载'); return 2
        print('安装:', pg.ev(INSTALL % (json.dumps(PID), json.dumps(KEY), json.dumps(PID))))
        time.sleep(2.5)

        def grab(mode, v, wait=2.2):
            """设定写入模式与目标值，等若干帧，取最后一次 core.update 后的状态"""
            pg.ev("(window.__sf.mode=%s, window.__sf.v=%s, window.__sf.last=null, 1)"
                  % (json.dumps(mode), json.dumps(v)))
            time.sleep(wait)
            return json.loads(pg.ev("JSON.stringify(window.__sf.last)") or 'null')

        grp = pg.ev("(function(){var m=window.__l2model;"
                    "return (m.internalModel.motionManager.state||{}).currentGroup||'null';})()")
        print('动作组:', grp)

        print('\n【A】动作在播（idle）')
        a0 = grab('pre', V0)
        a1 = grab('pre', V1)
        print('  beforeModelUpdate 写 %s → 帧末参数=%-8s pre写入瞬间=%-8s drawable=%s'
              % (V0, a0 and a0['v'], a0 and a0['pre'],
                 [(d[0], d[1], d[2]) for d in (a0['d'] if a0 else [])]))
        print('  beforeModelUpdate 写 %s → 帧末参数=%-8s pre写入瞬间=%-8s drawable=%s'
              % (V1, a1 and a1['v'], a1 and a1['pre'],
                 [(d[0], d[1], d[2]) for d in (a1['d'] if a1 else [])]))
        if a0 and a1:
            for x, y in zip(a0['d'], a1['d']):
                dOp = abs((x[1] or 0) - (y[1] or 0))
                dBx = max(abs(x[2][k] - y[2][k]) for k in range(4)) if (x[2] and y[2]) else 0
                print('    drawable %-5s Δop=%+.4f Δbbox=%.3f  %s'
                      % (x[0], (y[1] or 0) - (x[1] or 0), dBx,
                         'CHANGED' if (dOp > 0.02 or dBx > 0.5) else 'same'))

        # 对照：停动作后再测（验证「动作驱动」是不是干扰项）
        pg.ev("""(function(){var im=window.__l2model.internalModel;
          try{ im.motionManager.queueManager.stopAllMotions(); }catch(e){}
          try{ im.motionManager.state.complete(); }catch(e){}
          return 1;})()""")
        time.sleep(1.2)
        print('\n【B】动作停（stopAllMotions）')
        b0 = grab('pre', V0)
        b1 = grab('pre', V1)
        print('  pre 写 %s → 帧末参数=%-8s pre=%s drawable=%s'
              % (V0, b0 and b0['v'], b0 and b0['pre'], [(d[0], d[1], d[2]) for d in (b0['d'] if b0 else [])]))
        print('  pre 写 %s → 帧末参数=%-8s pre=%s drawable=%s'
              % (V1, b1 and b1['v'], b1 and b1['pre'], [(d[0], d[1], d[2]) for d in (b1['d'] if b1 else [])]))
        if b0 and b1:
            for x, y in zip(b0['d'], b1['d']):
                dOp = abs((x[1] or 0) - (y[1] or 0))
                dBx = max(abs(x[2][k] - y[2][k]) for k in range(4)) if (x[2] and y[2]) else 0
                print('    drawable %-5s Δop=%+.4f Δbbox=%.3f  %s'
                      % (x[0], (y[1] or 0) - (x[1] or 0), dBx,
                         'CHANGED' if (dOp > 0.02 or dBx > 0.5) else 'same'))

        print('\ncore.update 累计调用 %s 次；异常=%s'
              % (pg.ev("window.__sf.n"), pg.ev("window.__sf.err||'none'")))
        pg.ev("(window.__sf.mode='none', window.__sf.v=null, 1)")
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
