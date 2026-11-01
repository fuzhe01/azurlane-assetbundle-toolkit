# -*- coding: utf-8 -*-
r"""参数 pin 的**写入时机** A/B 仪器（2026-10-28）

## 要回答的问题

同一个参数、同一个目标值、同一个动作，只改「每帧在哪一步写」，
目标部件的可见帧数会不会变？

## 为什么必须单独做这一个

`l2d_param233_live_audit.py` 已经测到一件自相矛盾的事：
真实播 `idle` 时 `Param233` 读回**恒为 1**，但那 16 个部件 220 帧里**全不可见**；
换成 `idle9` 同样 pin 1，16 件 220/220 帧**全可见**。

「参数值对、画面不对」只有三种解释：keyform 没重算 / 有第二个开关 / 写入被覆盖。
`l2d_opacity_binding_hunt.py` 已排除第二种（冻结后基线可见，只有 `Param233=0` 能关掉它）。
本工具判定第一种 vs 第三种。

## 判据

在**同一动作、同一参数、同一目标值**下跑三组：

  A 组 `low`         —— 现状：写 `app.ticker` LOW（模型 `update()` 之后）
  B 组 `beforeUpdate` —— 候选：写 `internalModel.on('beforeModelUpdate')`（`update()` 之前）
  C 组 `none`         —— 阴性对照：不写，一切交给动作曲线

- **B 组可见帧数 > A 组** ⇒ 写入时机是根因，产品层应改挂点；
- **A≈B≈C 且全 0** ⇒ 时机不是根因，回到「别的机制在压可见性」；
- **C 组也能看到** ⇒ 连「动作把它关了」都不成立，前面的推断要全部推翻。

⚠️ C 组不是可选项。没有它，B>A 也可能只是「多写了一次让参数留存更久」这类
    与时机无关的副作用。

用法
  py -3 -u scripts/diag/l2d_pin_timing_ab.py [模型] [参数] [动作] [目标件,逗号分隔]
  py -3 -u scripts/diag/l2d_pin_timing_ab.py ougen_8 Param233 idle
  py -3 -u scripts/diag/l2d_pin_timing_ab.py ougen_8 Param233 idle9   # 对照动作（已知正常）
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
from gallery_ui_shots import Page  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else 'ougen_8'
PARAM = sys.argv[2] if len(sys.argv) > 2 else 'Param233'
GROUP = sys.argv[3] if len(sys.argv) > 3 else 'idle'
_raw = sys.argv[4] if len(sys.argv) > 4 else '405,413,665'
TARGETS = [int(x) for x in _raw.split(',') if x.strip().isdigit()]

BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = int(os.environ.get('AL_PORT', '9413'))
PROFILE = os.path.join(ROOT, '.diag', 'czh3_prof')
FRAMES = 150

# 三组共用的采样器：只读 coreModel，不写参数、不调 update()。
SAMPLER = """(function(){
  var c = window.__l2ModelRef().internalModel.coreModel;
  var pi = c.getParameterIndex(%s);
  if (pi >= c.getParameterCount()) return 'NO_PARAM';
  var o = window.__ab = {pi: pi, samples: [], target: %s};
  var tick = function(){
    var s = {p: +c.getParameterValueByIndex(o.pi).toFixed(4), op: {}, n: o.samples.length};
    for (var k = 0; k < o.target.length; k++) {
      var d = o.target[k];
      s.op[d] = [+c.getDrawableOpacity(d).toFixed(3),
                 c.getDrawableDynamicFlagIsVisible(d) ? 1 : 0];
    }
    o.samples.push(s);
    if (o.samples.length < %d) requestAnimationFrame(tick);
    else o.done = true;
  };
  requestAnimationFrame(tick);
  return 'ARMED:' + pi;})()""" % (json.dumps(PARAM), json.dumps(TARGETS), FRAMES)

COLLECT = """(function(){var o=window.__ab; if(!o) return 'NONE';
  return JSON.stringify({done: !!o.done, n: o.samples.length, s: o.samples});})()"""

# 三组挂点。**不新造 ticker**：产品层自己的 LOW 出口已经存在
# （`app.__statePinTick` 挂在 app.ticker LOW），"low" 组直接复用它，
# 于是三组之间唯一的差别就真的只剩「每帧写在哪一步」，没有别的变量混进来。
#   组 A low          = 让产品层 pin 生效（现产品代码的真实行为）
#   组 B beforeUpdate = 摘掉产品层 pin，改挂 beforeModelUpdate（update() 之前）
#   组 C none         = 摘掉产品层 pin，谁都不写（阴性对照）
# 每组开跑前先清掉本工具上一次装的 event 钩子，避免上一组的残留继续写。
SETUP = """(function(mode){
  var m = window.__l2ModelRef();
  var im = m && m.internalModel;
  if (!im) return 'NO_MODEL';
  var c = im.coreModel;
  var pi = c.getParameterIndex(%s);
  if (pi >= c.getParameterCount()) return 'NO_PARAM';
  if (window.__abHook && window.__abHook.im) {
    try { window.__abHook.im.off('beforeModelUpdate', window.__abHook.fn); } catch(e) {}
    window.__abHook = null;
  }
  /* pin 归属对象只认一次并缓存：后面几组会把这个键删掉，靠键本身再也找不回来 */
  if (!window.__abOwner) {
    var p = window.__costumePinsByModel || {};
    for (var kk in p) {
      if (!p[kk]) continue;
      for (var k2 in p[kk]) {
        if (k2 === %s) { window.__abOwner = p[kk]; window.__abOwnerKey = kk; break; }
      }
      if (window.__abOwner) break;
    }
  }
  var owner = window.__abOwner;
  if (!owner) return 'NO_PIN_OWNER';
  if (mode === 'low') {
    owner[%s] = 1;                 /* 交给产品层 __statePinTick 每帧重申 */
    return 'SETUP:low key=' + window.__abOwnerKey + ' pin=1';
  }
  delete owner[%s];                /* 摘掉产品层写入（置 undefined 会被 setParameterValueById 当值写进去） */
  if (mode === 'beforeUpdate' || mode === 'both') {
    var write = function(){ try { c.setParameterValueById(%s, 1); } catch(e) {} };
    im.on('beforeModelUpdate', write);
    window.__abHook = {im: im, fn: write};
  }
  if (mode === 'both') { owner[%s] = 1; }   /* 双写：渲染路径 + 读回路径都覆盖 */
  if (mode === 'none') return 'SETUP:none key=' + window.__abOwnerKey + ' (no writer)';
  return 'SETUP:' + mode + ' key=' + window.__abOwnerKey;})('__MODE__')""" % (
    json.dumps(PARAM), json.dumps(PARAM), json.dumps(PARAM),
    json.dumps(PARAM), json.dumps(PARAM), json.dumps(PARAM))

PLAY = """(function(g){ try { window.__l2play(g); return 'played:'+g; }
  catch(e){ return 'ERR:'+e.message; }})('__G__')"""

# 关键前置：把产品层自己的 pin 摘掉，否则它会混在每一组里写同一个值，
# 让 A/B/C 全都变成「有人在写」⇒ 分组失去意义。
# 注：SETUP 里已按组分别处理 pin 的存/取，这里只做一次可读的状态打印。
DISABLE_PRODUCT_PIN = """(function(){
  var p = window.__costumePinsByModel || {};
  var out = [];
  for (var k in p) { if (p[k] && p[k][%s] !== undefined) out.push(k + '=' + p[k][%s]); }
  return out.length ? ('pin-owners: ' + out.join(',')) : 'no-owner';})()""" % (
    json.dumps(PARAM), json.dumps(PARAM))


def open_model(pg):
    pg.ev("""(function(){var b=document.querySelector('#gOpt button[data-k=login]');
       if(b&&b.classList.contains('on')) b.click(); return 1;})()""")
    time.sleep(0.9)
    print('开卡:', pg.ev("""
    (function(){var s=(window.GALLERY.ships||[]).find(function(x){
         return (x.skins||[]).some(function(k){return k.key===%s;});});
      var c=[...document.querySelectorAll('.card')].find(function(e){
         return (e.textContent||'').indexOf(s.name)>=0;}); c.click(); return 'OK';})()"""
                    % json.dumps(KEY)))
    time.sleep(1.6)
    pg.ev("""(function(){var d=[...document.querySelectorAll('#mSkins .skin')].find(function(e){
       return e.dataset.k===%s;}); d.click(); return 1;})()""" % json.dumps(KEY))
    time.sleep(1.3)
    pg.ev("""(function(){var t=[...document.querySelectorAll('#mTabs .tab')].find(function(e){
       return e.dataset.k==='live2d';}); t.click(); return 1;})()""")
    for _ in range(60):
        if pg.ev("(function(){var m=window.__l2ModelRef&&window.__l2ModelRef(); return m?1:0;})()") == 1:
            return True
        time.sleep(1.0)
    return False


def summarize(tag, data):
    s = data['s']
    if not s:
        print('  %-14s 无样本' % tag)
        return None
    pv = [f['p'] for f in s]
    vis = {d: 0 for d in TARGETS}
    opmax = {d: 0.0 for d in TARGETS}
    for f in s:
        for d, (op, v) in f['op'].items():
            d = int(d)
            if v:
                vis[d] += 1
            if op > opmax[d]:
                opmax[d] = op
    nv = sum(vis.values())
    print('  %-14s 帧=%-4d %s=[%.3f,%.3f] 可见帧合计=%-5d %s'
          % (tag, len(s), PARAM, min(pv), max(pv), nv,
             ' '.join('#%d:%d' % (d, vis[d]) for d in TARGETS)))
    return {'frames': len(s), 'vis': nv, 'per': vis, 'opmax': opmax}


def run_group(pg, mode):
    print('\n=== 组 %s ===' % mode)
    print('  挂点:', pg.ev(SETUP.replace('__MODE__', mode)))
    print('  切动作:', pg.ev(PLAY.replace('__G__', GROUP)))
    time.sleep(0.35)
    print('  采样器:', pg.ev(SAMPLER))
    d = None
    for _ in range(40):
        time.sleep(0.15)
        raw = pg.ev(COLLECT)
        if raw == 'NONE':
            print('  [FAIL] 采样器没装上')
            return None
        d = json.loads(raw)
        if d['done']:
            break
    return summarize(mode, d)


def main():
    pg = Page(PORT, PROFILE, BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        if not open_model(pg):
            print('[FAIL] 模型没加载')
            return 2
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(2.0)
        fps = pg.require_frames(2.0)
        print('帧源闸: %.1f fps（>5 才算 rAF 没被节流）' % fps)
        if fps <= 5:
            print('[FAIL] 帧源被节流，测出来的可见帧数不可信')
            return 3
        print('\n=== 前置：把产品层自己的 pin 摘掉（否则三组都有人在写）===')
        print(' ', pg.ev(DISABLE_PRODUCT_PIN))

        res = {}
        for mode in ('none', 'low', 'beforeUpdate', 'both'):
            res[mode] = run_group(pg, mode)
            time.sleep(0.4)

        print('\n=== 判据（动作 %s / 参数 %s）===' % (GROUP, PARAM))
        try:
            c, a, b = res['none']['vis'], res['low']['vis'], res['beforeUpdate']['vis']
            d = res['both']['vis']
        except (TypeError, KeyError):
            print('  有组没采到数，结论不定')
            return 4
        print('  C none=%d   A low=%d   B beforeUpdate=%d   D both=%d' % (c, a, b, d))
        if d > 0 and d >= b:
            print('  -> both works: D visible too, product layer can keep readback semantics')
            return 0
        if b > a:
            print('  → 写入时机是根因：挂 beforeModelUpdate 才能让画面跟着参数走')
            return 0
        if a == b and b == c and b == 0:
            print('  → 时机不是根因，三组全 0，需另找压制可见性的机制（不要改挂点）')
            return 0
        if c > 0 and a >= c:
            print('  → 连阴性对照都能看到 ⇒ 前面「动作把它关了」的推断要推翻')
            return 0
        print('  → 三组有差但方向不单调，需人工判读（别据此改产品代码）')
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
