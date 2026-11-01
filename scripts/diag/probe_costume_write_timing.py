"""查「pins 写在 LOW ticker 之后，到底有没有进到本帧渲染」——参数写入时机的实证。

背景（2026-10-24）：热区点击后参数确实变成 1 且稳定，但「pins 稳态 lo=-1 vs hi=1」逐 drawable
比对为 0 差异；而同一 evaluate 内强制 `im.update()` 再比，却有 2 个 drawable 差异。
两者矛盾 ⇒ 必须分清三种时刻的参数/部件状态：
  A. 帧内 update 前（参数已被 loadParameters 铺过）
  B. LOW ticker 里（pins/tween 刚写完参数，尚未重新求 keyform）
  C. 下一帧 update 之后（keyform 按 B 留下的参数重算）

做法：在页面里装一个 LOW 优先级 ticker（排在最末），逐帧记录
  [参数值, 460/461 的 opacity, 驱动集合全部 opacity]，并同时记录 `paramSets[idle]` 是否含该参数。
  · 若某帧的记录里 opacity 随 pin 值变化 ⇒ 写入到达渲染（功能正确）。
  · 若 opacity 恒等于 motion 值、只有 pin 值在变 ⇒ 写入被 loadParameters 覆盖，需要改时机。

用法: py -3 scripts/diag/probe_costume_write_timing.py ougen_8 ShoseOff 0 1
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
  var pr=window.PIXI.Container.prototype;if(pr.__wt)return;pr.__wt=1;var o=pr.addChild;
  pr.addChild=function(){for(var i=0;i<arguments.length;i++){var c=arguments[i];
    try{if(c&&c.internalModel&&c.internalModel.coreModel)window.__l2model=c;}catch(e){}}return o.apply(this,arguments);};}p();})()
"""

# 装一个「最末」LOW ticker：记录参数 + 驱动部件 opacity + 本帧 update 前快照
INSTALL = r"""
(function(){
  var m=window.__l2model;
  if(!m||!window.PIXI||!window.PIXI.Application) return 'NO_APP';
  var core=m.internalModel.coreModel, pid=%s;
  var drv=((window.PARAM_DRAWABLES||{})[%s]||{})[%s]||[];
  var im=m.internalModel;
  var idle=(m.internalModel.motionManager.groups||{}).idle;
  window.__wt={rows:[], drv:drv, on:true};
  /* 帧内 update 前探针（beforeModelUpdate = loadParameters 之前、model.update 之前） */
  im.on('beforeModelUpdate', function(){
    try{ window.__wt.pre = core.getParameterValueById(pid); }catch(e){ window.__wt.pre=null; }
    try{ window.__wt.preOp = drv.map(function(i){ return +core.getDrawableOpacity(i).toFixed(3); }); }catch(e){}
  });
  /* 找到 app：从 mdl.parent 一路到带 ticker 的 Application */
  var app=null, n=m;
  while(n && !app){ if(n.ticker && n.renderer) app=n; n=n.parent; }
  if(!app) return 'NO_APP_OBJ';
  var LOW=(window.PIXI.UPDATE_PRIORITY&&window.PIXI.UPDATE_PRIORITY.LOW)||-25;
  var last=0;
  app.ticker.add(function(){
    if(!window.__wt.on) return;
    var now=performance.now();
    if(now-last<25) return; last=now;
    var r={t:Math.round(now), pre:window.__wt.pre, v:null, pin:null, op:[], preOp:window.__wt.preOp,
           g:(m.internalModel.motionManager.state||{}).currentGroup||null};
    try{ r.v=+core.getParameterValueById(pid).toFixed(4); }catch(e){}
    try{ r.pin=((window.__costumePinsByModel||{})[%s]||{})[pid]; }catch(e){}
    try{ r.op=drv.map(function(i){ return +core.getDrawableOpacity(i).toFixed(3); }); }catch(e){}
    window.__wt.rows.push(r);
  }, null, LOW);
  /* idle 是否驱动该参数（决定 loadParameters 会不会把它拉回） */
  window.__wt.idleDrives=null;
  return 'INSTALLED idle='+idle+' drv='+JSON.stringify(drv);
})()
"""

IDLE_DRIVES = r"""
(function(){
  var want=%s;
  /* 从运行时的 paramSets 拿不到（页面闭包内），改为逐 idle 变体读 motion3.json 太慢；
     这里用更直接的证据：浅探 model3 的 Live2DModel 上 motionManager 已解析的 motion 对象。
     取不到就返回 unknown（不当假阴性用）。 */
  try{
    var mg=window.__l2model.internalModel.motionManager;
    var out={};
    for(var g in (mg.motionGroups||{})){
      var arr=mg.motionGroups[g]||[];
      if(!arr.length) continue;
      var mm=arr[0]&&arr[0]._motion;
      if(!mm||!mm._model||!mm._model.curves) continue;
      var hit=false;
      for(var i=0;i<mm._model.curves.length;i++){
        var c=mm._model.curves[i], id=c._targetId||(c.target&&c.target._id)||c._id;
        if(id===want){ hit=true; break; }
      }
      out[g]=hit;
    }
    return JSON.stringify({loaded:Object.keys(out).length, drives:out});
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""


def main():
    try:
        with urllib.request.urlopen(BASE, timeout=6) as r:
            assert r.status == 200
    except Exception as e:  # noqa: BLE001
        print('[INVALID]', e); return 2
    pg = open_page(BASE, tag='wt')
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
        print('装探针:', pg.ev(INSTALL % (json.dumps(PID), json.dumps(KEY), json.dumps(PID),
                                         json.dumps(KEY))))
        # 等 idle 播起来（让 loadParameters 有真实值可铺）
        time.sleep(3.0)

        def setpin(v):
            pg.ev("""(function(){var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
              if(!pm[%s]) pm[%s]=Object.create(null); pm[%s][%s]=%s; return 1;})()"""
                  % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY), json.dumps(PID), json.dumps(v)))

        for v in (V0, V1):
            pg.ev("(window.__wt.rows=[], 1)")
            setpin(v)
            time.sleep(1.2)
            rows = json.loads(pg.ev("JSON.stringify(window.__wt.rows)") or '[]')
            print('\n--- pin=%s，采样 %d 帧 ---' % (v, len(rows)))
            for r in rows[-6:]:
                print('  pre(update前)=%-8s LOW后 v=%-8s pin=%-8s op(LOW后)=%-18s preOp=%-18s g=%s'
                      % (r.get('pre'), r.get('v'), r.get('pin'),
                         str(r.get('op')), str(r.get('preOp')), r.get('g')))
        pg.ev("""(function(){var pm=(window.__costumePinsByModel||{})[%s]||{};
          delete pm[%s]; return 1;})()""" % (json.dumps(KEY), json.dumps(PID)))
        print('\n该参数是否被已加载的动作驱动:', pg.ev(IDLE_DRIVES % json.dumps(PID)))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
