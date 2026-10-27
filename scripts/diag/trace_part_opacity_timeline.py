"""trace_part_opacity_timeline.py — 逐时刻记录「部件不透明度」与当前动作组。

为什么需要（2026-10-24）：同一个页面、同一份资产、同一条 URL 连跑多次，
drawable 256..277 的不透明度会出现 1.0 与 0.0 两种互斥结果（1 次可见 / 5 次消失）。
旧探针只在「固定帧数」采一个点，跨越了动作结束→回落待机的边界，于是把
「动作播放中可见 / 回落待机后消失」误读成「整段动作全程消失」，进而
错误地得出「本仓库回归」的结论。本脚本按时刻采样，直接看 1↔0 发生在哪一刻。

判据：
  - 若 op 在 `mail` 播放期恒 >0、在回落到 idle 组之后变 0   → 消失发生在**回落之后**
  - 若 op 在 `mail` 播放期就已经在 0/1 之间摆动             → 消失发生在**动作播放期**
  - 若两侧页面表现一致                                     → 不是本仓库回归

用法:
  py -3 scripts/diag/trace_part_opacity_timeline.py <url> <秒数> [--tags=256,331,212]

注意：
  - 不要调 `core.update()`：它会重算 drawable 不透明度，把「渲染用的那一帧」状态改掉
    （实测在动作未推进的瞬间调用会得到与画面不一致的读数）。
  - `state.currentGroup` 在库内部有延迟，回落判定要同时看 `reservedGroup`。
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))
import paths as P  # noqa: E402
import gallery_ui_shots as GU  # noqa: E402

GU.CHROME = P.CHROME
from gallery_ui_shots import Page  # noqa: E402

SAMPLE = r"""
(function(){
  var A=window.__AB || (window.__l2model? {model:window.__l2model}:null);
  if(!(A&&A.model)) return 'NOAB';
  var mdl=A.model, c=mdl.internalModel.coreModel, mm=mdl.internalModel.motionManager;
  var o={};
  try{ o.f=A.frames; }catch(e){}
  try{ o.ms=Math.round(performance.now()); }catch(e){}
  try{ o.g=mm.state.currentGroup||''; o.pri=mm.state.currentPriority; }catch(e){}
  try{ o.rg=mm.state.reservedGroup||''; }catch(e){}
  try{ o.ci=mm.state.currentIndex; }catch(e){}
  window.__TAGS.forEach(function(t){
    if(t.part){ try{ o['p'+t.i]=+c.getPartOpacityByIndex(t.i).toFixed(4); }catch(e){ o['p'+t.i]=null; } }
    else { try{ o['d'+t.i]=+c.getDrawableOpacity(t.i).toFixed(4); }catch(e){ o['d'+t.i]=null; } }
  });
  return JSON.stringify(o);
})()
"""

READY = "JSON.stringify({m:!!((window.__AB&&window.__AB.model)||window.__l2model)})"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        print(__doc__)
        return 2
    url, secs = args[0], float(args[1])
    tags_raw = '256,262,270,277,331,332'
    for a in sys.argv[1:]:
        if a.startswith('--tags='):
            tags_raw = a.split('=', 1)[1]
    tags = []
    for t in tags_raw.split(','):
        t = t.strip()
        if not t:
            continue
        if t.startswith('p'):
            tags.append({'i': int(t[1:]), 'part': True})
        else:
            tags.append({'i': int(t), 'part': False})

    prof = os.path.join(P.ROOT if hasattr(P, 'ROOT') else r'D:\azur', '.diag',
                        'chrome_tl%d' % int(time.time() % 100000))
    pg = Page(9450 + (int(time.time()) % 50), prof, url, (1000, 1000))
    rows = []
    try:
        for _ in range(60):
            time.sleep(1)
            if '"m":true' in (pg.ev(READY) or ''):
                break
        pg.ev("window.__TAGS=%s" % json.dumps(tags))
        t0 = time.time()
        while time.time() - t0 < secs:
            raw = pg.ev(SAMPLE)
            # ev() 返回的是 CDP 的裸返回值（字符串），不是已解析的对象
            if isinstance(raw, str) and raw.startswith('{'):
                try:
                    d = json.loads(raw)
                except ValueError:
                    d = None
                if d:
                    d['t'] = round(time.time() - t0, 2)
                    rows.append(d)
            time.sleep(0.15)
    finally:
        pg.close()

    keys = [('p%d' % t['i']) if t.get('part') else ('d%d' % t['i']) for t in tags]
    hdr = ['t', 'f', 'g', 'rg', 'pri'] + keys
    print('  '.join('%-7s' % h for h in hdr))
    for r in rows:
        print('  '.join('%-7s' % (r.get(h) if r.get(h) is not None else '-') for h in hdr))

    print('\n--- 汇总 ---')
    for k in keys:
        vals = [r.get(k) for r in rows if r.get(k) is not None]
        if not vals:
            print('%-8s 无读数' % k)
            continue
        nz = [v for v in vals if v > 0.001]
        groups_nz = sorted(set(r.get('g', '') for r in rows if (r.get(k) or 0) > 0.001))
        groups_z = sorted(set(r.get('g', '') for r in rows if (r.get(k) or 0) <= 0.001))
        print('%-8s min=%-7s max=%-7s 非零帧=%d/%d  非零时的动作组=%s  为零时的动作组=%s'
              % (k, min(vals), max(vals), len(nz), len(vals), groups_nz, groups_z))
    return 0


if __name__ == '__main__':
    sys.exit(main())
