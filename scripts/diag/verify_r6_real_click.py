# -*- coding: utf-8 -*-
"""R6：真实点击验收——用 CDP 派发真实鼠标事件，不调用任何内部函数。

为什么必须这一层（项目既有教训）：
  直接调 __costumeToggle 只证明「函数能跑」，不证明「用户点得到」。
  onUp 里的接续顺序（stateFind → costumeHitAt → 播动作）一旦写错，
  函数本身仍然好用，但真实点击会走进动作分支、热区永远不触发。

判据（四层，全部走真实输入）：
  ① 用 __costumeScreenOf 找到该参数**真实命中**的屏幕点（不是几何中心——
     中心可能落在别的参数地盘，这正是我用错判据那次的教训）
  ② 用 Input.dispatchMouseEvent 派发 mousePressed + mouseReleased 到该点
  ③ 断言参数值从 lo 变到 hi（读 coreModel，走产品自己的 pins/tween 链路）
  ④ 同时断言「没有播 motion」——热区交互是换装，不该改姿态
     （若 state.currentGroup 从 idle 变成某个 touch_*，说明点歪进了动作分支）

用法: py -3 scripts/diag/verify_r6_real_click.py [param_id] [key]
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'diag'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import ensure_servers  # noqa: E402
from cdp_helper import open_page  # noqa: E402

PID = sys.argv[1] if len(sys.argv) > 1 else 'ShoseOff'
KEY = sys.argv[2] if len(sys.argv) > 2 else 'ougen_8'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookR6) return;
    proto.__dshHookR6=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c&&c.internalModel&&c.internalModel.coreModel){
          if(c.destroyed!==true) window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  boot();
})();
"""

CARD = """(function(){var s=(window.GALLERY.ships||[]).find(function(x){
    return (x.skins||[]).some(function(k){return k.key===%s;});});
  var c=[...document.querySelectorAll('.card')].find(function(e){
    return (e.textContent||'').indexOf(s.name)>=0;}); if(c) c.click(); return 1;})()"""
SKIN = """(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
    return e.dataset.k===%s;}); if(d) d.click(); return 1;})()"""
TAB = """(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
    return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()"""

STATE = """
(function(){
  try{
    var m=window.__l2model, im=m.internalModel, cm=im.coreModel;
    var g=(im.motionManager.state||{}).currentGroup;
    var v=null; try{ v=cm.getParameterValueById(%s); }catch(e){ v='ERR'; }
    var label=(document.getElementById('l2Hit')||{}).textContent;
    return JSON.stringify({g:g, v:v, label:label});
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""

# 找真实命中点：在 ScreenOf 给的矩形里逐点问 __costumeHit，取第一个命中目标的点
REALPOINT = """
(function(){
  try{
    var a=arguments[0], b=arguments[1], c=arguments[2], d=arguments[3];
    var want=%s;
    var cand=[];
    for(var y=a[1]; y<=b[1]; y+=3){
      for(var x=a[0]; x<=b[0]; x+=3){
        var h=window.__costumeHit(x,y);
        if(h && h.id===want) cand.push([x,y]);
      }
    }
    if(!cand.length) return JSON.stringify({ok:false});
    var mid=cand[Math.floor(cand.length/2)];
    return JSON.stringify({ok:true, n:cand.length, pt:mid});
  }catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
})()
"""


def click_at(pg, x, y):
    """用 CDP 派发真实鼠标事件（mousePressed + mouseReleased）。"""
    pg.cmd('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y,
                                        'button': 'none', 'clickCount': 0})
    time.sleep(0.08)
    pg.cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y,
                                        'button': 'left', 'clickCount': 1})
    time.sleep(0.08)
    pg.cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y,
                                        'button': 'left', 'clickCount': 1})


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1

    pg = open_page(URL, tag='r6', win=(1400, 1000))
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(5)
        pg.ev("(function(){var b=document.querySelector('#gOpt button[data-k=login]');"
              "if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()")
        time.sleep(0.9)
        pg.ev(CARD % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev(SKIN % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev(TAB)
        time.sleep(15)

        if pg.ev("(typeof window.__l2play==='function'&&!!window.__l2model)?1:0") != 1:
            print('!! Live2D 未就绪')
            return 1

        st = STATE % json.dumps(PID)

        so = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(PID))
        t = json.loads(so) if so and so != 'null' else None
        if not t:
            print('!! __costumeScreenOf(%s) 返回 null' % PID)
            return 1
        bb = t['box']
        print('搜索区域: %s  （ScreenOf 报告命中 %d 点）' % (bb, t.get('n')))

        rp = json.loads(pg.ev("""(function(){return (function(){
          var a=[%d,%d], b=[%d,%d], want=%s;
          var cand=[];
          for(var y=a[1]; y<=b[1]; y+=3){
            for(var x=a[0]; x<=b[0]; x+=3){
              var h=window.__costumeHit(x,y);
              if(h && h.id===want) cand.push([x,y]);
            }
          }
          if(!cand.length) return JSON.stringify({ok:false});
          return JSON.stringify({ok:true, n:cand.length,
                                 pt:cand[Math.floor(cand.length/2)]});
        })();})()""" % (bb[0], bb[1], bb[2], bb[3], json.dumps(PID))))

        if not rp.get('ok'):
            print('!! 区域内找不到命中 %s 的点' % PID)
            return 1
        x, y = rp['pt']
        print('选定点击点: (%d, %d)  该区域内可命中 %d 点' % (x, y, rp.get('n', 0)))

        before = json.loads(pg.ev(st))
        print('\n点击前:', json.dumps(before, ensure_ascii=False))

        print('\n[派发真实鼠标事件]')
        click_at(pg, x, y)
        time.sleep(1.5)

        after = json.loads(pg.ev(st))
        print('点击后:', json.dumps(after, ensure_ascii=False))

        print('\n=== 判定 ===')
        r1 = (isinstance(before.get('v'), (int, float))
              and isinstance(after.get('v'), (int, float))
              and abs(after['v'] - before['v']) > 0.5)
        print('  ① 真实点击命中该参数 :', 'PASS' if abs(after['v'] - before['v']) > 1e-9
              else 'FAIL（参数没动）')
        print('  ② 参数值 %s → %s 变化>0.5 : %s'
              % (before.get('v'), after.get('v'), 'PASS' if r1 else 'FAIL'))
        moved_motion = (before.get('g') != after.get('g')
                        and str(after.get('g', '')).startswith('touch'))
        print('  ③ 未误触动作分支     : %s（组 %s → %s）'
              % ('PASS' if not moved_motion else 'FAIL',
                 before.get('g'), after.get('g')))
        print('  ④ 页面提示 pill      : %r' % after.get('label'))

        print()
        if r1 and not moved_motion:
            print('==> R6 PASS：真实鼠标点击能触发换装参数，且没有误触动作')
        elif moved_motion:
            print('==> R6 FAIL：点击误触了动作分支（组变成 %s），热区没生效' % after.get('g'))
        else:
            print('==> R6 FAIL：真实点击没有改变参数')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
