# -*- coding: utf-8 -*-
"""验证 window.__l2model 是不是当前正在渲染的那个模型实例。

⚠️ 本轮最大的探针陷阱（必须记录）：
  此前所有参数读取都用 hook addChild 捕获的 window.__l2model。
  但前端切换皮肤/重建 Live2D 时会创建新实例，旧实例仍留在内存里。
  若 __l2model 指向废弃实例，读到的是：
     ParamAngleX 恒 0、motion 队列 qLen=0、userTime 读不到、参数缓慢漂移
  —— 这与"动作曲线没生效"的假象完全吻合，会把人带进沟里。

  页面自己的取法是：l2State.app.stage.children[0]

本脚本对比两种取法的对象身份（===）与关键字段，确立唯一可信的读取路径。
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

import ensure_servers  # noqa: E402
from cdp_helper import open_page  # noqa: E402

KEY = 'ougen_8'
GROUP = 'touch_idle14'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  window.__ALLMODELS = [];
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookID) return;
    proto.__dshHookID=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c&&c.internalModel&&c.internalModel.coreModel){
            window.__ALLMODELS.push(c);
            window.__l2model=c;
          }
        }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
})();
"""

COMPARE = """
(function(){
  try{
    const hook = window.__l2model;
    const stg = (window.l2State && l2State.app && l2State.app.stage)
                  ? l2State.app.stage : null;
    const page = stg ? stg.children[0] : null;
    const out={
      allCount: (window.__ALLMODELS||[]).length,
      hasHook: !!hook, hasPage: !!page, hasStage: !!stg,
      same: hook === page,
      stageChildCount: stg? stg.children.length : null
    };
    const desc=(m, tag)=>{
      if(!m) return {tag:tag, none:true};
      try{
        const im=m.internalModel, mm=im&&im.motionManager;
        const cm=im&&im.coreModel;
        const gv=(p)=>{ try{const i=cm.getParameterIndex(p);
                           return i>=0? cm.getParameterValueByIndex(i): null;}catch(e){return null;} };
        let q=null;
        try{ q=(mm._motions||[]).filter(x=>x!=null).length; }catch(e){}
        return {tag:tag, destroyed: (m.destroyed===true),
                g:(mm&&mm.state)? mm.state.currentGroup : null,
                qLen:q,
                userTime: (mm&&typeof mm._userTimeSeconds==='number')? mm._userTimeSeconds : null,
                vals:{A:gv('ParamAngleX'), P194:gv('Param194'), P207:gv('Param207')},
                mmKeys: mm? Object.keys(mm).slice(0,14) : null};
      }catch(e){ return {tag:tag, err:String(e)}; }
    };
    out.hook=desc(hook,'hook');
    out.page=desc(page,'page');
    // 列出所有 hook 过的实例
    out.all=(window.__ALLMODELS||[]).map((m,i)=>desc(m,'#'+i));
    return JSON.stringify(out);
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1
    with urllib.request.urlopen(URL, timeout=6) as r:
        if r.status != 200:
            print('[INVALID] HTTP', r.status)
            return 2

    pg = open_page(URL, tag='id')
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              "if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        time.sleep(0.9)
        pg.ev("""(function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(14)

        d = json.loads(pg.ev(COMPARE))
        print('全部 hook 到的模型实例数:', d.get('allCount'))
        print('hook 对象存在:', d.get('hasHook'), ' 页面对象存在:', d.get('hasPage'))
        print('**两者是否同一对象**: ', d.get('same'))
        print('stage.children 数:', d.get('stageChildCount'))
        print('\n[hook 对象]', json.dumps(d.get('hook'), ensure_ascii=False))
        print('\n[page 对象]', json.dumps(d.get('page'), ensure_ascii=False))
        print('\n所有实例:')
        for a in (d.get('all') or []):
            print('  ', json.dumps(a, ensure_ascii=False)[:300])

        if d.get('same') is False:
            print('\n==> 确认：__l2model 与页面实际渲染对象【不是同一个】')
            print('    本轮此前所有基于 __l2model 的参数读数全部无效，需重新取证')
        elif d.get('same') is True:
            print('\n==> 两者同一对象，探针本身没问题，问题在库里')

        # 播动作后用 page 对象读
        pg.ev("(function(){try{window.__l2play(%s,3);}catch(e){}return 1;})()" % json.dumps(GROUP))
        for t in (0.4, 0.9, 0.9):
            time.sleep(t)
            d2 = json.loads(pg.ev(COMPARE))
            print('\n  --- 播放中 ---')
            print('   hook:', json.dumps(d2.get('hook'), ensure_ascii=False)[:220])
            print('   page:', json.dumps(d2.get('page'), ensure_ascii=False)[:220])
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
