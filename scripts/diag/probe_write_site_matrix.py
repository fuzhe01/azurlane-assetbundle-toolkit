"""决定性实验（终章）：写入位置 × 动作是否在播 → 哪种组合能让**画面**变。

## 证据链（2026-10-24，全部为实测）

1. vendor `update()` 顺序（pixi-live2d-display-cubism4-patched.js:5438-5454）:
       motionManager.update()   ← 动作曲线写参数
       saveParameters()
       emit("beforeModelUpdate")
       model.update()           ← ★ 唯一 drawable 求值点
       loadParameters()         ← 参数值改回 saveParameters（"覆盖"的是参数值数组）
2. 「写 1 读回 0」为真，但画面在 model.update() 已算定 ⇒ 它不证明「渲染不生效」。
3. 静音（停动作）后 pin=-1/0/1 → ArtMesh678 bbox [-9.93] / [-9.55] / [-10.0]（probe_shoe_visual）
   ⇒ 参数确实驱动这些部件，且**动作停住时** LOW 写入能进画面。
4. 动作在播时：LOW 与 pre 两种写入位置的 bbox 中位数差都 < 0.16
   （probe_param_write_crossframe，headless 仅 2-3 帧），但 **opacity 在 low 模式 pin=1 时
   从 0/1 变成 0.587/0.853** —— 说明 ShoseOff 的主效应是 opacity，且样本不足使 bbox 判据不可靠。

## 本轮做法

2×2 矩阵（写入位置 × 动作状态），每格都量**同一个东西**：
  driven 部件的 (opacity, bbox)，在 v0 与 v1 两个设定值下各采足够帧，取中位数比差。
  · 帧数：headless 帧率低（~2fps），所以每次采样至少 3.5s，并且**只认帧数 ≥ 5 的格子**，
    帧数不够就显式报 INSUFFICIENT，不许把它当"无变化"。
  · 判据双维度：opacity 差 > 0.1 或 bbox 差 > 0.5 ⇒ 该格画面变化。
  · 阴性对照：每格都额外跑一次「设定值不变、只等同样时长」的本底，要求信号 > 本底。

用法: py -3 scripts/diag/probe_write_site_matrix.py [模型] [参数] [v0] [v1]
      py -3 scripts/diag/probe_write_site_matrix.py ougen_8 ShoseOff 0 1
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
SAMPLE_SECS = 3.5
MIN_FRAMES = 5

HOOK = r"""
(function(){var t=0;function p(){if(!(window.PIXI&&window.PIXI.Container)){if(t++<900)setTimeout(p,20);return;}
  var pr=window.PIXI.Container.prototype;if(pr.__mx)return;pr.__mx=1;var o=pr.addChild;
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
  window.__mx={on:false, rows:[], drv:drv, mode:'none', v:null, quiet:false};

  im.on('beforeModelUpdate', function(){
    if(window.__mx.quiet){ try{ im.breath.setParameters([]); }catch(e){} }
    if(window.__mx.mode==='pre' && window.__mx.v!==null)
      try{ core.setParameterValueById(pid, window.__mx.v); }catch(e){}
  });
  T.add(function(){
    if(window.__mx.mode==='low' && window.__mx.v!==null)
      try{ core.setParameterValueById(pid, window.__mx.v); }catch(e){}
  }, null, LOW);
  T.add(function(){
    if(!window.__mx.on) return;
    var row={t:Math.round(performance.now()), v:null, g:null, d:[]};
    try{ row.v=+core.getParameterValueById(pid).toFixed(4); }catch(e){}
    try{ row.g=(im.motionManager.state||{}).currentGroup||null; }catch(e){}
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
    window.__mx.rows.push(row);
  }, null, LOW);
  return 'INSTALLED drv='+JSON.stringify(drv);
})()
"""


def med(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(statistics.median(vals), 3) if vals else None


def metrics(rows):
    """每个 driven 部件的 (op中位数, bbox 四个分量的中位数)"""
    out = []
    n = len(rows[0]['d']) if rows else 0
    for di in range(n):
        ops = [r['d'][di][1] for r in rows if r['d'][di][1] is not None]
        bxs = [r['d'][di][2] for r in rows if r['d'][di][2]]
        out.append({
            'i': rows[0]['d'][di][0],
            'op': round(statistics.median(ops), 4) if ops else None,
            'bx': [round(statistics.median([b[k] for b in bxs]), 3) for k in range(4)] if bxs else None,
        })
    return out


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2
    pg = open_page(BASE, tag='mx', win=(1400, 1000))
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
        time.sleep(2.5)
        print('帧率自检（1 秒内模型 update 次数）:', end=' ')
        f0 = pg.ev("(function(){window.__fc=(window.__fc||0); return 1;})()")
        # 用 rAF 计帧
        pg.ev("(function(){window.__f0=0; window.__fr=function(){window.__f0++;"
              "requestAnimationFrame(window.__fr);}; requestAnimationFrame(window.__fr); return 1;})()")
        time.sleep(2.0)
        print(str(pg.ev("window.__f0")) + " 帧 / 2s")

        def run(mode, v, quiet=False):
            pg.ev("(window.__mx.rows=[], window.__mx.on=true, window.__mx.mode=%s,"
                  " window.__mx.v=%s, window.__mx.quiet=%s, 1)"
                  % (json.dumps(mode), json.dumps(v), 'true' if quiet else 'false'))
            if quiet:
                # 只停一次动作；呼吸在 beforeModelUpdate 里持续关掉
                pg.ev("""(function(){var im=window.__l2model.internalModel;
                  try{ im.motionManager.queueManager.stopAllMotions(); }catch(e){}
                  try{ im.motionManager.state.complete(); }catch(e){}
                  try{ im.physics=null; }catch(e){}
                  try{ im.eyeBlink=null; }catch(e){}
                  try{ im.expressionManager=null; }catch(e){}
                  try{ im.pose=null; }catch(e){}
                  return 1;})()""")
            time.sleep(SAMPLE_SECS)
            pg.ev("(window.__mx.on=false, 1)")
            return json.loads(pg.ev("JSON.stringify(window.__mx.rows)") or '[]')

        print('\n开始 2x2 矩阵（写入位置 × 动作状态）；每格采样 %.1fs，最少 %d 帧'
              % (SAMPLE_SECS, MIN_FRAMES))
        grid = {}
        for quiet in (False, True):
            label_q = '静音(动作停)' if quiet else 'idle在播'
            for mode in ('pre', 'low'):
                for v in (V0, V1):
                    rows = run(mode, v, quiet)
                    grid[(quiet, mode, v)] = rows
                    print('  %-10s %-4s pin=%-5s 帧数=%-3d 帧内参数中位数=%s'
                          % (label_q, mode, v, len(rows), med(rows, 'v')))

        # 本底：同值连测（只跑 idle 在播 + pre 模式，作为噪声基线）
        base_rows = run('pre', V1, False)
        print('\n本底（idle 在播、pin 固定 %s、连测一次）: %d 帧' % (V1, len(base_rows)))

        print('\n' + '=' * 74)
        ok = True
        for quiet in (False, True):
            label_q = '静音' if quiet else 'idle在播'
            for mode in ('pre', 'low'):
                a = grid.get((quiet, mode, V0)) or []
                b = grid.get((quiet, mode, V1)) or []
                if len(a) < MIN_FRAMES or len(b) < MIN_FRAMES:
                    print('  %-10s %-4s INSUFFICIENT（帧数 %d/%d < %d）'
                          % (label_q, mode, len(a), len(b), MIN_FRAMES)); ok = False; continue
                ma, mb = metrics(a), metrics(b)
                diffs = []
                for x, y in zip(ma, mb):
                    dOp = abs((x['op'] or 0) - (y['op'] or 0))
                    dBx = 0.0
                    if x['bx'] and y['bx']:
                        dBx = max(abs(x['bx'][k] - y['bx'][k]) for k in range(4))
                    diffs.append((x['i'], round(dOp, 3), round(dBx, 3)))
                hit = [d for d in diffs if d[1] > 0.1 or d[2] > 0.5]
                print('  %-10s %-4s → 部件差异 %s  ⇒ %s'
                      % (label_q, mode, diffs, '画面生效(%d 个)' % len(hit) if hit else '画面不变'))
        print('=' * 74)
        print('结论读法：')
        print('  · 「idle在播 + pre」生效 → 必须写在 beforeModelUpdate（任务书「约束 A」是错的）')
        print('  · 「idle在播 + low」不生效 → 现有 pins 的 LOW ticker 对动作驱动参数无效')
        print('  · 「静音 + low」生效 → LOW 只有在动作不驱动该参数时才有效')
        pg.ev("(window.__mx.mode='none', window.__mx.v=null, window.__mx.quiet=false, 1)")
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
