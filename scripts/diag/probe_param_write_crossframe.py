"""决定性实验 Z：idle **正常播放**时，参数写在哪个位置能让画面真的变。

## 为什么要这一轮（2026-10-24 证据链，任务书「约束 A」被证伪）

已确立的事实：
1. vendor `update()` 顺序（pixi-live2d-display-cubism4-patched.js:5438-5454）：
      motionManager.update()   ← idle 的定值曲线写参数
      saveParameters()
      emit("beforeModelUpdate")
      model.update()           ← ★ 唯一的 drawable 求值点
      loadParameters()         ← 参数值改回 saveParameters
2. 「写 1 读回 0」为真（loadParameters 覆盖参数值数组），但**画面在 model.update() 已算定**。
3. `probe_shoe_visual` 证明 ShoseOff **确实**驱动 ArtMesh678 / ArtMesh243 的顶点：
   pin=-1 / 0 / 1 → bbox 分别是 [-9.93,-1.14] / [-9.55,-0.95] / [-10.0,-1.27]，差异远超噪声。
   （所以「ShoseOff 没有可见效果」是错的，先前判据被 idle 演进污染了。）
4. `probe_param_write_site2`（单帧读）两种写入位置都读不到差异 —— 因为**同一帧里**
   写入发生在 model.update 之后（LOW）或写后立刻被 loadParameters 改回读数（pre）；
   真正的证据必须**跨帧**取（下一帧 model.update 才会按新参数值重算）。

## 做法

idle 保持正常播放（不复用前面的静音），两种写入位置各跑一组：
  每组把 pin 值设为 v0 与 v1，各采 N 帧（跨帧！），比较 driven 部件的 bbox 分布。
判据：两组 bbox 的中位数差异 > 0.5 单位 ⇒ 该写入位置能让**画面**随参数变化。

两组都在 LOW ticker **末尾**采样（此时本帧 model.update 已跑完、loadParameters 也跑完，
读到的就是这一帧真正画出去的状态）。

用法: py -3 scripts/diag/probe_param_write_crossframe.py [模型] [参数] [v0] [v1]
      py -3 scripts/diag/probe_param_write_crossframe.py ougen_8 ShoseOff 0 1
"""
import json
import os
import statistics
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
  var pr=window.PIXI.Container.prototype;if(pr.__cf)return;pr.__cf=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

INSTALL = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var im=m.internalModel, core=im.coreModel, pid=%s;
  var drv=((window.PARAM_DRAWABLES||{})[%s]||{})[%s]||[];
  var T=window.PIXI.Ticker.shared;
  var LOW=(window.PIXI.UPDATE_PRIORITY&&window.PIXI.UPDATE_PRIORITY.LOW)||-25;
  window.__cf={on:false, rows:[], drv:drv, mode:'none', v:null};

  /* 写入者 A：beforeModelUpdate（model.update 之前） */
  im.on('beforeModelUpdate', function(){
    if(window.__cf.mode==='pre' && window.__cf.v!==null)
      try{ core.setParameterValueById(pid, window.__cf.v); }catch(e){}
  });
  /* 写入者 B：LOW ticker（model.update 之后） */
  T.add(function(){
    if(window.__cf.mode==='low' && window.__cf.v!==null)
      try{ core.setParameterValueById(pid, window.__cf.v); }catch(e){}
  }, null, LOW);
  /* 采样器：同 LOW、后注册 → 读到本帧真正画出去的状态 */
  T.add(function(){
    if(!window.__cf.on) return;
    var row={t:Math.round(performance.now()), pinVal:null, d:[]};
    try{ row.pinVal=+core.getParameterValueById(pid).toFixed(4); }catch(e){}
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
    window.__cf.rows.push(row);
  }, null, LOW);
  return 'INSTALLED drv='+JSON.stringify(drv);
})()
"""


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2
    pg = open_page(BASE, tag='cf', win=(1400, 1000))
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
        print('装探针:', pg.ev(INSTALL % (json.dumps(PID), json.dumps(KEY), json.dumps(PID))))
        time.sleep(3.0)   # 让 idle 真的播起来（这是本实验的前提：动作在跑）
        grp = pg.ev("(function(){var m=window.__l2model;"
                    "return (m.internalModel.motionManager.state||{}).currentGroup||'null';})()")
        print('当前动作组（必须在播）:', grp)
        if grp == 'null':
            print('[WARN] 动作未在播 —— 本实验的结论只能代表静止态')

        def run(mode, v, secs=1.6):
            pg.ev("(window.__cf.rows=[], window.__cf.on=true, window.__cf.mode=%s, window.__cf.v=%s, 1)"
                  % (json.dumps(mode), json.dumps(v)))
            time.sleep(secs)
            pg.ev("(window.__cf.on=false, 1)")
            rows = json.loads(pg.ev("JSON.stringify(window.__cf.rows)") or '[]')
            return rows

        def summarize(rows, di):
            xs = [r['d'][di][2][0] for r in rows if r['d'][di][2]]
            ys = [r['d'][di][2][1] for r in rows if r['d'][di][2]]
            ops = [r['d'][di][1] for r in rows if r['d'][di][1] is not None]
            if not xs:
                return None
            return {'n': len(xs), 'x_med': round(statistics.median(xs), 3),
                    'y_med': round(statistics.median(ys), 3),
                    'x_rng': round(max(xs) - min(xs), 3),
                    'op_med': round(statistics.median(ops), 3) if ops else None,
                    'readback_med': round(statistics.median(
                        [r['pinVal'] for r in rows if r['pinVal'] is not None]), 3)}

        results = {}
        for mode in ('pre', 'low'):
            for v in (V0, V1):
                rows = run(mode, v)
                results[(mode, v)] = rows
                print('\n%-4s 模式  pin=%s：采样 %d 帧' % (mode, v, len(rows)))
                for di in range(len(json.loads(pg.ev(
                        "JSON.stringify((window.__cf||{}).drv||[])")))):
                    s = summarize(rows, di)
                    if s:
                        print('   driven[%d] x中位数=%s y中位数=%s x极差=%s op中位数=%s'
                              '（帧末参数读回中位数=%s）'
                              % (di, s['x_med'], s['y_med'], s['x_rng'], s['op_med'],
                                 s['readback_med']))

        print('\n' + '=' * 66)
        print('判定：同一写入位置下，v0 与 v1 的 bbox 中位数差 > 0.5 单位 = 该位置能让画面变')
        verdict = {}
        for mode in ('pre', 'low'):
            a, b = results.get((mode, V0)), results.get((mode, V1))
            if not a or not b:
                print('  %-4s 无数据' % mode); continue
            deltas = []
            for di in range(len(json.loads(pg.ev("JSON.stringify((window.__cf||{}).drv||[])")))):
                sa, sb = summarize(a, di), summarize(b, di)
                if sa and sb:
                    deltas.append(round(abs(sa['x_med'] - sb['x_med']), 3))
            verdict[mode] = deltas
            print('  %-4s 写入 → 各部件的 x 中位数差 = %s  ⇒ %s'
                  % (mode, deltas,
                     '画面生效' if any(d > 0.5 for d in deltas) else '画面不变'))
        pg.ev("(window.__cf.mode='none', window.__cf.v=null, 1)")
        print('=' * 66)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
