r"""不透明度绑定搜寻：指定的 drawable 到底被哪个参数控制？（2026-10-28）

为什么需要这个工具：`l2d_param_effect_scan.py` 只能回答「参数 P 影响哪些部件」，
方向是「一参数 → 多部件」。当现象反过来——「某部件一直不显示，不知道谁管它」——
就必须反过来扫：**把全模型的参数逐个推到 min/max，看目标部件有没有变**。

能回答的问题：判定「某部位画面消失」属于哪一种
  a) 数据缺件（几何不存在，镜像位找不到配对件）；
  b) 绑定到某个参数且该参数处于关闭位（找到参数即可修）；
  c) 绑定到不存在的参数（moc3 里的悬空绑定，数据坏了）。
本工具把 b 一次定死；扫不到任何参数 ⇒ 落在 a 或 c。

用法
  py -3 scripts/diag/l2d_opacity_binding_hunt.py [模型] [目标drawable,...] [对照组drawable,...]
  例：py -3 scripts/diag/l2d_opacity_binding_hunt.py ougen_8 411,413 184,461

  ⚠️ 第三组是**阳性对照**，必须填：它应当被某个已知参数打开（ougen_8 用 184,461
  ↔ ShoseOff）。没有阳性对照，「0 命中」无法区分「真没绑定」和「仪器坏了」。

⚠️ 性能判据（本条是本工具存在的理由）：早期版本在 Python 侧循环、每次改值都走一次
CDP 往返（582 参数 × 2 极值 × 快照 ≈ 2000+ 次往返），实测 20 分钟跑不完且输出被
缓冲成空文件。现在整段扫描**在页面内一次 JS 调用里同步跑完**：
  * JS 单线程 ⇒ 扫描期间 rAF 不会插进来，`loadParameters` 无法把参数拉回；
  * 只调 `coreModel.update()`（重算不透明度/动态标志），**不调** `internalModel.update()`
    ——后者会跑 motion 并重新 loadParameters，等于自己把刚写的值抹掉（假阴性）。
实测 582 参数 × 2 极值全程 < 2 秒。

⚠️ 另一条陷阱：492 个参数名是 `ParamN` 这种无语义编号，别指望靠名字猜，只能全量扫。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
TARGETS = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else '411,413').split(',')]
CONTROL = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else '184,461').split(',')]
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = int(os.environ.get('AL_PORT', '9411'))
PROFILE = os.path.join(ROOT, '.diag', 'czh_prof')

NEUTRALIZE = """(function(){var m=(window.__l2ModelRef&&window.__l2ModelRef())||null; if(!m) return 'NO_MODEL';
  var im=m.internalModel, mm=im&&im.motionManager, done=[];
  if(mm&&mm.groups){ if(!mm.__idleBak) mm.__idleBak=mm.groups.idle;
    mm.groups.idle='__hz_frozen__'; done.push('idleOff'); }
  try{ if(mm){ mm.queueManager.stopAllMotions(); mm.state.reset&&mm.state.reset(); } done.push('mot'); }catch(e){}
  if(typeof im.updateNaturalMovements==='function'){
    im.updateNaturalMovements=function(){}; done.push('breath'); }
  if(im.physics&&typeof im.physics.reset==='function'){ try{ im.physics.reset(); done.push('phys'); }
    catch(e){} }
  return done.join(',');})()"""


SWEEP = r"""(function(){
  var m=window.__l2ModelRef&&window.__l2ModelRef();
  if(!m||!m.internalModel) return '{"err":"NO_MODEL"}';
  var c=m.internalModel.coreModel;
  var T=%(t)s, CT=%(ct)s;
  function snap(idxs){
    var o=[];
    for(var k=0;k<idxs.length;k++){ var i=idxs[k];
      o.push([+c.getDrawableOpacity(i).toFixed(4), c.getDrawableDynamicFlagIsVisible(i)?1:0]); }
    return o;
  }
  function same(a,b){
    for(var k=0;k<a.length;k++){ if(a[k][0]!==b[k][0]||a[k][1]!==b[k][1]) return false; }
    return true;
  }
  var n=c.getParameterCount();
  // ⚠️ CubismFramework 的 CubismModel 没有 getParameterId(i)；参数名只能从私有
  // _parameterIds 取（csmVector 有 .at()/.getSize()，也可能被 polyfill 成数组）。
  var ids=c._parameterIds;
  function idAt(i){ return ids.at? ids.at(i) : ids[i]; }
  var nid = ids.getSize? ids.getSize() : ids.length;
  if(nid!==n) return JSON.stringify({err:'ID_COUNT_MISMATCH', n:n, nid:nid});
  try{ c.update(); }catch(e){}
  var baseT=snap(T), baseC=snap(CT);
  var hits=[], nskipped=0, ntested=0;
  for(var i=0;i<n;i++){
    var id=idAt(i); if(!id) continue;
    var mn=0, mx=0;
    try{ mn=c.getParameterMinimumValue(i); mx=c.getParameterMaximumValue(i); }catch(e){ continue; }
    if(mx===mn){ nskipped++; continue; }
    var v0=0; try{ v0=c.getParameterValueByIndex(i); }catch(e){}
    for(var s=0;s<2;s++){
      var v=s?mx:mn;
      ntested++;
      try{ c.setParameterValueByIndex(i,v); }catch(e){ continue; }
      try{ c.update(); }catch(e){}
      var nt=snap(T), nc=snap(CT);
      if(!same(nt,baseT)||!same(nc,baseC)){
        hits.push([id, +v.toFixed(4), nt, nc]);
      }
      try{ c.setParameterValueByIndex(i,v0); }catch(e){}
      try{ c.update(); }catch(e){}
    }
  }
  return JSON.stringify({n:n, nskipped:nskipped, ntested:ntested,
    baseT:baseT, baseC:baseC, hits:hits});
})()"""


def open_model(pg):
    pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
       if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
    time.sleep(0.9)
    print('开卡:', pg.ev("""
    (function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key===%s;});});
      if(!s) return 'NO_SHIP';
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;});
      if(!c) return 'NO_CARD'; c.click(); return 'OK:'+s.name;})()""" % json.dumps(KEY)))
    time.sleep(1.6)
    print('选肤:', pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k===%s;}); if(!d) return 'NO_ROW'; d.click(); return 'OK';})()"""
                         % json.dumps(KEY)))
    time.sleep(1.3)
    print('切L2D:', pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k==='live2d';}); if(!t) return 'NO_TAB';
       if(t.classList.contains('dis')) return 'DIS'; t.click(); return 'OK';})()"""))
    for _ in range(60):
        if pg.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef(); return m?1:0;})()") == 1:
            return True
        time.sleep(1.0)
    return False


def main():
    pg = Page(PORT, PROFILE, BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        if not open_model(pg):
            print('[FAIL] 模型没加载'); return 2
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(2.5)
        print('帧源闸: %.1f fps' % pg.require_frames(2.0))
        print('冻结姿态:', pg.ev(NEUTRALIZE))
        time.sleep(1.5)
        pg.require_frames(1.0)

        t0 = time.time()
        r = json.loads(pg.ev(SWEEP % {'t': json.dumps(TARGETS),
                                     'ct': json.dumps(CONTROL)}))
        if r.get('err'):
            print('[FAIL]', r); return 2
        print('参数总数 %d（常量跳过 %d，实测 %d 次）用时 %.2fs'
              % (r['n'], r['nskipped'], r['ntested'], time.time() - t0))
        print('基线 目标件(op,vis)=%s' % r['baseT'])
        print('基线 阳性对照(op,vis)=%s' % r['baseC'])

        ctrl_hits = [h for h in r['hits'] if h[3] != r['baseC']]
        tgt_hits = [h for h in r['hits'] if h[2] != r['baseT']]

        print('\n=== 阳性对照：被哪些参数驱动（应当非空）===')
        if not ctrl_hits:
            print('  [FAIL] 阳性对照零命中 ⇒ 仪器无效，下面的结论不可信'); return 3
        for h in ctrl_hits:
            print('  %-22s = %-8s 对照件→%s' % (h[0], h[1], h[3]))

        print('\n=== 目标件：被哪些参数驱动 ===')
        if not tgt_hits:
            print('  零命中 ⇒ 没有任何参数能改变它（落在「数据缺件」或「悬空绑定」）')
        for h in tgt_hits:
            print('  %-22s = %-8s 目标件→%s' % (h[0], h[1], h[2]))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
