"""切换轴验证（参数直读版）——技能要求的正确轴。

技能原文：
  「常量曲线只在切动作/切段复位轴生效；idle 单次循环内不触发复位。」
  「运行时验证用参数直读（play 后姿势参数精确等于定值、切回 idle 归零），
    截图差分只做佐证。」
  「fade 混合中间态：固定 sleep 采样会落在 FadeIn 窗口内，实测=期望×权重，
    必须 settle 轮询收敛。」

为什么不能靠截图：Live2D 模型持续呼吸/待机，画面帧永远不同（实测 30 秒都达不到
「连续两帧相同」），所以截图差分只有佐证价值，不能当主判据。

前端没有暴露 coreModel（模型对象是闭包局部变量 mdl），所以在页面脚本执行**之前**
注入一个钩子：包住 PIXI.Container.prototype.addChild，捕获带 internalModel.coreModel
的显示对象，把它挂到 window.__l2model。

判据：
  1. 播 touch_idleN 后，该 clip 的 constant 定值参数应 ≈ 定值（含 clamp 到参数范围）
  2. 切回 idle 后，这些参数应回到 idle 组的 constant 定值
  3. 采样必须 settle 轮询：每 2.5s 采一次，直到相邻两次读数收敛

用法: py -3 .diag/verify_switch_params.py [key]
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

import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402
GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
# 期望值来源目录：默认读当前正式产物；做 A/B 对照时可指向另一套产物
# （例如当前 Output 放的是"丢 constant"的对照组，期望值仍应从完整版读，
#   否则对照组会因为"自己也读不到定值"而提前退出，测不出运行时行为差异）。
EXPECT_FROM = None
if '--expect-from' in sys.argv:
    EXPECT_FROM = sys.argv[sys.argv.index('--expect-from') + 1]

HOOK = r"""
(function(){
  var tries = 0;
  function patch(){
    if(!(window.PIXI && window.PIXI.Container)){
      if(tries++ < 400) setTimeout(patch, 25);
      return;
    }
    var proto = window.PIXI.Container.prototype;
    if(proto.__dshHooked) return;
    proto.__dshHooked = true;
    var orig = proto.addChild;
    proto.addChild = function(){
      for(var i=0;i<arguments.length;i++){
        var c = arguments[i];
        try{
          if(c && c.internalModel && c.internalModel.coreModel){
            window.__l2model = c;
          }
        }catch(e){}
      }
      return orig.apply(this, arguments);
    };
  }
  patch();
})();
"""


def play(pg, group):
    return pg.ev("""
    (function(){
      var sel=document.getElementById('l2Motion');
      if(sel){ var has=[...sel.options].some(function(o){return o.value===%s;});
               if(!has) return 'NO_GROUP'; sel.value=%s; }
      if(typeof window.__l2play!=='function') return 'NO_HOOK';
      return window.__l2play(%s)? 'PLAYED':'FALSE';
    })()
    """ % (json.dumps(group), json.dumps(group), json.dumps(group)))


def read(pg, ids):
    return pg.ev("""
    (function(){
      var m=window.__l2model;
      if(!m) return 'NO_MODEL';
      var core=m.internalModel.coreModel;
      var out={}, rng={};
      %s.forEach(function(id){
        try{
          var idx=core.getParameterIndex(id);
          if(idx<0){ out[id]=null; return; }
          out[id]=core.getParameterValueById(id);
          rng[id]=[core.getParameterMinimumValue(idx), core.getParameterMaximumValue(idx)];
        }catch(e){ out[id]=null; }
      });
      return JSON.stringify({v:out, r:rng});
    })()
    """ % json.dumps(ids))


def settle(pg, ids, max_wait=30, eps=0.05):
    """轮询到相邻两次读数收敛（避开 fade 混合中间态）。"""
    t0 = time.time()
    prev = None
    while time.time() - t0 < max_wait:
        raw = read(pg, ids)
        try:
            cur = json.loads(raw).get('v', {}) if isinstance(raw, str) and raw.startswith('{') else None
        except Exception:  # noqa: BLE001
            cur = None
        if cur and prev:
            if all((cur.get(k) is None and prev.get(k) is None)
                   or (cur.get(k) is not None and prev.get(k) is not None
                       and abs(cur[k] - prev[k]) < eps) for k in ids):
                return cur, raw, round(time.time() - t0, 1)
        prev = cur
        time.sleep(2.5)
    return prev, raw, -1


def clip_const(model_dir, clip):
    """读磁盘上该 clip 的 constant 定值。

    自产 motion3.json 的定值曲线 Segments 格式是 5 元素 `[0, v, 0, duration, v]`
    （段类型码 0 = Linear；值在第 1 与第 4 位）。
    ⚠️ 曾在索引 1/3 上取"值"——那是值与时长的错位，导致 284 条定值一条都认不出来，
    判据静默变成空集合假通过。
    """
    p = os.path.join(model_dir, clip + '.motion3.json')
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding='utf-8'))
    exp = {}
    for c in d.get('Curves', []):
        s = c.get('Segments') or []
        if len(s) == 5 and abs(s[1] - s[-1]) < 1e-9:
            exp[c.get('Id')] = s[1]
    return exp


def main():
    mdir = os.path.join(ROOT, 'Output', 'Live2D', KEY, 'motion')
    # 期望值目录可与被测目录不同（A/B 对照用）
    mdir_exp = EXPECT_FROM or mdir
    pg = Page(9237, os.path.join(ROOT, '.diag', 'chrome_params'),
              'http://127.0.0.1:8778/gallery_v2/index.html', (1400, 1000))
    try:
        # 关键：在页面脚本前注入钩子
        try:
            pg.cmd('Page.addScriptToEvaluateOnNewDocument', {'source': HOOK})
            pg.cmd('Page.navigate', {'url': 'http://127.0.0.1:8778/gallery_v2/index.html'})
            time.sleep(3)
            print('钩子已注入（页面已重载）')
        except Exception as e:  # noqa: BLE001
            print('[warn] addScriptToEvaluateOnNewDocument 失败:', e)

        pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
           if(b&&(b.classList.contains('on')||b.dataset.on==='1')) b.click(); return 1;})()""")
        time.sleep(0.5)

        pg.ev("""
        (function(){var ship=(window.GALLERY.ships||[]).find(function(s){
           return (s.skins||[]).some(function(k){return k.key==='%s';});});
          var c=[...document.querySelectorAll('.card')].find(function(el){
             return (el.textContent||'').indexOf(ship.name)>=0;});
          if(c) c.click(); return 1;})()
        """ % KEY)
        time.sleep(1.2)
        pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(el){
           return el.dataset.k==='%s';}); if(d) d.click(); return 1;})()""" % KEY)
        time.sleep(0.8)
        pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(el){
           return el.dataset.k==='live2d';}); if(t&&!t.classList.contains('dis')) t.click(); return 1;})()""")
        time.sleep(5)

        print('模型钩子:', 'OK' if pg.ev("typeof window.__l2model") == 'object' else pg.ev("typeof window.__l2model"))

        # 挑一个 idle 变体与对应 touch 组
        # idle9 与 idle 有 9 条姿势定值不同（Param345=-1.28、Param494/500/502/506/91/97/352=1.0），
        # 且这 9 条在 idle9 里**只被 constant 覆盖、没有动画曲线** —— 这是唯一能区分
        # 「有 constant / 丢 constant」两组的轴（技能记录的原始判例就是 idle9）。
        # idle5 的差异参数同时有动画曲线驱动，两组都能达到定值，测不出区别。
        idle_g, touch_g = 'idle', 'idle9'
        exp_touch = clip_const(mdir_exp, touch_g)
        exp_idle = clip_const(mdir_exp, idle_g)
        print('\n期望值来源: %s' % mdir_exp)
        print('%s constant 定值参数数: %d' % (touch_g, len(exp_touch)))
        print('%s constant 定值参数数: %d' % (idle_g, len(exp_idle)))

        # 选参必须挑「两组定值都有效且互不相同」的——否则观测参数没有区分度，
        # 各状态读出来都是同一个值，判据会静默变成空断言（2026-10-23 踩过：
        # 首版挑了 14 个定值恰好全为 0 的参数，A/B/C 全是 0，看不出任何东西）。
        cand = [k for k in exp_touch
                if k in exp_idle and abs(exp_touch[k] - exp_idle[k]) > 0.05]
        cand.sort(key=lambda k: -abs(exp_touch[k] - exp_idle[k]))
        ids = cand[:14]
        print('两组定值不同的参数数: %d（取前 %d 个做观测）' % (len(cand), len(ids)))
        for k in ids[:6]:
            print('   %-22s idle 定值 %8.3f | %s 定值 %8.3f'
                  % (k, exp_idle[k], touch_g, exp_touch[k]))
        if not ids:
            print('[FAIL] 找不到两组定值不同的参数——判据无区分度，不得继续')
            return 1

        # A: idle
        print('\n[A] 播 idle:', play(pg, idle_g))
        va, raw_a, ta = settle(pg, ids)
        print('    settle %ss -> %s' % (ta, json.dumps(va, ensure_ascii=False) if va else raw_a))

        # B: touch
        print('[B] 播 %s: %s' % (touch_g, play(pg, touch_g)))
        vb, raw_b, tb = settle(pg, ids)
        print('    settle %ss -> %s' % (tb, json.dumps(vb, ensure_ascii=False) if vb else raw_b))

        # C: 切回 idle
        print('[C] 切回 idle:', play(pg, idle_g))
        vc, raw_c, tc = settle(pg, ids)
        print('    settle %ss -> %s' % (tc, json.dumps(vc, ensure_ascii=False) if vc else raw_c))

        if not (va and vb and vc):
            print('\n[FAIL] 参数未取到（钩子失效或未收敛），判据无效')
            return 1

        print('\n=== 判据（参数直读，与磁盘定值比对）===')
        # 期望值取「clamp 后的定值」：Cubism 会把赋值钳进 [min,max]，
        # 所以超范围定值在运行时的正确读数就是边界值（技能已记录此假阴性来源）。
        rng = {}
        try:
            rng = json.loads(raw_a).get('r', {}) if isinstance(raw_a, str) and raw_a.startswith('{') else {}
        except Exception:  # noqa: BLE001
            rng = {}

        def want(v, k):
            v = float(v)
            r = rng.get(k)
            if isinstance(r, list) and len(r) == 2:
                return min(max(v, r[0]), r[1])
            return v

        rows = []
        for k in ids:
            ea = want(exp_idle[k], k)
            eb = want(exp_touch[k], k)
            ra = va.get(k); rb = vb.get(k); rc = vc.get(k)
            if None in (ra, rb, rc):
                continue
            hit_a = abs(ra - ea) <= 0.05
            hit_b = abs(rb - eb) <= 0.05
            hit_c = abs(rc - ea) <= 0.05
            rows.append((k, ea, eb, ra, rb, rc, hit_a, hit_b, hit_c))

        if not rows:
            print('  [FAIL] 无有效观测行')
            return 1
        oka = sum(1 for r in rows if r[6])
        okb = sum(1 for r in rows if r[7])
        okc = sum(1 for r in rows if r[8])
        n = len(rows)
        print('  参数行数 %d' % n)
        print('  A(idle)    实测 == idle 定值 : %d/%d' % (oka, n))
        print('  B(touch)   实测 == touch 定值: %d/%d' % (okb, n))
        print('  C(切回)    实测 == idle 定值 : %d/%d' % (okc, n))
        print('  逐参数明细（前 8 行）:')
        print('     %-20s %9s %9s | %9s %9s %9s' % ('参数', 'idle定值', 'touch定值', 'A实测', 'B实测', 'C实测'))
        for k, ea, eb, ra, rb, rc, ha, hb, hc in rows[:8]:
            print('     %-20s %9.3f %9.3f | %9.3f%s %9.3f%s %9.3f%s'
                  % (k, ea, eb, ra, '' if ha else '!', rb, '' if hb else '!', rc, '' if hc else '!'))

        ok = oka == n and okb == n and okc == n
        print('  结论:', 'PASS（定值生效 + 切回完全复位）' if ok
              else 'FAIL（B 未达定值 = constant 未生效；C 未回 idle 定值 = 未复位）')
        return 0 if ok else 1
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())