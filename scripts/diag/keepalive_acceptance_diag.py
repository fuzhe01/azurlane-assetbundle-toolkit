"""验证「周期性 Page.bringToFront」是否真能挡住加载后 18–23 秒的 1 Hz 衰减。

这是对 `gallery_ui_shots.Page.keepalive` 修法的**唯一验收判据**：
必须成对出现，阳性侧要稳到 70 秒，阴性侧要**照样衰减** —— 否则阳性侧的"稳"
只是这一轮没撞上（本轮已多次见到衰减窗口漂移：18s / 20s / 23s / 25s 都出现过）。

  K1 keepalive=False（阴性对照，预期 20 秒后衰减到 <10fps）
  K2 keepalive=True （阳性侧，预期 70 秒全程 ≥55fps）

⚠️ 这里**必须**用 `gallery_ui_shots.Page` 本体，不能自己再写一份 CDP 封装：
本轮的教训就是"仪器另写一份，参数没接上"（`cdp_helper.open_page` 漏传 gpu 导致
全库 64 个探针跑软件渲染）⇒ 验证修法必须走真实调用点，否则验的不是要上线的那份代码。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r'd:\azur\scripts\diag')

from gallery_ui_shots import Page  # noqa: E402

URL = 'file:///D:/azur/scripts/diag/glmin_size.html?w=800&h=600#gallery_v2'
WATCH = 70

READ = r"""
(function(){
  var p=window.__rafc||{n:0,t0:0,gapMax:0,stalls:0};
  return JSON.stringify({n:p.n, ms:+(performance.now()-(p.t0||0)).toFixed(0),
    gapMax:+(p.gapMax||0).toFixed(0), stalls:p.stalls||0,
    vis:document.visibilityState, foc:document.hasFocus()});
})()
"""


def run(tag, keepalive, port):
    print('\n===== %s (keepalive=%s) 观测 %d 秒 =====' % (tag, keepalive, WATCH))
    pg = Page(port, r'D:\azur\.diag\ka_prof_%d' % port, URL,
              (1400, 1000), gpu=True, keepalive=keepalive)
    marks = {}
    try:
        time.sleep(1.5)
        prev = json.loads(pg.ev(READ))
        for _ in range(WATCH):
            s = json.loads(pg.ev(READ))
            dm = s['ms'] - prev['ms']
            f = (s['n'] - prev['n']) * 1000.0 / dm if dm else 0.0
            for t in (10, 20, 30, 50, 68):
                if abs(s['ms'] - t * 1000) <= 700 and t not in marks:
                    marks[t] = f
            if f < 30.0:
                print('   %-6d fps=%-6.1f gapMax=%-6d stalls=%-3d vis=%-7s foc=%s  <<<'
                      % (s['ms'], f, s['gapMax'], s['stalls'], s['vis'], s['foc']))
            prev = s
            time.sleep(1.0)
    finally:
        pg.close()
    worst = min(marks.values()) if marks else -1.0
    print('  ⇒ ' + ' | '.join('t=%ds %.1f' % (k, marks[k]) for k in sorted(marks))
          + '  【最低 %.1f】' % worst)
    return worst


def main():
    neg = run('K1 阴性对照', False, 9395)
    pos = run('K2 阳性（修法）', True, 9396)
    print('\n===== 判据 =====')
    print('  K1 阳性侧必须衰减 (<10fps)：实际最低 %.1f ⇒ %s'
          % (neg, 'PASS' if neg < 10 else 'FAIL（衰减没复现，本轮无区分力）'))
    print('  K2 修法后必须全程 ≥55fps：实际最低 %.1f ⇒ %s'
          % (pos, 'PASS' if pos >= 55 else 'FAIL'))
    return 0 if (neg < 10 and pos >= 55) else 1


if __name__ == '__main__':
    sys.exit(main())
