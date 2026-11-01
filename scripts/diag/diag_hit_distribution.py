# -*- coding: utf-8 -*-
"""诊断 R3 修复后仍「全命中 Paramring」的真因。

现象（2026-10-25）：
  __costumeScreenOf('ShoseOff') 返回 {n:238, cx:512, cy:409, box:[473,361,551,457]}
  其中 n=238 表示搜索循环内**有 238 个点确实命中 ShoseOff**（否则 n=0 会 return null）
  但把 cx,cy（=包围盒中心）单独喂给 __costumeHit，却返回 Paramring。

假设：命中区域不是矩形，包围盒中心落在未命中区。
  __costumeScreenOf 返回的是 (x0+x1)/2, (y0+y1)/2 —— **几何中心**，
  而不是「确实命中的那个点」。若 ShoseOff 的可点区偏在一侧（或 L 形），
  中心就会落到别处，而那个位置的胜者可能是 Paramring。

本脚本：
  1. 对每个参数，用 __costumeScreenOf 拿到搜索区域
  2. 在该区域内**逐点**扫描，统计每个点命中的是谁（不只中心）
  3. 给出「命中率最高的那个点」及其命中 id —— 这才是可靠的屏幕点
  4. 报告每个点上的胜负分布，确认是否 Paramring 在大范围劫持
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

KEY = 'ougen_8'
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'

HOOK = r"""
(function(){
  var tries=0;
  function boot(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<1200) setTimeout(boot,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookSG) return;
    proto.__dshHookSG=true;
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

# 在给定矩形内逐点扫描，统计每个 id 被命中多少次，并返回最佳点
SCAN = """
(function(){
  try{
    var a=arguments[0], b=arguments[1], c=arguments[2], d=arguments[3];
    var want=%s;
    var stat={}, best=null, bestN=0;
    for(var y=a[1]; y<=b[1]; y+=4){
      for(var x=a[0]; x<=b[0]; x+=4){
        var h=window.__costumeHit(x,y);
        var k=h? h.id : '(none)';
        stat[k]=(stat[k]||0)+1;
        if(k===want){
          var sp=Math.pow(x-(a[0]+b[0])/2,2)+Math.pow(y-(a[1]+b[1])/2,2);
          if(!best || sp<best.sp){ best={x:x,y:y,sp:sp}; }
        }
      }
    }
    var tot=0; for(var k2 in stat) tot+=stat[k2];
    return JSON.stringify({want:want, total:tot, stat:stat,
                           best:best, hitPts:stat[want]||0});
  }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""


def main():
    ok, why = ensure_servers.ensure('new')
    print('server 8778:', ok, why)
    if not ok:
        return 1

    pg = open_page(URL, tag='sg')
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

        boxes = json.loads(pg.ev("JSON.stringify(window.__costumeBoxes())"))
        print('=== 每个参数的命中分布（在其自身包围盒区域内扫描）===')
        for b in boxes:
            pid = b['id']
            tgt = pg.ev("JSON.stringify(window.__costumeScreenOf(%s))" % json.dumps(pid))
            t = json.loads(tgt) if tgt and tgt != 'null' else None
            if not t:
                print('  %-12s ScreenOf 返回 null（热区内无点命中自己）' % pid)
                continue
            bb = t['box']
            r = pg.ev("""(function(){return (function(){
              var a=[%d,%d], b=[%d,%d], want=%s;
              var stat={}, best=null;
              for(var y=a[1]; y<=b[1]; y+=4){
                for(var x=a[0]; x<=b[0]; x+=4){
                  var h=window.__costumeHit(x,y);
                  var k=h? h.id : '(none)';
                  stat[k]=(stat[k]||0)+1;
                  if(k===want){
                    var sp=Math.pow(x-(a[0]+b[0])/2,2)+Math.pow(y-(a[1]+b[1])/2,2);
                    if(!best||sp<best.sp) best={x:x,y:y,sp:sp};
                  }
                }
              }
              var tot=0; for(var k2 in stat) tot+=stat[k2];
              return JSON.stringify({want:want,total:tot,stat:stat,best:best});
            })();})()"""
                      % (bb[0], bb[1], bb[2], bb[3], json.dumps(pid)))
            d = json.loads(r)
            if 'err' in d:
                print('  %-12s ERR %s' % (pid, d['err']))
                continue
            stat = d.get('stat') or {}
            top = sorted(stat.items(), key=lambda kv: -kv[1])[:4]
            print('  %-12s 采样%4d 点  分布: %s'
                  % (pid, d.get('total', 0),
                     ', '.join('%s=%d' % (k, v) for k, v in top)))
            if d.get('best'):
                hit = pg.ev("(function(){var h=window.__costumeHit(%d,%d);"
                            "return h? h.id : 'null';})()" % (d['best']['x'], d['best']['y']))
                print('               最佳真实命中点 (%d,%d) → 实测命中 %s'
                      % (d['best']['x'], d['best']['y'], hit))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
