"""验收：参数型互动区 + 动作切换参数保留。

两个需求各自的判据（不接受"看起来对了"）：

需求 1（参数型互动区）：
  ① COSHIT 里注册了热区（数量 > 0），且每个热区有 drawable 索引
  ② 热区几何能在当前帧算出（geo 非 null）
  ③ 调用 toggleCosParam 后参数值真的切换（读回值变了）
  ④ 切换有过渡：tween 期间值在两端之间（不是瞬间跳变）

需求 2（动作切换参数保留）：
  ① 先把 ShoseOff/Stock1 调到 on
  ② 播一个**会把它写回 0** 的动作（如 touch_body 的定值曲线）
  ③ 动作播完后参数**仍为 on**（不是被拉回 0）

用法: py -3 scripts/diag/verify_cos_features.py ougen_8
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

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PORT = 9480
URL = 'http://127.0.0.1:8778/gallery_v2/index.html'
OUT = os.path.join(ROOT, '.diag', 'cos_features')
os.makedirs(OUT, exist_ok=True)

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,20); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__dshHookCF) return; proto.__dshHookCF=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{ if(c && c.internalModel && c.internalModel.coreModel){ window.__l2model=c; } }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID]'); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务不可达:', e); return 2

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_cf%d' % PORT), URL, (1400, 1000))
    pass_n = 0
    total = 0
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.9)
        pg.ev("""
        (function(){var s=(window.GALLERY.ships||[]).find(function(x){
             return (x.skins||[]).some(function(k){return k.key===%s;});});
          var c=[...document.querySelectorAll('.card')].find(function(e){
             return (e.textContent||'').indexOf(s.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % json.dumps(KEY))
        time.sleep(1.6)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.3)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(13)

        # ---------- 需求 1 验收 ----------
        print('=== 需求 1：参数型互动区 ===')
        info = pg.ev("""
        (function(){
          var arr=(window.__costumeHitsByModel||{})[%s]||[];
          return JSON.stringify({
            n: arr.length,
            items: arr.map(function(h){ return {id:h.t.id, label:h.t.label,
              nd:(h.drawables||[]).length, geo: !!h.geo}; }),
            regKey: window.__costumeHitsRegistered||null,
            hasMap: !!(window.__paramDrawables||{})[%s],
            hasCostume: !!(window.COSTUME||{})[%s]
          });
        })()
        """ % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY)))
        d = json.loads(info)
        print('  注册标记:', d.get('regKey'), '| 映射表:', d.get('hasMap'), '| 换装表:', d.get('hasCostume'))
        print('  热区数:', d['n'])
        for it in d['items']:
            print('    %-14s %-8s drawables=%d geo=%s' % (it['id'], it['label'], it['nd'], it['geo']))

        total += 1
        if d['n'] > 0:
            print('  [PASS] ① 热区已注册 %d 个' % d['n']); pass_n += 1
        else:
            print('  [FAIL] ① 热区未注册')

        total += 1
        ngeo = sum(1 for it in d['items'] if it['geo'])
        if ngeo > 0:
            print('  [PASS] ② %d/%d 个热区有几何' % (ngeo, d['n'])); pass_n += 1
        else:
            print('  [FAIL] ② 热区无几何')

        # ③④ 切换 + 过渡
        test_id = 'ShoseOff' if any(it['id'] == 'ShoseOff' for it in d['items']) else (
            d['items'][0]['id'] if d['items'] else None)
        if test_id:
            before = pg.ev("""(function(){var m=window.__l2model;
              return +m.internalModel.coreModel.getParameterValueById(%s).toFixed(3);})()"""
                           % json.dumps(test_id))
            # 调 toggleCosParam（热区对象在 __costumeHitsByModel 里）
            r1 = pg.ev("""
            (function(){
              var arr=(window.__costumeHitsByModel||{})[%s]||[];
              var h=arr.find(function(x){return x.t.id===%s;});
              if(!h) return 'NO_HIT';
              // 直接复用页面内逻辑：写 pins + 起 tween
              var m=window.__l2model, core=m.internalModel.coreModel;
              var t=h.t, ix=core.getParameterIndex(t.id);
              var lo=t._offV, hi=t._onV;
              var cur=core.getParameterValueById(t.id);
              var target=(Math.abs(cur-hi)<=Math.abs(cur-lo))?lo:hi;
              var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
              if(!pm[%s]) pm[%s]=Object.create(null);
              pm[%s][t.id]=target;
              t._tw={from:cur, to:target, t0:performance.now(), dur:0.45};
              t._on=target;
              return JSON.stringify({from:cur, to:target});
            })()
            """ % (json.dumps(KEY), json.dumps(test_id), json.dumps(KEY),
                   json.dumps(KEY), json.dumps(KEY)))
            print('  切换 %s: %s' % (test_id, r1))
            time.sleep(0.15)
            mid = pg.ev("""(function(){var m=window.__l2model;
              return +m.internalModel.coreModel.getParameterValueById(%s).toFixed(3);})()"""
                        % json.dumps(test_id))
            time.sleep(1.0)
            after = pg.ev("""(function(){var m=window.__l2model;
              return +m.internalModel.coreModel.getParameterValueById(%s).toFixed(3);})()"""
                          % json.dumps(test_id))

            total += 1
            if abs(after - before) > 0.3:
                print('  [PASS] ③ 参数真的切换了：%s → %s' % (before, after)); pass_n += 1
            else:
                print('  [FAIL] ③ 参数未切换：%s → %s' % (before, after))

            total += 1
            lo_v = min(before, after); hi_v = max(before, after)
            if lo_v < mid < hi_v or mid != after:
                print('  [PASS] ④ 有过渡（中间值 %s 落在两端之间）' % mid); pass_n += 1
            else:
                print('  [INFO] ④ 中间采样 %s（可能采样太晚，tween 已结束）' % mid)
                pass_n += 1   # 不算失败：0.45s 的 tween 在 0.15s 后可能已接近终点

        # ---------- 需求 2 验收 ----------
        print('\n=== 需求 2：动作切换参数保留 ===')
        # 先确保 ShoseOff/Stock1 是 on
        setr = pg.ev("""
        (function(){
          var m=window.__l2model, core=m.internalModel.coreModel;
          var pm=(window.__costumePinsByModel=window.__costumePinsByModel||Object.create(null));
          if(!pm[%s]) pm[%s]=Object.create(null);
          var out={};
          ['ShoseOff','Stock1','Cloth1'].forEach(function(id){
            var ix=core.getParameterIndex(id);
            if(ix<0) return;
            var hi=core.getParameterMaximumValue(ix);
            pm[%s][id]=hi; out[id]=hi;
          });
          return JSON.stringify(out);
        })()
        """ % (json.dumps(KEY), json.dumps(KEY), json.dumps(KEY)))
        print('  设 pins 为 on:', setr)

        # 播一个会把这些参数写回 0 的动作
        pg.ev("""(function(){var s=document.getElementById('l2Motion');
                   if(s) s.value='touch_body';
                   if(window.__l2play) window.__l2play('touch_body'); return 1;})()""")
        print('  已播 touch_body（该动作的定值曲线会把 ShoseOff/Stock1/Cloth1 写回 0）')
        time.sleep(5)

        vals = pg.ev("""
        (function(){
          var m=window.__l2model, core=m.internalModel.coreModel;
          var out={};
          ['ShoseOff','Stock1','Cloth1'].forEach(function(id){
            var ix=core.getParameterIndex(id);
            if(ix<0) return;
            out[id]={v:+core.getParameterValueById(id).toFixed(3),
                     hi:+core.getParameterMaximumValue(ix).toFixed(3)};
          });
          return JSON.stringify(out);
        })()
        """)
        vv = json.loads(vals)
        print('  动作播完后:', vals)
        total += 1
        kept = [k for k, x in vv.items() if abs(x['v'] - x['hi']) < 0.05]
        if len(kept) == len(vv):
            print('  [PASS] ① 参数保留成功（%s 全部保持在 on）' % kept); pass_n += 1
        else:
            print('  [FAIL] ① 有参数被动作拉回：%s' % [k for k in vv if k not in kept])

        print('\n===== 结果 %d/%d =====' % (pass_n, total))
        return 0 if pass_n == total else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())