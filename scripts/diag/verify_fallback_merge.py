# -*- coding: utf-8 -*-
"""验证「两段回落合并成一段」后：每个非待机动作**只回落一次**，且落到 motion_chain 的 best。

背景（docs/TROUBLESHOOTING.md §146）：
  旧版有两条回落路径（库 startRandomMotion 包装 / setTimeout 定时器），各自选组、各自写
  pose_keep，并共用 lastGroup 这个变量。路径 A 先把 lastGroup 改写成 idle 变体之后，
  路径 B 查表恒落空 → 落回默认 idle 第 0 帧（用户报的「回落成功后闪回初始待机」）。
  实测 touch_idle14 出现两次回落：3.08s idle9(NORMAL) → 3.63s idle(IDLE)。

判据（全部必须成立才算通过）：
  1. 同一动作的 `state.start()` 日志里，priority===IDLE(1) 的条目**恰好 1 条**
     —— 多于 1 条即为两段回落并存（回归）。
  2. 该 IDLE 条目的 group 等于 motion_chain.json 的 chain[动作].best。
  3. 若 motion_chain 里该动作有 pose_keep，则 `__posePinsByModel[skin]` 非空。
  4. 非 touch_* 动作（如 mission）也要落到 best —— 旧版 2a 缺陷会把它固定成 idle。

⚠️ 检测点选 `state.start` 而不是 `startMotion` 包装：startMotion 是 async，
   包它只能看到「请求」，看不到「有没有被 reserve/优先级拒绝」，会把失败当成功。
   state.start 是库最终决定播放哪一组的地方，且带 currentPriority 前后值。

用法: py -3 scripts/diag/verify_fallback_merge.py [key] [group1,group2,...]
"""
import json
import os
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

ARGV = [x for x in sys.argv[1:] if not x.startswith('--')]
KEY = ARGV[0] if ARGV else 'ougen_8'
GROUPS = ARGV[1].split(',') if len(ARGV) > 1 else ['touch_idle14', 'mission', 'touch_body', 'home']
PORT = 9321
URL = 'http://127.0.0.1:8777/gallery_v2/index.html'
# 对照组：指向另一份页面（旧实现），用同一个探针跑，判据必须变红。
# 不加这个开关就无法排除「探针本身永远 PASS」的假绿灯。
#
# ⚠️ 2026-10-24 实测教训：**只加 `--url=` 做对照是不够的**（对照组同样全绿）。
#    旧版的两段回落是**竞争条件**，在无头低帧率下路径 B（定时器）通常先到，
#    于是同一动作也只回落一次、落点也对，看不出缺陷（这正是此缺陷复现不稳定的原因）。
#    要稳定区分，必须人为制造「路径 A 先跑」的时序：`--poke=N` 在播放后 N 秒
#    调用 mm.state.complete() 把 currentGroup 清零 —— 旧版 ticker 看门狗的条件
#    `!cg && !_fbPending` 随即成立 → 路径 A 用 NORMAL 回 idleGroup 并把 lastGroup
#    改写成 'idle' → 之后路径 B 查 chain['idle'] 恒落空 → 落回默认 idle 第 0 帧。
#    新版没有看门狗、lastGroup 不回写，同样的 poke 只会让定时器正常回落到 best。
POKE = None
for _a in sys.argv[1:]:
    if _a.startswith('--url='):
        URL = _a[6:]
    elif _a.startswith('--poke='):
        POKE = float(_a[7:])

HOOK = r"""
(function(){
  var tries=0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){ if(tries++<800) setTimeout(patch,25); return; }
    var proto=window.PIXI.Container.prototype;
    if(proto.__fbHook) return; proto.__fbHook=true;
    var orig=proto.addChild;
    proto.addChild=function(){
      for(var i=0;i<arguments.length;i++){
        var c=arguments[i];
        try{
          if(c && c.internalModel && c.internalModel.coreModel
             && !c.internalModel.__stHooked){
            var mm=c.internalModel.motionManager, st=mm.state;
            c.internalModel.__stHooked=true;
            window.__mm=mm; window.__l2model=c; window.__stLog=[];
            var o=st.start.bind(st);
            st.start=function(motion,g,idx,pri){
              var e={t:+(performance.now()/1000).toFixed(2), req:g, idx:idx, pri:pri,
                     pre_cg:st.currentGroup, pre_cp:st.currentPriority};
              var ok;
              try{ ok=o(motion,g,idx,pri); }catch(err){ e.err=String(err); ok=false; }
              e.ok=ok; e.post_cg=st.currentGroup; e.post_cp=st.currentPriority;
              window.__stLog.push(e);
              return ok;
            };
          }
        }catch(e){}
      }
      return orig.apply(this,arguments);
    };
  }
  patch();
})();
"""

CLICK_SHIP = r"""
(function(){var s=(window.GALLERY.ships||[]).find(function(x){
   return (x.skins||[]).some(function(k){return k.key===%s;});});
  if(!s) return 'NO_SHIP';
  var c=[].slice.call(document.querySelectorAll('.card')).find(function(e){
     return (e.textContent||'').indexOf(s.name)>=0;});
  if(c) c.click(); return 'OK';})()
"""


def snap(pg):
    return pg.ev(r"""(function(){
      var m=window.__l2model; if(!m) return '{"err":"NO_MODEL"}';
      var st=m.internalModel.motionManager.state||{};
      var pins=(window.__posePinsByModel||{})[%s]||null;
      return JSON.stringify({cur:(st.currentGroup===undefined?'<undef>':st.currentGroup),
        pri:st.currentPriority,
        pins: pins?Object.keys(pins).length:0,
        log:(window.__stLog||[])});})()""" % json.dumps(KEY))


def main():
    try:
        with urllib.request.urlopen(URL, timeout=6) as r:
            if r.status != 200:
                print('[INVALID] HTTP', r.status); return 2
    except Exception as e:  # noqa: BLE001
        print('[INVALID] 服务器不可达:', e); return 2

    mc = json.load(open(os.path.join(ROOT, 'Output', 'gallery_v2', 'motion_chain.json'),
                        encoding='utf-8'))
    model = mc['models'].get(KEY, {})
    chain = model.get('chain', {})
    durs = model.get('durations', {})
    print('模型 %s：chain %d 组，durations %d 组' % (KEY, len(chain), len(durs)))

    pg = Page(PORT, os.path.join(ROOT, '.diag', 'chrome_fbmerge'), URL, (1400, 1000))
    fails = []
    try:
        pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
        pg.cmd('Page.navigate', {'url': URL})
        time.sleep(4)
        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.8)
        print('点卡片:', pg.ev(CLICK_SHIP % json.dumps(KEY)))
        time.sleep(1.5)
        pg.ev("""(function(){var d=[].slice.call(document.querySelectorAll('#mSkins .skin')).find(function(e){
           return e.dataset.k===%s;}); if(d) d.click(); return 1;})()""" % json.dumps(KEY))
        time.sleep(1.2)
        pg.ev("""(function(){var t=[].slice.call(document.querySelectorAll('#mTabs .tab')).find(function(e){
           return e.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(10)
        if pg.ev("window.__mm?1:0") != 1:
            print('[INVALID] 模型未就绪（__mm 缺失）'); return 2

        for g in GROUPS:
            exp = (chain.get(g) or {}).get('best')
            pk = (chain.get(g) or {}).get('pose_keep') or {}
            d = durs.get(g) or 10
            pg.ev("window.__stLog.length=0")
            r = pg.ev("""(function(){var s=document.getElementById('l2Motion');
               if(!s) return 'NO_SEL';
               if(![].slice.call(s.options).some(function(o){return o.value===%s;})) return 'NO_GROUP';
               s.value=%s; window.__l2play(%s); return 'PLAYED';})()"""
                        % (json.dumps(g), json.dumps(g), json.dumps(g)))
            if r != 'PLAYED':
                print('  [SKIP] %-14s %s' % (g, r)); continue
            if POKE is not None:
                time.sleep(POKE)
                pg.ev("""(function(){var st=window.__mm.state;
                   if(st&&st.complete) st.complete(); return 1;})()""")
                rest = d + 3.5 - POKE
            else:
                rest = d + 3.5
            time.sleep(max(0.5, rest))
            s = json.loads(snap(pg))
            log = s.get('log') or []
            fb = [e for e in log if e.get('pri') == 1]
            first = [e for e in log if e.get('pri') != 1]
            ok1 = len(fb) == 1
            got = fb[0]['req'] if fb else None
            ok2 = got == exp
            ok3 = (len(pk) == 0) or (s.get('pins', 0) > 0)
            tag = 'PASS' if (ok1 and ok2 and ok3) else 'FAIL'
            print('  [%s] %-14s 回落次数=%d(期望1) 落点=%-8s 期望=%-8s pins=%d(期望%s)' %
                  (tag, g, len(fb), got, exp, s.get('pins', 0),
                   ('>0' if pk else '0')))
            print('         播放请求: %s | 最终 currentGroup=%s' %
                  ([(e.get('req'), e.get('pri')) for e in first], s.get('cur')))
            if tag == 'FAIL':
                fails.append(g)
                for e in log:
                    print('           ', e)

        print('\n=== 结论 ===')
        if fails:
            print('  FAIL: %s' % ', '.join(fails)); return 1
        print('  全部通过：每个动作恰好一次回落，落点等于 chain.best，pose pin 正确写入')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
