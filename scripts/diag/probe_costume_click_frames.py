"""点热区后逐帧记录：参数值 + 目标 drawable 的 opacity/顶点 —— 查「参数变成 1 了，但部件没变」的真伪。

背景（2026-10-24）：验收脚本两次运行结果不一致——一次变化集合含 ShoseOff 驱动的 [460,461]，
一次不含。而 probe_param_value_states 证明 0 vs 1 之间**确实**有 2 个 drawable 的 opacity 差异。
所以必须逐帧看清「点击之后，渲染时刻的参数到底是多少、部件到底变没变」。

做法：一次 evaluate 里装一个 rAF 采样器（记录 参数值 + 460/461 的 opacity + 顶点包围盒 + 时钟），
再派发真实点击，等 2.5s 取回全部采样。判据落在**渲染同一帧**的参数与部件上，不跨帧猜。

用法: py -3 scripts/diag/probe_costume_click_frames.py ougen_8 ShoseOff
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

HOOK = r"""
(function(){var t=0;function p(){if(!(window.PIXI&&window.PIXI.Container)){if(t++<900)setTimeout(p,20);return;}
  var pr=window.PIXI.Container.prototype;if(pr.__czf)return;pr.__czf=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

# 采样器：每帧记录 参数值 + 驱动部件 opacity/包围盒 + 时间 + currentGroup
START_SAMPLER = r"""
(function(){
  var m=window.__l2model; if(!m) return 'NO_MODEL';
  var core=m.internalModel.coreModel, pid=%s;
  var drv=(window.PARAM_DRAWABLES||{})[%s]||{};
  var idxs=drv[pid]||[];
  window.__czf={rows:[], idxs:idxs, pid:pid, on:true};
  var last=0;
  function tick(ts){
    if(!window.__czf.on) return;
    if(ts-last<30){ requestAnimationFrame(tick); return; }
    last=ts;
    var ix=core.getParameterIndex(pid);
    var row={t:Math.round(performance.now()),
             v:(ix<0?null:+core.getParameterValueById(pid).toFixed(4)),
             pin:((window.__costumePinsByModel||{})[%s]||{})[pid],
             g:((m.internalModel.motionManager.state||{}).currentGroup)||null,
             d:[]};
    for(var k=0;k<idxs.length;k++){
      var i=idxs[k], op=null, bx=null;
      try{ op=+core.getDrawableOpacity(i).toFixed(4); }catch(e){}
      try{ var p=core.getDrawableVertexPositions(i);
        if(p&&p.length>=2){ var xs=[],ys=[];
          for(var q=0;q+1<p.length;q+=2){xs.push(p[q]);ys.push(p[q+1]);}
          bx=[Math.min.apply(null,xs),Math.min.apply(null,ys),
              Math.max.apply(null,xs),Math.max.apply(null,ys)]; } }catch(e){}
      row.d.push([i,op,bx]);
    }
    window.__czf.rows.push(row);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
  return 'STARTED idxs='+JSON.stringify(idxs);
})()
"""


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2
    pg = open_page(BASE, tag='czf')
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
            if pg.ev("(window.__l2model && window.COSTUME && window.PARAM_DRAWABLES)?1:0") == 1:
                break
        if pg.ev("(window.__l2model?1:0)") != 1:
            print('[FAIL] 模型未加载'); return 2

        scr = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID))
        sc = json.loads(scr)
        if not sc:
            print('[FAIL] __costumeScreenOf 为 null'); return 1
        print('屏幕点:', sc)
        print('命中:', pg.ev("JSON.stringify(window.__costumeHit(%d,%d))" % (sc['cx'], sc['cy'])))
        print('采样器:', pg.ev(START_SAMPLER % (json.dumps(PID), json.dumps(KEY), json.dumps(KEY))))
        time.sleep(0.6)   # 采几帧基线
        for typ in ('mousePressed', 'mouseReleased'):
            pg.cmd('Input.dispatchMouseEvent', {'type': typ, 'x': sc['cx'], 'y': sc['cy'],
                                                'button': 'left', 'clickCount': 1})
            time.sleep(0.06)
        print('已点击')
        time.sleep(2.0)
        pg.ev("(window.__czf.on=false, 1)")
        rows = json.loads(pg.ev("JSON.stringify(window.__czf.rows)") or '[]')
        print('采样 %d 帧' % len(rows))
        t0 = rows[0]['t'] if rows else 0
        prev = None
        for r in rows:
            if r['t'] - t0 > 2200:
                break
            line = '  t=%+5dms v=%s pin=%s g=%s ' % (r['t'] - t0, r['v'], r['pin'], r['g'])
            parts = []
            for d in r['d']:
                parts.append('%d(op=%s,bx=%s)' % (d[0], d[1],
                                                  'null' if not d[2] else '[%.2f,%.2f]' % (d[2][0], d[2][1])))
            line += ' | '.join(parts)
            print(line)
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
