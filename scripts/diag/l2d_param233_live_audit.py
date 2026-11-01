r"""在**真实播放态**（不冻结 idle/呼吸/物理）下核查 Param233 与那 16 个部件（2026-10-28）

为什么必须单独做这一个：`l2d_param233_visual.py` 会把 idle / 自然呼吸 / 物理全部
冻结，那是为了做参数差分的干净底座，但它**不能回答用户看到的观感问题**
（"idle 和 idle9 默认应该有两双红底高跟鞋，现在只有一双"）。冻结态下读到的一切
都是"底座姿态"，不代表用户实际看到的画面。

本工具回答三个问题：
  Q1 `Param233` 的**模型默认值 / 上下限**是多少 —— 决定"部件被隐藏"是模型本来如此，
     还是被某个东西拉回了 0；
  Q2 真实播 `idle` 时，`Param233` 与 16 件的 op/vis **随时间的取值分布**；
  Q3 真实播 `idle9`（用户点名的那另一个）时同样一组数值。
  Q4 一并记录：真实播放态下，16 件有多少帧是可见的（>0 即"用户本该看得到"）。

判据
  - Q1 默认值若为 0 ⇒ 隐藏是模型设计如此，不该由动作背锅；
  - 若 idle/idle9 全程 vis=0 且 op=0 ⇒ 用户描述"少一只鞋"与模型数据一致，
    即这是**素材本身的状态（缺省关闭）**，不是播放管线丢帧；
  - 若出现 op>0 / vis=1 的帧 ⇒ 说明画面确实会一闪，问题在"默认姿态"而非"渲染丢件"。

采样方式：轮询 `coreModel.update` 的**出口值**。只读值不写值，绝不动 motion 状态；
每 40 ms 采一次、连采 6 秒（约 150 帧），并在采样窗口内**不调用**任何
`setParameterValueByIndex`，保证读到的是 motion/physics 真实驱动的结果。

用法
  py -3 -u scripts/diag/l2d_param233_live_audit.py [模型] [参数名] [动作1] [动作2]
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
ACT1 = sys.argv[3] if len(sys.argv) > 3 else 'idle'
ACT2 = sys.argv[4] if len(sys.argv) > 4 else 'idle9'
BASE = 'http://127.0.0.1:8778/gallery_v2/index.html#gallery_v2'
PORT = int(os.environ.get('AL_PORT', '9412'))
PROFILE = os.path.join(ROOT, '.diag', 'czh2_prof')
OUT = os.path.join(ROOT, '.diag')

TARGETS = [405, 406, 407, 408, 409, 410, 411, 412, 413, 414,
           415, 416, 417, 447, 448, 665]

# 采样器：把采样挂在 requestAnimationFrame 里，只读不写。
# 关键：绝不在本函数内调用 coreModel.update()/setParameterValueByIndex，
# 否则会与 motion 的 loadParameters 抢写，读到的就不是真实值。
SAMPLER = """(function(){
  var c = window.__l2ModelRef().internalModel.coreModel;
  var pi = c.getParameterIndex(%s);
  if (pi >= c.getParameterCount()) return 'NO_PARAM';
  window.__p233 = {pi: pi, samples: [], target: %s,
    def: c.getParameterDefaultValue(pi),
    min: c.getParameterMinimumValue(pi),
    max: c.getParameterMaximumValue(pi)};
  var o = window.__p233;
  var tick = function(){
    var s = {p: +c.getParameterValueByIndex(o.pi).toFixed(4), op: {}, n: o.samples.length};
    for (var k = 0; k < o.target.length; k++) {
      var d = o.target[k];
      s.op[d] = [+c.getDrawableOpacity(d).toFixed(3),
                 c.getDrawableDynamicFlagIsVisible(d) ? 1 : 0];
    }
    o.samples.push(s);
    if (o.samples.length < 220) requestAnimationFrame(tick);
    else o.done = true;
  };
  requestAnimationFrame(tick);
  return JSON.stringify({pi: pi, def: o.def, min: o.min, max: o.max});})()"""

COLLECT = """(function(){var o=window.__p233; if(!o) return 'NONE';
  return JSON.stringify({done: !!o.done, n: o.samples.length, s: o.samples});})()"""

PLAY = """(function(g){
  try { window.__l2play(g); return 'played:'+g; }
  catch(e){ return 'ERR:'+e.message; }})('__G__')"""


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
    """把一串帧样本压成"值域 + 可见帧数"的可判读摘要。"""
    s = data['s']
    if not s:
        print('  %s: 无样本' % tag)
        return
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
    print('  %-6s 帧数=%-4d  %s: min=%.4f max=%.4f 首帧=%.4f 末帧=%.4f'
          % (tag, len(s), PARAM, min(pv), max(pv), pv[0], pv[-1]))
    live = [d for d in TARGETS if vis[d] > 0 or opmax[d] > 0]
    print('         16 件里「曾可见或曾有不透明度」的件数 = %d' % len(live))
    if live:
        for d in live:
            print('           #%-4d vis帧=%-4d opmax=%.3f' % (d, vis[d], opmax[d]))
    else:
        print('           → 全部 {} 帧内 vis=0 且 op=0（用户看不到，与"缺件"观感一致）'
              .format(len(s)))


def run_action(pg, group):
    print('\n=== 真实播放 %s ===' % group)
    print('  切换:', pg.ev(PLAY.replace('__G__', group)))
    time.sleep(0.4)
    print('  采样器:', pg.ev(SAMPLER % (json.dumps(PARAM), json.dumps(TARGETS))))
    for _ in range(40):
        time.sleep(0.15)
        raw = pg.ev(COLLECT)
        if raw == 'NONE':
            print('  [FAIL] 采样器没装上')
            return None
        d = json.loads(raw)
        if d['done']:
            break
    summarize(group, d)
    return d


def main():
    pg = Page(PORT, PROFILE, BASE, (1400, 1000), gpu=True, keepalive=True)
    try:
        time.sleep(3.0)
        if not open_model(pg):
            print('[FAIL] 模型没加载')
            return 2
        print('解耦帧源:', pg.detach_frames(60))
        time.sleep(2.5)
        print('帧源闸: %.1f fps（必须 >5 才认为 rAF 没被节流）' % pg.require_frames(2.0))
        print('\n=== Q1 模型侧取值域（不冻结，真实播放）===')
        probe = pg.ev("""(function(){var c=window.__l2ModelRef().internalModel.coreModel;
          var i=c.getParameterIndex(%s); if(i>=c.getParameterCount()) return 'NO_PARAM';
          return JSON.stringify({idx:i, cur:+c.getParameterValueByIndex(i).toFixed(4),
            def:+c.getParameterDefaultValue(i).toFixed(4),
            min:+c.getParameterMinimumValue(i).toFixed(4),
            max:+c.getParameterMaximumValue(i).toFixed(4)});})()""" % json.dumps(PARAM))
        print('  %s' % probe)
        try:
            q1 = json.loads(probe)
            print('  解读: 默认值=%.4f（模型初始姿态），当前值=%.4f，范围 [%.4f, %.4f]'
                  % (q1['def'], q1['cur'], q1['min'], q1['max']))
            if q1['def'] <= 0.0001:
                print('  → 默认值就是 0 ⇒ 这 16 件"开局即隐藏"是模型数据的设计，'
                      '不是播放管线把件弄丢了')
        except Exception:
            pass

        d1 = run_action(pg, ACT1)
        d2 = run_action(pg, ACT2)
        if d1 and d2:
            print('\n=== 判据 ===')
            tot = len(d1['s']) + len(d2['s'])
            # 逐帧数：本帧里 16 件**至少一件**可见/有不透明度，就算"这一帧用户看得见"
            vis_frames = 0
            for f in d1['s'] + d2['s']:
                if any(v or op > 0 for op, v in f['op'].values()):
                    vis_frames += 1
            print('  两个动作合计 %d 帧，其中「16 件里至少一件可见」的帧数 = %d'
                  % (tot, vis_frames))
            print('  结论: %s' % ('素材侧缺省关闭（观感"少一只鞋"与模型数据一致）'
                                 if vis_frames == 0 else
                                 '画面确实显示了这些件 ⇒ 缺件不是渲染丢帧，'
                                 '而是当前动作/低优先级写入没让它们出现在画面上'))
        return 0
    finally:
        pg.close()


if __name__ == '__main__':
    sys.exit(main())
